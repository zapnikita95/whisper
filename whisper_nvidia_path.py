"""
Windows: добавить в PATH все каталоги …/nvidia/*/bin с DLL (cuBLAS, cuDNN и т.д.).
Нужен и для whisper_server (exe), и для WhisperHotkey (exe), и для запуска из venv.
"""
from __future__ import annotations

import os
import site
import sys
from pathlib import Path


def prepend_nvidia_cuda_bin_dirs_to_path() -> tuple[int, bool]:
    """
    Возвращает (сколько каталогов добавлено в начало PATH, найден ли cublas64_12.dll среди них).
    На не-Windows — (0, True).
    """
    if sys.platform != "win32":
        return 0, True

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

    bin_paths: list[str] = []
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        nvidia = root / "nvidia"
        if not nvidia.is_dir():
            continue
        try:
            subs = sorted(nvidia.iterdir())
        except OSError:
            continue
        for sub in subs:
            bd = sub / "bin"
            if not bd.is_dir():
                continue
            try:
                if not any(bd.glob("*.dll")):
                    continue
                rs = str(bd.resolve())
            except OSError:
                continue
            if rs in seen:
                continue
            seen.add(rs)
            bin_paths.append(rs)

    cublas_ok = False
    for p in bin_paths:
        try:
            if (Path(p) / "cublas64_12.dll").is_file():
                cublas_ok = True
                break
        except OSError:
            pass

    if bin_paths:
        os.environ["PATH"] = os.pathsep.join(bin_paths) + os.pathsep + os.environ.get("PATH", "")

    return len(bin_paths), cublas_ok
