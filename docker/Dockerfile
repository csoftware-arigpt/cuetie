FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:99 \
    VNC_RESOLUTION=1366x768x24 \
    VNC_PORT=5900 \
    NOVNC_PORT=6080 \
    WEB_PORT=8080 \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-gi \
        python3-gi-cairo \
        gir1.2-gtk-3.0 \
        python3-mutagen \
        python3-charset-normalizer \
        ffmpeg \
        xvfb \
        x11vnc \
        fluxbox \
        novnc \
        websockify \
        nginx \
        supervisor \
        dbus-x11 \
        ca-certificates \
        fonts-dejavu \
        adwaita-icon-theme \
        gnome-icon-theme \
        hicolor-icon-theme \
        shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY cuetie /app/cuetie

COPY docker/supervisord.conf /etc/supervisor/conf.d/cuetie.conf
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY docker/run-cuetie.sh /usr/local/bin/run-cuetie
RUN chmod +x /usr/local/bin/run-cuetie \
    && rm -f /etc/nginx/sites-enabled/default \
    && mkdir -p /data /var/log/nginx /root/.fluxbox

VOLUME ["/data"]
EXPOSE 8080

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf", "-n"]
