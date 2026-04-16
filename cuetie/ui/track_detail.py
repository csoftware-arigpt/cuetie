from __future__ import annotations
from typing import Optional

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ..cue_parser import TrackInfo


class TrackDetailPanel(Gtk.Frame):
    def __init__(self):
        super().__init__(label=" Track metadata ")
        self._track: Optional[TrackInfo] = None

        grid = Gtk.Grid(column_spacing=8, row_spacing=4, border_width=8)
        self.add(grid)

        self._fields: dict[str, Gtk.Entry] = {}
        rows = [
            ("Title",     "title"),
            ("Performer", "performer"),
            ("Songwriter","songwriter"),
            ("ISRC",      "isrc"),
            ("Flags",     "flags"),
            ("Pregap",    "pregap"),
            ("Postgap",   "postgap"),
        ]
        for row, (label, key) in enumerate(rows):
            lbl = Gtk.Label(label=label + ":", xalign=1.0)
            grid.attach(lbl, 0, row, 1, 1)
            entry = Gtk.Entry(hexpand=True)
            if key in ("flags", "pregap", "postgap"):
                entry.set_sensitive(False)
            entry.connect("changed", self._on_field_changed, key)
            grid.attach(entry, 1, row, 1, 1)
            self._fields[key] = entry

        self.set_sensitive(False)

    def load(self, track: Optional[TrackInfo]):
        self._track = None
        self.set_sensitive(track is not None)
        if track is None:
            for e in self._fields.values():
                e.set_text("")
            return
        self._fields["title"].set_text(track.title)
        self._fields["performer"].set_text(track.performer)
        self._fields["songwriter"].set_text(track.songwriter)
        self._fields["isrc"].set_text(track.isrc)
        self._fields["flags"].set_text(" ".join(track.flags))
        self._fields["pregap"].set_text(track.pregap or "")
        self._fields["postgap"].set_text(track.postgap or "")
        self._track = track

    def _on_field_changed(self, entry: Gtk.Entry, key: str):
        if self._track is None:
            return
        val = entry.get_text()
        if key == "title":
            self._track.title = val
        elif key == "performer":
            self._track.performer = val
        elif key == "songwriter":
            self._track.songwriter = val
        elif key == "isrc":
            self._track.isrc = val
