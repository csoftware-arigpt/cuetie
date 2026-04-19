#!/usr/bin/env bash
# Launch CUEtie under a private D-Bus session so Gtk.Application can register
# its application_id. Wait briefly for the X server to come up.
set -euo pipefail

export DISPLAY="${DISPLAY:-:99}"
export HOME="${HOME:-/root}"
export PYTHONPATH="${PYTHONPATH:-/app}"
export GTK_A11Y="${GTK_A11Y:-none}"
export NO_AT_BRIDGE=1

# Wait for Xvfb socket before starting GTK.
for _ in $(seq 1 30); do
    if [ -S "/tmp/.X11-unix/X${DISPLAY#:}" ]; then
        break
    fi
    sleep 0.2
done

cd /app
exec dbus-run-session -- /usr/bin/python3 -m cuetie
