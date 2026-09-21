# -*- mode: python ; coding: utf-8 -*-
"""Portable onedir build: copy dist/WinAutoTest to a USB stick and double-click."""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH)
AMCAP = ROOT / "amcap+v3.0.9.exe"

datas = []
binaries = []
hiddenimports = [
    "app_paths",
    "audio_test",
    "camera_test",
    "i18n",
    "report",
    "scan_test",
    "serial_led",
    "serial",
    "serial.tools.list_ports",
    "sounddevice",
    "numpy",
]

sd_datas, sd_binaries, sd_hidden = collect_all("sounddevice")
datas += sd_datas
binaries += sd_binaries
hiddenimports += sd_hidden

if AMCAP.is_file():
    datas.append((str(AMCAP), "."))

a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "unittest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WinAutoTest",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="WinAutoTest",
)
