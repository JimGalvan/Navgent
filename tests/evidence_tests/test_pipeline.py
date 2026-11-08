import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from navgent.evidence import pipeline
from navgent.evidence.models import Assertion, BugReport, Frame, ReproBrief, ReproStep
from navgent.settings import AgentSettings

BRIEF = ReproBrief(
    steps=[ReproStep(instruction="Open the cart", source="written step 1")],
    assertion=Assertion(
        check="Cart total equals the sum of the line items",
        expected="$24.00",
        reported_actual="$36.00",
        look_in="page",
    ),
    unknowns=[],
)


class StubModel:
    def __init__(self) -> None:
        self.schema = None
        self.messages = None

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    async def ainvoke(self, messages):
        self.messages = messages
        return BRIEF


def make_report(**evidence) -> BugReport:
    return BugReport(
        target_url="https://shop.example.com",
        expected="Cart total is $24.00",
        actual="Cart total shows $36.00",
        **evidence,
    )


class BugReportTests(unittest.TestCase):
    def test_report_without_evidence_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "needs written steps, screenshots or a video"):
            make_report(steps_text="   ")


class UserMessageTests(unittest.TestCase):
    def test_message_has_the_report_then_each_label_and_image(self) -> None:
        frames = [Frame(label="screenshot 1", jpeg=b"one"), Frame(label="video 00:03", jpeg=b"two")]
        content = pipeline.build_user_message(make_report(steps_text="Open the cart"), frames).content
        self.assertEqual(len(content), 5)
        self.assertIn("Target URL: https://shop.example.com", content[0]["text"])
        self.assertIn("Written steps:\nOpen the cart", content[0]["text"])
        self.assertEqual(content[1], {"type": "text", "text": "screenshot 1"})
        self.assertEqual(content[2]["image_url"]["url"], "data:image/jpeg;base64,b25l")
        self.assertEqual(content[3], {"type": "text", "text": "video 00:03"})
        self.assertEqual(content[4]["image_url"]["url"], "data:image/jpeg;base64,dHdv")

    def test_report_without_written_steps_says_none(self) -> None:
        report = make_report(video_path=Path("clip.mp4"))
        self.assertIn("Written steps:\n(none)", pipeline.describe_report(report))


class AnalyzeEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_written_steps_send_text_only(self) -> None:
        model = StubModel()
        settings = AgentSettings(evidence_model="openai:evidence-model")
        with patch.object(pipeline, "build_evidence_model", return_value=model) as build:
            analysis = await pipeline.analyze_evidence(make_report(steps_text="Open the cart"), settings)
        build.assert_called_once_with("openai:evidence-model")
        self.assertIs(model.schema, ReproBrief)
        self.assertIs(analysis.brief, BRIEF)
        self.assertEqual(analysis.frames, [])
        self.assertEqual(len(model.messages[1].content), 1)

    async def test_screenshots_are_sent_and_returned(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cart.png"
            cv2.imwrite(str(path), np.full((100, 100, 3), 200, dtype=np.uint8))
            model = StubModel()
            with patch.object(pipeline, "build_evidence_model", return_value=model):
                analysis = await pipeline.analyze_evidence(make_report(screenshot_paths=(path,)), AgentSettings())
        self.assertEqual(len(analysis.frames), 1)
        self.assertEqual(analysis.frames[0].label, "screenshot 1")
        self.assertEqual(len(model.messages[1].content), 3)
