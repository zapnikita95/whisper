"""
Detect host capabilities and recommend a Whisper model + compute settings.
"""
from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass, asdict
from typing import Any

from whisper_models import MODEL_CATALOG, ModelSpec, SPEC_BY_KEY


@dataclass
class SystemProfile:
    os_name: str
    cpu_cores: int
    ram_gb: float
    has_nvidia_gpu: bool
    gpu_name: str | None
    vram_gb: float | None
    cuda_available: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ModelRecommendation:
    model_key: str
    hf_id: str
    label: str
    compute_type: str
    device: str
    reason: str
    alternatives: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ram_gb() -> float:
    if platform.system() == "Windows":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return round(stat.ullTotalPhys / (1024**3), 1)
        except Exception:
            pass
    try:
        import psutil  # type: ignore[import-untyped]

        return round(psutil.virtual_memory().total / (1024**3), 1)
    except Exception:
        return 8.0


def _nvidia_gpu() -> tuple[bool, str | None, float | None]:
    try:
        r = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if r.returncode != 0 or not (r.stdout or "").strip():
            return False, None, None
        line = (r.stdout or "").strip().splitlines()[0]
        parts = [p.strip() for p in line.split(",")]
        name = parts[0] if parts else None
        vram_mb = float(parts[1]) if len(parts) > 1 else None
        vram_gb = round(vram_mb / 1024, 1) if vram_mb is not None else None
        return True, name, vram_gb
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, ValueError):
        return False, None, None


def _cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def detect_system() -> SystemProfile:
    has_gpu, gpu_name, vram_gb = _nvidia_gpu()
    return SystemProfile(
        os_name=platform.system(),
        cpu_cores=os.cpu_count() or 4,
        ram_gb=_ram_gb(),
        has_nvidia_gpu=has_gpu,
        gpu_name=gpu_name,
        vram_gb=vram_gb,
        cuda_available=_cuda_available(),
    )


def _fits_gpu(spec: ModelSpec, vram_gb: float, *, margin: float = 0.8) -> bool:
    return vram_gb >= max(0.5, spec.min_vram_gb - margin)


def _score(spec: ModelSpec, prof: SystemProfile, *, prefer_russian: bool) -> float:
    score = float(spec.quality)
    if prefer_russian and "ru" in spec.languages:
        score += 1.5
    if not prefer_russian and spec.category == "english" and "en" in spec.languages:
        score += 0.5
    if prof.has_nvidia_gpu and prof.vram_gb is not None:
        if not _fits_gpu(spec, prof.vram_gb):
            score -= 10.0
    elif spec.min_vram_gb > 4.0:
        score -= 6.0
    return score


def recommend_model(
    profile: SystemProfile | None = None,
    *,
    prefer_russian: bool = False,
    prefer_english: bool = False,
) -> ModelRecommendation:
    prof = profile or detect_system()
    prefer_ru = prefer_russian and not prefer_english

    candidates = list(MODEL_CATALOG)
    if prefer_english and not prefer_ru:
        en_first = [m for m in candidates if "en" in m.languages or m.category == "english"]
        if en_first:
            candidates = en_first + [m for m in candidates if m not in en_first]

    if prof.has_nvidia_gpu and prof.vram_gb is not None:
        device = "cuda"
        vram = prof.vram_gb
        if vram >= 10:
            compute = "float16"
        elif vram >= 6:
            compute = "int8_float16"
        else:
            compute = "int8"

        ranked = sorted(candidates, key=lambda m: _score(m, prof, prefer_russian=prefer_ru), reverse=True)
        pick = ranked[0]
        for spec in ranked:
            if _fits_gpu(spec, vram):
                pick = spec
                break

        gpu_label = prof.gpu_name or "NVIDIA GPU"
        reason = (
            f"{gpu_label} with ~{vram:.1f} GB VRAM — "
            f"{'Russian-tuned' if pick.category == 'russian' else pick.label_en.split('—')[0].strip()} "
            f"fits GPU memory (compute: {compute})."
        )
        alts = [m.key for m in ranked[1:4] if m.key != pick.key]
        return ModelRecommendation(
            model_key=pick.key,
            hf_id=pick.hf_id,
            label=pick.label_en,
            compute_type=compute,
            device=device,
            reason=reason,
            alternatives=alts,
        )

    # CPU fallback
    device = "cpu"
    compute = "int8"
    ram = prof.ram_gb
    cores = prof.cpu_cores

    if prefer_ru and ram >= 12:
        pick_key = "medium"
    elif prefer_english or (not prefer_ru):
        if ram >= 8:
            pick_key = "small.en"
        else:
            pick_key = "base.en"
    elif ram >= 16 and cores >= 8:
        pick_key = "medium"
    elif ram >= 8:
        pick_key = "small"
    else:
        pick_key = "tiny"

    pick = SPEC_BY_KEY.get(pick_key) or SPEC_BY_KEY["base"]
    reason = (
        f"No usable NVIDIA GPU detected — CPU mode with {ram:.0f} GB RAM / {cores} cores. "
        f"Picked {pick.key} (int8) for reasonable latency."
    )
    alts = []
    for k in ("tiny.en", "base.en", "small", "medium", "distil-large-v3"):
        if k != pick.key and k in SPEC_BY_KEY:
            alts.append(k)
    return ModelRecommendation(
        model_key=pick.key,
        hf_id=pick.hf_id,
        label=pick.label_en,
        compute_type=compute,
        device=device,
        reason=reason,
        alternatives=alts[:3],
    )
