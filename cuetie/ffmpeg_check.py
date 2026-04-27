from __future__ import annotations
import os
import sys
import subprocess
import shutil
from dataclasses import dataclass


@dataclass
class FFmpegInfo:
    found: bool
    path: str
    version: str
    codecs: set[str]


def _candidate_dirs() -> list[str]:
    dirs: list[str] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(meipass)
        dirs.append(os.path.join(meipass, "ffmpeg"))
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        dirs.append(exe_dir)
        dirs.append(os.path.join(exe_dir, "ffmpeg"))
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    dirs.append(os.path.join(pkg_dir, "_ffmpeg"))
    return dirs


def ffmpeg_path() -> str:
    """Return path to bundled ffmpeg if present, else PATH lookup, else ''."""
    for d in _candidate_dirs():
        candidate = os.path.join(d, "ffmpeg")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK | os.R_OK):
            return candidate
    return shutil.which("ffmpeg") or ""


def check_ffmpeg() -> FFmpegInfo:
    path = ffmpeg_path()
    if not path:
        return FFmpegInfo(found=False, path="", version="", codecs=set())

    try:
        r = subprocess.run(
            [path, "-version"],
            capture_output=True, text=True, timeout=5,
        )
        version_line = r.stdout.splitlines()[0] if r.stdout else ""
        version = version_line.replace("ffmpeg version ", "").split(" ")[0]
    except Exception:
        return FFmpegInfo(found=False, path=path, version="", codecs=set())

    codecs = _probe_codecs(path)
    return FFmpegInfo(found=True, path=path, version=version, codecs=codecs)


def _probe_codecs(path: str) -> set[str]:
    try:
        r = subprocess.run(
            [path, "-encoders"],
            capture_output=True, text=True, timeout=5,
        )
        found: set[str] = set()
        for line in r.stdout.splitlines():
            line = line.strip()
            for name in ("flac", "libmp3lame", "libvorbis", "libopus", "pcm_s16le"):
                if name in line:
                    found.add(name)
        return found
    except Exception:
        return set()


FORMAT_CODEC = {
    "flac": "flac",
    "mp3":  "libmp3lame",
    "ogg":  "libvorbis",
    "opus": "libopus",
    "wav":  "pcm_s16le",
}


def missing_codecs(info: FFmpegInfo, fmt: str) -> list[str]:
    needed = FORMAT_CODEC.get(fmt)
    if not needed:
        return []
    if needed not in info.codecs:
        return [needed]
    return []
