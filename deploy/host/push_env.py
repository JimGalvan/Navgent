"""Write /etc/reprobe/reprobe.env on the VM from the local .env, without printing any secret.

    python deploy/host/push_env.py root@144.202.90.160

Only the keys the deployed app needs are copied. OPENAI_API_KEY and the Vultr account key stay local.
REPROBE_CREDENTIAL_KEY is kept if the VM already has one, otherwise the VM generates it.
"""

import subprocess
import sys
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
SECRET_NAMES = ("VULTR_INFERENCE_API_KEY", "WORKOS_API_KEY", "WORKOS_CLIENT_ID", "WORKOS_COOKIE_PASSWORD")
SETTINGS = {
    "VULTR_INFERENCE_BASE_URL": "https://api.vultrinference.com/v1",
    "REPROBE_STRONG_MODEL": "vultr:glm-5.3",
    "REPROBE_FAST_MODEL": "vultr:glm-5.3-flash",
    "REPROBE_EVIDENCE_MODEL": "vultr:glm-5.3-flash",
    "REPROBE_SANDBOX": "docker",
    "REPROBE_DATA_DIR": "/var/lib/reprobe",
    "REPROBE_MAX_CONCURRENT_RUNS": "2",
    "REPROBE_HEADLESS": "true",
}
REMOTE_COMMAND = """set -e
umask 027
target=/etc/reprobe/reprobe.env
key=$(grep '^REPROBE_CREDENTIAL_KEY=' "$target" 2>/dev/null || echo "REPROBE_CREDENTIAL_KEY=$(openssl rand -base64 32)")
cat > "$target.new"
echo "$key" >> "$target.new"
chown root:reprobe "$target.new"
chmod 640 "$target.new"
mv "$target.new" "$target"
echo "wrote $target with $(grep -c = "$target") settings"
"""


def read_local_env() -> dict[str, str]:
    values = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.partition("=")
        if separator and not name.strip().startswith("#"):
            values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def build_env_file(local: dict[str, str]) -> str:
    lines = []
    for name in SECRET_NAMES:
        value = local.get(name, "")
        if not value:
            raise SystemExit(f"{name} is missing from {ENV_FILE}")
        lines.append(f"{name}={value}")
    for name, value in SETTINGS.items():
        lines.append(f"{name}={value}")
    return "\n".join(lines) + "\n"


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python deploy/host/push_env.py root@<vm ip>")
    content = build_env_file(read_local_env())
    subprocess.run(["ssh", "-o", "BatchMode=yes", sys.argv[1], REMOTE_COMMAND], input=content, text=True, check=True)


if __name__ == "__main__":
    main()
