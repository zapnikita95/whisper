"""
Windows: CTranslate2 / faster-whisper ищут cublas64_12.dll и соседние NVIDIA DLL.

Тонкая обёртка над whisper_nvidia_path (единый код PATH + add_dll_directory).
"""
from __future__ import annotations

from whisper_nvidia_path import (
    ensure_cuda_dlls_on_path,
    prepend_nvidia_cuda_bin_dirs_to_path,
)


def prepend_nvidia_cuda_bins_to_path() -> bool:
    """Добавляет nvidia/*/bin в PATH (+ add_dll_directory). True если есть cublas64_12.dll."""
    _n, ok = prepend_nvidia_cuda_bin_dirs_to_path()
    return bool(ok)


__all__ = [
    "ensure_cuda_dlls_on_path",
    "prepend_nvidia_cuda_bins_to_path",
    "prepend_nvidia_cuda_bin_dirs_to_path",
]
