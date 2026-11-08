import importlib.util
import socket
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "sandbox" / "sandboxctl.py"
spec = importlib.util.spec_from_file_location("sandboxctl", SCRIPT)
sandboxctl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sandboxctl)


def address_info(*addresses: str) -> list:
    results = []
    for address in addresses:
        results.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)))
    return results


class FakeHost:
    """Records commands and answers the few that sandboxctl reads."""

    def __init__(self, sandboxes: str = "", rules: str = "-N DOCKER-USER", fail_on: str | None = None):
        self.commands: list[list[str]] = []
        self.sandboxes = sandboxes
        self.rules = rules
        self.fail_on = fail_on

    def run(self, args: list[str], check: bool = True) -> str:
        self.commands.append(args)
        if self.fail_on and args[:2] == ["docker", self.fail_on]:
            raise sandboxctl.SandboxError(f"docker {self.fail_on} failed")
        if args[:2] == ["docker", "ps"]:
            return self.sandboxes
        if args[:2] == ["docker", "logs"]:
            return "Listening on ws://0.0.0.0:3000/\n"
        if args[:2] == ["docker", "port"]:
            return "127.0.0.1:49153\n"
        if args[:2] == ["iptables", "-S"] and args[2] == "DOCKER-USER":
            return self.rules
        return ""

    def find(self, *prefix: str) -> list[list[str]]:
        found = []
        for command in self.commands:
            if command[:len(prefix)] == list(prefix):
                found.append(command)
        return found


class ValidationTests(unittest.TestCase):
    def test_run_ids_are_letters_digits_and_dashes_only(self) -> None:
        self.assertEqual(sandboxctl.validate_run_id("3f2a-9c"), "3f2a-9c")
        for value in ("", "../etc", "a;b", "a b", "x" * 65):
            with self.subTest(value=value):
                with self.assertRaises(sandboxctl.SandboxError):
                    sandboxctl.validate_run_id(value)

    def test_hosts_must_be_public_hostnames(self) -> None:
        self.assertEqual(sandboxctl.validate_host(" WWW.SauceDemo.com. "), "www.saucedemo.com")
        for value in ("localhost", "169.254.169.254", "10.0.0.1", "-bad.com", "a b.com", "host"):
            with self.subTest(value=value):
                with self.assertRaises(sandboxctl.SandboxError):
                    sandboxctl.validate_host(value)

    def test_a_host_that_resolves_to_a_private_address_is_refused(self) -> None:
        with patch.object(sandboxctl.socket, "getaddrinfo", return_value=address_info("10.1.2.3", "127.0.0.1")):
            with self.assertRaisesRegex(sandboxctl.SandboxError, "public address"):
                sandboxctl.resolve_public_ip("internal.example.com")

    def test_the_first_public_address_is_used(self) -> None:
        with patch.object(sandboxctl.socket, "getaddrinfo", return_value=address_info("192.168.1.5", "151.101.1.1")):
            self.assertEqual(sandboxctl.resolve_public_ip("www.saucedemo.com"), "151.101.1.1")


class AddressTests(unittest.TestCase):
    def test_pick_ip_skips_addresses_in_use(self) -> None:
        sandboxes = [
            {"run": "a", "ip": "172.31.0.10", "started": "1"},
            {"run": "b", "ip": "172.31.0.11", "started": "1"},
        ]
        self.assertEqual(sandboxctl.pick_ip(sandboxes), "172.31.0.12")


class RunCommandTests(unittest.TestCase):
    def test_the_container_is_contained(self) -> None:
        command = sandboxctl.build_run_command("run-1", "www.saucedemo.com", "172.31.0.10", "151.101.1.1")
        joined = " ".join(command)
        expected_flags = (
            "--runtime runsc", "--network reprobe-sbx", "--ip 172.31.0.10",
            "--add-host www.saucedemo.com:151.101.1.1", "--dns 127.0.0.1",
            "--cpus 1.5", "--memory 1536m", "--memory-swap 1536m", "--pids-limit 256",
            "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges",
            "--publish 127.0.0.1::3000", "--rm",
        )
        for flag in expected_flags:
            with self.subTest(flag=flag):
                self.assertIn(flag, joined)
        for forbidden in ("-e", "--env", "--env-file", "-v", "--volume", "--mount", "--privileged"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, command)
        self.assertEqual(command[-1], "reprobe-browser:1.64.1")


class LifecycleTests(unittest.TestCase):
    def test_start_allows_the_target_then_runs_the_sandbox(self) -> None:
        host = FakeHost()
        with patch.object(sandboxctl, "run", side_effect=host.run):
            with patch.object(sandboxctl.socket, "getaddrinfo", return_value=address_info("151.101.1.1")):
                result = sandboxctl.start("run-1", "www.saucedemo.com")
        self.assertEqual(result["ws_endpoint"], "ws://127.0.0.1:49153/")
        self.assertEqual(result["allowed_hosts"], ["www.saucedemo.com"])
        insert = host.find("iptables", "-I")[0]
        self.assertIn("172.31.0.10", insert)
        self.assertIn("151.101.1.1", insert)
        self.assertIn("reprobe-run-run-1", insert)
        self.assertLess(host.commands.index(insert), host.commands.index(host.find("docker", "run")[0]))

    def test_a_failed_start_removes_the_container_and_its_rules(self) -> None:
        rule = (
            "-A DOCKER-USER -s 172.31.0.10/32 -d 151.101.1.1/32 -p tcp "
            "-m comment --comment reprobe-run-run-1 -j ACCEPT"
        )
        host = FakeHost(rules=rule, fail_on="run")
        with patch.object(sandboxctl, "run", side_effect=host.run):
            with patch.object(sandboxctl.socket, "getaddrinfo", return_value=address_info("151.101.1.1")):
                with self.assertRaises(sandboxctl.SandboxError):
                    sandboxctl.start("run-1", "www.saucedemo.com")
        self.assertEqual(host.find("docker", "rm")[0][-1], "reprobe-sbx-run-1")
        deletes = host.find("iptables", "-D")
        self.assertEqual(deletes[0][2:], rule.split()[1:])

    def test_stop_only_deletes_rules_for_that_run(self) -> None:
        rules = "\n".join([
            "-N DOCKER-USER",
            "-A DOCKER-USER -s 172.31.0.10/32 -m comment --comment reprobe-run-run-1 -j ACCEPT",
            "-A DOCKER-USER -s 172.31.0.11/32 -m comment --comment reprobe-run-run-2 -j ACCEPT",
            "-A DOCKER-USER -s 172.31.0.0/24 -m comment --comment reprobe-base -j DROP",
        ])
        host = FakeHost(rules=rules)
        with patch.object(sandboxctl, "run", side_effect=host.run):
            sandboxctl.stop("run-1")
        deletes = host.find("iptables", "-D")
        self.assertEqual(len(deletes), 1)
        self.assertIn("reprobe-run-run-1", deletes[0])

    def test_reap_removes_old_sandboxes_and_orphaned_rules(self) -> None:
        sandboxes = "old 172.31.0.10 1000\nfresh 172.31.0.11 99999\n"
        rules = "\n".join([
            "-A DOCKER-USER -s 172.31.0.10/32 -m comment --comment reprobe-run-old -j ACCEPT",
            "-A DOCKER-USER -s 172.31.0.11/32 -m comment --comment reprobe-run-fresh -j ACCEPT",
            "-A DOCKER-USER -s 172.31.0.12/32 -m comment --comment reprobe-run-gone -j ACCEPT",
        ])
        host = FakeHost(sandboxes=sandboxes, rules=rules)
        with patch.object(sandboxctl, "run", side_effect=host.run):
            with patch.object(sandboxctl.time, "time", return_value=100000):
                result = sandboxctl.reap()
        self.assertEqual(sorted(result["removed"]), ["gone", "old"])
        removed_containers = []
        for command in host.find("docker", "rm"):
            removed_containers.append(command[-1])
        self.assertEqual(removed_containers, ["reprobe-sbx-old"])
