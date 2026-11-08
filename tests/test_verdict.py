import unittest
from unittest.mock import patch

from navgent.browser_agent.tools import build_browser_tools
from navgent.browser_agent.verdict import check_observed
from navgent.event_utils import EventUtils
from navgent.events import ReproductionVerdictEvent

PAGE_TEXT = "Page 5 of 5 — Confirmation\nOrder confirmed for Ada,   size large, gift wrap yes."


class PageTextBrowser:
    def __init__(self, page_text: str) -> None:
        self.page_text = page_text
        self.reads = 0

    async def get_page_text(self) -> str:
        self.reads += 1
        return self.page_text


class CheckObservedTests(unittest.TestCase):
    def test_value_matches_regardless_of_spacing(self) -> None:
        self.assertIsNone(check_observed("Ada, size\nlarge", PAGE_TEXT))

    def test_value_with_different_case_is_rejected(self) -> None:
        self.assertIn("is not on the current page", check_observed("size Large", PAGE_TEXT))

    def test_missing_value_is_rejected(self) -> None:
        problem = check_observed("size Large, gift wrap no", PAGE_TEXT)
        self.assertIn("is not on the current page", problem)

    def test_empty_value_is_rejected(self) -> None:
        self.assertIn("observed is empty", check_observed("  ", PAGE_TEXT))


class ReportVerdictToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.browser = PageTextBrowser(PAGE_TEXT)
        self.tool = None
        for browser_tool in build_browser_tools(self.browser):
            if browser_tool.name == "report_verdict":
                self.tool = browser_tool
        self.events = []
        event_patch = patch(
            "navgent.browser_agent.tools.publish_custom_event",
            side_effect=lambda event_type, payload: self.events.append((event_type, payload)),
        )
        event_patch.start()
        self.addCleanup(event_patch.stop)

    async def test_verdict_on_the_page_is_published(self) -> None:
        result = await self.tool.ainvoke({
            "verdict": "reproduced",
            "expected": "size Large",
            "observed": "size large",
            "step_number": 6,
            "reason": "The confirmation lowercases the picked size.",
        })
        self.assertEqual(result, "Verdict recorded. Finish with a one-line summary.")
        self.assertEqual(self.events, [("reproduction.verdict", {
            "verdict": "reproduced",
            "expected": "size Large",
            "observed": "size large",
            "step_number": 6,
            "reason": "The confirmation lowercases the picked size.",
        })])

    async def test_verdict_with_an_unseen_value_is_rejected(self) -> None:
        result = await self.tool.ainvoke({
            "verdict": "not_reproduced",
            "expected": "size Large",
            "observed": "size Large",
            "reason": "The size is shown as picked.",
        })
        self.assertIn("'size Large' is not on the current page", result)
        self.assertEqual(self.events, [])

    async def test_inconclusive_skips_the_page_check(self) -> None:
        await self.tool.ainvoke({
            "verdict": "inconclusive",
            "expected": "The API returns 24.00",
            "observed": "",
            "step_number": 3,
            "reason": "The assertion needs the network response.",
        })
        self.assertEqual(self.browser.reads, 0)
        self.assertEqual(self.events[0][1]["verdict"], "inconclusive")

    async def test_step_number_must_be_positive(self) -> None:
        with self.assertRaises(Exception):
            await self.tool.ainvoke({
                "verdict": "reproduced",
                "expected": "size Large",
                "observed": "size large",
                "step_number": 0,
                "reason": "Wrong step.",
            })
        self.assertEqual(self.events, [])


class VerdictEventTests(unittest.TestCase):
    def test_payload_builds_a_verdict_event(self) -> None:
        event = EventUtils.from_payload("reproduction.verdict", {
            "verdict": "reproduced",
            "expected": "size Large",
            "observed": "size large",
            "step_number": None,
            "reason": "Lowercased.",
        })
        self.assertEqual(event, ReproductionVerdictEvent("reproduced", "size Large", "size large", None, "Lowercased."))
