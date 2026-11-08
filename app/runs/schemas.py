from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    Field,
    SecretStr,
    computed_field,
    field_validator,
    model_validator,
)

from app.clock import utc_now
from navgent import (
    CONTROL_KEYS,
    MAX_CONTROL_SCROLL_PIXELS,
    VIEWPORT_HEIGHT,
    VIEWPORT_WIDTH,
    Verdict,
)


class RunStatus(StrEnum):
    QUEUED = "queued"
    READING_EVIDENCE = "reading_evidence"
    RUNNING = "running"
    WAITING_FOR_INPUT = "waiting_for_input"
    READY_FOR_FOLLOW_UP = "ready_for_follow_up"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"

    @property
    def is_terminal(self) -> bool:
        return self in {
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.TIMED_OUT,
        }


class ReproductionInput(BaseModel):
    target_url: str = Field(min_length=1, max_length=1_000)
    expected: str = Field(min_length=1, max_length=1_200)
    actual: str = Field(default="", max_length=1_200)
    steps_text: str = Field(default="", max_length=6_000)

    @field_validator("target_url")
    @classmethod
    def validate_target_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Use an http or https app URL")
        return value


class StoredBugReport(ReproductionInput):
    screenshot_names: list[str] = Field(default_factory=list)
    video_name: str | None = None


class EvidenceFrame(BaseModel):
    filename: str
    label: str


class RunVerdict(BaseModel):
    verdict: Verdict
    expected: str
    observed: str
    step_number: int | None
    reason: str

    @model_validator(mode="after")
    def ignore_step_on_passing_check(self):
        if self.verdict == "not_reproduced":
            self.step_number = None
        return self


class RunRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    thread_id: UUID = Field(default_factory=uuid4)
    user_id: UUID | None = None
    credential_ids: list[UUID] = Field(default_factory=list, max_length=25)
    task: str
    bug_report: StoredBugReport | None = None
    repro_brief: dict[str, Any] | None = None
    evidence_frames: list[EvidenceFrame] = Field(default_factory=list)
    reported_verdict: RunVerdict | None = Field(default=None, exclude=True)
    recordings: list[str] = Field(default_factory=list)
    status: RunStatus = RunStatus.QUEUED
    max_runtime_seconds: int
    final_output: str | None = None
    error: str | None = None
    follow_up_expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @computed_field
    @property
    def verdict(self) -> RunVerdict | None:
        if self.status.is_terminal and self.status != RunStatus.SUCCEEDED:
            return None
        if self.status == RunStatus.SUCCEEDED and self.reported_verdict is None:
            return RunVerdict(
                verdict="inconclusive", expected="", observed="", step_number=None,
                reason="The agent finished without a verdict.",
            )
        return self.reported_verdict


class RunEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    sequence: int
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class CreateRunRequest(BaseModel):
    task: str = Field(min_length=1, max_length=10_000)
    max_runtime_seconds: int = Field(default=600, ge=30, le=1_800)
    credential_ids: list[UUID] = Field(default_factory=list, max_length=25)


class UserInputRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=10_000)


class SensitiveInputRequest(BaseModel):
    request_id: UUID
    code: SecretStr = Field(min_length=1, max_length=128)


class FollowUpRequest(BaseModel):
    task: str = Field(min_length=1, max_length=10_000)


class BrowserControlEvent(BaseModel):
    type: Literal["click", "mouse_down", "mouse_up", "scroll", "key", "text"]
    x: float = Field(default=0.0, ge=0, le=VIEWPORT_WIDTH)
    y: float = Field(default=0.0, ge=0, le=VIEWPORT_HEIGHT)
    delta_y: float = Field(
        default=0.0,
        ge=-MAX_CONTROL_SCROLL_PIXELS,
        le=MAX_CONTROL_SCROLL_PIXELS,
    )
    key: str = Field(default="", max_length=16)
    text: str = Field(default="", max_length=1_000)

    @model_validator(mode="after")
    def check_payload_matches_type(self) -> BrowserControlEvent:
        if self.type == "key" and self.key not in CONTROL_KEYS:
            raise ValueError(f"{self.key!r} is not a forwardable key")

        if self.type == "text" and not self.text:
            raise ValueError("A text event carries no text")

        return self


class RunSummary(BaseModel):
    """A run as it appears in the dashboard history list."""

    id: UUID
    task: str
    status: RunStatus
    created_at: datetime
    updated_at: datetime


class RunListResponse(BaseModel):
    runs: list[RunSummary]


class RunResponse(BaseModel):
    run: RunRecord
    stream_url: str
    screen_url: str
    control_url: str
