from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from app.runs.schemas import RunEvent, RunRecord

if TYPE_CHECKING:
    from navgent import BrowserAgentSession


@dataclass
class RunContext:
    run: RunRecord
    session: BrowserAgentSession | None = None
    events: list[RunEvent] = field(default_factory=list)
    event_condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    frame_condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    latest_frame: bytes | None = None
    frame_sequence: int = 0
    next_event_sequence: int = 1
    event_task: asyncio.Task[None] | None = None
    frame_task: asyncio.Task[None] | None = None
    preparation_task: asyncio.Task[None] | None = None
    follow_up_expiry_task: asyncio.Task[None] | None = None
    sensitive_input_request_id: UUID | None = None
    mouse_controller: str | None = None
    control_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    finish_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
