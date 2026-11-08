#!/usr/bin/env python3
"""Start, stop and reap the gVisor browser sandboxes for Reprobe runs.

Installed root-owned as /usr/local/bin/sandboxctl. The app user may run it through sudo and nothing else,
so every argument is validated here and the sandbox flags can't be changed by the caller.

    sandboxctl setup
    sandboxctl start --run <run id> --host <target host>    (also opens HTTPS to the fixed CDN list)
    sandboxctl stop --run <run id>
    sandboxctl reap
"""

import argparse
import ipaddress
import json
import re
import socket
import subprocess
import sys
import time

IMAGE = "reprobe-browser:1.64.1"
NETWORK = "reprobe-sbx"
SUBNET = "172.31.0.0/24"
IP_PREFIX = "172.31.0."
FIRST_HOST = 10
LAST_HOST = 250
CONTAINER_PREFIX = "reprobe-sbx-"
RUN_LABEL = "reprobe.run"
IP_LABEL = "reprobe.ip"
TARGET_LABEL = "reprobe.target"
STARTED_LABEL = "reprobe.started"
RULE_PREFIX = "reprobe-run-"
BASE_RULE = "reprobe-base"
SERVER_PORT = "3000/tcp"
CPUS = "1.5"
MEMORY = "1536m"
PIDS = "256"
TMP_SIZE = "512m"
HOME_SIZE = "256m"
TIME_LIMIT_SECONDS = 900
MAX_AGE_SECONDS = 960
READY_SECONDS = 30
READY_LINE = "Listening on"
ALLOWED_PORTS = "80,443"
ASSET_PORT = "443"
# Public, read-only CDNs a target page may load scripts, styles, fonts and images from.
# Keep in sync with ASSET_HOSTS in navgent/browser/constants.py, which limits what the browser may request from them.
ASSET_HOSTS = (
    "cdn.jsdelivr.net",
    "unpkg.com",
    "cdnjs.cloudflare.com",
    "cdn.tailwindcss.com",
    "code.jquery.com",
    "ajax.googleapis.com",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "esm.sh",
)
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,64}$")
HOST_PATTERN = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


class SandboxError(Exception):
    pass


def run(args: list[str], check: bool = True) -> str:
    result = subprocess.run(args, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise SandboxError(f"{' '.join(args[:3])} failed: {result.stderr.strip()}")
    return result.stdout


def validate_run_id(run_id: str) -> str:
    if not RUN_ID_PATTERN.match(run_id):
        raise SandboxError("run id must be 1-64 letters, digits or dashes")
    return run_id


def validate_host(host: str) -> str:
    host = host.strip().lower().rstrip(".")
    if not HOST_PATTERN.match(host):
        raise SandboxError(f"{host!r} is not a public hostname")
    return host


def resolve_public_ip(host: str) -> str:
    try:
        results = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise SandboxError(f"could not resolve {host}: {error}") from error
    for result in results:
        address = result[4][0]
        if ipaddress.ip_address(address).is_global:
            return address
    raise SandboxError(f"{host} does not resolve to a public address")


def container_name(run_id: str) -> str:
    return CONTAINER_PREFIX + run_id


def rule_comment(run_id: str) -> str:
    return RULE_PREFIX + run_id


def list_sandboxes() -> list[dict[str, str]]:
    output = run([
        "docker", "ps", "-a", "--filter", f"label={RUN_LABEL}",
        "--format", "{{.Label \"" + RUN_LABEL + "\"}} {{.Label \"" + IP_LABEL + "\"}} {{.Label \"" + STARTED_LABEL + "\"}}",
    ])
    sandboxes = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) == 3:
            sandboxes.append({"run": parts[0], "ip": parts[1], "started": parts[2]})
    return sandboxes


def pick_ip(sandboxes: list[dict[str, str]]) -> str:
    used = set()
    for sandbox in sandboxes:
        used.add(sandbox["ip"])
    for host_number in range(FIRST_HOST, LAST_HOST + 1):
        address = f"{IP_PREFIX}{host_number}"
        if address not in used:
            return address
    raise SandboxError("no free sandbox address")


def allow_rule(sandbox_ip: str, target_ip: str, run_id: str) -> list[str]:
    return [
        "DOCKER-USER", "-s", sandbox_ip, "-d", target_ip, "-p", "tcp",
        "-m", "multiport", "--dports", ALLOWED_PORTS,
        "-m", "comment", "--comment", rule_comment(run_id), "-j", "ACCEPT",
    ]


def asset_rule(sandbox_ip: str, asset_ip: str, run_id: str) -> list[str]:
    return [
        "DOCKER-USER", "-s", sandbox_ip, "-d", asset_ip, "-p", "tcp", "--dport", ASSET_PORT,
        "-m", "comment", "--comment", rule_comment(run_id), "-j", "ACCEPT",
    ]


def resolve_asset_hosts(target_host: str) -> dict[str, str]:
    """Pin each CDN to one public address for this run, skipping any that don't resolve."""
    resolved = {}
    for asset_host in ASSET_HOSTS:
        if asset_host == target_host:
            continue
        try:
            resolved[asset_host] = resolve_public_ip(asset_host)
        except SandboxError:
            continue
    return resolved


def base_rules() -> list[list[str]]:
    forward = ["DOCKER-USER", "-s", SUBNET, "-m", "comment", "--comment", BASE_RULE, "-j", "DROP"]
    to_host = [
        "INPUT", "-s", SUBNET, "-m", "conntrack", "!", "--ctstate", "ESTABLISHED,RELATED",
        "-m", "comment", "--comment", BASE_RULE, "-j", "DROP",
    ]
    return [forward, to_host]


def build_run_command(
        run_id: str, host: str, sandbox_ip: str, target_ip: str, asset_ips: dict[str, str] | None = None,
) -> list[str]:
    asset_entries = []
    for asset_host, asset_ip in (asset_ips or {}).items():
        asset_entries += ["--add-host", f"{asset_host}:{asset_ip}"]
    return [
        "docker", "run", "--detach", "--rm",
        "--runtime", "runsc",
        "--name", container_name(run_id),
        "--label", f"{RUN_LABEL}={run_id}",
        "--label", f"{IP_LABEL}={sandbox_ip}",
        "--label", f"{TARGET_LABEL}={host}",
        "--label", f"{STARTED_LABEL}={int(time.time())}",
        "--network", NETWORK,
        "--ip", sandbox_ip,
        "--add-host", f"{host}:{target_ip}",
        *asset_entries,
        "--dns", "127.0.0.1",
        "--cpus", CPUS,
        "--memory", MEMORY,
        "--memory-swap", MEMORY,
        "--pids-limit", PIDS,
        "--read-only",
        "--tmpfs", f"/tmp:size={TMP_SIZE}",
        "--tmpfs", f"/home/pwuser:size={HOME_SIZE},mode=1777",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--publish", "127.0.0.1::3000",
        IMAGE,
    ]


def published_endpoint(run_id: str) -> str:
    output = run(["docker", "port", container_name(run_id), SERVER_PORT]).strip()
    address = output.splitlines()[0]
    return f"ws://{address}/"


def wait_until_ready(run_id: str) -> None:
    deadline = time.monotonic() + READY_SECONDS
    while time.monotonic() < deadline:
        logs = run(["docker", "logs", container_name(run_id)], check=False)
        if READY_LINE in logs:
            return
        time.sleep(0.25)
    raise SandboxError("the browser server did not start in time")


def delete_rules(comment: str) -> None:
    for chain in ("DOCKER-USER", "INPUT"):
        output = run(["iptables", "-S", chain], check=False)
        for line in output.splitlines():
            if f"--comment {comment}" in line and line.startswith("-A "):
                run(["iptables", "-D"] + line.split()[1:], check=False)


def setup() -> dict:
    networks = run(["docker", "network", "ls", "--format", "{{.Name}}"]).split()
    if NETWORK not in networks:
        run([
            "docker", "network", "create", NETWORK, "--subnet", SUBNET,
            "--opt", "com.docker.network.bridge.enable_icc=false",
        ])
    for rule in base_rules():
        exists = subprocess.run(["iptables", "-C"] + rule, capture_output=True).returncode == 0
        if not exists:
            run(["iptables", "-I"] + rule)
    return {"network": NETWORK, "subnet": SUBNET}


def start(run_id: str, host: str) -> dict:
    run_id = validate_run_id(run_id)
    host = validate_host(host)
    target_ip = resolve_public_ip(host)
    asset_ips = resolve_asset_hosts(host)
    sandbox_ip = pick_ip(list_sandboxes())
    run(["iptables", "-I"] + allow_rule(sandbox_ip, target_ip, run_id))
    try:
        for asset_ip in sorted(set(asset_ips.values())):
            run(["iptables", "-I"] + asset_rule(sandbox_ip, asset_ip, run_id))
        run(build_run_command(run_id, host, sandbox_ip, target_ip, asset_ips))
        wait_until_ready(run_id)
        endpoint = published_endpoint(run_id)
    except Exception:
        stop(run_id)
        raise
    return {
        "container": container_name(run_id),
        "ws_endpoint": endpoint,
        "runtime": "gVisor (runsc)",
        "allowed_hosts": [host],
        "asset_hosts": list(asset_ips),
        "limits": {
            "cpus": float(CPUS),
            "memory_mb": 1536,
            "pids": int(PIDS),
            "time_limit_seconds": TIME_LIMIT_SECONDS,
        },
    }


def stop(run_id: str) -> dict:
    run_id = validate_run_id(run_id)
    run(["docker", "rm", "--force", container_name(run_id)], check=False)
    delete_rules(rule_comment(run_id))
    return {"container": container_name(run_id), "stopped": True}


def reap() -> dict:
    now = int(time.time())
    removed = []
    handled_runs = set()
    for sandbox in list_sandboxes():
        handled_runs.add(sandbox["run"])
        if sandbox["started"].isdigit() and now - int(sandbox["started"]) > MAX_AGE_SECONDS:
            stop(sandbox["run"])
            removed.append(sandbox["run"])
    for comment in orphan_rule_comments(handled_runs):
        delete_rules(comment)
        removed.append(comment.removeprefix(RULE_PREFIX))
    return {"removed": removed}


def orphan_rule_comments(known_runs: set[str]) -> list[str]:
    comments = []
    output = run(["iptables", "-S", "DOCKER-USER"], check=False)
    for line in output.splitlines():
        match = re.search(r"--comment (" + RULE_PREFIX + r"[A-Za-z0-9-]+)", line)
        if match is None:
            continue
        comment = match.group(1)
        if comment.removeprefix(RULE_PREFIX) not in known_runs and comment not in comments:
            comments.append(comment)
    return comments


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage Reprobe browser sandboxes.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("setup", help="Create the sandbox network and base firewall rules.")
    start_parser = commands.add_parser("start", help="Start a sandbox for one run.")
    start_parser.add_argument("--run", required=True)
    start_parser.add_argument("--host", required=True)
    stop_parser = commands.add_parser("stop", help="Destroy a run's sandbox and its rules.")
    stop_parser.add_argument("--run", required=True)
    commands.add_parser("reap", help="Destroy sandboxes past their age limit and orphaned rules.")
    args = parser.parse_args()
    try:
        if args.command == "setup":
            result = setup()
        elif args.command == "start":
            result = start(args.run, args.host)
        elif args.command == "stop":
            result = stop(args.run)
        else:
            result = reap()
    except SandboxError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
