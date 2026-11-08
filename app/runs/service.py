import asyncio
import logging
from collections import OrderedDict
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from starlette.datastructures import UploadFile

from app.clock import utc_now
from app.config import DATABASE_PATH, read_agent_settings
from app.credentials.exceptions import CredentialNotFoundError
from app.credentials.service import CredentialService
from app.runs import constants
from app.runs.context import RunContext
from app.runs.event_utils import RunEventUtils
from app.runs.evidence import EvidenceUploadError, RunEvidenceStore, validate_video
from app.runs.exceptions import (
    RunCapacityReachedError,
    RunNotFoundError,
    RunNotReadyForFollowUpError,
    RunNotRerunnableError,
    RunNotWaitingForInputError,
    SensitiveInputNotPendingError,
)
from app.runs.repository import RunRepository
from app.runs.runtime import build_agent_runtime
from app.runs.schemas import (
    BrowserControlEvent,
    ReproductionInput,
    RunEvent,
    RunRecord,
    RunStatus,
    RunVerdict,
    StoredBugReport,
)
from navgent import (
    BrowserControlAppliedEvent,
    MouseUpAction,
    SessionNotReadyForFollowUpError,
    SessionNotWaitingForInputError,
    SessionStatusEvent,
)
from navgent import (
    SensitiveInputNotPendingError as SessionSensitiveInputNotPendingError,
)
from navgent.evidence import ReproBrief, analyze_evidence, build_reproduction_task


class RunManager:
    def __init__(
            self,
            repository: RunRepository,
            headless: bool = True,
            max_concurrent_runs: int = constants.DEFAULT_MAX_CONCURRENT_RUNS,
            follow_up_window_seconds: float = constants.DEFAULT_FOLLOW_UP_WINDOW_SECONDS,
            credential_service: CredentialService | None = None,
            sensitive_input_window_seconds: float = constants.DEFAULT_SENSITIVE_INPUT_WINDOW_SECONDS,
    ):
        if max_concurrent_runs < 1:
            raise ValueError("max_concurrent_runs must be at least 1")
        if follow_up_window_seconds <= 0:
            raise ValueError("follow_up_window_seconds must be greater than 0")
        if sensitive_input_window_seconds <= 0:
            raise ValueError("sensitive_input_window_seconds must be greater than 0")
        self._repository = repository
        self._evidence = RunEvidenceStore(repository.data_directory)
        self._headless = headless
        self._contexts: dict[UUID, RunContext] = {}
        self._manager_lock = asyncio.Lock()
        self._max_concurrent_runs = max_concurrent_runs
        self._follow_up_window_seconds = follow_up_window_seconds
        self._sensitive_input_window_seconds = sensitive_input_window_seconds
        self._credential_service = credential_service
        self._active_run_ids: set[UUID] = set()
        self._completed_frames: OrderedDict[UUID, bytes] = OrderedDict()

    async def create_run(
            self,
            task: str,
            max_runtime_seconds: int,
            user_id: UUID | None = None,
            credential_ids: list[UUID] | None = None,
            *,
            bug_report: ReproductionInput | None = None,
            screenshots: list[UploadFile] | None = None,
            video: UploadFile | None = None,
            reuse_evidence: RunRecord | None = None,
    ) -> RunRecord:
        async with self._manager_lock:
            if len(self._active_run_ids) >= self._max_concurrent_runs:
                raise RunCapacityReachedError("The demo is currently at capacity. Try again shortly.")
            selected_credential_ids = list(dict.fromkeys(credential_ids or []))
            if selected_credential_ids:
                if user_id is None or self._credential_service is None:
                    raise ValueError("Credential selection requires an authenticated user")
                self._credential_service.require_selected(selected_credential_ids, user_id)
            run = RunRecord(
                task=task.strip(), max_runtime_seconds=max_runtime_seconds,
                user_id=user_id, credential_ids=selected_credential_ids,
                bug_report=StoredBugReport(**bug_report.model_dump()) if bug_report else None,
            )
            context = RunContext(run=run)
            self._contexts[run.id] = context
            self._active_run_ids.add(run.id)
            try:
                self._repository.save_run(run)
                await self._publish(context, "run.created", {"task": run.task, "status": run.status.value})
            except Exception:
                self._contexts.pop(run.id, None)
                self._active_run_ids.discard(run.id)
                raise

        if bug_report is not None:
            await self._set_status(context, RunStatus.READING_EVIDENCE)
            try:
                if reuse_evidence is not None:
                    await asyncio.to_thread(self._evidence.copy_evidence, reuse_evidence, run)
                else:
                    await self._evidence.save_uploads(run, screenshots or [], video)
                self._repository.save_run(run)
            except Exception as exception:
                await self._fail_evidence(context, exception)
                return run
            if not run.status.is_terminal:
                context.preparation_task = asyncio.create_task(
                    self._prepare_reproduction(context), name=f"evidence-{run.id}",
                )
            return run

        try:
            await self._start_session(context, run.task)
        except Exception:
            await self._finish_context(context, RunStatus.FAILED)
            raise
        return run

    async def _start_session(self, context: RunContext, task: str) -> None:
        run = context.run
        context.session = build_agent_runtime(
            run.thread_id,
            user_id=run.user_id,
            recording_dir=self._evidence.run_directory(run) / "recording",
            credential_ids=tuple(run.credential_ids),
            credential_service=self._credential_service,
            headless=self._headless,
            max_runtime_seconds=run.max_runtime_seconds,
            sensitive_input_window_seconds=self._sensitive_input_window_seconds,
        )
        context.event_task = asyncio.create_task(self._forward_events(context), name=f"events-{run.id}")
        context.frame_task = asyncio.create_task(self._forward_frames(context), name=f"frames-{run.id}")
        await context.session.start(task)

    async def _prepare_reproduction(self, context: RunContext) -> None:
        run = context.run
        try:
            async with asyncio.timeout(90):
                report = self._evidence.build_report(run)
                reused = run.repro_brief is not None
                if reused:
                    brief = ReproBrief.model_validate(run.repro_brief)
                else:
                    if report.video_path is not None:
                        await asyncio.to_thread(validate_video, report.video_path)
                    analysis = await analyze_evidence(report, read_agent_settings(run.thread_id))
                    brief = ReproBrief.model_validate(analysis.brief.model_dump())
                    await asyncio.to_thread(self._evidence.save_analysis, run, analysis)
                task = build_reproduction_task(report, brief)
                self._repository.save_run(run)
                await self._publish(context, "evidence.ready", {"brief": brief.model_dump(), "reused": reused})
        except Exception as exception:
            await self._fail_evidence(context, exception)
            return

        try:
            await self._start_session(context, task)
        except Exception:
            run.error = "The browser session could not start. Try running again."
            await self._publish(context, "run.failed", {"error": run.error})
            await self._finish_context(context, RunStatus.FAILED)

    async def _fail_evidence(self, context: RunContext, exception: Exception) -> None:
        message = "Couldn't read the evidence. Check your files and steps, then try again."
        if isinstance(exception, EvidenceUploadError):
            message = f"Couldn't read the evidence. {exception}"
        context.run.error = message
        await self._publish(context, "evidence.failed", {"error": message})
        await self._publish(context, "run.failed", {"error": message})
        await self._finish_context(context, RunStatus.FAILED)

    async def submit_input(self, run_id: UUID, user_id: UUID, answer: str) -> RunRecord:
        context = self._require_waiting_context(run_id, user_id)
        try:
            await context.session.answer(answer)
        except SessionNotWaitingForInputError as exception:
            raise RunNotWaitingForInputError(str(exception)) from exception
        return context.run

    async def submit_sensitive_input(
            self, run_id: UUID, user_id: UUID, request_id: UUID, code: str,
    ) -> RunRecord:
        context, _ = self._resolve_owned(run_id, user_id)
        if context is None:
            raise RunNotFoundError(f"Run {run_id} was not found")
        if context.run.status != RunStatus.WAITING_FOR_INPUT:
            raise SensitiveInputNotPendingError("The run is not waiting for sensitive input")
        try:
            await context.session.submit_sensitive_input(request_id, code)
        except SessionSensitiveInputNotPendingError as exception:
            raise SensitiveInputNotPendingError(str(exception)) from exception
        return context.run

    async def decline_sensitive_input(self, run_id: UUID, user_id: UUID) -> RunRecord:
        context, _ = self._resolve_owned(run_id, user_id)
        if context is None:
            raise RunNotFoundError(f"Run {run_id} was not found")
        if context.sensitive_input_request_id is None:
            raise SensitiveInputNotPendingError("The run is not waiting for a verification code")
        try:
            await context.session.decline_sensitive_input(context.sensitive_input_request_id)
        except SessionSensitiveInputNotPendingError as exception:
            raise SensitiveInputNotPendingError(str(exception)) from exception
        return context.run

    async def open_control(self, run_id: UUID, user_id: UUID) -> RunContext:
        context, _ = self._resolve_owned(run_id, user_id)
        if context is None:
            raise RunNotFoundError(f"Run {run_id} was not found")
        self._require_control_status(context)
        try:
            await context.session.take_control()
        except SessionNotWaitingForInputError as exception:
            raise RunNotWaitingForInputError(str(exception)) from exception
        return context

    async def close_control(self, context: RunContext, controller_id: str = "default") -> None:
        async with context.control_lock:
            if context.mouse_controller == controller_id:
                if not context.run.status.is_terminal:
                    await context.session.apply_control(MouseUpAction())
                context.mouse_controller = None
            await context.session.release_control()

    @staticmethod
    def _require_control_status(context: RunContext) -> None:
        if context.run.status not in {RunStatus.WAITING_FOR_INPUT, RunStatus.READY_FOR_FOLLOW_UP}:
            raise RunNotWaitingForInputError("The browser is not available for user control")

    async def apply_control(
            self, context: RunContext, event: BrowserControlEvent, controller_id: str = "default",
    ) -> str:
        async with context.control_lock:
            if event.type == "mouse_up" and context.mouse_controller != controller_id:
                return "Mouse button released"
            if event.type != "mouse_up":
                self._require_control_status(context)
            if context.mouse_controller and event.type in {"click", "mouse_down", "scroll"}:
                raise RunNotWaitingForInputError("Release the held mouse button before another action")
            try:
                detail = await context.session.apply_control(RunEventUtils.control_action(event))
            except SessionNotWaitingForInputError as exception:
                raise RunNotWaitingForInputError(str(exception)) from exception
            if event.type == "mouse_down" and context.run.status in {
                RunStatus.WAITING_FOR_INPUT, RunStatus.READY_FOR_FOLLOW_UP,
            }:
                context.mouse_controller = controller_id
            elif event.type == "mouse_up":
                context.mouse_controller = None
            return detail

    async def submit_follow_up(self, run_id: UUID, user_id: UUID, task: str) -> RunRecord:
        async with self._manager_lock:
            context, _ = self._resolve_owned(run_id, user_id)
            if context is None:
                raise RunNotFoundError(f"Run {run_id} was not found")
            if context.run.status != RunStatus.READY_FOR_FOLLOW_UP or context.finish_lock.locked():
                raise RunNotReadyForFollowUpError("The run is not ready for a follow-up")
            expiry_task = context.follow_up_expiry_task
            context.follow_up_expiry_task = None
            if expiry_task:
                expiry_task.cancel()
            context.run.follow_up_expires_at = None
            context.run.final_output = None
            context.run.error = None
            follow_up_task = task.strip()
            await self._publish(context, "follow_up.started", {"task": follow_up_task})
            try:
                await context.session.follow_up(follow_up_task)
            except SessionNotReadyForFollowUpError as exception:
                raise RunNotReadyForFollowUpError(str(exception)) from exception
            await self._set_status(context, RunStatus.RUNNING)
        await self._await_cancelled_task(expiry_task)
        return context.run

    async def cancel_run(self, run_id: UUID, user_id: UUID) -> RunRecord:
        context, run = self._resolve_owned(run_id, user_id)
        if context is None:
            if not run.status.is_terminal:
                raise RunNotFoundError(f"Run {run_id} was not found")
            return run
        if context.run.status.is_terminal:
            return context.run
        if context.finish_lock.locked():
            async with context.finish_lock:
                return context.run
        if context.session is None:
            await self._stop_task(context.preparation_task)
            await self._publish(context, "run.cancelled", {})
            await self._finish_context(context, RunStatus.CANCELLED)
            return context.run
        await context.session.cancel()
        await self._await_cancelled_task(context.event_task)
        return context.run

    async def shutdown(self) -> None:
        contexts = list(self._contexts.values())
        for context in contexts:
            expiry_task = context.follow_up_expiry_task
            context.follow_up_expiry_task = None
            await self._stop_task(expiry_task)
            await self._stop_task(context.preparation_task)
            if context.session is not None:
                await context.session.close()
            await self._await_cancelled_task(context.event_task)
            await self._stop_task(context.frame_task)
        self._contexts.clear()
        self._active_run_ids.clear()
        self._completed_frames.clear()

    async def _forward_events(self, context: RunContext) -> None:
        assert context.session is not None
        try:
            async for event in context.session.events():
                if isinstance(event, BrowserControlAppliedEvent):
                    continue
                if isinstance(event, SessionStatusEvent):
                    status = RunStatus(event.status)
                    if status == RunStatus.TIMED_OUT:
                        context.run.error = None
                    if status == RunStatus.READY_FOR_FOLLOW_UP:
                        await self._set_status(context, status)
                        context.run.follow_up_expires_at = None
                        await self._finish_context(context, RunStatus.SUCCEEDED)
                        return
                    if status.is_terminal:
                        await self._finish_context(context, status)
                        return
                    await self._set_status(context, status)
                    continue
                payload = RunEventUtils.payload(event)
                if event.event_type == "reproduction.verdict":
                    context.run.reported_verdict = RunVerdict.model_validate(payload)
                    context.run.updated_at = utc_now()
                elif event.event_type == "run.completed":
                    context.run.final_output = event.output
                    context.run.follow_up_expires_at = utc_now() + timedelta(seconds=self._follow_up_window_seconds)
                    payload["follow_up_expires_at"] = context.run.follow_up_expires_at.isoformat()
                elif event.event_type == "run.failed":
                    context.run.error = event.error
                    context.run.follow_up_expires_at = None
                elif event.event_type == "run.cancelled":
                    context.run.follow_up_expires_at = None
                elif event.event_type == "sensitive_input.required":
                    context.sensitive_input_request_id = event.request_id
                elif event.event_type in {"sensitive_input.received", "sensitive_input.cancelled"}:
                    context.sensitive_input_request_id = None
                await self._publish(context, event.event_type, payload, persist=event.event_type != "agent.message.delta")
        except Exception as exception:
            context.run.error = str(exception)
            context.run.follow_up_expires_at = None
            try:
                await self._publish(context, "run.failed", {"error": str(exception)})
            finally:
                await self._finish_context(context, RunStatus.FAILED)

    async def _forward_frames(self, context: RunContext) -> None:
        assert context.session is not None
        async for frame in context.session.screen_frames():
            async with context.frame_condition:
                context.latest_frame = frame
                context.frame_sequence += 1
                context.frame_condition.notify_all()

    async def _finish_context(self, context: RunContext, status: RunStatus) -> None:
        async with context.finish_lock:
            if context.run.status.is_terminal:
                return
            try:
                await self._close_browser(context)
            except Exception:
                logging.getLogger(__name__).exception("Could not finalize browser evidence for run %s", context.run.id)
                await self._publish(context, "browser.capture.failed", {"message": "Some final browser evidence could not be saved."})
            await self._set_status(context, status)
            async with self._manager_lock:
                self._active_run_ids.discard(context.run.id)
                self._contexts.pop(context.run.id, None)
            async with context.frame_condition:
                context.frame_condition.notify_all()

    async def _close_browser(self, context: RunContext) -> None:
        expiry_task = context.follow_up_expiry_task
        context.follow_up_expiry_task = None
        await self._stop_task(expiry_task)
        if context.session is not None:
            await context.session.close()
            directory = (self._evidence.run_directory(context.run) / "recording").resolve()
            context.run.recordings = [
                path.name for path in context.session.recording_paths
                if path.resolve().parent == directory and path.suffix.lower() == ".webm" and path.is_file()
            ]
            await self._await_cancelled_task(context.frame_task)
            latest_frame = context.session.get_latest_frame()
            if latest_frame is not None:
                context.latest_frame = latest_frame
        if context.latest_frame is not None:
            evidence = DATABASE_PATH.parent / "evidence"
            evidence.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread((evidence / f"{context.run.id}.jpg").write_bytes, context.latest_frame)
            self._completed_frames[context.run.id] = context.latest_frame
            self._completed_frames.move_to_end(context.run.id)
            while len(self._completed_frames) > constants.MAX_COMPLETED_FRAME_COUNT:
                self._completed_frames.popitem(last=False)

    async def _set_status(self, context: RunContext, status: RunStatus) -> None:
        if context.run.status == status:
            return
        if status not in {RunStatus.WAITING_FOR_INPUT, RunStatus.READY_FOR_FOLLOW_UP}:
            context.mouse_controller = None
        context.run.status = status
        context.run.updated_at = utc_now()
        self._repository.save_run(context.run)
        payload: dict[str, Any] = {"status": status.value}
        if status.is_terminal:
            verdict = context.run.verdict
            payload["verdict"] = verdict.model_dump() if verdict else None
        if context.run.follow_up_expires_at is not None:
            payload["follow_up_expires_at"] = context.run.follow_up_expires_at.isoformat()
        await self._publish(context, "run.status", payload)

    async def _stop_task(self, task: asyncio.Task[None] | None) -> None:
        if task and task is not asyncio.current_task():
            task.cancel()
            await self._await_cancelled_task(task)

    async def rerun_run(self, run_id: UUID, user_id: UUID) -> RunRecord:
        _, run = self._resolve_owned(run_id, user_id)
        if not run.status.is_terminal:
            raise RunNotRerunnableError("Only a finished run can be started again")

        try:
            return await self.create_run(
                task=run.task,
                max_runtime_seconds=run.max_runtime_seconds,
                user_id=user_id,
                credential_ids=list(run.credential_ids),
                bug_report=run.bug_report,
                reuse_evidence=run if run.bug_report else None,
            )
        except CredentialNotFoundError as exception:
            raise RunNotRerunnableError(
                "A credential this run used is no longer available"
            ) from exception

    def list_runs(
            self,
            user_id: UUID,
            limit: int = constants.MAX_LISTED_RUNS,
    ) -> list[RunRecord]:
        stored_runs = self._repository.list_runs_for_user(user_id, limit)
        runs = []
        for run in stored_runs:
            context = self._contexts.get(run.id)
            runs.append(context.run if context else run)
        return runs

    def _resolve_owned(
            self,
            run_id: UUID,
            user_id: UUID,
    ) -> tuple[RunContext | None, RunRecord]:
        context = self._contexts.get(run_id)
        run = context.run if context is not None else self._repository.get_run(run_id)
        if run is None or run.user_id != user_id:
            raise RunNotFoundError(f"Run {run_id} was not found")

        return context, run

    def get_run(self, run_id: UUID, user_id: UUID) -> RunRecord:
        _, run = self._resolve_owned(run_id, user_id)
        return run

    def get_evidence_frame(self, run_id: UUID, user_id: UUID, number: int) -> Path:
        _, run = self._resolve_owned(run_id, user_id)
        path = self._evidence.frame_path(run, number)
        if path is None or not path.is_file():
            raise RunNotFoundError("This evidence frame was not found")
        return path

    def get_recording(self, run_id: UUID, user_id: UUID, number: int) -> Path:
        _, run = self._resolve_owned(run_id, user_id)
        if 1 <= number <= len(run.recordings):
            directory = (self._evidence.run_directory(run) / "recording").resolve()
            path = (directory / run.recordings[number - 1]).resolve()
            if path.parent == directory and path.is_file():
                return path
        raise RunNotFoundError("This recording was not found")

    def _require_waiting_context(self, run_id: UUID, user_id: UUID) -> RunContext:
        context, _ = self._resolve_owned(run_id, user_id)
        if context is None:
            raise RunNotFoundError(f"Run {run_id} was not found")

        if context.run.status != RunStatus.WAITING_FOR_INPUT:
            raise RunNotWaitingForInputError("The run is not waiting for user input")

        return context

    async def end_session(self, run_id: UUID, user_id: UUID) -> RunRecord:
        expiry_task = None
        async with self._manager_lock:
            context, run = self._resolve_owned(run_id, user_id)
            if context is None:
                if run.status.is_terminal:
                    return run
                raise RunNotFoundError(f"Run {run_id} was not found")

            if context.run.status != RunStatus.READY_FOR_FOLLOW_UP:
                raise RunNotReadyForFollowUpError("The run is not ready to end its follow-up window")

            expiry_task = context.follow_up_expiry_task
            context.follow_up_expiry_task = None
            if expiry_task is not None:
                expiry_task.cancel()

            context.run.follow_up_expires_at = None
            await self._publish(context, "follow_up.ended", {})

        await self._await_cancelled_task(expiry_task)
        await self._finish_context(context, RunStatus.SUCCEEDED)
        return context.run

    def get_latest_frame(self, run_id: UUID, user_id: UUID) -> bytes | None:
        context, _ = self._resolve_owned(run_id, user_id)
        if context is not None:
            return context.latest_frame

        completed_frame = self._completed_frames.get(run_id)
        if completed_frame is not None:
            self._completed_frames.move_to_end(run_id)
            return completed_frame

        return None

    def stream_events(
            self,
            run_id: UUID,
            user_id: UUID,
            after_sequence: int = 0,
    ) -> AsyncIterator[RunEvent]:
        context, _ = self._resolve_owned(run_id, user_id)
        return self._stream_events(run_id, context, after_sequence)

    async def _stream_events(
            self,
            run_id: UUID,
            context: RunContext | None,
            after_sequence: int,
    ) -> AsyncIterator[RunEvent]:
        if context is None:
            for event in self._repository.list_events(run_id, after_sequence):
                yield event
            return

        next_sequence = after_sequence + 1
        while True:
            async with context.event_condition:
                available_events = []
                for event in context.events:
                    if event.sequence >= next_sequence:
                        available_events.append(event)
                while not available_events and not context.run.status.is_terminal:
                    await context.event_condition.wait()
                    available_events = []
                    for event in context.events:
                        if event.sequence >= next_sequence:
                            available_events.append(event)

                is_terminal = context.run.status.is_terminal

            for event in available_events:
                next_sequence = event.sequence + 1
                yield event

            if is_terminal:
                return

    def stream_frames(self, run_id: UUID, user_id: UUID) -> AsyncIterator[bytes]:
        context, _ = self._resolve_owned(run_id, user_id)
        if context is None:
            raise RunNotFoundError(f"Run {run_id} was not found")

        return self._stream_frames(context)

    async def _stream_frames(self, context: RunContext) -> AsyncIterator[bytes]:
        delivered_frame_sequence = 0
        while True:
            async with context.frame_condition:
                has_new_frame = context.latest_frame is not None and context.frame_sequence > delivered_frame_sequence
                while not has_new_frame and not context.run.status.is_terminal:
                    await context.frame_condition.wait()
                    has_new_frame = context.latest_frame is not None and context.frame_sequence > delivered_frame_sequence

                is_terminal = context.run.status.is_terminal
                frame = context.latest_frame if has_new_frame else None
                if has_new_frame:
                    delivered_frame_sequence = context.frame_sequence

            if frame is not None:
                yield frame

            if is_terminal:
                return

    async def _expire_follow_up_window(self, context: RunContext) -> None:
        try:
            await asyncio.sleep(self._follow_up_window_seconds)
        except asyncio.CancelledError:
            return

        async with self._manager_lock:
            current_context = self._contexts.get(context.run.id)
            if (
                    current_context is not context
                    or context.run.status != RunStatus.READY_FOR_FOLLOW_UP
            ):
                return

            context.follow_up_expiry_task = None
            context.run.follow_up_expires_at = None
            await self._publish(context, "follow_up.expired", {})

        await self._finish_context(context, RunStatus.SUCCEEDED)

    async def _await_cancelled_task(
            self,
            task: asyncio.Task[None] | None,
    ) -> None:
        if task is None or task is asyncio.current_task():
            return

        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _publish(
            self,
            context: RunContext,
            event_type: str,
            payload: dict[str, Any],
            persist: bool = True,
    ) -> RunEvent:
        event = RunEvent(run_id=context.run.id, sequence=context.next_event_sequence, event_type=event_type,
                         payload=RunEventUtils.json_safe(payload))
        context.next_event_sequence += 1
        context.events.append(event)

        if persist:
            self._repository.save_event(
                event, updated_run=context.run if event_type == "reproduction.verdict" else None,
            )

        async with context.event_condition:
            context.event_condition.notify_all()

        if event_type == "agent.message.delta":
            self._trim_live_message_events(context)

        return event

    def _trim_live_message_events(self, context: RunContext) -> None:
        message_event_count = 0
        for event in context.events:
            if event.event_type == "agent.message.delta":
                message_event_count += 1

        events_to_remove = message_event_count - constants.MAX_LIVE_MESSAGE_EVENT_COUNT
        if events_to_remove <= 0:
            return

        retained_events = []
        for event in context.events:
            if event.event_type == "agent.message.delta" and events_to_remove > 0:
                events_to_remove -= 1
                continue
            retained_events.append(event)

        context.events = retained_events


__all__ = ["RunManager"]
