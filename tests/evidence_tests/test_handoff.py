import unittest

from navgent.evidence.handoff import build_reproduction_task
from navgent.evidence.models import Assertion, BugReport, ReproBrief, ReproStep

REPORT = BugReport(
    target_url="https://shop.example.com",
    expected="Cart total is $24.00",
    actual="Cart total shows $36.00",
    steps_text="Add two mugs and open the cart",
)
ASSERTION = Assertion(
    check="Cart total equals the sum of the line items",
    expected="$24.00",
    reported_actual="$36.00",
    look_in="page",
)
STEPS = [
    ReproStep(instruction="Set quantity to 2 and click 'Add to cart'", source="video 00:04"),
    ReproStep(instruction="Open the cart", source="video 00:07"),
]


class ReproductionTaskTests(unittest.TestCase):
    def test_task_lists_numbered_steps_assertion_and_unknowns(self) -> None:
        brief = ReproBrief(steps=STEPS, assertion=ASSERTION, unknowns=["Whether the user was logged in"])
        expected = "\n".join([
            "Reproduce this bug on https://shop.example.com.",
            "",
            "<steps>",
            "1. Set quantity to 2 and click 'Add to cart'",
            "2. Open the cart",
            "</steps>",
            "",
            "<assertion>",
            "Check: Cart total equals the sum of the line items",
            "Expected: $24.00",
            "Reported actual: $36.00",
            "Look in: page",
            "</assertion>",
            "",
            "<unknowns>",
            "- Whether the user was logged in",
            "</unknowns>",
        ])
        self.assertEqual(build_reproduction_task(REPORT, brief), expected)

    def test_task_leaves_out_unknowns_when_there_are_none(self) -> None:
        brief = ReproBrief(steps=STEPS, assertion=ASSERTION, unknowns=[])
        task = build_reproduction_task(REPORT, brief)
        self.assertNotIn("<unknowns>", task)
        self.assertTrue(task.endswith("</assertion>"))
