# CUEtie

GTK3 desktop application for splitting CUE sheet audio into individual tracks with full metadata and cover art support.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![License](https://img.shields.io/badge/License-AGPL%20v3-green)

## Features

- **Full CUE spec parsing** — `CATALOG`, `CDTEXTFILE`, `PERFORMER`, `SONGWRITER`, `TITLE`, `FILE`, `TRACK`, `FLAGS`, `ISRC`, `PREGAP`, `POSTGAP`, `INDEX`, all `REM` extensions
- **Track picker** — select any subset of tracks via checkboxes before splitting
- **Per-track metadata editor** — edit title, performer, songwriter, ISRC inline; changes apply to output tags
- **Album metadata editor** — edit title, performer, genre, date, catalog, comment before processing
- **Cover art** — auto-detected from adjacent images (`folder.jpg`, `cover.png`, …) or `REM COVER`; replaceable via file picker; embedded into output files
- **Output formats** — FLAC, MP3 (libmp3lame), OGG Vorbis, Opus, WAV
- **Quality control** — FLAC compression level, bitrate for lossy formats
- **Filename templates** — `{track:02d} {title}`, `{artist} - {title}`, etc.
- **ffmpeg validation** — checks binary and required encoders on startup
- **Drag & drop** — drop a `.cue` file onto the window
- **Processing log** — ffmpeg output streamed to in-app log panel
- **Cancel** — abort in-progress split at any time

## Requirements

| Dependency | Purpose |
|---|---|
| Python 3.10+ | Runtime |
| [ffmpeg](https://ffmpeg.org/) | Audio splitting and encoding |
| [PyGObject](https://pygobject.gnome.org/) | GTK3 UI |
| [mutagen](https://mutagen.readthedocs.io/) | Metadata and cover art embedding |

## Installation

### NixOS / nix-shell

```bash
git clone https://github.com/csoftware-arigpt/cuetie
cd cuetie
nix-shell
python -m cuetie
```

### Arch Linux

```bash
git clone https://github.com/csoftware-arigpt/cuetie
cd cuetie
sudo pacman -S python-gobject gtk3 ffmpeg python-mutagen
pip install -e .
python -m cuetie
```

### Debian / Ubuntu

```bash
git clone https://github.com/csoftware-arigpt/cuetie
cd cuetie
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 ffmpeg
pip install mutagen
pip install -e .
python -m cuetie
```

### Fedora

```bash
git clone https://github.com/csoftware-arigpt/cuetie
cd cuetie
sudo dnf install python3-gobject gtk3 ffmpeg python3-mutagen
pip install -e .
python -m cuetie
```

## Usage

```bash
# Open GUI
python -m cuetie

# Open with a CUE file directly
python -m cuetie /path/to/album.cue
```

1. Open a `.cue` file via **Open CUE…** or drag-and-drop
2. Review and edit album metadata in the top panel
3. Click a track row to edit its title, performer, ISRC in the right panel
4. Check/uncheck tracks to include in the split
5. Choose output directory and format
6. Click **Start**

## CUE Spec Coverage

| Field | Supported |
|---|---|
| `CATALOG` | ✓ |
| `CDTEXTFILE` | ✓ |
| `PERFORMER` | ✓ global + per-track |
| `SONGWRITER` | ✓ global + per-track |
| `TITLE` | ✓ global + per-track |
| `FILE … WAVE/AIFF/MP3/BINARY` | ✓ |
| `TRACK n AUDIO` | ✓ |
| `FLAGS DCP 4CH PRE SCMS` | ✓ parsed |
| `ISRC` | ✓ |
| `PREGAP` / `POSTGAP` | ✓ parsed |
| `INDEX 00/01/…` | ✓ |
| `REM GENRE/DATE/DISCID/COMMENT` | ✓ |
| `REM COVER` | ✓ |
| Any other `REM` key | ✓ stored |

## License

GNU Affero General Public License v3.0 — see [LICENSE](LICENSE).
