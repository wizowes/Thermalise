# -*- mode: python ; coding: utf-8 -*-
#
# Single-file EXE for Thermalise.
#
# Build:
#   pyinstaller Thermalise.spec
#
# Modes:
#   Thermalise.exe          -> system tray app (email watcher + auto-print)
#   Thermalise.exe --gui    -> manual label tool (full GUI)

a = Analysis(
    ['vinted4x6_tray.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # pystray Windows backend
        'pystray._win32',
        # PIL/tkinter glue sometimes missed
        'PIL._tkinter_finder',
        # email stdlib modules not always auto-detected
        'email.mime.multipart',
        'email.mime.text',
        'imaplib',
    ],
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
    a.binaries,
    a.datas,
    [],
    name='Thermalise',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
