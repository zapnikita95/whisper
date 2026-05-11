"""
Windows: CTranslate2 / faster-whisper ищут cublas64_12.dll и соседние NVIDIA DLL.
Wheels кладут их в site-packages/nvidia/<пакет>/bin/ — недостаточно добавить только cublas:
часто нужны cudnn, cufft, curand и т.д. в том же PATH.

Использование: вызвать prepend_nvidia_cuda_bins_to_path() до import faster_whisper.
"""
from __future__ import annotations

import os
import site
import sys
from pathlib import Path


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        meip = getattr(sys, "_MEIPASS", None)
        if meip:
            roots.append(Path(meip))
        roots.append(exe_dir / "_internal")
        roots.append(exe_dir)
    try:
        roots.append(Path(site.getusersitepackages()))
    except Exception:
        pass
    try:
        roots.extend(Path(p) for p in site.getsitepackages())
    except Exception:
        pass
    roots.append(Path(sys.prefix) / "Lib" / "site-packages")
    return roots


def prepend_nvidia_cuda_bins_to_path() -> bool:
    """
    Добавляет в начало PATH все каталоги site-packages/nvidia/*/bin с .dll.
    Возвращает True, если среди них есть cublas64_12.dll (или не Windows).
    """
    if sys.platform != "win32":
        return True

    bin_dirs: list[Path] = []
    seen: set[str] = set()
    roots_seen: set[str] = set()

    for base in _candidate_roots():
        try:
            base = base.resolve()
        except OSError:
            continue
        if not base.is_dir():
            continue
        key = str(base)
        if key in roots_seen:
            continue
        roots_seen.add(key)

        nvidia = base / "nvidia"
        if not nvidia.is_dir():
            continue
        try:
            subs = sorted(nvidia.iterdir())
        except OSError:
            continue
        for sub in subs:
            if not sub.is_dir():
                continue
            bd = sub / "bin"
            if not bd.is_dir():
                continue
            try:
                bd_r = bd.resolve()
            except OSError:
                continue
            sk = str(bd_r)
            if sk in seen:
                continue
            try:
                if not any(bd_r.glob("*.dll")):
                    continue
            except OSError:
                continue
            seen.add(sk)
            bin_dirs.append(bd_r)

    if not bin_dirs:
        return False

    prefix = os.pathsep.join(str(b) for b in bin_dirs)
    os.environ["PATH"] = prefix + os.pathsep + os.environ.get("PATH", "")
    return any((b / "cublas64_12.dll").is_file() for b in bin_dirs)
