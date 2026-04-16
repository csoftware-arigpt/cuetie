import sys

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio

from .ui.main_window import MainWindow


class CUEtieApp(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id="io.github.cuetie",
            flags=Gio.ApplicationFlags.HANDLES_OPEN,
        )

    def do_activate(self):
        MainWindow(self).show_all()

    def do_open(self, files, n_files, hint):
        win = MainWindow(self)
        win.show_all()
        for gfile in files:
            path = gfile.get_path()
            if path and path.lower().endswith(".cue"):
                win._load_cue(path)
                break


def main():
    sys.exit(CUEtieApp().run(sys.argv))


if __name__ == "__main__":
    main()
