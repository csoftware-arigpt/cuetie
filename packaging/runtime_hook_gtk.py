"""PyInstaller runtime hook: wire GTK3 / PyGObject env paths.

Runs before user code at frozen-app startup. Points GI_TYPELIB_PATH and
GDK_PIXBUF_MODULE_FILE at bundled copies and regenerates loaders.cache so
absolute MSYS2 paths baked at build time don't poison the user's machine.
"""
from __future__ import annotations
import os
import sys
import subprocess


def _base_dir() -> str:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return meipass
    return os.path.dirname(os.path.abspath(sys.executable))


def _install_crash_log() -> None:
    if os.name != "nt":
        return
    try:
        log_dir = os.path.join(
            os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
            "CUEtie",
        )
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "cuetie-crash.log")
        f = open(log_path, "a", encoding="utf-8", buffering=1)
        sys.stderr = f
        sys.stdout = f
        import traceback

        def _hook(exc_type, exc, tb):
            traceback.print_exception(exc_type, exc, tb, file=f)
            f.flush()

        sys.excepthook = _hook
    except Exception:
        pass


def _setup() -> None:
    _install_crash_log()
    base = _base_dir()

    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(base)
        except Exception:
            pass

    typelib = os.path.join(base, "lib", "girepository-1.0")
    if os.path.isdir(typelib):
        os.environ.setdefault("GI_TYPELIB_PATH", typelib)

    pixbuf_root = os.path.join(base, "lib", "gdk-pixbuf-2.0", "2.10.0")
    loaders_dir = os.path.join(pixbuf_root, "loaders")
    cache_file = os.path.join(pixbuf_root, "loaders.cache")
    query_bin = os.path.join(base, "gdk-pixbuf-query-loaders.exe")
    if os.path.isdir(loaders_dir):
        os.environ["GDK_PIXBUF_MODULEDIR"] = loaders_dir
        os.environ["GDK_PIXBUF_MODULE_FILE"] = cache_file
        if os.path.isfile(query_bin):
            try:
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                result = subprocess.run(
                    [query_bin],
                    capture_output=True, text=True,
                    env={**os.environ},
                    creationflags=creationflags,
                )
                if result.returncode == 0 and result.stdout:
                    with open(cache_file, "w", encoding="utf-8") as f:
                        f.write(result.stdout)
            except Exception:
                pass

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

    os.environ.setdefault("GTK_PATH", base)
    os.environ.setdefault("GTK_EXE_PREFIX", base)
    os.environ.setdefault("GTK_DATA_PREFIX", base)


_setup()
