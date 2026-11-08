import base64

from langchain_core.messages import HumanMessage, SystemMessage

from navgent.evidence.images import extract_video_frames, load_screenshots
from navgent.evidence.models import BugReport, EvidenceAnalysis, Frame, ReproBrief
from navgent.evidence.prompts import SYSTEM_PROMPT
from navgent.settings import AgentSettings
from navgent.shared.llm import build_evidence_model


async def analyze_evidence(report: BugReport, settings: AgentSettings) -> EvidenceAnalysis:
    frames = collect_frames(report)
    model = build_evidence_model(settings.evidence_model)
    messages = [SystemMessage(SYSTEM_PROMPT), build_user_message(report, frames)]
    brief = await model.with_structured_output(ReproBrief).ainvoke(messages)
    return EvidenceAnalysis(brief=brief, frames=frames)


def collect_frames(report: BugReport) -> list[Frame]:
    frames = load_screenshots(report.screenshot_paths)
    if report.video_path is not None:
        frames.extend(extract_video_frames(report.video_path))
    return frames


def build_user_message(report: BugReport, frames: list[Frame]) -> HumanMessage:
    content = [{"type": "text", "text": describe_report(report)}]
    for frame in frames:
        content.append({"type": "text", "text": frame.label})
        content.append({"type": "image_url", "image_url": {"url": to_data_url(frame.jpeg)}})
    return HumanMessage(content=content)


def describe_report(report: BugReport) -> str:
    steps = report.steps_text.strip()
    if not steps:
        steps = "(none)"
    return (
        f"Target URL: {report.target_url}\n"
        f"Expected: {report.expected}\n"
        f"Actual: {report.actual}\n"
        f"Written steps:\n{steps}"
    )


def to_data_url(jpeg: bytes) -> str:
    encoded = base64.b64encode(jpeg).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"
