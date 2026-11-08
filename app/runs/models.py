from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models import Base


class RunModel(Base):
    __tablename__ = "runs"

    thread_id: Mapped[UUID]
    user_id: Mapped[UUID | None] = mapped_column(index=True)
    credential_ids: Mapped[list[str]] = mapped_column(JSON)
    task: Mapped[str]
    bug_report: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    repro_brief: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    evidence_frames: Mapped[list[dict[str, str]]] = mapped_column(JSON)
    reported_verdict: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    recordings: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[str]
    max_runtime_seconds: Mapped[int]
    final_output: Mapped[str | None]
    error: Mapped[str | None]
    follow_up_expires_at: Mapped[datetime | None]


class RunEventModel(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "sequence"),)

    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id"))
    sequence: Mapped[int]
    event_type: Mapped[str]
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
