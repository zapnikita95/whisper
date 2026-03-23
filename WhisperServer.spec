# -*- mode: python ; coding: utf-8 -*-
# distpath/workpath задаёт packaging\build-server-gui-exe.bat (--distpath dist\.whisper_stage).
# Без nvidia/*/dll в _internal: RuntimeError cublas64_12.dll при POST /transcribe (как WhisperHotkey.spec).
import sysconfig
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

_pylib = Path(sysconfig.get_paths()["purelib"])
datas = [("packaging\\VERSION", "packaging")]
_icon = Path("assets/app_icon.ico")
if _icon.is_file():
    datas.append((str(_icon), "assets"))

for _nv_sub in ("cublas", "cudnn", "cusparse", "cufft", "curand", "nvjitlink"):
    _p = _pylib / "nvidia" / _nv_sub
    if _p.is_dir():
        datas.append((str(_p), f"nvidia/{_nv_sub}"))

binaries: list = []
hiddenimports = [
    "whisper_server",
    "whisper_models",
    "whisper_file_log",
    "whisper_nvidia_path",
    "faster_whisper",
    "whisper_version",
    "whisper_update_check",
    "speaker_verify",
]

for _pkg in ("uvicorn", "fastapi", "starlette"):
    _tmp = collect_all(_pkg)
    datas += _tmp[0]
    binaries += _tmp[1]
    hiddenimports += _tmp[2]

a = Analysis(
    ["whisper_server_gui.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if _icon.is_file():
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="WhisperServer",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=[str(_icon)],
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="WhisperServer",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="WhisperServer",
)
