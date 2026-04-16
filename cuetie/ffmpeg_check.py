from __future__ import annotations
import subprocess
import shutil
from dataclasses import dataclass


@dataclass
class FFmpegInfo:
    found: bool
    path: str
    version: str
    codecs: set[str]


def check_ffmpeg() -> FFmpegInfo:
    path = shutil.which("ffmpeg")
    if not path:
        return FFmpegInfo(found=False, path="", version="", codecs=set())

    try:
        r = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, text=True, timeout=5,
        )
        version_line = r.stdout.splitlines()[0] if r.stdout else ""
        version = version_line.replace("ffmpeg version ", "").split(" ")[0]
    except Exception:
        return FFmpegInfo(found=False, path=path, version="", codecs=set())

    codecs = _probe_codecs()
    return FFmpegInfo(found=True, path=path, version=version, codecs=codecs)


def _probe_codecs() -> set[str]:
    try:
        r = subprocess.run(
            ["ffmpeg", "-encoders"],
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
