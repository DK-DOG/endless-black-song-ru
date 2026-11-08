# -*- mode: python ; coding: utf-8 -*-
"""Build recipe for the Russian-patch installer exe.

The exe is the same program as src/install.py plus the payload folder.
Nothing here is hidden: PyInstaller only packs those sources.
"""

from pathlib import Path

root = Path(SPECPATH)

a = Analysis(
    [str(root / "src" / "install.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=[(str(root / "payload"), "payload")],
    hiddenimports=["tkinter", "tkinter.filedialog", "tkinter.messagebox"],
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
    name="Русификатор Endless Black Song",
    icon=str(root / "icon.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
