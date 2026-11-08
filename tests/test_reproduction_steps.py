import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from navgent.browser.browser_manager import BrowserManager
from navgent.browser.browser_session import BrowserSession
from navgent.browser.models import Bounds, Element
from navgent.browser_agent.tools import build_browser_tools
from navgent.event_utils import EventUtils
from navgent.events import BrowserActionCompletedEvent

NO_BOUNDS = Bounds(0, 0, 0, 0, 0, 0, 0, 0)

FORM_PAGE = """
<!doctype html>
<html><body>
  <input id="first" placeholder="First Name" value="Demo">
  <label for="last">Last Name</label><input id="last">
  <input type="password" placeholder="Password" value="secret_sauce">
  <input type="hidden" name="token" value="abc">
  <select aria-label="Size"><option>Small</option><option selected>Large</option></select>
  <label><input type="checkbox" id="gift" checked> Gift wrap</label>
  <div id="keys"></div>
  <script>
    document.getElementById('last').addEventListener('keydown', function (event) {
      document.getElementById('keys').textContent += event.key;
    });
  </script>
</body></html>
"""


class FormBrowser:
    def __init__(self) -> None:
        self.elements = {
            1: Element(1, "first", "input", "First Name", "type=text", 0, 0, NO_BOUNDS),
            2: Element(2, "last", "input", "Last Name", "type=text", 0, 0, NO_BOUNDS),
            3: Element(3, "button", "button", "Continue", "", 0, 0, NO_BOUNDS),
            4: Element(4, "pass", "input", "Password", "type=password", 0, 0, NO_BOUNDS),
        }
        self.actions = []
        self.form_values = ["First Name: Demo", "Last Name: (empty)"]
        self.page = SimpleNamespace(url="https://shop.example/checkout")

    def get_stored_element(self, element_index):
        return self.elements.get(element_index)

    async def fill(self, element_index, value):
        self.actions.append(("fill", element_index, value))

    async def type_text(self, element_index, value):
        self.actions.append(("type", element_index, value))
        self.form_values = ["First Name: Tester", "Last Name: (empty)"]

    async def click(self, element_index):
        self.actions.append(("click", element_index))

    async def get_form_values(self):
        return self.form_values

    async def wait_for_page_to_settle(self):
        return self.page.url

    def take_performed_clicks(self):
        return []


class ReproductionStepTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.browser = FormBrowser()
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

    async def execute(self, steps: list, brief_step: int | None, reason: str = "Run the step.") -> dict:
        result = await self.tools["execute_steps"].coroutine(steps=steps, reason=reason, brief_step=brief_step)
        return json.loads(result)

    async def test_brief_steps_cannot_go_backwards(self) -> None:
        await self.execute([{"action": "click", "element_index": 3}], brief_step=7)
        result = await self.execute([{"action": "type", "element_index": 2, "value": "Tester"}], brief_step=6)
        self.assertFalse(result["ok"])
        self.assertEqual(result["kind"], "validation_error")
        self.assertIn("brief step 6 comes after step 7", result["error"])
        self.assertEqual(self.browser.actions, [("click", 3)])

    async def test_same_increasing_or_missing_brief_steps_run(self) -> None:
        for brief_step in (5, 5, 6, None, 8):
            result = await self.execute([{"action": "click", "element_index": 3}], brief_step=brief_step)
            self.assertTrue(result["ok"])
        self.assertEqual(len(self.browser.actions), 5)

    async def test_plan_without_a_reason_is_rejected(self) -> None:
        result = await self.execute([{"action": "click", "element_index": 3}], brief_step=None, reason="")
        self.assertEqual(result["kind"], "validation_error")
        self.assertEqual(self.browser.actions, [])

    async def test_type_step_must_target_an_input(self) -> None:
        result = await self.execute([{"action": "type", "element_index": 3, "value": "Tester"}], brief_step=6)
        self.assertEqual(result["kind"], "validation_error")
        self.assertIn("not an input or textarea", result["error"])

    async def test_type_events_carry_value_reason_step_and_fields(self) -> None:
        result = await self.execute(
            [{"action": "type", "element_index": 2, "value": "Tester"}],
            brief_step=6,
            reason="Type the last name, which is step 6.",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(self.browser.actions, [("type", 2, "Tester")])
        started = {
            "action": "type",
            "target": "Last Name",
            "value": "Tester",
            "reason": "Type the last name, which is step 6.",
            "brief_step": 6,
        }
        self.assertEqual(self.events, [
            ("browser.action.started", started),
            ("browser.action.completed", {**started, "fields": ["First Name: Tester", "Last Name: (empty)"]}),
        ])

    async def test_password_values_never_reach_events(self) -> None:
        for action in ("fill", "type"):
            self.events = []
            await self.execute([{"action": action, "element_index": 4, "value": "secret_sauce"}], brief_step=2)
            self.assertEqual(self.events[0][1]["value"], "")
            self.assertNotIn("secret_sauce", json.dumps(self.events))

    async def test_clicks_carry_no_value_or_fields(self) -> None:
        await self.execute([{"action": "click", "element_index": 3}], brief_step=8)
        completed = self.events[-1][1]
        self.assertEqual(completed["value"], "")
        self.assertNotIn("fields", completed)

    def test_completed_payload_builds_an_event_with_field_tuple(self) -> None:
        event = EventUtils.from_payload("browser.action.completed", {
            "action": "type", "target": "Last Name", "value": "Tester", "reason": "Step 6.", "brief_step": 6,
            "fields": ["First Name: Tester"],
        })
        self.assertIsInstance(event, BrowserActionCompletedEvent)
        self.assertEqual(event.fields, ("First Name: Tester",))


class RealPageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        page_path = Path(directory.name) / "form.html"
        page_path.write_text(FORM_PAGE, encoding="utf-8")
        self.manager = BrowserManager(headless=True)
        self.addAsyncCleanup(self.manager.stop)
        self.browser = BrowserSession(self.manager)
        self.addAsyncCleanup(self.browser.close)
        await self.browser.attempt_navigate_and_observe(page_path.as_uri())

    def element_index(self, text: str) -> int:
        for element in self.browser._elements:
            if element.tag == "input" and text in element.text + element.attrs:
                return element.index
        raise AssertionError(f"No input matching {text!r}")

    async def test_form_values_list_visible_fields_without_secrets(self) -> None:
        self.assertEqual(await self.browser.get_form_values(), [
            "First Name: Demo",
            "Last Name: (empty)",
            "Size: Large",
            "Gift wrap: checked",
        ])

    async def test_type_text_presses_each_key(self) -> None:
        await self.browser.type_text(self.element_index("Last Name"), "Tester")
        keys = await self.browser.page.inner_text("#keys")
        self.assertTrue(keys.endswith("Tester"))
        self.assertIn("Last Name: Tester", await self.browser.get_form_values())
