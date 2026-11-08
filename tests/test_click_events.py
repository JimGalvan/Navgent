import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2

from navgent.browser.browser_manager import BrowserManager
from navgent.browser.browser_session import BrowserSession
from navgent.browser.models import Bounds, Element
from navgent.browser.recording import PerformedClick, Recording
from navgent.browser_agent.tools import build_browser_tools
from navgent.event_utils import EventUtils
from navgent.events import BrowserClickEvent

NO_BOUNDS = Bounds(0, 0, 0, 0, 0, 0, 0, 0)

LEAVING_PAGE = """
<!doctype html>
<html><body style="margin:0">
  <button id="go" style="position:absolute;left:200px;top:120px;width:100px;height:40px"
          onclick="location.href='next.html'">Go</button>
</body></html>
"""

NEXT_PAGE = "<!doctype html><html><body><p>Next page</p></body></html>"

FRAME_PAGE = """
<!doctype html>
<html><body style="margin:0">
  <iframe style="position:absolute;left:100px;top:50px;width:400px;height:300px;border:4px solid black"
          srcdoc="<body style='margin:0'><button style='position:absolute;left:10px;top:20px;width:80px;height:40px'>Inner</button></body>">
  </iframe>
</body></html>
"""

FLASH_PAGE = """
<!doctype html>
<html><body style="margin:0;background:#000">
  <button id="flash" style="position:absolute;left:20px;top:20px;width:120px;height:40px;background:#000;color:#000;border:0"
          onclick="document.body.style.background='#fff'">Flash</button>
</body></html>
"""

POPUP_PAGE = """
<!doctype html>
<html><body>
  <button id="open" onclick="window.open('closing.html')">Open</button>
</body></html>
"""

CLOSING_PAGE = """
<!doctype html>
<html><body><p>Closing soon</p><script>setTimeout(() => window.close(), 400)</script></body></html>
"""


def element_named(observation, text):
    for element in observation.elements:
        if element.text.strip() == text:
            return element
    raise AssertionError(f"No element named {text}")


def first_bright_frame_after_dark_ms(path: Path) -> float:
    video = cv2.VideoCapture(str(path))
    frames_per_second = video.get(cv2.CAP_PROP_FPS)
    number = 0
    seen_dark = False
    while True:
        readable, image = video.read()
        if not readable:
            break
        bright = image.mean() > 128
        if seen_dark and bright:
            video.release()
            return number * 1000 / frames_per_second
        seen_dark = seen_dark or not bright
        number += 1
    video.release()
    raise AssertionError("The recording never turned bright after the dark page")


class RecordingTimelineTests(unittest.TestCase):
    def test_wall_time_maps_to_playback_time_from_the_first_frame(self) -> None:
        recording = Recording("abc", Path("abc.webm"), 1365, 768, start_wall_time_ms=1_000.0)
        self.assertEqual(recording.recording_time_ms(1_250.5), 250.5)
        self.assertEqual(recording.recording_time_ms(1_000.0), 0)

    def test_times_before_the_first_frame_have_no_playback_time(self) -> None:
        recording = Recording("abc", Path("abc.webm"), 1365, 768, start_wall_time_ms=1_000.0)
        self.assertIsNone(recording.recording_time_ms(999.0))

    def test_recording_without_frames_has_no_playback_time(self) -> None:
        recording = Recording("abc", Path("abc.webm"), 1365, 768, start_wall_time_ms=None)
        self.assertIsNone(recording.recording_time_ms(5_000.0))


class ClickCaptureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.site = Path(directory.name) / "site"
        self.site.mkdir()
        self.recordings = Path(directory.name) / "recordings"
        for name, html in {
            "leaving.html": LEAVING_PAGE,
            "next.html": NEXT_PAGE,
            "frame.html": FRAME_PAGE,
            "flash.html": FLASH_PAGE,
            "popup.html": POPUP_PAGE,
            "closing.html": CLOSING_PAGE,
        }.items():
            (self.site / name).write_text(html, encoding="utf-8")
        self.manager = BrowserManager(headless=True)
        self.addAsyncCleanup(self.manager.stop)

    def browser(self, recording: bool = True) -> BrowserSession:
        browser = BrowserSession(self.manager, recording_dir=self.recordings if recording else None)
        self.addAsyncCleanup(browser.close)
        return browser

    async def test_click_keeps_the_dispatched_point_after_the_page_navigates(self) -> None:
        browser = self.browser()
        observation = await browser.attempt_navigate_and_observe((self.site / "leaving.html").as_uri())
        button = element_named(observation, "Go")
        await browser.click(button.index)
        await browser.wait_for_page_to_settle()
        self.assertTrue(browser.page.url.endswith("next.html"))

        [click] = browser.take_performed_clicks()
        self.assertEqual((click.x, click.y), (250, 140))
        self.assertEqual((click.x, click.y), (button.cx, button.cy))
        self.assertEqual((click.viewport_width, click.viewport_height), (1365, 768))
        self.assertRegex(click.id, "^[0-9a-f]{32}$")
        self.assertEqual(browser.take_performed_clicks(), [])

    async def test_click_inside_a_frame_is_reported_in_page_viewport_pixels(self) -> None:
        browser = self.browser(recording=False)
        await browser.attempt_navigate_and_observe((self.site / "frame.html").as_uri())
        await browser.switch_to_iframe("frame:1")
        observation = await browser.attempt_observe_page()
        await browser.click(element_named(observation, "Inner").index)

        [click] = browser.take_performed_clicks()
        self.assertEqual((click.x, click.y), (100 + 4 + 10 + 40, 50 + 4 + 20 + 20))
        self.assertIsNone(click.recording_id)
        self.assertIsNone(click.recording_time_ms)

    async def test_a_click_that_cannot_be_dispatched_is_not_reported(self) -> None:
        browser = self.browser()
        observation = await browser.attempt_navigate_and_observe((self.site / "leaving.html").as_uri())

        async def refuse(*args, **kwargs):
            raise RuntimeError("Target closed")

        with patch.object(browser.page.mouse, "click", side_effect=refuse):
            with self.assertRaises(RuntimeError):
                await browser.click(element_named(observation, "Go").index)
        with self.assertRaises(ValueError):
            await browser.click(99)
        self.assertEqual(browser.take_performed_clicks(), [])

    async def test_click_names_the_recording_file_and_its_playback_time(self) -> None:
        browser = self.browser()
        observation = await browser.attempt_navigate_and_observe((self.site / "flash.html").as_uri())
        await browser.page.wait_for_timeout(300)
        await browser.click(element_named(observation, "Flash").index)
        await browser.page.wait_for_timeout(500)
        [click] = browser.take_performed_clicks()
        await browser.close()

        [path] = browser.recording_paths
        [recording] = browser.recordings
        self.assertEqual(path.stem, click.recording_id)
        self.assertEqual(recording.id, click.recording_id)
        self.assertEqual(recording.path, path)
        self.assertEqual((recording.width, recording.height), (1365, 768))
        self.assertEqual(click.recording_time_ms, recording.recording_time_ms(click.wall_time_ms))
        self.assertGreater(click.recording_time_ms, 0)

        frame_period_ms = 40
        bright_at = first_bright_frame_after_dark_ms(path)
        self.assertGreaterEqual(bright_at, click.recording_time_ms - frame_period_ms)
        self.assertLessEqual(bright_at, click.recording_time_ms + 250)

    async def test_a_tab_the_site_closes_keeps_its_recording(self) -> None:
        browser = self.browser()
        observation = await browser.attempt_navigate_and_observe((self.site / "popup.html").as_uri())
        await browser.click(element_named(observation, "Open").index)
        await browser.page.wait_for_timeout(1_200)
        await browser.close()

        self.assertEqual(len(browser.recording_paths), 2)
        for path, recording in zip(browser.recording_paths, browser.recordings):
            self.assertEqual(path.stem, recording.id)
            self.assertGreater(path.stat().st_size, 0)
            self.assertIsNotNone(recording.start_wall_time_ms)


class FakeClickBrowser:
    def __init__(self) -> None:
        self.elements = {
            1: Element(1, "name", "input", "Name", "type=text", 0, 0, NO_BOUNDS),
            2: Element(2, "save", "button", "Save", "", 0, 0, NO_BOUNDS),
        }
        self.page = SimpleNamespace(url="https://shop.example")
        self.performed_clicks = []
        self.fill_error = None

    def get_stored_element(self, element_index):
        return self.elements.get(element_index)

    def click_at(self, x, y):
        self.performed_clicks.append(PerformedClick(x, y, 1365, 768, 5_000.0, "rec1", 1_200.0))

    async def click(self, element_index):
        self.click_at(250, 140)

    async def fill(self, element_index, value):
        self.click_at(80, 40)
        if self.fill_error:
            raise self.fill_error

    async def get_form_values(self):
        return ["Name: Ada"]

    async def wait_for_page_to_settle(self):
        return self.page.url

    def take_performed_clicks(self):
        clicks = self.performed_clicks
        self.performed_clicks = []
        return clicks


class ClickEventPublishingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.browser = FakeClickBrowser()
        self.tools = {}
        for browser_tool in build_browser_tools(self.browser):
            self.tools[browser_tool.name] = browser_tool
        self.events = []
        event_patch = patch(
            "navgent.browser_agent.tools.publish_custom_event",
            side_effect=lambda event_type, payload: self.events.append((event_type, payload)),
        )
        event_patch.start()
        self.addCleanup(event_patch.stop)

    async def execute(self, steps):
        return json.loads(await self.tools["execute_steps"].coroutine(steps, "Save the name.", 3))

    async def test_click_event_sits_between_the_action_start_and_completion(self) -> None:
        result = await self.execute([{"action": "click", "element_index": 2}])
        self.assertTrue(result["ok"])
        self.assertEqual([event_type for event_type, _ in self.events], [
            "browser.action.started", "browser.click", "browser.action.completed",
        ])
        click = self.events[1][1]
        self.assertRegex(click.pop("click_id"), "^[0-9a-f]{32}$")
        self.assertEqual(click, {
            "action": "click", "brief_step": 3, "recording_id": "rec1", "x": 250, "y": 140,
            "viewport_width": 1365, "viewport_height": 768, "wall_time_ms": 5_000.0, "recording_time_ms": 1_200.0,
        })

    async def test_fills_report_the_click_that_focused_the_field(self) -> None:
        await self.execute([{"action": "fill", "element_index": 1, "value": "Ada"}])
        click = self.events[1][1]
        self.assertEqual((click["action"], click["x"], click["y"]), ("fill", 80, 40))

    async def test_a_click_that_happened_before_a_failure_is_still_reported(self) -> None:
        self.browser.fill_error = RuntimeError("Keyboard detached")
        result = await self.execute([{"action": "fill", "element_index": 1, "value": "Ada"}])
        self.assertFalse(result["ok"])
        self.assertEqual([event_type for event_type, _ in self.events], [
            "browser.action.started", "browser.click", "browser.action.failed",
        ])

    async def test_failed_click_publishes_no_click_event(self) -> None:
        async def refuse(element_index):
            raise RuntimeError("Element detached")

        self.browser.click = refuse
        await self.execute([{"action": "click", "element_index": 2}])
        self.assertEqual([event_type for event_type, _ in self.events], [
            "browser.action.started", "browser.action.failed",
        ])

    async def test_click_payloads_hold_no_typed_values(self) -> None:
        await self.execute([{"action": "fill", "element_index": 1, "value": "s3cret-value"}])
        click = self.events[1][1]
        self.assertNotIn("s3cret-value", json.dumps(click))


class ClickEventCompatibilityTests(unittest.TestCase):
    def test_click_payload_round_trips_through_the_event_stream(self) -> None:
        click = PerformedClick(250, 140, 1365, 768, 5_000.0, "rec1", 1_200.0)
        payload = click.event_payload("click", 2)
        event = EventUtils.from_payload("browser.click", payload)
        self.assertIsInstance(event, BrowserClickEvent)
        serialized = asdict(event)
        self.assertEqual(serialized.pop("event_type"), "browser.click")
        self.assertEqual(serialized, payload)
        self.assertEqual(json.loads(json.dumps(serialized)), payload)

    def test_click_without_a_recording_still_builds_an_event(self) -> None:
        payload = PerformedClick(1, 2, 1365, 768, 5_000.0, None, None).event_payload("press", None)
        event = EventUtils.from_payload("browser.click", payload)
        self.assertIsNone(event.recording_id)
        self.assertIsNone(event.recording_time_ms)
