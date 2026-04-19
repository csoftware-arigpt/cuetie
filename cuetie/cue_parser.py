from __future__ import annotations
import re
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class IndexEntry:
    number: int
    time: str


@dataclass
class TrackInfo:
    number: int
    datatype: str
    title: str = ""
    performer: str = ""
    songwriter: str = ""
    isrc: str = ""
    flags: list[str] = field(default_factory=list)
    pregap: Optional[str] = None
    postgap: Optional[str] = None
    indexes: list[IndexEntry] = field(default_factory=list)
    selected: bool = True

    @property
    def start_time(self) -> str:
        for idx in self.indexes:
            if idx.number == 1:
                return idx.time
        return self.indexes[0].time if self.indexes else "00:00:00"

    @property
    def start_seconds(self) -> float:
        return cue_time_to_seconds(self.start_time)


@dataclass
class FileEntry:
    filename: str
    filetype: str
    tracks: list[TrackInfo] = field(default_factory=list)


@dataclass
class AlbumInfo:
    title: str = ""
    performer: str = ""
    songwriter: str = ""
    catalog: str = ""
    cdtextfile: str = ""
    rem: dict[str, str] = field(default_factory=dict)
    files: list[FileEntry] = field(default_factory=list)
    cover_path: Optional[str] = None
    cue_path: str = ""
    output_dir: str = ""

    @property
    def genre(self) -> str:
        return self.rem.get("GENRE", "")

    @property
    def date(self) -> str:
        return self.rem.get("DATE", "")

    @property
    def discid(self) -> str:
        return self.rem.get("DISCID", "")

    @property
    def comment(self) -> str:
        return self.rem.get("COMMENT", "")

    @property
    def all_tracks(self) -> list[TrackInfo]:
        return [t for fe in self.files for t in fe.tracks]


def cue_time_to_seconds(time_str: str) -> float:
    parts = time_str.strip().split(":")
    if len(parts) != 3:
        return 0.0
    mm, ss, ff = int(parts[0]), int(parts[1]), int(parts[2])
    return mm * 60 + ss + ff / 75.0


_RE_CATALOG    = re.compile(r'^CATALOG\s+(\S+)', re.I)
_RE_CDTEXTFILE = re.compile(r'^CDTEXTFILE\s+"([^"]+)"', re.I)
_RE_FILE       = re.compile(r'^FILE\s+"([^"]+)"\s+(\S+)', re.I)
_RE_TRACK      = re.compile(r'^TRACK\s+(\d+)\s+(\S+)', re.I)
_RE_FLAGS      = re.compile(r'^FLAGS\s+(.*)', re.I)
_RE_ISRC       = re.compile(r'^ISRC\s+(\S+)', re.I)
_RE_PERFORMER  = re.compile(r'^PERFORMER\s+"([^"]*)"', re.I)
_RE_SONGWRITER = re.compile(r'^SONGWRITER\s+"([^"]*)"', re.I)
_RE_TITLE      = re.compile(r'^TITLE\s+"([^"]*)"', re.I)
_RE_PREGAP     = re.compile(r'^PREGAP\s+(\d+:\d+:\d+)', re.I)
_RE_POSTGAP    = re.compile(r'^POSTGAP\s+(\d+:\d+:\d+)', re.I)
_RE_INDEX      = re.compile(r'^INDEX\s+(\d+)\s+(\d+:\d+:\d+)', re.I)
_RE_REM        = re.compile(r'^REM\s+(\S+)\s+(.*)', re.I)


def parse_cue(cue_path: str) -> AlbumInfo:
    lines = _read_cue(cue_path)
    abs_cue = os.path.abspath(cue_path)
    album = AlbumInfo(cue_path=abs_cue)
    cue_dir = os.path.dirname(abs_cue)
    current_file: Optional[FileEntry] = None
    current_track: Optional[TrackInfo] = None
    in_track = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        m = _RE_REM.match(line)
        if m:
            if not in_track:
                album.rem[m.group(1).upper()] = m.group(2).strip().strip('"')
            continue

        m = _RE_FILE.match(line)
        if m:
            if current_track and current_file:
                current_file.tracks.append(current_track)
                current_track = None
            if current_file:
                album.files.append(current_file)
            in_track = False
            abs_path = os.path.join(cue_dir, m.group(1))
            current_file = FileEntry(
                filename=abs_path if os.path.exists(abs_path) else m.group(1),
                filetype=m.group(2).upper(),
            )
            continue

        m = _RE_TRACK.match(line)
        if m:
            if current_track and current_file:
                current_file.tracks.append(current_track)
            in_track = True
            current_track = TrackInfo(
                number=int(m.group(1)),
                datatype=m.group(2).upper(),
                performer=album.performer,
                songwriter=album.songwriter,
            )
            continue

        if not in_track and current_file is None:
            m = _RE_CATALOG.match(line)
            if m:
                album.catalog = m.group(1)
                continue
            m = _RE_CDTEXTFILE.match(line)
            if m:
                album.cdtextfile = m.group(1)
                continue
            m = _RE_PERFORMER.match(line)
            if m:
                album.performer = m.group(1)
                continue
            m = _RE_SONGWRITER.match(line)
            if m:
                album.songwriter = m.group(1)
                continue
            m = _RE_TITLE.match(line)
            if m:
                album.title = m.group(1)
                continue

        if in_track and current_track is not None:
            m = _RE_TITLE.match(line)
            if m:
                current_track.title = m.group(1)
                continue
            m = _RE_PERFORMER.match(line)
            if m:
                current_track.performer = m.group(1)
                continue
            m = _RE_SONGWRITER.match(line)
            if m:
                current_track.songwriter = m.group(1)
                continue
            m = _RE_ISRC.match(line)
            if m:
                current_track.isrc = m.group(1)
                continue
            m = _RE_FLAGS.match(line)
            if m:
                current_track.flags = m.group(1).upper().split()
                continue
            m = _RE_PREGAP.match(line)
            if m:
                current_track.pregap = m.group(1)
                continue
            m = _RE_POSTGAP.match(line)
            if m:
                current_track.postgap = m.group(1)
                continue
            m = _RE_INDEX.match(line)
            if m:
                current_track.indexes.append(IndexEntry(int(m.group(1)), m.group(2)))
                continue

    if current_track and current_file:
        current_file.tracks.append(current_track)
    if current_file:
        album.files.append(current_file)

    album.cover_path = _find_cover(cue_dir, album)
    base = os.path.splitext(os.path.basename(abs_cue))[0]
    album.output_dir = os.path.join(cue_dir, base + "_tracks")
    return album


def _read_cue(path: str) -> list[str]:
    with open(path, "rb") as f:
        raw = f.read()

    # BOM detection first
    if raw[:3] == b"\xef\xbb\xbf":
        return raw.decode("utf-8-sig").splitlines(True)
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        enc = "utf-16"
        return raw.decode(enc).splitlines(True)

    # Try UTF-8 (strict)
    try:
        return raw.decode("utf-8").splitlines(True)
    except UnicodeDecodeError:
        pass

    # Auto-detect via charset-normalizer
    try:
        from charset_normalizer import from_bytes
        result = from_bytes(raw).best()
        if result and result.encoding:
            return str(result).splitlines(True)
    except ImportError:
        pass

    # Manual fallback chain (ordered by prevalence in CUE files)
    for enc in ("cp1251", "cp1252", "shift_jis", "gb2312", "gb18030",
                "euc-kr", "big5", "iso-8859-1", "iso-8859-2",
                "iso-8859-5", "iso-8859-15", "cp437", "cp866"):
        try:
            return raw.decode(enc, errors="strict").splitlines(True)
        except (UnicodeDecodeError, LookupError):
            continue

    # Last resort — lossy latin-1 (accepts any byte)
    return raw.decode("latin-1").splitlines(True)


def _find_cover(cue_dir: str, album: AlbumInfo) -> Optional[str]:
    rem_cover = album.rem.get("COVER", "")
    if rem_cover:
        p = os.path.join(cue_dir, rem_cover)
        if os.path.exists(p):
            return p

    for name in ("folder.jpg", "folder.png", "cover.jpg", "cover.png",
                 "front.jpg", "front.png", "album.jpg", "album.png",
                 "albumart.jpg", "Folder.jpg", "Cover.jpg"):
        p = os.path.join(cue_dir, name)
        if os.path.exists(p):
            return p

    try:
        for fname in sorted(os.listdir(cue_dir)):
            if fname.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp")):
                return os.path.join(cue_dir, fname)
    except OSError:
        pass
    return None
