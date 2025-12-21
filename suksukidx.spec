# -*- mode: python ; coding: utf-8 -*-

aimport = __import__
import os
from pathlib import Path

ROOT = Path(SPECPATH).resolve()
UI = ROOT / "backend" / "ui"
BIN = ROOT / "backend" / "bin"

# Ensure build/dist are always created under project ROOT,
# regardless of where PyInstaller is invoked from (prevents dist/dist, dist/build nesting).
os.chdir(str(ROOT))

a_datas = [
    (str(UI / "index.html"),    "backend/ui"),
    (str(UI / "master.js"),     "backend/ui"),
    (str(UI / "toolbar.js"),    "backend/ui"),
    (str(UI / "ui.css"),        "backend/ui"),
    (str(UI / "publish.css"),   "backend/ui"),
    (str(UI / "suksukidx.ico"), "backend/ui"),
    # Native tools (portable)
    (str(BIN / "ffmpeg.exe"), "backend/bin"),
    (str(BIN / "poppler"),   "backend/bin/poppler"),
]

a = Analysis(
    ['backend\\app.py'],
    pathex=[str(ROOT)],
    binaries=[],
    datas=a_datas,
    hiddenimports=[],
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
    name='suksukidx',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(UI / "suksukidx.ico"),
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
    name='suksukidx',
)
