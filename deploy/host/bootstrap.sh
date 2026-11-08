#!/usr/bin/env bash
# One-time setup for a fresh Ubuntu 24.04 Reprobe VM. Run as root.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y ca-certificates curl gnupg git python3 python3-venv debian-keyring debian-archive-keyring apt-transport-https

install -m 0755 -d /etc/apt/keyrings

curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list

curl -fsSL https://gvisor.dev/archive.key | gpg --dearmor --yes -o /etc/apt/keyrings/gvisor.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/gvisor.gpg] https://storage.googleapis.com/gvisor/releases release main" \
    > /etc/apt/sources.list.d/gvisor.list

curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor --yes -o /etc/apt/keyrings/caddy.gpg
echo "deb [signed-by=/etc/apt/keyrings/caddy.gpg] https://dl.cloudsmith.io/public/caddy/stable/deb/debian any-version main" \
    > /etc/apt/sources.list.d/caddy.list

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin runsc caddy

runsc install
systemctl restart docker

curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh

id reprobe >/dev/null 2>&1 || useradd --system --create-home --home-dir /opt/reprobe --shell /usr/sbin/nologin reprobe
install -d -o reprobe -g reprobe -m 0750 /var/lib/reprobe
install -d -o root -g reprobe -m 0750 /etc/reprobe

sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl reload ssh

if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
    ufw allow 80/tcp
    ufw allow 443/tcp
fi

docker run --rm --runtime=runsc alpine dmesg | head -3
echo "Bootstrap done."
