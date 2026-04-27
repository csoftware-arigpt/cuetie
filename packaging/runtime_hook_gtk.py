"""PyInstaller runtime hook: wire GTK3 / PyGObject env paths (Linux).

Runs before user code at frozen-app startup. Points GI_TYPELIB_PATH and
GDK_PIXBUF_MODULE_FILE at bundled copies if present.
"""
from __future__ import annotations
import os
import sys


def _base_dir() -> str:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return meipass
    return os.path.dirname(os.path.abspath(sys.executable))


def _setup() -> None:
    base = _base_dir()

    typelib = os.path.join(base, "lib", "girepository-1.0")
    if os.path.isdir(typelib):
        os.environ.setdefault("GI_TYPELIB_PATH", typelib)

    pixbuf_root = os.path.join(base, "lib", "gdk-pixbuf-2.0", "2.10.0")
    loaders_dir = os.path.join(pixbuf_root, "loaders")
    cache_file = os.path.join(pixbuf_root, "loaders.cache")
    if os.path.isdir(loaders_dir):
        os.environ["GDK_PIXBUF_MODULEDIR"] = loaders_dir
        os.environ["GDK_PIXBUF_MODULE_FILE"] = cache_file

    schemas = os.path.join(base, "share", "glib-2.0", "schemas")
    if os.path.isdir(schemas):
        os.environ.setdefault("GSETTINGS_SCHEMA_DIR", schemas)

    fonts = os.path.join(base, "etc", "fonts")
    if os.path.isdir(fonts):
        os.environ.setdefault("FONTCONFIG_PATH", fonts)

    share = os.path.join(base, "share")
    if os.path.isdir(share):
        existing = os.environ.get("XDG_DATA_DIRS", "")
        os.environ["XDG_DATA_DIRS"] = (
            share + (os.pathsep + existing if existing else "")
        )


_setup()
