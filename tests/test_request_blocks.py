import tempfile
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from navgent import AgentSettings, BrowserAgentSession, SandboxRequestBlockedEvent
from navgent.browser.browser_manager import BrowserManager
from navgent.browser.browser_session import BrowserSession
from navgent.browser.request_blocks import BlockedRequest, RequestBlockTracker

PAGE_WITH_OFF_TARGET_REQUESTS = """<!doctype html>
<title>Shop</title>
<h1>Shop</h1>
<img src="http://cdn.blocked.test/logo.png?user=42">
<img src="http://cdn.blocked.test/banner.png">
<script src="http://tracker.blocked.test/t.js"></script>
"""


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        pass


class RequestBlockTrackerTests(unittest.TestCase):
    def test_a_failed_request_to_another_host_is_reported_once(self) -> None:
        tracker = RequestBlockTracker(("www.saucedemo.com",))
        first = tracker.check("https://fonts.example.com/a.woff2?v=1", "net::ERR_NAME_NOT_RESOLVED", 3)
        second = tracker.check("https://fonts.example.com/b.woff2", "net::ERR_NAME_NOT_RESOLVED", 4)
        self.assertEqual(first, BlockedRequest("fonts.example.com", "https://fonts.example.com/a.woff2", "ERR_NAME_NOT_RESOLVED", 3))
        self.assertIsNone(second)

    def test_the_target_and_ordinary_failures_are_not_blocks(self) -> None:
        tracker = RequestBlockTracker(("www.saucedemo.com",))
        cases = (
            ("https://WWW.SAUCEDEMO.COM/inventory.html", "net::ERR_NAME_NOT_RESOLVED"),
            ("https://other.example.com/x.js", "net::ERR_ABORTED"),
            ("https://other.example.com/y.js", None),
            ("data:image/png;base64,AAAA", "net::ERR_NAME_NOT_RESOLVED"),
        )
        for url, failure in cases:
            with self.subTest(url=url, failure=failure):
                self.assertIsNone(tracker.check(url, failure, None))

    def test_blocked_connections_count_as_blocks(self) -> None:
        tracker = RequestBlockTracker(("www.saucedemo.com",))
        blocked = tracker.check("https://1.1.1.1/", "net::ERR_CONNECTION_TIMED_OUT", None)
        self.assertEqual(blocked.host, "1.1.1.1")
        self.assertEqual(blocked.error, "ERR_CONNECTION_TIMED_OUT")


class BrowserRequestBlockTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        Path(directory.name, "shop.html").write_text(PAGE_WITH_OFF_TARGET_REQUESTS, encoding="utf-8")
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=directory.name))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.url = f"http://localhost:{server.server_address[1]}/shop.html"

    async def test_off_target_requests_on_a_real_page_are_reported_with_the_brief_step(self) -> None:
        manager = BrowserManager(allowed_hosts=("localhost",))
        self.addAsyncCleanup(manager.stop)
        blocked: list[BlockedRequest] = []
        browser = BrowserSession(manager, allowed_hosts=("localhost",), on_request_blocked=blocked.append)
        browser.current_brief_step = 2
        await browser.attempt_navigate_and_observe(self.url)
        await browser.page.wait_for_timeout(500)
        await browser.close()
        hosts = []
        for request in blocked:
            hosts.append(request.host)
            self.assertEqual(request.brief_step, 2)
            self.assertEqual(request.error, "ERR_NAME_NOT_RESOLVED")
        self.assertEqual(sorted(hosts), ["cdn.blocked.test", "tracker.blocked.test"])

    async def test_nothing_is_reported_without_an_allowlist(self) -> None:
        manager = BrowserManager()
        self.addAsyncCleanup(manager.stop)
        blocked: list[BlockedRequest] = []
        browser = BrowserSession(manager, on_request_blocked=blocked.append)
        await browser.attempt_navigate_and_observe(self.url)
        await browser.close()
        self.assertEqual(blocked, [])


class SessionRequestBlockTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_session_turns_a_blocked_request_into_an_event(self) -> None:
        with patch("navgent.session.build_browser_agent"):
            session = BrowserAgentSession(AgentSettings(allowed_hosts=("www.saucedemo.com",)))
        session._report_blocked_request(BlockedRequest("cdn.example.com", "https://cdn.example.com/a.js", "ERR_NAME_NOT_RESOLVED", 5))
        event = session._event_queue.get_nowait()
        self.assertEqual(event, SandboxRequestBlockedEvent("cdn.example.com", "https://cdn.example.com/a.js", "ERR_NAME_NOT_RESOLVED", 5))
