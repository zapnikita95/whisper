"""
Windows: добавить в PATH все каталоги …/nvidia/*/bin с DLL (cuBLAS, cuDNN и т.д.).
Нужен и для whisper_server (exe), и для WhisperHotkey (exe), и для запуска из venv.

На Python 3.8+ одного PATH мало: LoadLibrary для нативных модулей часто требует
os.add_dll_directory — иначе CTranslate2 падает с «cublas64_12.dll is not found»
и распознавание уходит в CPU на десятки минут.
"""
from __future__ import annotations

import os
import site
import sys
from pathlib import Path

_DLL_DIRS_ADDED: set[str] = set()


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        meip = getattr(sys, "_MEIPASS", None)
        if meip:
            roots.append(Path(meip))
        roots.append(exe_dir / "_internal")
        roots.append(exe_dir)
    # When launching base pythonw + venv site-packages via PYTHONPATH / VIRTUAL_ENV
    # (Windows venv Scripts\\pythonw.exe is a stub), site.getsitepackages() misses the venv.
    venv = (os.environ.get("VIRTUAL_ENV") or "").strip()
    if venv:
        roots.append(Path(venv) / "Lib" / "site-packages")
    for part in (os.environ.get("PYTHONPATH") or "").split(os.pathsep):
        p = (part or "").strip()
        if p:
            roots.append(Path(p))
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


def prepend_nvidia_cuda_bin_dirs_to_path() -> tuple[int, bool]:
    """
    Возвращает (сколько каталогов добавлено в начало PATH, найден ли cublas64_12.dll среди них).
    На не-Windows — (0, True).
    """
    if sys.platform != "win32":
        return 0, True

    bin_paths: list[str] = []
    seen: set[str] = set()
    for root in _candidate_roots():
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
        for p in bin_paths:
            if p in _DLL_DIRS_ADDED:
                continue
            try:
                os.add_dll_directory(p)
                _DLL_DIRS_ADDED.add(p)
            except (OSError, AttributeError):
                pass

    return len(bin_paths), cublas_ok


def ensure_cuda_dlls_on_path() -> bool:
    """Call once at process start (before faster-whisper / CTranslate2)."""
    _n, ok = prepend_nvidia_cuda_bin_dirs_to_path()
    return bool(ok)
