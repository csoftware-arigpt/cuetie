from __future__ import annotations
import os
from typing import Optional

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, GLib, GdkPixbuf, Gdk, Pango

from ..cue_parser import AlbumInfo, TrackInfo, parse_cue
from ..processor import BatchProcessor, Job, OutputSettings
from ..ffmpeg_check import check_ffmpeg, missing_codecs, FFmpegInfo
from .track_detail import TrackDetailPanel
from .workers_panel import WorkersPanel

COL_SEL      = 0
COL_NUM      = 1
COL_TITLE    = 2
COL_ARTIST   = 3
COL_DURATION = 4
COL_START    = 5
COL_ISRC     = 6
COL_OBJ      = 7

CUE_COL_NAME  = 0
CUE_COL_COUNT = 1
CUE_COL_OBJ   = 2


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application):
        super().__init__(application=app, title="CUEtie")
        self._apply_adaptive_size()
        self._albums: list[AlbumInfo] = []
        self._current: Optional[AlbumInfo] = None
        self._processor: Optional[BatchProcessor] = None
        self._ffmpeg: FFmpegInfo = check_ffmpeg()
        self._suppress_meta_sync = False
        self._build_ui()
        self._setup_dnd()
        screen = self.get_screen()
        if screen is not None:
            screen.connect("size-changed", self._on_screen_size_changed)
        self.connect("realize", lambda *_: self.maximize())
        GLib.idle_add(self._check_ffmpeg_warn)

    def _apply_adaptive_size(self) -> None:
        """Pick a default size that fits the current monitor; maximize on show."""
        w, h = 1180, 760
        try:
            disp = Gdk.Display.get_default()
            mon = None
            if disp is not None:
                mon = disp.get_primary_monitor() or (
                    disp.get_monitor(0) if disp.get_n_monitors() else None
                )
            if mon is not None:
                geo = mon.get_geometry()
                w = max(640, min(1600, int(geo.width * 0.9)))
                h = max(480, min(1000, int(geo.height * 0.9)))
        except Exception:
            pass
        self.set_default_size(w, h)
        self.set_size_request(480, 360)

    def _on_screen_size_changed(self, _screen) -> None:
        if self.is_visible():
            self.unmaximize()
            GLib.idle_add(self.maximize)
        GLib.idle_add(self._set_sidebar_position)
        GLib.idle_add(self._set_vpaned_position)
        GLib.idle_add(self._set_content_hpaned_position)

    def _set_sidebar_position(self) -> bool:
        if not hasattr(self, "_main_paned"):
            return False
        alloc = self.get_allocation()
        width = alloc.width if alloc.width > 0 else self.get_default_size()[0]
        pos = max(180, min(280, int(width * 0.18)))
        self._main_paned.set_position(pos)
        return False

    def _set_vpaned_position(self) -> bool:
        if not hasattr(self, "_vpaned"):
            return False
        alloc = self.get_allocation()
        height = alloc.height if alloc.height > 0 else self.get_default_size()[1]
        pos = max(240, int(height * 0.62))
        self._vpaned.set_position(pos)
        return False

    def _set_content_hpaned_position(self) -> bool:
        if not hasattr(self, "_content_hpaned"):
            return False
        alloc = self._content_hpaned.get_allocation()
        width = alloc.width if alloc.width > 0 else self.get_default_size()[0]
        pos = max(280, int(width * 0.62))
        self._content_hpaned.set_position(pos)
        return False

    # ---------------- UI construction ----------------

    def _build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)

        root.pack_start(self._make_header(), False, False, 0)
        root.pack_start(Gtk.Separator(), False, False, 0)

        main_paned = Gtk.HPaned()
        main_paned.pack1(self._make_cue_sidebar(), resize=False, shrink=True)
        main_paned.pack2(self._make_content(), resize=True, shrink=True)
        self._main_paned = main_paned
        GLib.idle_add(self._set_sidebar_position)

        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        bottom.pack_start(self._make_output_panel(), False, False, 0)
        bottom.pack_start(Gtk.Separator(), False, False, 0)
        bottom.pack_start(self._make_progress_panel(), False, False, 0)
        bottom.pack_start(Gtk.Separator(), False, False, 0)

        log_scroll = Gtk.ScrolledWindow()
        log_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        log_scroll.set_min_content_height(80)
        self._log_buf = Gtk.TextBuffer()
        tv = Gtk.TextView(buffer=self._log_buf,
                          editable=False, cursor_visible=False,
                          wrap_mode=Gtk.WrapMode.WORD_CHAR,
                          monospace=True)
        self._log_view = tv
        log_scroll.add(tv)
        bottom.pack_start(log_scroll, True, True, 0)

        vpaned = Gtk.VPaned()
        vpaned.pack1(main_paned, resize=True, shrink=True)
        vpaned.pack2(bottom, resize=True, shrink=True)
        self._vpaned = vpaned
        GLib.idle_add(self._set_vpaned_position)
        root.pack_start(vpaned, True, True, 0)

        root.pack_start(Gtk.Separator(), False, False, 0)
        self._workers_panel = WorkersPanel(on_kill_one=self._on_kill_one)
        root.pack_start(self._workers_panel, False, False, 0)

        root.pack_start(Gtk.Separator(), False, False, 0)
        status_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                             spacing=6, border_width=4)
        self._status_label = Gtk.Label(label="Idle", xalign=0.0)
        self._status_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._status_label.set_hexpand(True)
        status_bar.pack_start(self._status_label, True, True, 0)
        root.pack_start(status_bar, False, False, 0)

        root.show_all()
        self._detail_panel.load(None)
        self._refresh_content_sensitive()

    def _make_header(self) -> Gtk.Widget:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                      border_width=6)
        btn_add = Gtk.Button(label="Add CUE…")
        btn_add.connect("clicked", self._on_open_cue)
        bar.pack_start(btn_add, False, False, 0)

        btn_clear = Gtk.Button(label="Clear All")
        btn_clear.connect("clicked", self._on_clear_all)
        bar.pack_start(btn_clear, False, False, 0)

        self._cue_label = Gtk.Label(label="Drop .cue files or click Add CUE…",
                                    xalign=0.0)
        bar.pack_start(self._cue_label, True, True, 0)
        title = Gtk.Label()
        title.set_markup('<b>CUEtie</b>')
        bar.pack_end(title, False, False, 8)
        return bar

    def _make_cue_sidebar(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                      border_width=6)
        lbl = Gtk.Label(xalign=0.0)
        lbl.set_markup("<b>Loaded CUEs</b>")
        box.pack_start(lbl, False, False, 0)

        self._cue_store = Gtk.ListStore(str, str, object)
        tv = Gtk.TreeView(model=self._cue_store, headers_visible=False)
        tv.get_selection().set_mode(Gtk.SelectionMode.SINGLE)
        tv.get_selection().connect("changed", self._on_cue_selection_changed)

        r_name = Gtk.CellRendererText(ellipsize=3)  # END
        c_name = Gtk.TreeViewColumn("CUE", r_name, text=CUE_COL_NAME)
        c_name.set_expand(True)
        tv.append_column(c_name)

        r_count = Gtk.CellRendererText(xalign=1.0)
        c_count = Gtk.TreeViewColumn("", r_count, text=CUE_COL_COUNT)
        tv.append_column(c_count)

        self._cue_view = tv
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(tv)
        box.pack_start(scroll, True, True, 0)

        btn_remove = Gtk.Button(label="Remove Selected")
        btn_remove.connect("clicked", self._on_remove_cue)
        box.pack_start(btn_remove, False, False, 0)
        return box

    def _make_content(self) -> Gtk.Widget:
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        top.set_border_width(8)
        top.pack_start(self._make_cover_panel(), False, False, 0)
        top.pack_start(self._make_album_meta_panel(), True, True, 0)
        vbox.pack_start(top, False, False, 0)

        vbox.pack_start(Gtk.Separator(), False, False, 0)

        hpaned = Gtk.HPaned()
        hpaned.set_border_width(8)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        left.pack_start(self._make_track_toolbar(), False, False, 0)
        track_scroll = Gtk.ScrolledWindow()
        track_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        track_scroll.set_min_content_height(140)
        track_scroll.add(self._make_track_list())
        left.pack_start(track_scroll, True, True, 0)
        hpaned.pack1(left, resize=True, shrink=True)

        self._detail_panel = TrackDetailPanel()
        self._detail_panel.set_size_request(200, -1)
        hpaned.pack2(self._detail_panel, resize=True, shrink=True)
        self._content_hpaned = hpaned
        GLib.idle_add(self._set_content_hpaned_position)
        vbox.pack_start(hpaned, True, True, 0)

        self._content_box = vbox
        return vbox

    def _make_cover_panel(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._cover_image = Gtk.Image()
        self._cover_image.set_size_request(128, 128)
        self._set_cover_image(None)
        frame = Gtk.Frame()
        frame.add(self._cover_image)
        box.pack_start(frame, False, False, 0)
        btn_change = Gtk.Button(label="Change Cover…")
        btn_change.connect("clicked", self._on_change_cover)
        box.pack_start(btn_change, False, False, 0)
        btn_clear = Gtk.Button(label="Clear Cover")
        btn_clear.connect("clicked", lambda _: self._assign_cover(None))
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
            entry.connect("changed", self._on_album_field_changed, key)
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
        self._track_store = Gtk.ListStore(
            bool, int, str, str, str, str, str, object)
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
        self._out_dir = Gtk.Entry(
            hexpand=True,
            placeholder_text="Per-CUE default: <cue_name>_tracks/",
        )
        self._out_dir.connect("changed", self._on_outdir_changed)
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

        grid.attach(Gtk.Label(label="Workers:", xalign=1.0), 0, 3, 1, 1)
        self._workers_spin = Gtk.SpinButton(
            adjustment=Gtk.Adjustment(value=1, lower=1, upper=16, step_increment=1))
        self._workers_spin.set_tooltip_text(
            "1 = queue (sequential). >1 = parallel ffmpeg workers.")
        grid.attach(self._workers_spin, 1, 3, 1, 1)

        mode_lbl = Gtk.Label(
            label="queue mode (1) / parallel (>1); shared across all loaded CUEs",
            xalign=0.0,
        )
        mode_lbl.get_style_context().add_class("dim-label")
        grid.attach(mode_lbl, 2, 3, 3, 1)

        return grid

    def _make_progress_panel(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                      border_width=8)

        row1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row1.pack_start(Gtk.Label(label="Overall:"), False, False, 0)
        self._progress = Gtk.ProgressBar(hexpand=True, show_text=True)
        row1.pack_start(self._progress, True, True, 0)
        box.pack_start(row1, False, False, 0)

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

    # ---------------- drag & drop ----------------

    def _setup_dnd(self):
        self.drag_dest_set(
            Gtk.DestDefaults.ALL,
            [Gtk.TargetEntry.new("text/uri-list", 0, 0)],
            Gdk.DragAction.COPY,
        )
        self.connect("drag-data-received", self._on_drag_received)

    def _on_drag_received(self, widget, ctx, x, y, data, info, time):
        from urllib.parse import unquote, urlparse
        loaded = 0
        for uri in data.get_uris():
            if not uri.lower().endswith(".cue"):
                continue
            parsed = urlparse(uri)
            path = unquote(parsed.path)
            if self._load_cue(path):
                loaded += 1
        Gtk.drag_finish(ctx, loaded > 0, False, time)

    # ---------------- file dialogs ----------------

    def _on_open_cue(self, _):
        dlg = Gtk.FileChooserDialog(
            title="Open CUE files", parent=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dlg.set_select_multiple(True)
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                        Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        filt = Gtk.FileFilter()
        filt.set_name("CUE sheets (*.cue)")
        filt.add_pattern("*.cue")
        filt.add_pattern("*.CUE")
        dlg.add_filter(filt)
        if dlg.run() == Gtk.ResponseType.OK:
            for path in dlg.get_filenames():
                self._load_cue(path)
        dlg.destroy()

    def _on_change_cover(self, _):
        if not self._current:
            return
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
            self._assign_cover(dlg.get_filename())
        dlg.destroy()

    def _on_browse_outdir(self, _):
        if not self._current:
            return
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
        fmt = (combo.get_active_text() or "FLAC").lower()
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

    # ---------------- CUE list ----------------

    def _on_clear_all(self, _):
        self._albums.clear()
        self._current = None
        self._cue_store.clear()
        self._reset_widgets()
        self._refresh_content_sensitive()
        self._cue_label.set_text("Drop .cue files or click Add CUE…")

    def _on_remove_cue(self, _):
        sel = self._cue_view.get_selection()
        model, it = sel.get_selected()
        if not it:
            return
        album: AlbumInfo = model.get_value(it, CUE_COL_OBJ)
        model.remove(it)
        try:
            self._albums.remove(album)
        except ValueError:
            pass
        if self._current is album:
            self._current = None
        new_it = self._cue_store.get_iter_first()
        if new_it:
            sel.select_iter(new_it)
        else:
            self._reset_widgets()
            self._refresh_content_sensitive()

    def _on_cue_selection_changed(self, selection):
        model, it = selection.get_selected()
        if it is None:
            return
        album: AlbumInfo = model.get_value(it, CUE_COL_OBJ)
        if album is self._current:
            return
        self._switch_album(album)

    def _switch_album(self, album: AlbumInfo):
        self._current = album
        self._populate_from_album(album)
        self._refresh_content_sensitive()

    def _refresh_content_sensitive(self):
        has = self._current is not None
        self._content_box.set_sensitive(has)
        self._out_dir.set_sensitive(has)

    def _reset_widgets(self):
        self._suppress_meta_sync = True
        for e in self._album_fields.values():
            e.set_text("")
        self._track_store.clear()
        self._out_dir.set_text("")
        self._set_cover_image(None)
        self._detail_panel.load(None)
        self._suppress_meta_sync = False

    def _populate_from_album(self, album: AlbumInfo):
        self._suppress_meta_sync = True
        self._album_fields["title"].set_text(album.title)
        self._album_fields["performer"].set_text(album.performer)
        self._album_fields["songwriter"].set_text(album.songwriter)
        self._album_fields["genre"].set_text(album.genre)
        self._album_fields["date"].set_text(album.date)
        self._album_fields["catalog"].set_text(album.catalog)
        self._album_fields["comment"].set_text(album.comment)
        self._set_cover_image(album.cover_path)
        self._out_dir.set_text(album.output_dir)

        self._track_store.clear()
        self._detail_panel.load(None)
        tracks = album.all_tracks
        for i, track in enumerate(tracks):
            if i < len(tracks) - 1:
                dur_sec = tracks[i + 1].start_seconds - track.start_seconds
                dur_str = f"{int(dur_sec // 60)}:{int(dur_sec % 60):02d}"
            else:
                dur_str = "?"
            self._track_store.append([
                track.selected, track.number, track.title,
                track.performer, dur_str, track.start_time,
                track.isrc, track,
            ])
        self._suppress_meta_sync = False

    # ---------------- track list ----------------

    def _on_track_toggled(self, renderer, path):
        it = self._track_store.get_iter(path)
        cur = self._track_store.get_value(it, COL_SEL)
        self._track_store.set_value(it, COL_SEL, not cur)
        track: TrackInfo = self._track_store.get_value(it, COL_OBJ)
        if track:
            track.selected = not cur
        self._refresh_cue_row_counts()

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
        self._refresh_cue_row_counts()

    def _refresh_cue_row_counts(self):
        it = self._cue_store.get_iter_first()
        while it:
            album: AlbumInfo = self._cue_store.get_value(it, CUE_COL_OBJ)
            sel = sum(1 for t in album.all_tracks
                      if t.selected and t.datatype == "AUDIO")
            total = sum(1 for t in album.all_tracks if t.datatype == "AUDIO")
            self._cue_store.set_value(it, CUE_COL_COUNT, f"{sel}/{total}")
            it = self._cue_store.iter_next(it)

    # ---------------- album meta sync ----------------

    def _on_album_field_changed(self, entry: Gtk.Entry, key: str):
        if self._suppress_meta_sync or not self._current:
            return
        val = entry.get_text()
        a = self._current
        if key == "title":
            a.title = val
        elif key == "performer":
            a.performer = val
        elif key == "songwriter":
            a.songwriter = val
        elif key == "catalog":
            a.catalog = val
        elif key == "genre":
            a.rem["GENRE"] = val
        elif key == "date":
            a.rem["DATE"] = val
        elif key == "comment":
            a.rem["COMMENT"] = val

    def _on_outdir_changed(self, entry: Gtk.Entry):
        if self._suppress_meta_sync or not self._current:
            return
        self._current.output_dir = entry.get_text()

    def _assign_cover(self, path: Optional[str]):
        if self._current:
            self._current.cover_path = path
        self._set_cover_image(path)

    # ---------------- ffmpeg / start ----------------

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
            self._append_log(
                f"Encoders: {', '.join(sorted(self._ffmpeg.codecs)) or 'none detected'}"
            )
        return False

    def _on_start(self, _):
        if not self._albums:
            self._error("No CUE files loaded.")
            return
        if not self._ffmpeg.found:
            self._error("ffmpeg not found in PATH.\n\nInstall ffmpeg and restart CUEtie.")
            return
        fmt = (self._fmt_combo.get_active_text() or "FLAC").lower()
        missing = missing_codecs(self._ffmpeg, fmt)
        if missing:
            self._error(
                f"ffmpeg missing encoder(s) for {fmt.upper()}: {', '.join(missing)}"
            )
            return

        q = int(self._quality_spin.get_value())
        tpl = self._tpl_entry.get_text() or "{track:02d} {title}"
        embed = self._embed_cover_chk.get_active()
        workers = int(self._workers_spin.get_value())

        jobs: list[Job] = []
        for album in self._albums:
            out_dir = album.output_dir.strip() or self._default_out_dir(album)
            album.output_dir = out_dir
            settings = OutputSettings(
                output_dir=out_dir,
                fmt=fmt,
                flac_compression=q if fmt == "flac" else 5,
                mp3_bitrate=q if fmt == "mp3" else 320,
                opus_bitrate=q if fmt in ("opus", "ogg") else 256,
                ogg_quality=min(10.0, q / 51.2) if fmt == "ogg" else 8.0,
                embed_cover=embed,
                filename_template=tpl,
            )
            jobs.append(Job(album=album, settings=settings))

        total_tracks = sum(
            1 for a in self._albums for t in a.all_tracks
            if t.selected and t.datatype == "AUDIO"
        )
        if total_tracks == 0:
            self._error("No tracks selected across loaded CUEs.")
            return

        self._btn_start.set_sensitive(False)
        self._btn_cancel.set_sensitive(True)
        self._progress.set_fraction(0)
        self._progress.set_text("0%")
        self._log_buf.set_text("")
        self._workers_panel.clear()
        self._append_log(
            f"Starting: {len(jobs)} cue · {total_tracks} tracks · workers={workers}"
        )

        self._processor = BatchProcessor(
            jobs=jobs,
            on_progress=self._on_progress,
            on_done=self._on_done,
            workers=workers,
            on_task_start=self._on_task_start,
            on_task_end=self._on_task_end,
        )
        self._processor.start()

    def _default_out_dir(self, album: AlbumInfo) -> str:
        if album.cue_path:
            base = os.path.splitext(os.path.basename(album.cue_path))[0]
            return os.path.join(os.path.dirname(album.cue_path), base + "_tracks")
        return os.path.join(os.getcwd(), "tracks")

    def _on_cancel(self, _):
        if self._processor:
            self._processor.cancel()

    def _on_kill_one(self, task_id: int) -> None:
        if self._processor:
            self._processor.cancel_task(task_id)

    def _on_task_start(self, task_id: int, album_tag: str, title: str) -> None:
        GLib.idle_add(self._workers_panel.add_worker, task_id, album_tag, title)

    def _on_task_end(self, task_id: int, status: str) -> None:
        GLib.idle_add(self._workers_panel.remove_worker, task_id)

    # ---------------- progress / log ----------------

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
        self._progress.set_text("Done" if success else "Stopped")
        self._status_label.set_text(msg)
        self._workers_panel.clear()
        self._append_log(f"=== {msg} ===")
        return False

    # ---------------- cue loading ----------------

    def _load_cue(self, path: str) -> bool:
        try:
            album = parse_cue(path)
        except Exception as e:
            self._error(f"Failed to parse CUE:\n{path}\n\n{e}")
            return False

        existing = next(
            (a for a in self._albums if a.cue_path == album.cue_path), None,
        )
        if existing:
            self._append_log(f"Already loaded: {path}")
            self._select_album_in_list(existing)
            return False

        self._albums.append(album)
        name = os.path.basename(album.cue_path or path)
        sel = sum(1 for t in album.all_tracks
                  if t.selected and t.datatype == "AUDIO")
        total = sum(1 for t in album.all_tracks if t.datatype == "AUDIO")
        it = self._cue_store.append([name, f"{sel}/{total}", album])
        self._cue_view.get_selection().select_iter(it)
        self._cue_label.set_text(
            f"{len(self._albums)} CUE loaded"
            + (f" · latest: {name}" if name else "")
        )

        self._append_log(f"Loaded: {path}")
        self._append_log(
            f"  {len(album.all_tracks)} tracks · {len(album.files)} file(s)"
        )
        if album.cover_path:
            self._append_log(f"  Cover: {os.path.basename(album.cover_path)}")
        for k, v in album.rem.items():
            self._append_log(f"  REM {k}: {v}")
        return True

    def _select_album_in_list(self, album: AlbumInfo):
        it = self._cue_store.get_iter_first()
        while it:
            if self._cue_store.get_value(it, CUE_COL_OBJ) is album:
                self._cue_view.get_selection().select_iter(it)
                return
            it = self._cue_store.iter_next(it)

    # ---------------- visuals ----------------

    def _set_cover_image(self, path: Optional[str]):
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
