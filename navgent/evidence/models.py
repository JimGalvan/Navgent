from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class BugReport:
    target_url: str
    expected: str
    actual: str
    steps_text: str = ""
    screenshot_paths: tuple[Path, ...] = ()
    video_path: Path | None = None

    def __post_init__(self) -> None:
        if not self.steps_text.strip() and not self.screenshot_paths and self.video_path is None:
            raise ValueError("A bug report needs written steps, screenshots or a video")


@dataclass(frozen=True)
class Frame:
    label: str
    jpeg: bytes = field(repr=False)


class ReproStep(BaseModel):
    instruction: str
    source: str


class Assertion(BaseModel):
    check: str
    expected: str
    reported_actual: str
    look_in: Literal["page", "network", "console"]


class ReproBrief(BaseModel):
    steps: list[ReproStep] = Field(min_length=1, max_length=15)
    assertion: Assertion
    unknowns: list[str]


@dataclass(frozen=True)
class EvidenceAnalysis:
    brief: ReproBrief
    frames: list[Frame]
