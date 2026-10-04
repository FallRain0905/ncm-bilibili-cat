# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

project = Path(SPECPATH)

analysis = Analysis(
    [str(project / "music_cat_app.py")],
    pathex=[str(project)],
    binaries=[
        (str(project / "ncmdump" / "tools" / "ncmdump-1.5.1" / "ncmdump.exe"), "bin"),
        (str(project / "tools" / "ffmpeg-9.0.2-essentials_build" / "bin" / "ffmpeg.exe"), "bin"),
        (str(project / "tools" / "ffmpeg-9.0.2-essentials_build" / "bin" / "ffprobe.exe"), "bin"),
    ],
    datas=[],
    hiddenimports=["tkinterdnd2", "yt_dlp"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="MusicCat",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(project / "assets" / "icon.ico"),
)
coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="MusicCat",
)
