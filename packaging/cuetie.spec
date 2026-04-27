# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for CUEtie (GTK3 + PyGObject).

Build:
    pyinstaller packaging/cuetie.spec --noconfirm

Bundles binaries placed under packaging/_ffmpeg/ before invocation
(ffmpeg, ffprobe, plus .exe variants on Windows).
"""
from __future__ import annotations
import os
from pathlib import Path

block_cipher = None

ROOT = Path(SPECPATH).resolve().parent
FFMPEG_DIR = ROOT / "packaging" / "_ffmpeg"
ENTRY = str(ROOT / "packaging" / "cuetie_launcher.py")

binaries: list[tuple[str, str]] = []
if FFMPEG_DIR.is_dir():
    for name in os.listdir(FFMPEG_DIR):
        full = FFMPEG_DIR / name
        if full.is_file():
            binaries.append((str(full), "."))

datas: list[tuple[str, str]] = []

hiddenimports = [
    "gi",
    "gi._gi",
    "gi.repository.Gtk",
    "gi.repository.Gdk",
    "gi.repository.GLib",
    "gi.repository.Gio",
    "gi.repository.GObject",
    "gi.repository.Pango",
    "gi.repository.GdkPixbuf",
    "mutagen",
    "mutagen.flac",
    "mutagen.id3",
    "mutagen.oggvorbis",
    "mutagen.oggopus",
    "charset_normalizer",
    "cuetie",
    "cuetie.cue_parser",
    "cuetie.ffmpeg_check",
    "cuetie.processor",
    "cuetie.ui",
    "cuetie.ui.main_window",
    "cuetie.ui.track_detail",
    "cuetie.ui.workers_panel",
]

try:
    from PyInstaller.utils.hooks import collect_all
    for pkg in ("gi",):
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
except Exception:
    pass

a = Analysis(
    [ENTRY],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="cuetie",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="cuetie",
)
