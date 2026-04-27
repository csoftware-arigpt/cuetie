import sys

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Gio

GLib.set_prgname("cuetie")
GLib.set_application_name("CUEtie")

from .ui.main_window import MainWindow


def _follow_system_theme():
    settings = Gtk.Settings.get_default()
    if settings is None:
        return
    settings.set_property("gtk-application-prefer-dark-theme", _detect_dark_mode())


def _detect_dark_mode() -> bool:
    try:
        import subprocess
        result = subprocess.run(
            ["dbus-send", "--session", "--print-reply=literal",
             "--dest=org.freedesktop.portal.Desktop",
             "/org/freedesktop/portal/desktop",
             "org.freedesktop.portal.Settings.Read",
             "string:org.freedesktop.appearance",
             "string:color-scheme"],
            capture_output=True, text=True, timeout=2,
        )
        return "uint32 1" in result.stdout
    except Exception:
        return False


class CUEtieApp(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id="io.github.cuetie",
            flags=Gio.ApplicationFlags.HANDLES_OPEN,
        )

    def do_activate(self):
        _follow_system_theme()
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
