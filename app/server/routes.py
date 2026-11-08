import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from fastapi import (
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.auth import routes as auth_routes
from app.auth.sessions import (
    AuthKitSessionMiddleware,
    CurrentUser,
    read_session_state,
    read_websocket_user,
    user_repository,
    verify_auth_configuration,
)
from app.config import (
    DATABASE_PATH,
    STATIC_DIRECTORY,
    read_credential_encryption_key,
    read_follow_up_window_seconds,
    read_headless_setting,
    read_max_concurrent_runs,
)
from app.credentials.cipher import (
    LocalAesGcmCredentialCipher,
    UnavailableCredentialCipher,
)
from app.credentials.exceptions import (
    CredentialConfigurationError,
    CredentialConflictError,
    CredentialInvalidError,
    CredentialNotFoundError,
)
from app.credentials.repository import CredentialRepository
from app.credentials.service import CredentialService
from app.runs import constants
from app.runs.context import RunContext
from app.runs.exceptions import (
    RunCapacityReachedError,
    RunNotFoundError,
    RunNotReadyForFollowUpError,
    RunNotRerunnableError,
    RunNotWaitingForInputError,
    SensitiveInputNotPendingError,
)
from app.runs.repository import RunRepository
from app.runs.schemas import ReproductionInput, RunEvent, RunRecord
from app.runs.service import RunManager
from app.server.constants import (
    CONTROL_CLOSE_RUN_NOT_FOUND,
    CONTROL_CLOSE_RUN_NOT_WAITING,
    CONTROL_CLOSE_UNAUTHENTICATED,
    CONTROL_EVENT_NOT_UNDERSTOOD,
    CONTROL_MESSAGE_NOT_JSON,
    MJPEG_BOUNDARY,
    NO_CACHE,
    NO_CACHE_HEADERS,
    SCREEN_CACHE_HEADERS,
    SSE_STREAM_HEADERS,
)
from app.server.schemas import (
    BrowserControlEvent,
    CreateCredentialRequest,
    CreateRunRequest,
    CredentialListResponse,
    CredentialMetadata,
    FollowUpRequest,
    RunListResponse,
    RunResponse,
    RunSummary,
    SensitiveInputRequest,
    UpdateCredentialRequest,
    UserInputRequest,
)
from app.server.uploads import UploadLimitMiddleware

logger = logging.getLogger(__name__)


repository = RunRepository(DATABASE_PATH)
credential_repository = CredentialRepository(DATABASE_PATH)
credential_encryption_key = read_credential_encryption_key()
credential_cipher = (
    LocalAesGcmCredentialCipher(credential_encryption_key)
    if credential_encryption_key
    else UnavailableCredentialCipher()
)
credential_service = CredentialService(credential_repository, credential_cipher)
run_manager = RunManager(
    repository,
    credential_service=credential_service,
    headless=read_headless_setting(),
    max_concurrent_runs=read_max_concurrent_runs(constants.DEFAULT_MAX_CONCURRENT_RUNS),
    follow_up_window_seconds=read_follow_up_window_seconds(constants.DEFAULT_FOLLOW_UP_WINDOW_SECONDS),
)


@asynccontextmanager
async def lifespan(application: FastAPI):
    if os.getenv("REPROBE_PREVIEW", "false").lower() != "true":
        verify_auth_configuration()
    repository.initialize()
    user_repository.initialize()
    credential_repository.initialize()
    yield
    await run_manager.shutdown()


app = FastAPI(
    title="Reprobe Agent API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(AuthKitSessionMiddleware)
app.include_router(auth_routes.router)
from app.auth.password import router as password_router

app.include_router(password_router)

_RUN_ERROR_STATUSES = {
    RunNotFoundError: status.HTTP_404_NOT_FOUND,
    RunCapacityReachedError: status.HTTP_429_TOO_MANY_REQUESTS,
    RunNotWaitingForInputError: status.HTTP_409_CONFLICT,
    RunNotReadyForFollowUpError: status.HTTP_409_CONFLICT,
    RunNotRerunnableError: status.HTTP_409_CONFLICT,
    SensitiveInputNotPendingError: status.HTTP_409_CONFLICT,
    CredentialNotFoundError: status.HTTP_404_NOT_FOUND,
    CredentialConflictError: status.HTTP_409_CONFLICT,
    CredentialInvalidError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    CredentialConfigurationError: status.HTTP_503_SERVICE_UNAVAILABLE,
}


def _register_run_error_handlers(application: FastAPI) -> None:
    for error_type, status_code in _RUN_ERROR_STATUSES.items():

        async def handle(request: Request, exception: Exception, code: int = status_code) -> JSONResponse:
            return JSONResponse(status_code=code, content={"detail": str(exception)})

        application.add_exception_handler(error_type, handle)


_register_run_error_handlers(app)


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(
    request: Request, exception: RequestValidationError
) -> JSONResponse:
    """Return validation details without reflecting submitted values."""
    errors = []
    for error in exception.errors():
        errors.append(
            {
                key: value
                for key, value in error.items()
                if key in {"type", "loc", "msg"}
            }
        )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": errors},
    )


class RevalidatedStaticFiles(StaticFiles):
    """Serve static files that browsers must revalidate before reusing."""

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["cache-control"] = NO_CACHE
        return response


app.mount("/static", RevalidatedStaticFiles(directory=STATIC_DIRECTORY), name="static")


def _serve_page(name: str) -> FileResponse:
    return FileResponse(STATIC_DIRECTORY / name, headers=NO_CACHE_HEADERS)


@app.get("/", include_in_schema=False)
async def get_landing_page() -> FileResponse:
    """Public: nothing here reads a run, so it needs no session."""
    return _serve_page("index.html")


@app.get("/app", include_in_schema=False)
async def get_dashboard(request: Request) -> Response:
    if read_session_state(request) is None:
        return RedirectResponse(
            app.url_path_for("start_sign_in"),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    return _serve_page("new.html")


@app.get("/api/health")
async def get_health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/runs", response_model=RunListResponse)
async def list_runs(user: CurrentUser) -> RunListResponse:
    runs = await run_in_threadpool(run_manager.list_runs, user.id)
    return RunListResponse(
        runs=[RunSummary.model_validate(run.model_dump()) for run in runs]
    )


@app.get("/api/credentials", response_model=CredentialListResponse)
async def list_credentials(user: CurrentUser) -> CredentialListResponse:
    credentials = await run_in_threadpool(credential_service.list, user.id)
    return CredentialListResponse(credentials=credentials)


@app.post(
    "/api/credentials",
    response_model=CredentialMetadata,
    status_code=status.HTTP_201_CREATED,
)
async def create_credential(
    request: CreateCredentialRequest, user: CurrentUser
) -> CredentialMetadata:
    return await run_in_threadpool(credential_service.create, user.id, request)


@app.patch("/api/credentials/{credential_id}", response_model=CredentialMetadata)
async def update_credential(
    credential_id: UUID,
    request: UpdateCredentialRequest,
    user: CurrentUser,
) -> CredentialMetadata:
    return await run_in_threadpool(
        credential_service.update, credential_id, user.id, request
    )


@app.delete(
    "/api/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_credential(credential_id: UUID, user: CurrentUser) -> Response:
    await run_in_threadpool(credential_service.revoke, credential_id, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post(
    "/api/runs",
    response_model=RunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_run(request: CreateRunRequest, user: CurrentUser) -> RunResponse:
    run = await run_manager.create_run(
        task=request.task,
        max_runtime_seconds=request.max_runtime_seconds,
        user_id=user.id,
        credential_ids=request.credential_ids,
    )
    return _build_run_response(run)


@app.post("/api/reproductions", response_model=RunResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_reproduction(
    user: CurrentUser,
    target_url: str = Form(...),
    expected: str = Form(...),
    actual: str = Form(""),
    steps_text: str = Form(""),
    max_runtime_seconds: int = Form(600, ge=30, le=1_800),
    credential_ids: list[UUID] | None = Form(None, max_length=25),
    screenshots: list[UploadFile] | None = File(None),
    video: UploadFile | None = File(None),
) -> RunResponse:
    try:
        report = ReproductionInput(
            target_url=target_url, expected=expected, actual=actual, steps_text=steps_text,
        )
    except ValidationError as exception:
        raise RequestValidationError(exception.errors()) from exception
    title = "Reproduction"
    for line in report.steps_text.splitlines():
        if line.strip():
            title = line.strip()[:140]
            break
    task = json.dumps({
        "title": title, "url": report.target_url, "steps": report.steps_text,
        "expected": report.expected, "actual": report.actual,
    })
    run = await run_manager.create_run(
        task=task,
        max_runtime_seconds=max_runtime_seconds,
        user_id=user.id,
        credential_ids=credential_ids,
        bug_report=report,
        screenshots=screenshots,
        video=video,
    )
    return _build_run_response(run)


@app.get("/api/runs/{run_id}", response_model=RunResponse)
async def get_run(run_id: UUID, user: CurrentUser) -> RunResponse:
    run = await run_in_threadpool(run_manager.get_run, run_id, user.id)
    return _build_run_response(run)


@app.get("/api/runs/{run_id}/evidence/{number}.jpg")
async def get_evidence_frame(run_id: UUID, number: int, user: CurrentUser) -> FileResponse:
    path = await run_in_threadpool(run_manager.get_evidence_frame, run_id, user.id, number)
    return FileResponse(path, media_type="image/jpeg", headers=NO_CACHE_HEADERS)


@app.get("/api/runs/{run_id}/stream")
async def stream_run_events(
    run_id: UUID,
    request: Request,
    user: CurrentUser,
    last_event_id: str | None = Header(default=None),
) -> StreamingResponse:
    events = await run_in_threadpool(
        run_manager.stream_events,
        run_id,
        user.id,
        _parse_last_event_id(last_event_id),
    )

    async def event_stream() -> AsyncIterator[str]:
        async for event in events:
            if await request.is_disconnected():
                return

            yield _format_sse_event(event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_STREAM_HEADERS,
    )


@app.get("/api/runs/{run_id}/screen.jpg")
async def get_run_screen(run_id: UUID, user: CurrentUser) -> Response:
    frame = await run_in_threadpool(run_manager.get_latest_frame, run_id, user.id)
    saved = DATABASE_PATH.parent / "evidence" / f"{run_id}.jpg"
    if frame is None and saved.is_file():
        frame = await run_in_threadpool(saved.read_bytes)
    if frame is None:
        return Response(
            status_code=status.HTTP_204_NO_CONTENT,
            headers=SCREEN_CACHE_HEADERS,
        )

    return Response(
        content=frame,
        media_type="image/jpeg",
        headers=SCREEN_CACHE_HEADERS,
    )


@app.get("/api/runs/{run_id}/screen.mjpeg")
async def stream_run_screen(run_id: UUID, user: CurrentUser) -> StreamingResponse:
    frames = await run_in_threadpool(run_manager.stream_frames, run_id, user.id)

    async def frame_stream() -> AsyncIterator[bytes]:
        async for frame in frames:
            frame_header = (
                f"--{MJPEG_BOUNDARY}\r\n"
                "Content-Type: image/jpeg\r\n"
                f"Content-Length: {len(frame)}\r\n\r\n"
            ).encode("ascii")
            yield frame_header + frame + b"\r\n"

    return StreamingResponse(
        frame_stream(),
        media_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}",
        headers=SCREEN_CACHE_HEADERS,
    )


@app.websocket("/api/runs/{run_id}/control")
async def control_run_browser(websocket: WebSocket, run_id: UUID) -> None:
    """Let the person watching a parked run drive its browser themselves.
    """
    if websocket.headers.get("origin") not in {None, str(websocket.url.replace(scheme="https" if websocket.url.scheme == "wss" else "http", path="", query="" )).rstrip("/")}:
        await websocket.close(code=1008)
        return
    user = read_websocket_user(websocket)
    if user is None:
        await websocket.close(code=CONTROL_CLOSE_UNAUTHENTICATED)
        return

    try:
        context = await run_manager.open_control(run_id, user.id)
    except RunNotFoundError:
        await websocket.close(code=CONTROL_CLOSE_RUN_NOT_FOUND)
        return
    except RunNotWaitingForInputError:
        await websocket.close(code=CONTROL_CLOSE_RUN_NOT_WAITING)
        return

    try:
        await websocket.accept()
        while True:
            try:
                payload = await websocket.receive_json()
            except json.JSONDecodeError:
                await _acknowledge(websocket, False, CONTROL_MESSAGE_NOT_JSON)
                continue

            await _handle_control_message(websocket, context, payload)
    except WebSocketDisconnect:
        pass
    finally:
        await run_manager.close_control(context, str(id(websocket)))


async def _handle_control_message(
    websocket: WebSocket,
    context: RunContext,
    payload: Any,
) -> None:
    """Validate and play one action, answering with what became of it.
    """
    try:
        event = BrowserControlEvent.model_validate(payload)
    except ValidationError:
        await _acknowledge(websocket, False, CONTROL_EVENT_NOT_UNDERSTOOD)
        return

    try:
        outcome = await run_manager.apply_control(context, event, str(id(websocket)))
    except Exception as exception:
        logger.warning("Takeover event failed for run %s: %s", context.run.id, exception)
        await _acknowledge(websocket, False, str(exception))
        return

    await _acknowledge(websocket, True, outcome)


async def _acknowledge(websocket: WebSocket, applied: bool, detail: str) -> None:
    """Answer one control message. The dashboard reads both fields."""
    await websocket.send_json({"applied": applied, "detail": detail})


@app.post("/api/runs/{run_id}/input", response_model=RunResponse)
async def submit_run_input(
    run_id: UUID,
    request: UserInputRequest,
    user: CurrentUser,
) -> RunResponse:
    run = await run_manager.submit_input(run_id, user.id, request.answer)
    return _build_run_response(run)


@app.post("/api/runs/{run_id}/sensitive-input", response_model=RunResponse)
async def submit_sensitive_input(
    run_id: UUID,
    request: SensitiveInputRequest,
    user: CurrentUser,
) -> RunResponse:
    run = await run_manager.submit_sensitive_input(
        run_id,
        user.id,
        request.request_id,
        request.code.get_secret_value(),
    )
    return _build_run_response(run)


@app.post("/api/runs/{run_id}/sensitive-input/decline", response_model=RunResponse)
async def decline_sensitive_input(run_id: UUID, user: CurrentUser) -> RunResponse:
    run = await run_manager.decline_sensitive_input(run_id, user.id)
    return _build_run_response(run)


@app.post(
    "/api/runs/{run_id}/rerun",
    response_model=RunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def rerun_run(run_id: UUID, user: CurrentUser) -> RunResponse:
    run = await run_manager.rerun_run(run_id, user.id)
    return _build_run_response(run)


@app.post("/api/runs/{run_id}/cancel", response_model=RunResponse)
async def cancel_run(run_id: UUID, user: CurrentUser) -> RunResponse:
    run = await run_manager.cancel_run(run_id, user.id)
    return _build_run_response(run)


@app.post("/api/runs/{run_id}/follow-ups", response_model=RunResponse)
async def submit_follow_up(
    run_id: UUID,
    request: FollowUpRequest,
    user: CurrentUser,
) -> RunResponse:
    run = await run_manager.submit_follow_up(run_id, user.id, request.task)
    return _build_run_response(run)


@app.post("/api/runs/{run_id}/end", response_model=RunResponse)
async def end_run_session(run_id: UUID, user: CurrentUser) -> RunResponse:
    run = await run_manager.end_session(run_id, user.id)
    return _build_run_response(run)


def _build_run_response(run: RunRecord) -> RunResponse:
    return RunResponse(
        run=run,
        stream_url=app.url_path_for("stream_run_events", run_id=run.id),
        screen_url=app.url_path_for("get_run_screen", run_id=run.id),
        control_url=app.url_path_for("control_run_browser", run_id=run.id),
    )


def _parse_last_event_id(last_event_id: str | None) -> int:
    if last_event_id is None:
        return 0

    try:
        return max(int(last_event_id), 0)
    except ValueError:
        return 0


def _format_sse_event(event: RunEvent) -> str:
    event_data = event.model_dump(mode="json")
    serialized_data = json.dumps(event_data, ensure_ascii=False)
    return (
        f"id: {event.sequence}\nevent: {event.event_type}\ndata: {serialized_data}\n\n"
    )


class OriginMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope)
            if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
                origin = request.headers.get("origin")
                if origin and origin != str(request.base_url).rstrip("/"):
                    await JSONResponse({"detail": "Request origin is not allowed."}, status_code=403)(scope, receive, send)
                    return
            async def no_cache(message):
                if message["type"] == "http.response.start" and not request.url.path.startswith("/static/"):
                    message["headers"].append((b"cache-control", b"no-store"))
                await send(message)
            await self.app(scope, receive, no_cache)
            return
        await self.app(scope, receive, send)


app.add_middleware(OriginMiddleware)
app.add_middleware(UploadLimitMiddleware)


@app.get("/api/capabilities")
async def capabilities():
    return {"auth_configured": bool(os.getenv("WORKOS_API_KEY") and os.getenv("WORKOS_CLIENT_ID") and os.getenv("WORKOS_COOKIE_PASSWORD")), "media_analysis": True}


@app.get("/preview", include_in_schema=False)
@app.get("/preview/{screen}", include_in_schema=False)
async def preview(screen: str = "new"):
    if os.getenv("REPROBE_PREVIEW", "false").lower() != "true":
        raise HTTPException(404)
    if screen not in {"new", "live", "report", "reports"}:
        raise HTTPException(404)
    return _serve_page(f"{screen}.html")


@app.get("/app/reports", include_in_schema=False)
@app.get("/app/runs/{run_id}", include_in_schema=False)
@app.get("/app/reports/{run_id}", include_in_schema=False)
async def run_page(request: Request, run_id: UUID | None = None):
    if read_session_state(request) is None:
        return RedirectResponse("/login", status_code=303)
    page = "reports" if run_id is None else "live" if "/runs/" in request.url.path else "report"
    return _serve_page(page + ".html")
