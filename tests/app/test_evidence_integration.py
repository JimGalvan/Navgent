import asyncio
import json
import sqlite3
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.auth.sessions import get_current_user
from app.config import read_agent_settings
from app.main import app
from app.runs.repository import RunRepository
from app.runs.service import RunManager
from app.server import routes
from navgent.events import RunCompletedEvent, SessionStatusEvent
from navgent.evidence import Assertion, ReproBrief, ReproStep

BRIEF = ReproBrief(
    steps=[
        ReproStep(instruction="Open the cart", source="written step 1"),
        ReproStep(instruction="Remove the bottle", source="inferred"),
    ],
    assertion=Assertion(
        check="Compare the cart total with its remaining line items",
        expected="$30.00",
        reported_actual="$42.00",
        look_in="page",
    ),
    unknowns=["The evidence does not show whether the user is signed in."],
)
REPORT = {
    "target_url": "https://shop.example.test/cart",
    "expected": "The total drops to $30.00",
    "actual": "The page still shows $42.00",
    "steps_text": "Open the cart and remove the bottle",
}


def image_bytes(color: int = 180) -> bytes:
    image = np.full((90, 160, 3), color, dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


class StubEvidenceModel:
    def __init__(self):
        self.schema = None
        self.messages = []
        self.brief = BRIEF
        self.error = None
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    async def ainvoke(self, messages):
        self.messages.append(messages)
        self.entered.set()
        while not self.release.is_set():
            await asyncio.sleep(0.01)
        if self.error:
            raise self.error
        return self.brief


class CompletedSession:
    def __init__(self):
        self.tasks = []
        self.queue = asyncio.Queue()
        self.closed = asyncio.Event()

    async def start(self, task):
        self.tasks.append(task)
        await self.queue.put(SessionStatusEvent("running"))
        await self.queue.put(RunCompletedEvent("Observed the cart total."))
        await self.queue.put(SessionStatusEvent("ready_for_follow_up"))

    async def events(self):
        while True:
            event = await self.queue.get()
            if event is None:
                return
            yield event

    async def screen_frames(self):
        yield self.get_latest_frame()
        await self.closed.wait()

    def get_latest_frame(self):
        return image_bytes()

    async def close(self):
        self.closed.set()
        await self.queue.put(None)


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("REPROBE_PREVIEW", "true")
    repository = RunRepository(tmp_path / "runs.db")
    manager = RunManager(repository)
    model = StubEvidenceModel()
    sessions = []
    models = []

    def build_model(name):
        models.append(name)
        return model

    def build_session(*args, **kwargs):
        session = CompletedSession()
        sessions.append(session)
        return session

    monkeypatch.setattr("navgent.evidence.pipeline.build_evidence_model", build_model)
    monkeypatch.setattr("app.runs.service.build_agent_runtime", build_session)
    monkeypatch.setattr("app.runs.service.DATABASE_PATH", tmp_path / "runs.db")
    monkeypatch.setattr(routes, "DATABASE_PATH", tmp_path / "runs.db")
    monkeypatch.setattr(routes, "repository", repository)
    monkeypatch.setattr(routes, "run_manager", manager)
    monkeypatch.setattr(routes, "user_repository", SimpleNamespace(initialize=lambda: None))
    monkeypatch.setattr(routes, "credential_repository", SimpleNamespace(initialize=lambda: None))
    user = SimpleNamespace(id=uuid4(), email="evidence@example.test")
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as connection:
        yield SimpleNamespace(
            http=connection, user=user, manager=manager, repository=repository,
            model=model, sessions=sessions, models=models, directory=tmp_path,
        )
    app.dependency_overrides.clear()


def create_run(client, data=None, files=None):
    response = client.http.post("/api/reproductions", data=data or REPORT, files=files)
    assert response.status_code == 202, response.text
    return response.json()["run"]["id"]


def finish_run(client, run_id):
    for _ in range(200):
        response = client.http.get(f"/api/runs/{run_id}")
        assert response.status_code == 200, response.text
        run = response.json()["run"]
        if run["status"] in {"succeeded", "failed", "cancelled"} and UUID(run_id) not in routes.run_manager._contexts:
            return run
        time.sleep(0.01)
    pytest.fail(f"Run did not finish: {run}")


def make_video(directory: Path, extension: str) -> bytes:
    path = directory / f"clip{extension}"
    codec = "VP80" if extension == ".webm" else "mp4v"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*codec), 4, (96, 64))
    assert writer.isOpened(), f"Test codec unavailable: {codec}"
    try:
        for color in [0, 0, 100, 100, 200, 200, 200, 200]:
            writer.write(np.full((64, 96, 3), color, dtype=np.uint8))
    finally:
        writer.release()
    return path.read_bytes()


def test_written_steps_are_analyzed_before_the_browser_starts(client, monkeypatch):
    monkeypatch.setenv("REPROBE_EVIDENCE_MODEL", "openai:test-evidence-model")
    run_id = create_run(client)
    run = finish_run(client, run_id)
    assert run["status"] == "succeeded"
    assert client.model.schema is ReproBrief
    assert client.models == ["openai:test-evidence-model"]
    assert len(client.model.messages) == 1
    assert len(client.model.messages[0][1].content) == 1
    assert run["repro_brief"] == BRIEF.model_dump()
    assert run["evidence_frames"] == []
    task = client.sessions[0].tasks[0]
    assert task.startswith(f"Reproduce this bug on {REPORT['target_url']}.")
    assert "1. Open the cart\n2. Remove the bottle" in task
    assert "Reported actual: $42.00" in task
    assert "<unknowns>" in task
    events = client.http.get(f"/api/runs/{run_id}/stream").text
    assert events.index("reading_evidence") < events.index("evidence.ready") < events.index('"status": "running"')


def test_ordered_screenshots_are_saved_with_jpeg_frames_and_labels(client, caplog):
    files = [
        ("screenshots", ("../../cart.png", image_bytes(40), "image/png")),
        ("screenshots", ("cart.webp", image_bytes(220), "image/webp")),
    ]
    data = {**REPORT, "steps_text": ""}
    run_id = create_run(client, data, files)
    run = finish_run(client, run_id)
    assert run["status"] == "succeeded"
    assert run["bug_report"]["screenshot_names"] == ["screenshot-01.png", "screenshot-02.webp"]
    assert len(client.model.messages[0][1].content) == 5
    directory = client.repository.data_directory / run_id
    assert (directory / "uploads" / "screenshot-01.png").read_bytes() == image_bytes(40)
    labels = []
    for frame in run["evidence_frames"]:
        labels.append(frame["label"])
    assert labels == ["screenshot 1", "screenshot 2"]
    for number, frame in enumerate(run["evidence_frames"], start=1):
        response = client.http.get(f"/api/runs/{run_id}/evidence/{number}.jpg")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert response.content.startswith(b"\xff\xd8")
        assert response.content == (directory / "evidence" / frame["filename"]).read_bytes()
    events = client.http.get(f"/api/runs/{run_id}/stream").text
    assert "data:image/" not in json.dumps(run) + events + caplog.text
    client.user.id = uuid4()
    assert client.http.get(f"/api/runs/{run_id}/evidence/1.jpg").status_code == 404


@pytest.mark.parametrize("extension,mime", [(".mp4", "video/mp4"), (".webm", "video/webm"), (".mov", "video/quicktime")])
def test_video_is_saved_and_read_from_disk(client, extension, mime):
    clip = make_video(client.directory, extension)
    run_id = create_run(client, {**REPORT, "steps_text": ""}, [("video", ("clip" + extension, clip, mime))])
    run = finish_run(client, run_id)
    assert run["status"] == "succeeded"
    assert run["bug_report"]["video_name"] == "recording" + extension
    saved = client.repository.data_directory / run_id / "uploads" / ("recording" + extension)
    assert saved.read_bytes() == clip
    assert run["evidence_frames"]
    for frame in run["evidence_frames"]:
        assert frame["label"].startswith("video ")
    assert len(client.model.messages) == 1


def test_all_evidence_types_are_read_in_one_call(client):
    clip = make_video(client.directory, ".mp4")
    run_id = create_run(client, files=[
        ("screenshots", ("cart.png", image_bytes(), "image/png")),
        ("video", ("clip.mp4", clip, "video/mp4")),
    ])
    run = finish_run(client, run_id)
    assert run["status"] == "succeeded"
    assert len(client.model.messages) == 1
    assert run["evidence_frames"][0]["label"] == "screenshot 1"
    assert run["evidence_frames"][1]["label"].startswith("video ")


@pytest.mark.parametrize("field,filename,mime", [("screenshots", "bad.png", "image/png"), ("video", "bad.mp4", "video/mp4"), ("screenshots", "bad.exe", "image/png")])
def test_bad_upload_fails_without_starting_a_browser(client, field, filename, mime):
    run_id = create_run(client, files=[(field, (filename, b"not readable evidence", mime))])
    run = finish_run(client, run_id)
    assert run["status"] == "failed"
    assert run["error"].startswith("Couldn't read the evidence")
    assert not client.sessions
    assert not client.model.messages
    assert not client.manager._active_run_ids
    assert "evidence.failed" in client.http.get(f"/api/runs/{run_id}/stream").text


def test_empty_report_fails_without_starting_a_browser(client):
    run_id = create_run(client, {**REPORT, "steps_text": "  "})
    run = finish_run(client, run_id)
    assert run["status"] == "failed"
    assert "Couldn't read the evidence" in run["error"]
    assert not client.sessions
    assert not client.model.messages


@pytest.mark.parametrize("validation_error", [False, True])
def test_model_errors_fail_cleanly_without_persisting_request_data(client, caplog, validation_error):
    if validation_error:
        with pytest.raises(ValueError) as raised:
            ReproBrief.model_validate({"steps": [], "assertion": {"check": "data:image/jpeg;base64,private"}})
        client.model.error = raised.value
    else:
        client.model.error = RuntimeError("Request failed: data:image/jpeg;base64,private")
    run_id = create_run(client)
    run = finish_run(client, run_id)
    assert run["status"] == "failed"
    assert "Couldn't read the evidence" in run["error"]
    assert not client.sessions
    saved = client.http.get(f"/api/runs/{run_id}/stream").text
    assert "data:image/" not in json.dumps(run) + saved + caplog.text


def test_rerun_reuses_persisted_brief_and_frames_after_reload(client, monkeypatch):
    run_id = create_run(client, files=[("screenshots", ("cart.png", image_bytes(), "image/png"))])
    original = finish_run(client, run_id)
    repository = RunRepository(client.directory / "runs.db")
    repository.initialize()
    reloaded_manager = RunManager(repository)
    monkeypatch.setattr(routes, "run_manager", reloaded_manager)
    client.model.error = AssertionError("Reruns must not call the evidence model")
    response = client.http.post(f"/api/runs/{run_id}/rerun")
    assert response.status_code == 201, response.text
    rerun_id = response.json()["run"]["id"]
    rerun = finish_run(client, rerun_id)
    assert rerun["status"] == "succeeded"
    assert len(client.model.messages) == 1
    assert rerun["repro_brief"] == original["repro_brief"]
    assert rerun["evidence_frames"] == original["evidence_frames"]
    assert client.sessions[0].tasks == client.sessions[1].tasks
    assert client.http.get(f"/api/runs/{rerun_id}/evidence/1.jpg").content == client.http.get(f"/api/runs/{run_id}/evidence/1.jpg").content
    assert '"reused": true' in client.http.get(f"/api/runs/{rerun_id}/stream").text


def test_reading_evidence_is_live_cancellable_and_counts_toward_capacity(client):
    client.model.release.clear()
    client.manager._max_concurrent_runs = 1
    run_id = create_run(client)
    try:
        assert client.model.entered.wait(2)
        assert client.http.get(f"/api/runs/{run_id}").json()["run"]["status"] == "reading_evidence"
        assert not client.sessions
        assert client.http.post("/api/reproductions", data=REPORT).status_code == 429
        response = client.http.post(f"/api/runs/{run_id}/cancel")
        assert response.status_code == 200
        assert response.json()["run"]["status"] == "cancelled"
        assert not client.sessions
        assert not client.manager._contexts
        assert not client.manager._active_run_ids
    finally:
        client.model.release.set()


def test_invalid_stored_brief_fails_without_reanalyzing_or_starting_a_browser(client):
    run_id = create_run(client)
    finish_run(client, run_id)
    run = client.repository.get_run(UUID(run_id))
    run.repro_brief = {"steps": []}
    client.repository.save_run(run)
    response = client.http.post(f"/api/runs/{run_id}/rerun")
    assert response.status_code == 201, response.text
    rerun = finish_run(client, response.json()["run"]["id"])
    assert rerun["status"] == "failed"
    assert "Couldn't read the evidence" in rerun["error"]
    assert len(client.model.messages) == 1
    assert len(client.sessions) == 1


def test_screenshot_count_is_enforced_before_analysis(client):
    files = []
    for number in range(11):
        files.append(("screenshots", (f"cart-{number}.png", image_bytes(), "image/png")))
    run_id = create_run(client, files=files)
    run = finish_run(client, run_id)
    assert run["status"] == "failed"
    assert "up to 10 screenshots" in run["error"]
    assert not client.model.messages
    assert not client.sessions


def test_upload_size_is_enforced_on_the_backend(client, monkeypatch):
    monkeypatch.setattr("app.runs.evidence.MAX_IMAGE_BYTES", 5)
    run_id = create_run(client, files=[("screenshots", ("cart.png", image_bytes(), "image/png"))])
    run = finish_run(client, run_id)
    assert run["status"] == "failed"
    assert "10 MB" in run["error"]
    assert not client.sessions
    assert not client.model.messages
    assert not list((client.repository.data_directory / run_id / "uploads").iterdir())


def test_video_duration_is_enforced_before_analysis(client, monkeypatch):
    monkeypatch.setattr("app.runs.evidence.MAX_VIDEO_SECONDS", 1)
    clip = make_video(client.directory, ".mp4")
    run_id = create_run(client, files=[("video", ("clip.mp4", clip, "video/mp4"))])
    run = finish_run(client, run_id)
    assert run["status"] == "failed"
    assert "2 minutes" in run["error"]
    assert not client.sessions
    assert not client.model.messages


def test_target_url_is_validated_before_creating_a_run(client):
    response = client.http.post("/api/reproductions", data={**REPORT, "target_url": "javascript:private"})
    assert response.status_code == 422
    assert "private" not in response.text
    assert not client.sessions
    assert client.manager.list_runs(client.user.id) == []


def test_large_request_is_rejected_before_multipart_parsing(client, monkeypatch):
    monkeypatch.setattr("app.server.uploads.MAX_REQUEST_BYTES", 10)
    response = client.http.post("/api/reproductions", data=REPORT)
    assert response.status_code == 413
    assert not client.sessions
    assert client.manager.list_runs(client.user.id) == []


def test_chunked_request_is_bounded_while_it_is_read(client, monkeypatch):
    monkeypatch.setattr("app.server.uploads.MAX_REQUEST_BYTES", 10)
    response = client.http.post(
        "/api/reproductions", content=iter([b"target_url=", b"x" * 20]),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 413
    assert not client.sessions


def test_evidence_model_default_is_preserved(monkeypatch):
    from navgent import AgentSettings

    monkeypatch.delenv("REPROBE_EVIDENCE_MODEL", raising=False)
    assert read_agent_settings(uuid4()).evidence_model == AgentSettings.evidence_model


def test_existing_run_database_is_upgraded_without_losing_runs(tmp_path):
    path = tmp_path / "old.db"
    run_id, thread_id, user_id = uuid4(), uuid4(), uuid4()
    with sqlite3.connect(path) as connection:
        connection.execute("""
            CREATE TABLE runs (
                id CHAR(32) PRIMARY KEY, thread_id CHAR(32) NOT NULL,
                user_id CHAR(32), credential_ids JSON NOT NULL, task VARCHAR NOT NULL,
                status VARCHAR NOT NULL, max_runtime_seconds INTEGER NOT NULL,
                final_output VARCHAR, error VARCHAR, follow_up_expires_at DATETIME,
                created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
            )
        """)
        connection.execute(
            "INSERT INTO runs VALUES (?, ?, ?, '[]', 'Open the cart', 'succeeded', 600, NULL, NULL, NULL, ?, ?)",
            (run_id.hex, thread_id.hex, user_id.hex, "2026-11-07 12:00:00", "2026-11-07 12:00:00"),
        )
    repository = RunRepository(path)
    repository.initialize()
    repository.initialize()
    run = repository.get_run(run_id)
    assert run.task == "Open the cart"
    assert run.bug_report is None
    assert run.repro_brief is None
    assert run.evidence_frames == []
