from __future__ import annotations
import os
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass
from typing import Callable, Optional

from .cue_parser import AlbumInfo, TrackInfo, FileEntry
from .ffmpeg_check import ffmpeg_path


@dataclass
class OutputSettings:
    output_dir: str = ""
    fmt: str = "flac"
    flac_compression: int = 5
    mp3_bitrate: int = 320
    ogg_quality: float = 8.0
    opus_bitrate: int = 256
    embed_cover: bool = True
    filename_template: str = "{track:02d} {title}"


@dataclass
class Job:
    album: AlbumInfo
    settings: OutputSettings


@dataclass
class _Task:
    task_id: int
    job_index: int
    album: AlbumInfo
    settings: OutputSettings
    track: TrackInfo
    src: str
    out_path: str
    start_sec: float
    end_sec: Optional[float]


# (done_count, total, current_title, fraction, message)
ProgressCallback = Callable[[int, int, str, float, str], None]

# (task_id, album_tag, track_title)
TaskStartCallback = Callable[[int, str, str], None]

# (task_id, status)  status in {"ok","fail","cancelled"}
TaskEndCallback = Callable[[int, str], None]


class ProcessingCancelled(Exception):
    pass


class BatchProcessor:
    """
    Process one or many (AlbumInfo, OutputSettings) jobs.

    workers == 1 behaves as a FIFO queue. workers > 1 runs that
    many ffmpeg subprocesses in parallel across all pending tasks.
    """

    def __init__(
        self,
        jobs: list[Job],
        on_progress: ProgressCallback,
        on_done: Callable[[bool, str], None],
        workers: int = 1,
        on_task_start: Optional[TaskStartCallback] = None,
        on_task_end: Optional[TaskEndCallback] = None,
    ):
        self.jobs = jobs
        self.on_progress = on_progress
        self.on_done = on_done
        self.on_task_start = on_task_start
        self.on_task_end = on_task_end
        self.workers = max(1, workers)
        self._cancel = threading.Event()
        self._running: dict[int, subprocess.Popen] = {}
        self._running_lock = threading.Lock()
        self._cancelled_ids: set[int] = set()
        self._done_count = 0
        self._done_lock = threading.Lock()
        self._ok_count = 0
        self._fail_count = 0
        self._cancel_count = 0

    def start(self) -> None:
        self._cancel.clear()
        threading.Thread(target=self._run, daemon=True).start()

    def cancel(self) -> None:
        """Kill every running ffmpeg subprocess and stop the batch."""
        self._cancel.set()
        with self._running_lock:
            for p in list(self._running.values()):
                try:
                    p.terminate()
                except Exception:
                    pass

    def cancel_task(self, task_id: int) -> bool:
        """Kill a single running worker. Remaining tasks continue."""
        self._cancelled_ids.add(task_id)
        with self._running_lock:
            proc = self._running.get(task_id)
        if proc is None:
            return False
        try:
            proc.terminate()
        except Exception:
            return False
        return True

    def _run(self) -> None:
        try:
            tasks = self._build_tasks()
            total = len(tasks)
            if total == 0:
                self.on_done(True, "No tracks selected.")
                return
            self._execute(tasks, total)
            if self._cancel.is_set():
                self.on_done(
                    False,
                    f"Cancelled after {self._done_count}/{total}.",
                )
                return
            parts = [f"{self._ok_count} ok"]
            if self._fail_count:
                parts.append(f"{self._fail_count} failed")
            if self._cancel_count:
                parts.append(f"{self._cancel_count} cancelled")
            msg = f"Done: {', '.join(parts)} ({len(self.jobs)} cue)"
            self.on_done(self._fail_count == 0 and self._cancel_count == 0, msg)
        except Exception as e:
            self.on_done(False, f"Error: {e}")

    def _build_tasks(self) -> list[_Task]:
        tasks: list[_Task] = []
        next_id = 0
        for idx, job in enumerate(self.jobs):
            album = job.album
            settings = job.settings
            out_dir = settings.output_dir or album.output_dir
            if not out_dir:
                self._log(f"Skip {album.title or album.cue_path}: no output dir")
                continue
            os.makedirs(out_dir, exist_ok=True)

            track_to_file: dict[int, FileEntry] = {
                t.number: fe for fe in album.files for t in fe.tracks
            }
            selected = [
                t for t in album.all_tracks
                if t.selected and t.datatype == "AUDIO"
            ]
            for track in selected:
                fe = track_to_file.get(track.number)
                if fe is None:
                    self._log(f"Skip {track.number}: no file entry")
                    continue
                src = fe.filename
                if not os.path.exists(src):
                    self._log(f"Source not found: {src}")
                    continue
                siblings = fe.tracks
                i = next(
                    (i for i, t in enumerate(siblings)
                     if t.number == track.number),
                    None,
                )
                start_sec = track.start_seconds
                end_sec = (
                    siblings[i + 1].start_seconds
                    if i is not None and i < len(siblings) - 1
                    else None
                )
                name = _format_filename(track, album, settings.filename_template)
                out_path = os.path.join(out_dir, name + "." + settings.fmt)
                tasks.append(_Task(
                    task_id=next_id,
                    job_index=idx,
                    album=album,
                    settings=settings,
                    track=track,
                    src=src,
                    out_path=out_path,
                    start_sec=start_sec,
                    end_sec=end_sec,
                ))
                next_id += 1
        return tasks

    def _execute(self, tasks: list[_Task], total: int) -> None:
        if self.workers == 1:
            for task in tasks:
                if self._cancel.is_set():
                    break
                self._run_task(task, total)
            return

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures: list[Future] = [
                pool.submit(self._run_task, task, total) for task in tasks
            ]
            for f in futures:
                try:
                    f.result()
                except Exception as e:
                    self._log(f"Worker error: {e}")

    def _run_task(self, task: _Task, total: int) -> None:
        if self._cancel.is_set():
            return
        title = task.track.title or f"Track {task.track.number}"
        album_tag = task.album.title or os.path.basename(task.album.cue_path) or "cue"

        if task.task_id in self._cancelled_ids:
            status = "cancelled"
            ok = False
        else:
            if self.on_task_start:
                try:
                    self.on_task_start(task.task_id, album_tag, title)
                except Exception:
                    pass
            self._log(f"→ [{album_tag}] {title}")
            ok = self._cut(task)
            cancelled = task.task_id in self._cancelled_ids
            if cancelled:
                status = "cancelled"
                ok = False
            else:
                status = "ok" if ok else "fail"

        if self.on_task_end:
            try:
                self.on_task_end(task.task_id, status)
            except Exception:
                pass

        with self._done_lock:
            self._done_count += 1
            if status == "ok":
                self._ok_count += 1
            elif status == "cancelled":
                self._cancel_count += 1
            else:
                self._fail_count += 1
            done = self._done_count
        frac = done / total if total else 1.0
        label = {"ok": "OK", "fail": "FAIL", "cancelled": "CANCELLED"}[status]
        self.on_progress(
            done, total, f"{album_tag} · {title}", frac,
            f"{label}: {title}",
        )

    def _cut(self, task: _Task) -> bool:
        s = task.settings
        ff = ffmpeg_path() or "ffmpeg"
        cmd = [ff, "-y", "-i", task.src, "-ss", f"{task.start_sec:.6f}"]
        if task.end_sec is not None and task.end_sec > task.start_sec:
            cmd += ["-t", f"{task.end_sec - task.start_sec:.6f}"]

        fmt = s.fmt
        if fmt == "flac":
            cmd += ["-c:a", "flac", "-compression_level", str(s.flac_compression)]
        elif fmt == "mp3":
            cmd += ["-c:a", "libmp3lame", "-b:a", f"{s.mp3_bitrate}k",
                    "-id3v2_version", "3"]
        elif fmt == "ogg":
            cmd += ["-c:a", "libvorbis", "-q:a", f"{s.ogg_quality:.1f}"]
        elif fmt == "opus":
            cmd += ["-c:a", "libopus", "-b:a", f"{s.opus_bitrate}k"]
        elif fmt == "wav":
            cmd += ["-c:a", "pcm_s16le"]

        for k, v in _metadata(task.track, task.album).items():
            cmd += ["-metadata", f"{k}={v}"]

        cmd += ["-map_metadata", "-1", "-map", "0:a", task.out_path]
        self._log("$ " + " ".join(cmd))

        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                universal_newlines=True,
            )
        except FileNotFoundError:
            self._log("ERROR: ffmpeg not found in PATH")
            return False
        except Exception as e:
            self._log(f"ERROR: {e}")
            return False

        with self._running_lock:
            self._running[task.task_id] = proc
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                if self._cancel.is_set() or task.task_id in self._cancelled_ids:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    break
                stripped = line.rstrip()
                if stripped:
                    self._log(stripped)
            proc.wait()
        finally:
            with self._running_lock:
                self._running.pop(task.task_id, None)

        if self._cancel.is_set() or task.task_id in self._cancelled_ids:
            return False
        if proc.returncode != 0:
            self._log(f"ffmpeg exited {proc.returncode}")
            return False

        if s.embed_cover and task.album.cover_path:
            _embed_cover(task.out_path, task.album.cover_path, s.fmt, self._log)

        return True

    def _log(self, msg: str) -> None:
        self.on_progress(-1, -1, "", -1.0, msg)


def _metadata(track: TrackInfo, album: AlbumInfo) -> dict[str, str]:
    raw = {
        "title":          track.title,
        "artist":         track.performer or album.performer,
        "album":          album.title,
        "album_artist":   album.performer,
        "composer":       track.songwriter or album.songwriter,
        "genre":          album.genre,
        "date":           album.date,
        "comment":        album.comment,
        "track":          str(track.number),
        "isrc":           track.isrc,
        "catalog_number": album.catalog,
    }
    return {k: v for k, v in raw.items() if v}


def _format_filename(
    track: TrackInfo, album: AlbumInfo, template: str
) -> str:
    def safe(s: str) -> str:
        return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s).strip(". ")
    try:
        return template.format(
            track=track.number,
            title=safe(track.title),
            artist=safe(track.performer or album.performer),
            album=safe(album.title),
        )
    except (KeyError, ValueError):
        return f"{track.number:02d}"


def _embed_cover(
    audio_path: str, cover_path: str, fmt: str,
    log: Callable[[str], None],
) -> None:
    if not cover_path or not os.path.exists(cover_path):
        return
    try:
        import base64
        with open(cover_path, "rb") as f:
            img_data = f.read()
        mime = "image/png" if cover_path.lower().endswith(".png") else "image/jpeg"

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
        log("mutagen not installed — cover skipped")
    except Exception as e:
        log(f"Cover embed failed: {e}")


# Backward-compatible single-album wrapper.
class Processor:
    def __init__(
        self,
        album: AlbumInfo,
        settings: OutputSettings,
        on_progress: ProgressCallback,
        on_done: Callable[[bool, str], None],
    ):
        self._batch = BatchProcessor(
            jobs=[Job(album=album, settings=settings)],
            on_progress=on_progress,
            on_done=on_done,
            workers=1,
        )

    def start(self) -> None:
        self._batch.start()

    def cancel(self) -> None:
        self._batch.cancel()
