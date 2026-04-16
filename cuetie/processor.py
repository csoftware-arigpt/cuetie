from __future__ import annotations
import os
import re
import subprocess
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from .cue_parser import AlbumInfo, TrackInfo, FileEntry


@dataclass
class OutputSettings:
    output_dir: str
    fmt: str = "flac"
    flac_compression: int = 5
    mp3_bitrate: int = 320
    ogg_quality: float = 8.0
    opus_bitrate: int = 256
    embed_cover: bool = True
    filename_template: str = "{track:02d} {title}"


ProgressCallback = Callable[[int, int, str, float, str], None]


class ProcessingCancelled(Exception):
    pass


class Processor:
    def __init__(self, album: AlbumInfo, settings: OutputSettings,
                 on_progress: ProgressCallback,
                 on_done: Callable[[bool, str], None]):
        self.album = album
        self.settings = settings
        self.on_progress = on_progress
        self.on_done = on_done
        self._cancel = threading.Event()

    def start(self):
        self._cancel.clear()
        threading.Thread(target=self._run, daemon=True).start()

    def cancel(self):
        self._cancel.set()

    def _run(self):
        try:
            self._process()
            self.on_done(True, "Done.")
        except ProcessingCancelled:
            self.on_done(False, "Cancelled.")
        except Exception as e:
            self.on_done(False, str(e))

    def _process(self):
        os.makedirs(self.settings.output_dir, exist_ok=True)

        selected = [t for t in self.album.all_tracks
                    if t.selected and t.datatype == "AUDIO"]
        total = len(selected)
        if total == 0:
            return

        track_to_file: dict[int, FileEntry] = {
            t.number: fe
            for fe in self.album.files
            for t in fe.tracks
        }
        file_tracks: dict[str, list[TrackInfo]] = {
            fe.filename: fe.tracks for fe in self.album.files
        }

        for done, track in enumerate(selected):
            if self._cancel.is_set():
                raise ProcessingCancelled()

            fe = track_to_file.get(track.number)
            if fe is None:
                self._log(f"Skip {track.number}: no file entry")
                continue

            src = fe.filename
            if not os.path.exists(src):
                self._log(f"Source not found: {src}")
                self.on_progress(done + 1, total, track.title,
                                 (done + 1) / total, f"SKIP {track.title}")
                continue

            siblings = file_tracks[fe.filename]
            idx_in_file = next(
                (i for i, t in enumerate(siblings) if t.number == track.number), None
            )
            start_sec = track.start_seconds
            end_sec = (siblings[idx_in_file + 1].start_seconds
                       if idx_in_file is not None and idx_in_file < len(siblings) - 1
                       else None)

            out_path = os.path.join(
                self.settings.output_dir,
                self._filename(track) + "." + self.settings.fmt,
            )

            self.on_progress(done, total, track.title, done / total,
                             f"Processing: {track.title}")

            ok = self._cut(src, out_path, track, start_sec, end_sec)

            self.on_progress(done + 1, total, track.title, (done + 1) / total,
                             f"{'OK' if ok else 'FAIL'}: {track.title}")

    def _cut(self, src: str, out: str, track: TrackInfo,
             start: float, end: Optional[float]) -> bool:
        cmd = ["ffmpeg", "-y", "-i", src, "-ss", f"{start:.6f}"]
        if end is not None and end > start:
            cmd += ["-t", f"{end - start:.6f}"]

        fmt = self.settings.fmt
        if fmt == "flac":
            cmd += ["-c:a", "flac", "-compression_level",
                    str(self.settings.flac_compression)]
        elif fmt == "mp3":
            cmd += ["-c:a", "libmp3lame", "-b:a",
                    f"{self.settings.mp3_bitrate}k", "-id3v2_version", "3"]
        elif fmt == "ogg":
            cmd += ["-c:a", "libvorbis", "-q:a",
                    f"{self.settings.ogg_quality:.1f}"]
        elif fmt == "opus":
            cmd += ["-c:a", "libopus", "-b:a",
                    f"{self.settings.opus_bitrate}k"]
        elif fmt == "wav":
            cmd += ["-c:a", "pcm_s16le"]

        for k, v in self._metadata(track).items():
            cmd += ["-metadata", f"{k}={v}"]

        cmd += ["-map_metadata", "-1", "-map", "0:a", out]
        self._log("$ " + " ".join(cmd))

        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                universal_newlines=True,
            )
            for line in proc.stdout:  # type: ignore[union-attr]
                if self._cancel.is_set():
                    proc.terminate()
                    raise ProcessingCancelled()
                self._log(line.rstrip())
            proc.wait()
        except ProcessingCancelled:
            raise
        except FileNotFoundError:
            self._log("ERROR: ffmpeg not found in PATH")
            return False
        except Exception as e:
            self._log(f"ERROR: {e}")
            return False

        if proc.returncode != 0:
            self._log(f"ffmpeg exited {proc.returncode}")
            return False

        if self.settings.embed_cover and self.album.cover_path:
            self._embed_cover(out)

        return True

    def _metadata(self, track: TrackInfo) -> dict[str, str]:
        a = self.album
        raw = {
            "title":         track.title,
            "artist":        track.performer or a.performer,
            "album":         a.title,
            "album_artist":  a.performer,
            "composer":      track.songwriter or a.songwriter,
            "genre":         a.genre,
            "date":          a.date,
            "comment":       a.comment,
            "track":         str(track.number),
            "isrc":          track.isrc,
            "catalog_number": a.catalog,
        }
        return {k: v for k, v in raw.items() if v}

    def _embed_cover(self, audio_path: str):
        cover = self.album.cover_path
        if not cover or not os.path.exists(cover):
            return
        try:
            import base64
            with open(cover, "rb") as f:
                img_data = f.read()
            mime = "image/png" if cover.lower().endswith(".png") else "image/jpeg"
            fmt = self.settings.fmt

            if fmt == "flac":
                from mutagen.flac import FLAC, Picture
                audio = FLAC(audio_path)
                pic = Picture()
                pic.type, pic.mime, pic.data = 3, mime, img_data
                audio.clear_pictures()
                audio.add_picture(pic)
                audio.save()

            elif fmt == "mp3":
                from mutagen.id3 import ID3, APIC, error as ID3Error
                try:
                    audio = ID3(audio_path)
                except ID3Error:
                    audio = ID3()
                audio.delall("APIC")
                audio.add(APIC(encoding=3, mime=mime, type=3,
                               desc="Cover", data=img_data))
                audio.save(audio_path)

            elif fmt in ("ogg", "opus"):
                from mutagen.flac import Picture
                from mutagen.oggvorbis import OggVorbis
                from mutagen.oggopus import OggOpus
                pic = Picture()
                pic.data, pic.type, pic.mime = img_data, 3, mime
                pic.width = pic.height = pic.depth = pic.colors = 0
                block = base64.b64encode(pic.write()).decode("ascii")
                audio = OggVorbis(audio_path) if fmt == "ogg" else OggOpus(audio_path)
                audio["metadata_block_picture"] = [block]
                audio.save()

        except ImportError:
            self._log("mutagen not installed — cover skipped")
        except Exception as e:
            self._log(f"Cover embed failed: {e}")

    def _filename(self, track: TrackInfo) -> str:
        def safe(s: str) -> str:
            return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s).strip(". ")
        tpl = self.settings.filename_template
        try:
            return tpl.format(
                track=track.number,
                title=safe(track.title),
                artist=safe(track.performer or self.album.performer),
                album=safe(self.album.title),
            )
        except (KeyError, ValueError):
            return f"{track.number:02d}"

    def _log(self, msg: str):
        self.on_progress(-1, -1, "", -1.0, msg)
