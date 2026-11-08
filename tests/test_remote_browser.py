import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
from playwright.async_api import Error as PlaywrightError

from navgent.browser.browser_manager import (
    BrowserManager,
    build_host_resolver_rules,
    build_launch_args,
)
from navgent.browser.browser_session import BrowserSession

SITE = Path(__file__).resolve().parent / "e2e" / "nav"
SERVER_START_SECONDS = 30


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        pass


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_port(port: int, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + SERVER_START_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("playwright run-server exited before it was ready")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("playwright run-server did not start in time")


class HostResolverRuleTests(unittest.TestCase):
    def test_rules_block_every_host_except_the_allowed_ones(self) -> None:
        rules = build_host_resolver_rules(("www.saucedemo.com", "api.saucedemo.com"))
        self.assertEqual(
            rules,
            "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE www.saucedemo.com, EXCLUDE api.saucedemo.com",
        )

    def test_no_allowed_hosts_adds_no_rule(self) -> None:
        self.assertEqual(build_launch_args(()), ["--disable-blink-features=AutomationControlled"])


class RemoteBrowserTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        handler = partial(QuietHandler, directory=str(SITE))
        cls.site = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.site.serve_forever, daemon=True).start()
        cls.site_port = cls.site.server_address[1]
        cls.server_port = free_port()
        command = [
            sys.executable, "-m", "playwright", "run-server",
            "--host", "127.0.0.1", "--port", str(cls.server_port), "--unsafe",
        ]
        cls.server = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            wait_for_port(cls.server_port, cls.server)
        except RuntimeError:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.terminate()
        cls.server.wait(timeout=10)
        cls.site.shutdown()
        cls.site.server_close()

    def endpoint(self) -> str:
        return f"ws://127.0.0.1:{self.server_port}/"

    def page_url(self, host: str) -> str:
        return f"http://{host}:{self.site_port}/home.html"

    async def test_a_remote_tab_is_recorded_on_this_machine(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        folder = Path(directory.name)
        manager = BrowserManager(ws_endpoint=self.endpoint(), allowed_hosts=("localhost",))
        self.addAsyncCleanup(manager.stop)
        browser = BrowserSession(manager, recording_dir=folder)
        await browser.attempt_navigate_and_observe(self.page_url("localhost"))
        await browser.page.wait_for_timeout(500)
        await browser.close()
        self.assertEqual(len(browser.recording_paths), 1)
        path = browser.recording_paths[0]
        self.assertEqual(path.parent, folder)
        video = cv2.VideoCapture(str(path))
        readable, _ = video.read()
        video.release()
        self.assertTrue(readable)

    async def test_a_remote_browser_cannot_resolve_hosts_outside_the_allowlist(self) -> None:
        manager = BrowserManager(ws_endpoint=self.endpoint(), allowed_hosts=("www.saucedemo.com",))
        self.addAsyncCleanup(manager.stop)
        browser = await manager.start()
        page = await browser.new_page()
        with self.assertRaisesRegex(PlaywrightError, "ERR_NAME_NOT_RESOLVED"):
            await page.goto(self.page_url("localhost"))

    async def test_a_remote_browser_reaches_an_allowed_host(self) -> None:
        manager = BrowserManager(ws_endpoint=self.endpoint(), allowed_hosts=("localhost",))
        self.addAsyncCleanup(manager.stop)
        browser = await manager.start()
        page = await browser.new_page()
        response = await page.goto(self.page_url("localhost"))
        self.assertEqual(response.status, 200)


class LocalAllowlistTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_local_browser_honors_the_allowlist_too(self) -> None:
        manager = BrowserManager(allowed_hosts=("www.saucedemo.com",))
        self.addAsyncCleanup(manager.stop)
        browser = await manager.start()
        page = await browser.new_page()
        with self.assertRaisesRegex(PlaywrightError, "ERR_NAME_NOT_RESOLVED"):
            await page.goto("http://example.com/")
