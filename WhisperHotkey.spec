# -*- mode: python ; coding: utf-8 -*-
# distpath/workpath задавай в packaging\build-hotkey-gui-exe.bat (--distpath dist\.whisper_hotkey_stage).
from PyInstaller.utils.hooks import collect_all

datas = [('packaging\\VERSION', 'packaging'), ('assets\\app_icon.ico', 'assets')]
binaries = []
hiddenimports = ['whisper_hotkey_core', 'whisper_hotkey_tray', 'whisper_models', 'whisper_file_log', 'speaker_verify', 'faster_whisper', 'whisper_version', 'keyboard', 'pyaudio', 'pyperclip', 'soundfile', 'numpy', 'plyer.platforms.win.notification', 'pystray', 'PIL', 'PIL.Image']
tmp_ret = collect_all('torch')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('resemblyzer')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['whisper_hotkey_tray.py'],
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

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='WhisperHotkey',
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
    icon=['assets\\app_icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='WhisperHotkey',
)
