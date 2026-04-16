from __future__ import annotations
import os
from typing import Optional

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, GLib, GdkPixbuf, Gdk

from ..cue_parser import AlbumInfo, TrackInfo, parse_cue
from ..processor import Processor, OutputSettings
from ..ffmpeg_check import check_ffmpeg, missing_codecs, FFmpegInfo
from .track_detail import TrackDetailPanel

COL_SEL      = 0
COL_NUM      = 1
COL_TITLE    = 2
COL_ARTIST   = 3
COL_DURATION = 4
COL_START    = 5
COL_ISRC     = 6
COL_OBJ      = 7


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application):
        super().__init__(application=app, title="CUEtie")
        self.set_default_size(1000, 720)
        self._album: Optional[AlbumInfo] = None
        self._processor: Optional[Processor] = None
        self._ffmpeg: FFmpegInfo = check_ffmpeg()
        self._build_ui()
        self._setup_dnd()
        GLib.idle_add(self._check_ffmpeg_warn)

    def _build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)

        root.pack_start(self._make_header(), False, False, 0)
        root.pack_start(Gtk.Separator(), False, False, 0)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        top.set_border_width(8)
        top.pack_start(self._make_cover_panel(), False, False, 0)
        top.pack_start(self._make_album_meta_panel(), True, True, 0)
        root.pack_start(top, False, False, 0)

        root.pack_start(Gtk.Separator(), False, False, 0)

        hpaned = Gtk.HPaned()
        hpaned.set_border_width(8)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        left.pack_start(self._make_track_toolbar(), False, False, 0)
        track_scroll = Gtk.ScrolledWindow()
        track_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        track_scroll.set_min_content_height(220)
        track_scroll.add(self._make_track_list())
        left.pack_start(track_scroll, True, True, 0)
        hpaned.pack1(left, resize=True, shrink=False)

        self._detail_panel = TrackDetailPanel()
        self._detail_panel.set_size_request(280, -1)
        hpaned.pack2(self._detail_panel, resize=False, shrink=False)

        root.pack_start(hpaned, True, True, 0)

        root.pack_start(Gtk.Separator(), False, False, 0)
        root.pack_start(self._make_output_panel(), False, False, 0)
        root.pack_start(Gtk.Separator(), False, False, 0)
        root.pack_start(self._make_progress_panel(), False, False, 0)
        root.pack_start(Gtk.Separator(), False, False, 0)

        log_scroll = Gtk.ScrolledWindow()
        log_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        log_scroll.set_min_content_height(100)
        self._log_buf = Gtk.TextBuffer()
        tv = Gtk.TextView(buffer=self._log_buf,
                          editable=False, cursor_visible=False,
                          wrap_mode=Gtk.WrapMode.WORD_CHAR,
                          monospace=True)
        self._log_view = tv
        log_scroll.add(tv)
        root.pack_start(log_scroll, False, True, 0)

        root.show_all()
        self._detail_panel.load(None)

    def _make_header(self) -> Gtk.Widget:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                      border_width=6)
        btn = Gtk.Button(label="Open CUE…")
        btn.connect("clicked", self._on_open_cue)
        bar.pack_start(btn, False, False, 0)
        self._cue_label = Gtk.Label(label="Drop a .cue file or click Open",
                                    xalign=0.0)
        bar.pack_start(self._cue_label, True, True, 0)
        title = Gtk.Label()
        title.set_markup('<b>CUE<span foreground="#e07000">tie</span></b>')
        bar.pack_end(title, False, False, 8)
        return bar

    def _make_cover_panel(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_size_request(160, -1)
        self._cover_image = Gtk.Image()
        self._cover_image.set_size_request(160, 160)
        self._set_cover(None)
        frame = Gtk.Frame()
        frame.add(self._cover_image)
        box.pack_start(frame, False, False, 0)
        btn_change = Gtk.Button(label="Change Cover…")
        btn_change.connect("clicked", self._on_change_cover)
        box.pack_start(btn_change, False, False, 0)
        btn_clear = Gtk.Button(label="Clear Cover")
        btn_clear.connect("clicked", lambda _: self._set_cover(None))
        box.pack_start(btn_clear, False, False, 0)
        return box

    def _make_album_meta_panel(self) -> Gtk.Widget:
        grid = Gtk.Grid(column_spacing=8, row_spacing=4, border_width=4)
        self._album_fields: dict[str, Gtk.Entry] = {}
        for row, (label, key) in enumerate([
            ("Title",     "title"),
            ("Performer", "performer"),
            ("Songwriter","songwriter"),
            ("Genre",     "genre"),
            ("Date",      "date"),
            ("Catalog",   "catalog"),
            ("Comment",   "comment"),
        ]):
            lbl = Gtk.Label(label=label + ":", xalign=1.0)
            grid.attach(lbl, 0, row, 1, 1)
            entry = Gtk.Entry(hexpand=True)
            grid.attach(entry, 1, row, 1, 1)
            self._album_fields[key] = entry
        return grid

    def _make_track_toolbar(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        for label, state in (("Select All", True), ("Select None", False)):
            btn = Gtk.Button(label=label)
            btn.connect("clicked", lambda _, s=state: self._set_all_selected(s))
            box.pack_start(btn, False, False, 0)
        lbl = Gtk.Label(label="Click row to edit track metadata →", xalign=0.0)
        lbl.get_style_context().add_class("dim-label")
        box.pack_start(lbl, True, True, 8)
        return box

    def _make_track_list(self) -> Gtk.Widget:
        self._track_store = Gtk.ListStore(bool, int, str, str, str, str, str, object)
        tv = Gtk.TreeView(model=self._track_store, headers_visible=True)
        tv.get_selection().set_mode(Gtk.SelectionMode.SINGLE)
        tv.get_selection().connect("changed", self._on_track_selection_changed)
        self._track_view = tv

        r_toggle = Gtk.CellRendererToggle()
        r_toggle.connect("toggled", self._on_track_toggled)
        col = Gtk.TreeViewColumn("", r_toggle, active=COL_SEL)
        col.set_fixed_width(36)
        tv.append_column(col)

        for title, idx, expand, width in [
            ("#",        COL_NUM,      False, 42),
            ("Title",    COL_TITLE,    True,  -1),
            ("Artist",   COL_ARTIST,   False, 150),
            ("Duration", COL_DURATION, False, 70),
            ("Start",    COL_START,    False, 78),
            ("ISRC",     COL_ISRC,     False, 125),
        ]:
            r = Gtk.CellRendererText()
            c = Gtk.TreeViewColumn(title, r, text=idx)
            c.set_resizable(True)
            c.set_expand(expand)
            if width > 0:
                c.set_fixed_width(width)
                c.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
            tv.append_column(c)

        return tv

    def _make_output_panel(self) -> Gtk.Widget:
        grid = Gtk.Grid(column_spacing=8, row_spacing=6, border_width=8)

        grid.attach(Gtk.Label(label="Output Dir:", xalign=1.0), 0, 0, 1, 1)
        self._out_dir = Gtk.Entry(hexpand=True,
                                  placeholder_text="Default: <cue_name>_tracks/")
        grid.attach(self._out_dir, 1, 0, 3, 1)
        btn_dir = Gtk.Button(label="Browse…")
        btn_dir.connect("clicked", self._on_browse_outdir)
        grid.attach(btn_dir, 4, 0, 1, 1)

        grid.attach(Gtk.Label(label="Format:", xalign=1.0), 0, 1, 1, 1)
        self._fmt_combo = Gtk.ComboBoxText()
        for f in ("FLAC", "MP3", "OGG", "OPUS", "WAV"):
            self._fmt_combo.append_text(f)
        self._fmt_combo.set_active(0)
        self._fmt_combo.connect("changed", self._on_fmt_changed)
        grid.attach(self._fmt_combo, 1, 1, 1, 1)

        self._quality_label = Gtk.Label(label="Compression:", xalign=1.0)
        grid.attach(self._quality_label, 2, 1, 1, 1)
        self._quality_spin = Gtk.SpinButton(
            adjustment=Gtk.Adjustment(value=5, lower=0, upper=12, step_increment=1))
        grid.attach(self._quality_spin, 3, 1, 1, 1)

        self._embed_cover_chk = Gtk.CheckButton(label="Embed cover art", active=True)
        grid.attach(self._embed_cover_chk, 4, 1, 1, 1)

        grid.attach(Gtk.Label(label="Filename:", xalign=1.0), 0, 2, 1, 1)
        self._tpl_entry = Gtk.Entry(text="{track:02d} {title}", hexpand=True)
        grid.attach(self._tpl_entry, 1, 2, 3, 1)
        hint = Gtk.Label(
            label="{track} {title} {artist} {album}", xalign=0.0)
        hint.get_style_context().add_class("dim-label")
        grid.attach(hint, 4, 2, 1, 1)

        return grid

    def _make_progress_panel(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                      border_width=8)

        row1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row1.pack_start(Gtk.Label(label="Overall:"), False, False, 0)
        self._progress = Gtk.ProgressBar(hexpand=True, show_text=True)
        row1.pack_start(self._progress, True, True, 0)
        box.pack_start(row1, False, False, 0)

        self._status_label = Gtk.Label(label="Idle", xalign=0.0)
        box.pack_start(self._status_label, False, False, 0)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._btn_start = Gtk.Button(label="Start")
        self._btn_start.get_style_context().add_class("suggested-action")
        self._btn_start.connect("clicked", self._on_start)
        self._btn_cancel = Gtk.Button(label="Cancel", sensitive=False)
        self._btn_cancel.connect("clicked", self._on_cancel)
        btn_row.pack_start(self._btn_start, False, False, 0)
        btn_row.pack_start(self._btn_cancel, False, False, 0)
        box.pack_start(btn_row, False, False, 0)

        return box

    def _setup_dnd(self):
        self.drag_dest_set(
            Gtk.DestDefaults.ALL,
            [Gtk.TargetEntry.new("text/uri-list", 0, 0)],
            Gdk.DragAction.COPY,
        )
        self.connect("drag-data-received", self._on_drag_received)

    def _on_drag_received(self, widget, ctx, x, y, data, info, time):
        for uri in data.get_uris():
            if uri.lower().endswith(".cue"):
                path = uri.replace("file://", "").replace("%20", " ")
                self._load_cue(path)
                break
        Gtk.drag_finish(ctx, True, False, time)

    def _on_open_cue(self, _):
        dlg = Gtk.FileChooserDialog(
            title="Open CUE file", parent=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                        Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        filt = Gtk.FileFilter()
        filt.set_name("CUE sheets (*.cue)")
        filt.add_pattern("*.cue")
        filt.add_pattern("*.CUE")
        dlg.add_filter(filt)
        if dlg.run() == Gtk.ResponseType.OK:
            self._load_cue(dlg.get_filename())
        dlg.destroy()

    def _on_change_cover(self, _):
        dlg = Gtk.FileChooserDialog(
            title="Choose cover art", parent=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                        Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        filt = Gtk.FileFilter()
        filt.set_name("Images")
        for p in ("*.jpg", "*.jpeg", "*.png", "*.bmp", "*.webp"):
            filt.add_pattern(p)
        dlg.add_filter(filt)
        if dlg.run() == Gtk.ResponseType.OK:
            path = dlg.get_filename()
            if self._album:
                self._album.cover_path = path
            self._set_cover(path)
        dlg.destroy()

    def _on_browse_outdir(self, _):
        dlg = Gtk.FileChooserDialog(
            title="Choose output directory", parent=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                        Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        if dlg.run() == Gtk.ResponseType.OK:
            self._out_dir.set_text(dlg.get_filename())
        dlg.destroy()

    def _on_fmt_changed(self, combo):
        fmt = combo.get_active_text().lower()
        if fmt == "flac":
            self._quality_label.set_text("Compression:")
            self._quality_spin.set_adjustment(
                Gtk.Adjustment(value=5, lower=0, upper=12, step_increment=1))
            self._quality_spin.set_sensitive(True)
        elif fmt == "mp3":
            self._quality_label.set_text("Bitrate kbps:")
            self._quality_spin.set_adjustment(
                Gtk.Adjustment(value=320, lower=64, upper=320, step_increment=32))
            self._quality_spin.set_sensitive(True)
        elif fmt in ("ogg", "opus"):
            self._quality_label.set_text("Bitrate kbps:")
            self._quality_spin.set_adjustment(
                Gtk.Adjustment(value=256, lower=64, upper=512, step_increment=32))
            self._quality_spin.set_sensitive(True)
        else:
            self._quality_label.set_text("Quality:")
            self._quality_spin.set_sensitive(False)

    def _on_track_toggled(self, renderer, path):
        it = self._track_store.get_iter(path)
        cur = self._track_store.get_value(it, COL_SEL)
        self._track_store.set_value(it, COL_SEL, not cur)
        track: TrackInfo = self._track_store.get_value(it, COL_OBJ)
        if track:
            track.selected = not cur

    def _on_track_selection_changed(self, selection):
        model, it = selection.get_selected()
        if it:
            track: TrackInfo = model.get_value(it, COL_OBJ)
            self._detail_panel.load(track)
            self._detail_panel.connect(
                "notify", lambda *a: self._refresh_row(it))
        else:
            self._detail_panel.load(None)

    def _refresh_row(self, it):
        track: TrackInfo = self._track_store.get_value(it, COL_OBJ)
        if track:
            self._track_store.set_value(it, COL_TITLE, track.title)
            self._track_store.set_value(it, COL_ARTIST, track.performer)
            self._track_store.set_value(it, COL_ISRC, track.isrc)

    def _set_all_selected(self, state: bool):
        it = self._track_store.get_iter_first()
        while it:
            self._track_store.set_value(it, COL_SEL, state)
            track: TrackInfo = self._track_store.get_value(it, COL_OBJ)
            if track:
                track.selected = state
            it = self._track_store.iter_next(it)

    def _check_ffmpeg_warn(self):
        if not self._ffmpeg.found:
            bar = Gtk.InfoBar(message_type=Gtk.MessageType.ERROR,
                              show_close_button=True)
            bar.get_content_area().add(
                Gtk.Label(label="ffmpeg not found in PATH — splitting will fail. "
                                "Install ffmpeg and restart CUEtie."))
            bar.connect("response", lambda b, _: b.destroy())
            bar.show_all()
            self.get_child().pack_start(bar, False, False, 0)
            self.get_child().reorder_child(bar, 1)
        else:
            self._append_log(f"ffmpeg {self._ffmpeg.version} · {self._ffmpeg.path}")
            self._append_log(f"Encoders: {', '.join(sorted(self._ffmpeg.codecs)) or 'none detected'}")
        return False

    def _on_start(self, _):
        if not self._album:
            self._error("No CUE file loaded.")
            return
        if not self._ffmpeg.found:
            self._error("ffmpeg not found in PATH.\n\nInstall ffmpeg and restart CUEtie.")
            return
        fmt = self._fmt_combo.get_active_text().lower()
        missing = missing_codecs(self._ffmpeg, fmt)
        if missing:
            self._error(f"ffmpeg missing encoder(s) for {fmt.upper()}: {', '.join(missing)}\n\n"
                        f"Rebuild ffmpeg with the required codec support.")
            return
        self._flush_album_meta()
        q = int(self._quality_spin.get_value())
        out_dir = self._out_dir.get_text().strip()
        if not out_dir:
            src = self._album.files[0].filename if self._album.files else "."
            base = os.path.splitext(os.path.basename(
                self._cue_label.get_text()))[0]
            out_dir = os.path.join(os.path.dirname(src), base + "_tracks")

        settings = OutputSettings(
            output_dir=out_dir,
            fmt=fmt,
            flac_compression=q if fmt == "flac" else 5,
            mp3_bitrate=q if fmt == "mp3" else 320,
            opus_bitrate=q if fmt in ("opus", "ogg") else 256,
            ogg_quality=min(10.0, q / 51.2) if fmt == "ogg" else 8.0,
            embed_cover=self._embed_cover_chk.get_active(),
            filename_template=self._tpl_entry.get_text() or "{track:02d} {title}",
        )

        self._btn_start.set_sensitive(False)
        self._btn_cancel.set_sensitive(True)
        self._progress.set_fraction(0)
        self._progress.set_text("0%")
        self._log_buf.set_text("")

        self._processor = Processor(
            album=self._album, settings=settings,
            on_progress=self._on_progress,
            on_done=self._on_done,
        )
        self._processor.start()

    def _on_cancel(self, _):
        if self._processor:
            self._processor.cancel()

    def _on_progress(self, done: int, total: int, title: str,
                     frac: float, msg: str):
        GLib.idle_add(self._update_progress, done, total, title, frac, msg)

    def _update_progress(self, done, total, title, frac, msg):
        if msg:
            self._append_log(msg)
        if frac >= 0 and total > 0:
            self._progress.set_fraction(min(frac, 1.0))
            self._progress.set_text(f"{int(frac * 100)}%  ({done}/{total})")
        if title:
            self._status_label.set_text(title)
        return False

    def _on_done(self, success: bool, msg: str):
        GLib.idle_add(self._finish, success, msg)

    def _finish(self, success, msg):
        self._btn_start.set_sensitive(True)
        self._btn_cancel.set_sensitive(False)
        self._progress.set_fraction(1.0 if success else 0.0)
        self._progress.set_text("Done" if success else "Cancelled")
        self._status_label.set_text(msg)
        self._append_log(f"=== {msg} ===")
        return False

    def _load_cue(self, path: str):
        try:
            album = parse_cue(path)
        except Exception as e:
            self._error(f"Failed to parse CUE:\n{e}")
            return
        self._album = album
        self._cue_label.set_text(os.path.basename(path))
        self._album_fields["title"].set_text(album.title)
        self._album_fields["performer"].set_text(album.performer)
        self._album_fields["songwriter"].set_text(album.songwriter)
        self._album_fields["genre"].set_text(album.genre)
        self._album_fields["date"].set_text(album.date)
        self._album_fields["catalog"].set_text(album.catalog)
        self._album_fields["comment"].set_text(album.comment)
        self._set_cover(album.cover_path)

        src_dir = os.path.dirname(os.path.abspath(path))
        base = os.path.splitext(os.path.basename(path))[0]
        self._out_dir.set_text(os.path.join(src_dir, base + "_tracks"))

        self._track_store.clear()
        self._detail_panel.load(None)
        all_tracks = album.all_tracks

        for i, track in enumerate(all_tracks):
            if i < len(all_tracks) - 1:
                dur_sec = all_tracks[i + 1].start_seconds - track.start_seconds
                dur_str = f"{int(dur_sec // 60)}:{int(dur_sec % 60):02d}"
            else:
                dur_str = "?"
            self._track_store.append([
                track.selected, track.number, track.title,
                track.performer, dur_str, track.start_time,
                track.isrc, track,
            ])

        self._append_log(f"Loaded: {path}")
        self._append_log(f"  {len(all_tracks)} tracks · {len(album.files)} file(s)")
        if album.cover_path:
            self._append_log(f"  Cover: {os.path.basename(album.cover_path)}")
        for k, v in album.rem.items():
            self._append_log(f"  REM {k}: {v}")

    def _flush_album_meta(self):
        if not self._album:
            return
        a = self._album
        a.title      = self._album_fields["title"].get_text()
        a.performer  = self._album_fields["performer"].get_text()
        a.songwriter = self._album_fields["songwriter"].get_text()
        a.rem["GENRE"]   = self._album_fields["genre"].get_text()
        a.rem["DATE"]    = self._album_fields["date"].get_text()
        a.catalog        = self._album_fields["catalog"].get_text()
        a.rem["COMMENT"] = self._album_fields["comment"].get_text()

    def _set_cover(self, path: Optional[str]):
        if self._album:
            self._album.cover_path = path
        if path and os.path.exists(path):
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 160, 160, True)
                self._cover_image.set_from_pixbuf(pb)
                return
            except Exception:
                pass
        self._cover_image.set_from_icon_name("audio-x-generic", Gtk.IconSize.DIALOG)
        self._cover_image.set_pixel_size(128)

    def _append_log(self, text: str):
        self._log_buf.insert(self._log_buf.get_end_iter(), text + "\n")
        adj = self._log_view.get_vadjustment()
        if adj:
            adj.set_value(adj.get_upper())

    def _error(self, msg: str):
        dlg = Gtk.MessageDialog(parent=self, flags=0,
                                message_type=Gtk.MessageType.ERROR,
                                buttons=Gtk.ButtonsType.OK, text=msg)
        dlg.run()
        dlg.destroy()
