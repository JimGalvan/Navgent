#!/usr/bin/env bash
# Run as root on the VM from the repo root after Docker and gVisor (runsc) are installed.
set -euo pipefail

docker info --format '{{json .Runtimes}}' | grep -q runsc || { echo "runsc is not a Docker runtime" >&2; exit 1; }

install -o root -g root -m 0755 deploy/sandbox/sandboxctl.py /usr/local/bin/sandboxctl
install -o root -g root -m 0440 deploy/host/reprobe-sandbox.sudoers /etc/sudoers.d/reprobe-sandbox
visudo -cf /etc/sudoers.d/reprobe-sandbox

for unit in reprobe-sandbox-setup.service reprobe-sandbox-reap.service reprobe-sandbox-reap.timer; do
    install -o root -g root -m 0644 "deploy/host/$unit" "/etc/systemd/system/$unit"
done

docker build -t reprobe-browser:1.64.1 deploy/sandbox

systemctl daemon-reload
systemctl enable --now reprobe-sandbox-setup.service reprobe-sandbox-reap.timer
sandboxctl setup
echo "Sandbox installed. Try: sandboxctl start --run smoke --host www.saucedemo.com"
