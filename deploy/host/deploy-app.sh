#!/usr/bin/env bash
# Run as root on the VM. Expects the source tarball at /root/reprobe-src.tar and /etc/reprobe/reprobe.env.
set -euo pipefail

HOST=${1:?usage: deploy-app.sh <public host name>}
SOURCE=/opt/reprobe/src
VENV=/opt/reprobe/venv

test -f /etc/reprobe/reprobe.env || { echo "/etc/reprobe/reprobe.env is missing" >&2; exit 1; }

rm -rf "$SOURCE.new"
mkdir "$SOURCE.new"
tar -xf /root/reprobe-src.tar -C "$SOURCE.new"
rm -rf "$SOURCE"
mv "$SOURCE.new" "$SOURCE"
chown -R reprobe:reprobe "$SOURCE"
cd /opt/reprobe

if [ ! -x "$VENV/bin/python" ]; then
    sudo -u reprobe -H uv venv --python 3.12 "$VENV"
fi
sudo -u reprobe -H uv pip install --python "$VENV/bin/python" -r "$SOURCE/app/requirements.txt"

install -o root -g root -m 0644 "$SOURCE/deploy/host/reprobe.service" /etc/systemd/system/reprobe.service
systemctl daemon-reload
systemctl enable reprobe.service
systemctl restart reprobe.service

sed "s/REPROBE_HOST/$HOST/" "$SOURCE/deploy/host/Caddyfile" > /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
systemctl reload caddy

for attempt in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:8000/health; then
        echo
        echo "Deployed to https://$HOST"
        exit 0
    fi
    sleep 1
done
journalctl -u reprobe --no-pager -n 40
exit 1
