import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from navgent.browser.browser_manager import BrowserManager
from navgent.browser.browser_session import BrowserSession
from navgent.browser.models import Box
from navgent.browser.recording import Recording
from navgent.browser_agent.findings import candidate_quotes, explain, finding_payloads
from navgent.browser_agent.tools import build_browser_tools
from navgent.event_utils import EventUtils
from navgent.events import ReproductionFindingEvent

CART_PAGE = """
<!doctype html>
<html><body style="margin:0;font:16px sans-serif">
  <p style="position:absolute;left:40px;top:30px;margin:0">Mug $12.00</p>
  <p style="position:absolute;left:40px;top:60px;margin:0">Mug $12.00</p>
  <p id="total" style="position:absolute;left:40px;top:100px;margin:0">Total: <b>$<span>42</span>.00</b></p>
  <p style="display:none">Total: $42.00</p>
  <label for="last" style="position:absolute;left:40px;top:150px">Last Name</label>
  <input id="last" style="position:absolute;left:140px;top:150px;width:200px;height:24px">
  <p style="position:absolute;left:40px;top:2000px;margin:0">Below the fold</p>
  <p id="covered" style="position:absolute;left:400px;top:30px;margin:0">Covered value</p>
  <div style="position:absolute;left:380px;top:20px;width:300px;height:60px;background:white"></div>
</body></html>
"""

FRAME_PAGE = """
<!doctype html>
<html><body style="margin:0">
  <iframe style="position:absolute;left:100px;top:50px;width:400px;height:300px;border:0"
          srcdoc="<body style='margin:0'><p style='position:absolute;left:10px;top:20px;margin:0'>Inside $9.99</p></body>">
  </iframe>
</body></html>
"""


class QuoteGeometryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        site = Path(directory.name)
        (site / "cart.html").write_text(CART_PAGE, encoding="utf-8")
        (site / "frame.html").write_text(FRAME_PAGE, encoding="utf-8")
        self.site = site
        manager = BrowserManager(headless=True)
        self.addAsyncCleanup(manager.stop)
        self.browser = BrowserSession(manager)
        self.addAsyncCleanup(self.browser.close)

    async def open(self, name: str) -> None:
        await self.browser.attempt_navigate_and_observe((self.site / name).as_uri())

    async def element_box(self, selector: str) -> dict:
        return await self.browser.page.evaluate(
            "selector => { const box = document.querySelector(selector).getBoundingClientRect();"
            " return {x: box.left, y: box.top, width: box.width, height: box.height}; }",
            selector,
        )

    async def test_text_split_across_elements_is_boxed_tightly(self) -> None:
        await self.open("cart.html")
        box = await self.browser.locate_quote("$42.00")
        bold = await self.element_box("#total b")
        self.assertAlmostEqual(box.x, bold["x"], delta=1)
        self.assertAlmostEqual(box.y, bold["y"], delta=2)
        self.assertAlmostEqual(box.width, bold["width"], delta=1)
        self.assertGreater(box.height, 0)

    async def test_hidden_copies_do_not_make_a_quote_ambiguous(self) -> None:
        await self.open("cart.html")
        self.assertIsNotNone(await self.browser.locate_quote("Total: $42.00"))

    async def test_repeated_text_is_not_boxed(self) -> None:
        await self.open("cart.html")
        self.assertIsNone(await self.browser.locate_quote("$12.00"))

    async def test_text_off_screen_or_covered_is_not_boxed(self) -> None:
        await self.open("cart.html")
        self.assertIsNone(await self.browser.locate_quote("Below the fold"))
        self.assertIsNone(await self.browser.locate_quote("Covered value"))
        self.assertIsNone(await self.browser.locate_quote("Not on this page"))

    async def test_form_field_quote_boxes_the_field(self) -> None:
        await self.open("cart.html")
        box = await self.browser.locate_quote("Last Name: (empty)")
        field = await self.element_box("#last")
        self.assertEqual((box.x, box.y), (round(field["x"], 1), round(field["y"], 1)))
        self.assertEqual((box.width, box.height), (round(field["width"], 1), round(field["height"], 1)))

    async def test_text_inside_a_frame_is_reported_in_page_viewport_pixels(self) -> None:
        await self.open("frame.html")
        await self.browser.switch_to_iframe("frame:1")
        box = await self.browser.locate_quote("$9.99")
        self.assertGreater(box.x, 100 + 10)
        self.assertAlmostEqual(box.y, 50 + 20, delta=3)


class FakeRecorder:
    id = "rec1"

    def recording_time_ms(self, wall_time_ms: float) -> float:
        return Recording("rec1", Path("rec1.webm"), 1365, 768, 1_000.0).recording_time_ms(wall_time_ms)


class FakeFindingBrowser:
    def __init__(self, boxes: dict[str, list[Box | None]], recorder=None) -> None:
        self.boxes = boxes
        self.recorder = recorder
        self.page_text = "Total: $42.00\nFirst Name: r"
        self.form_values = ["Last Name: (empty)"]

    async def locate_quote(self, quote: str) -> Box | None:
        answers = self.boxes.get(quote, [None])
        if len(answers) > 1:
            return answers.pop(0)
        return answers[0]

    def viewport_size(self) -> tuple[int, int]:
        return 1365, 768

    def current_recording(self):
        return self.recorder

    async def get_page_text(self) -> str:
        return self.page_text

    async def get_form_values(self) -> list[str]:
        return self.form_values


TOTAL_BOX = Box(48.0, 100.0, 52.5, 18.0)


class FindingPayloadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        stability_patch = patch("navgent.browser_agent.findings.STABILITY_CHECK_SECONDS", 0)
        stability_patch.start()
        self.addCleanup(stability_patch.stop)

    async def test_located_quote_becomes_a_numbered_finding_on_the_recording(self) -> None:
        browser = FakeFindingBrowser({"$42.00": [TOTAL_BOX]}, FakeRecorder())
        clock = iter([1_500.0, 1_720.0])
        with patch("navgent.browser_agent.findings.wall_time_ms", side_effect=lambda: next(clock)):
            [payload] = await finding_payloads(browser, "v1", "$42.00", "$30.00", 4)
        self.assertRegex(payload.pop("annotation_id"), "^[0-9a-f]{32}$")
        self.assertEqual(payload, {
            "verdict_id": "v1", "number": 1, "explanation": "Shows $42.00. Expected $30.00.", "brief_step": 4,
            "recording_id": "rec1", "x": 48.0, "y": 100.0, "width": 52.5, "height": 18.0,
            "viewport_width": 1365, "viewport_height": 768,
            "start_wall_time_ms": 1_500.0, "end_wall_time_ms": 1_720.0,
            "start_recording_time_ms": 500.0, "end_recording_time_ms": 720.0,
        })

    async def test_unlocated_quote_produces_no_rectangle(self) -> None:
        browser = FakeFindingBrowser({}, FakeRecorder())
        self.assertEqual(await finding_payloads(browser, "v1", "$42.00", "$30.00", 4), [])

    async def test_a_box_that_moves_between_checks_is_dropped(self) -> None:
        browser = FakeFindingBrowser({"$42.00": [TOTAL_BOX, Box(48.0, 140.0, 52.5, 18.0)]})
        self.assertEqual(await finding_payloads(browser, "v1", "$42.00", "$30.00", 4), [])

    async def test_each_locatable_quote_gets_its_own_number(self) -> None:
        name_box = Box(140.0, 150.0, 200.0, 24.0)
        browser = FakeFindingBrowser({"First Name: r": [name_box], "Last Name: (empty)": [TOTAL_BOX]})
        payloads = await finding_payloads(
            browser, "v1", "First Name: r; Last Name: (empty)", "Last Name: Tester", 6,
        )
        self.assertEqual([payload["number"] for payload in payloads], [1, 2])
        self.assertEqual(payloads[0]["explanation"], "Shows First Name: r. Expected Last Name: Tester.")
        self.assertIsNone(payloads[0]["recording_id"])
        self.assertIsNone(payloads[0]["start_recording_time_ms"])

    def test_whole_quote_is_tried_before_its_parts(self) -> None:
        self.assertEqual(candidate_quotes("Total; tax included"), [["Total; tax included"], ["Total", "tax included"]])
        self.assertEqual(candidate_quotes(" $42.00 "), [["$42.00"]])

    def test_explanation_is_short_and_single_line(self) -> None:
        self.assertEqual(explain("Order confirmed.", "Order shipped."), "Shows Order confirmed. Expected Order shipped.")
        self.assertEqual(explain("$42.00", ""), "Shows $42.00.")
        long_explanation = explain("x" * 500, "y\n" * 300)
        self.assertLess(len(long_explanation), 260)
        self.assertNotIn("\n", long_explanation)


class ReportVerdictFindingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        stability_patch = patch("navgent.browser_agent.findings.STABILITY_CHECK_SECONDS", 0)
        stability_patch.start()
        self.addCleanup(stability_patch.stop)
        self.events = []
        event_patch = patch(
            "navgent.browser_agent.tools.publish_custom_event",
            side_effect=lambda event_type, payload: self.events.append((event_type, payload)),
        )
        event_patch.start()
        self.addCleanup(event_patch.stop)

    async def report(self, browser, verdict: str, observed: str = "$42.00") -> str:
        for browser_tool in build_browser_tools(browser):
            if browser_tool.name == "report_verdict":
                return await browser_tool.ainvoke({
                    "verdict": verdict, "expected": "$30.00", "observed": observed,
                    "step_number": 4 if verdict != "not_reproduced" else None, "reason": "The total is wrong.",
                })
        raise AssertionError("report_verdict is missing")

    async def test_reproduced_verdict_is_followed_by_its_finding(self) -> None:
        browser = FakeFindingBrowser({"$42.00": [TOTAL_BOX]}, FakeRecorder())
        await self.report(browser, "reproduced")
        self.assertEqual([event_type for event_type, _ in self.events], ["reproduction.verdict", "reproduction.finding"])
        verdict, finding = self.events[0][1], self.events[1][1]
        self.assertEqual(finding["verdict_id"], verdict["verdict_id"])
        self.assertEqual(finding["brief_step"], 4)

    async def test_unlocated_finding_keeps_the_textual_verdict(self) -> None:
        browser = FakeFindingBrowser({})
        result = await self.report(browser, "reproduced")
        self.assertEqual(result, "Verdict recorded. Finish with a one-line summary.")
        self.assertEqual([event_type for event_type, _ in self.events], ["reproduction.verdict"])

    async def test_only_reproduced_verdicts_are_annotated(self) -> None:
        browser = FakeFindingBrowser({"$42.00": [TOTAL_BOX]})
        await self.report(browser, "not_reproduced")
        await self.report(browser, "inconclusive", observed="")
        self.assertEqual([event_type for event_type, _ in self.events], ["reproduction.verdict", "reproduction.verdict"])

    async def test_locator_errors_do_not_lose_the_verdict(self) -> None:
        browser = FakeFindingBrowser({})

        async def broken(quote):
            raise TimeoutError("The page stopped responding")

        browser.locate_quote = broken
        result = await self.report(browser, "reproduced")
        self.assertEqual(result, "Verdict recorded. Finish with a one-line summary.")
        self.assertEqual([event_type for event_type, _ in self.events], ["reproduction.verdict"])


class FindingEventTests(unittest.TestCase):
    def test_finding_payload_builds_a_serializable_event(self) -> None:
        payload = {
            "annotation_id": "a1", "verdict_id": "v1", "number": 1, "explanation": "Shows $42.00. Expected $30.00.",
            "brief_step": 4, "recording_id": "rec1", "x": 48.0, "y": 100.0, "width": 52.5, "height": 18.0,
            "viewport_width": 1365, "viewport_height": 768, "start_wall_time_ms": 1_500.0,
            "end_wall_time_ms": 1_720.0, "start_recording_time_ms": 500.0, "end_recording_time_ms": 720.0,
        }
        event = EventUtils.from_payload("reproduction.finding", payload)
        self.assertIsInstance(event, ReproductionFindingEvent)
        serialized = asdict(event)
        self.assertEqual(serialized.pop("event_type"), "reproduction.finding")
        self.assertEqual(serialized, payload)
