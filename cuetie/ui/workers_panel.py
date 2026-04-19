from __future__ import annotations
from typing import Callable

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk


class WorkersPanel(Gtk.Frame):
    """
    Live list of currently running ffmpeg workers.

    Each row shows [album · title] with a per-worker × button that
    terminates just that subprocess. The surrounding batch keeps
    running; use the main Cancel button to kill every worker.
    """

    def __init__(self, on_kill_one: Callable[[int], None]):
        super().__init__(label=" Running workers ")
        self._on_kill_one = on_kill_one
        self._rows: dict[int, Gtk.ListBoxRow] = {}

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                      border_width=6)
        self.add(box)

        self._empty_label = Gtk.Label(
            label="No running workers.", xalign=0.0,
        )
        self._empty_label.get_style_context().add_class("dim-label")
        box.pack_start(self._empty_label, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(60)
        self._listbox = Gtk.ListBox()
        self._listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll.add(self._listbox)
        box.pack_start(scroll, True, True, 0)

    def add_worker(self, task_id: int, album_tag: str, title: str) -> None:
        if task_id in self._rows:
            return
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                       border_width=4)
        row.add(hbox)

        spinner = Gtk.Spinner()
        spinner.start()
        hbox.pack_start(spinner, False, False, 0)

        label = Gtk.Label(
            label=f"{album_tag} · {title}", xalign=0.0, hexpand=True,
            ellipsize=3,
        )
        hbox.pack_start(label, True, True, 0)

        btn = Gtk.Button(label="×")
        btn.set_tooltip_text("Kill this worker only")
        btn.connect("clicked", lambda _: self._on_kill_one(task_id))
        hbox.pack_start(btn, False, False, 0)

        self._listbox.add(row)
        row.show_all()
        self._rows[task_id] = row
        self._update_empty()

    def remove_worker(self, task_id: int) -> None:
        row = self._rows.pop(task_id, None)
        if row is not None:
            self._listbox.remove(row)
        self._update_empty()

    def clear(self) -> None:
        for row in list(self._rows.values()):
            self._listbox.remove(row)
        self._rows.clear()
        self._update_empty()

    def _update_empty(self) -> None:
        self._empty_label.set_visible(not self._rows)
