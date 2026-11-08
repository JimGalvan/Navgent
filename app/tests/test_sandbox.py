"""Exercise the app controller contract without Docker or external providers."""

import asyncio
import json
import os
import subprocess
import sys
import time
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from starlette.websockets import WebSocketDisconnect

from app.auth.sessions import is_local_request
from app.runs.sandbox import SandboxController, SandboxError
from app.server import routes
from app.tests.test_application import FakeSession
from app.tests.test_application import client as client
from navgent.events import RunFailedEvent, SessionStatusEvent


def controller(tmp_path, mode="ok"):
    script = tmp_path / "sandboxctl.py"
    log = tmp_path / "calls.jsonl"
    script.write_text('''import json, os, sys
from pathlib import Path
args = sys.argv[2:]
with Path(sys.argv[1]).open('a') as out:
    out.write(json.dumps({'args': args, 'secret': os.getenv('VULTR_INFERENCE_API_KEY')}) + '\\n')
mode = MODE
if args[0] == 'start':
    if mode == 'fail':
        print('provider-secret-must-not-leak', file=sys.stderr)
        sys.exit(1)
    print(json.dumps({'container': 'reprobe-sbx-' + args[2], 'ws_endpoint': 'ws://127.0.0.1:31000/',
        'runtime': 'gVisor (runsc)', 'allowed_hosts': [args[4]],
        'limits': {'cpus': 1.5, 'memory_mb': 1536, 'pids': 256, 'time_limit_seconds': 900}}))
elif args[0] == 'stop':
    print(json.dumps({'stopped': mode != 'cleanup-fail'}))
else:
    print('{}')
'''.replace("MODE", repr(mode)), encoding="utf-8")
    return SandboxController("docker", (sys.executable, str(script), str(log))), log


def wait_status(connection, run_id, expected):
    for _ in range(200):
        run = connection.get(f"/api/runs/{run_id}").json()["run"]
        if run["status"] == expected:
            return run
        time.sleep(.01)
    pytest.fail(f"Expected {expected}, got {run['status']}")


@pytest.mark.parametrize("ending", ["succeeded", "failed", "cancelled", "timed_out", "shutdown"])
def test_lifecycle_saves_recordings_before_teardown(client, monkeypatch, tmp_path, ending):
    connection, user, manager = client
    manager._sandbox_controller, log = controller(tmp_path)
    sessions, options = [], []

    def build(*args, **kwargs):
        options.append(kwargs)
        session = FakeSession()
        original_close = session.close

        async def close():
            assert len(log.read_text().splitlines()) == 1, "Controller must not stop before browser close"
            directory = kwargs["recording_dir"]
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / "tab.webm"
            path.write_bytes(b"saved recording")
            session.recording_paths = (path,)
            await original_close()
        session.close = close
        sessions.append(session)
        return session

    monkeypatch.setenv("VULTR_INFERENCE_API_KEY", "do-not-forward")
    monkeypatch.setattr("app.runs.service.build_agent_runtime", build)
    response = connection.post("/api/runs", json={"task": json.dumps({"url": "https://target.example.test/path"})})
    assert response.status_code == 202, response.text
    run_id = response.json()["run"]["id"]
    wait_status(connection, run_id, "waiting_for_input")
    assert options[0]["browser_ws_endpoint"] == "ws://127.0.0.1:31000/"
    assert options[0]["allowed_hosts"] == ("target.example.test",)
    if ending == "succeeded":
        connection.post(f"/api/runs/{run_id}/input", json={"answer": "Continue"})
    elif ending == "cancelled":
        connection.post(f"/api/runs/{run_id}/cancel")
    elif ending == "shutdown":
        connection.portal.call(manager.shutdown)
    else:
        async def finish():
            if ending == "failed":
                await sessions[0].queue.put(RunFailedEvent("Browser failed"))
            await sessions[0].queue.put(SessionStatusEvent(ending))
        connection.portal.call(finish)
    saved = wait_status(connection, run_id, "cancelled" if ending == "shutdown" else ending)
    assert saved["recordings"] == ["tab.webm"]
    events = connection.get(f"/api/runs/{run_id}/events").json()
    assert [item["event_type"] for item in events if item["event_type"].startswith("sandbox.")] == ["sandbox.starting", "sandbox.started", "sandbox.destroyed"]
    assert "ws_endpoint" not in next(item["payload"] for item in events if item["event_type"] == "sandbox.started")
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert [item["args"][0] for item in calls] == ["start", "stop"]
    assert calls[0]["args"] == ["start", "--run", run_id, "--host", "target.example.test"]
    assert all(item["secret"] is None for item in calls)


def test_failed_start_never_builds_agent_and_attempts_cleanup(client, monkeypatch, tmp_path):
    connection, _, manager = client
    manager._sandbox_controller, log = controller(tmp_path, "fail")
    monkeypatch.setattr("app.runs.service.build_agent_runtime", lambda *a, **kw: pytest.fail("Must not start a local agent"))
    response = connection.post("/api/runs", json={"task": json.dumps({"url": "https://target.example.test"})})
    run = response.json()["run"]
    assert run["status"] == "failed"
    assert "Sandbox start failed" in run["error"]
    assert "provider-secret" not in response.text
    assert [json.loads(line)["args"][0] for line in log.read_text().splitlines()] == ["start", "stop"]


def test_cleanup_failure_never_claims_destroyed(client, tmp_path):
    connection, _, manager = client
    manager._sandbox_controller, _ = controller(tmp_path, "cleanup-fail")
    run_id = connection.post("/api/runs", json={"task": json.dumps({"url": "https://target.example.test"})}).json()["run"]["id"]
    wait_status(connection, run_id, "waiting_for_input")
    connection.post(f"/api/runs/{run_id}/cancel")
    events = connection.get(f"/api/runs/{run_id}/events").json()
    assert any(item["event_type"] == "sandbox.cleanup_failed" for item in events)
    assert not any(item["event_type"] == "sandbox.destroyed" for item in events)


def test_browser_close_failure_still_stops_sandbox(client, tmp_path):
    connection, _, manager = client
    manager._sandbox_controller, log = controller(tmp_path)
    run_id = connection.post("/api/runs", json={"task": json.dumps({"url": "https://target.example.test"})}).json()["run"]["id"]
    wait_status(connection, run_id, "waiting_for_input")
    context = manager._contexts[UUID(run_id)]
    async def broken_close():
        raise RuntimeError("Remote browser disconnected")
    context.session.close = broken_close
    connection.post(f"/api/runs/{run_id}/cancel")
    assert [json.loads(line)["args"][0] for line in log.read_text().splitlines()] == ["start", "stop"]
    assert context.frame_task.done()
    events = connection.get(f"/api/runs/{run_id}/events").json()
    assert any(item["event_type"] == "sandbox.destroyed" for item in events)


def test_runtime_constructs_remote_agent_settings(monkeypatch, tmp_path):
    from app.runs.runtime import build_agent_runtime
    captured = []
    monkeypatch.setattr("app.runs.runtime.BrowserAgentSession", lambda settings, **kw: captured.append(settings))
    build_agent_runtime(uuid4(), None, tmp_path, browser_ws_endpoint="ws://127.0.0.1:31000/", allowed_hosts=("target.example.test",))
    assert captured[0].browser_ws_endpoint == "ws://127.0.0.1:31000/"
    assert captured[0].allowed_hosts == ("target.example.test",)
    assert captured[0].recording_dir == tmp_path


def test_local_mode_never_invokes_controller(tmp_path):
    local = SandboxController("local", ("nonexistent-controller",))
    async def exercise():
        assert await local.start(uuid4(), "target.example.test") is None
        await local.stop(uuid4())
        await local.reap()
    asyncio.run(exercise())
    with pytest.raises(SandboxError):
        SandboxController("dokcer")


def test_reap_calls_helper(tmp_path):
    remote, log = controller(tmp_path)
    asyncio.run(remote.reap())
    assert json.loads(log.read_text())["args"] == ["reap"]


def test_data_directory_configuration_is_applied_before_import(tmp_path):
    environment = {**os.environ, "REPROBE_DATA_DIR": str(tmp_path / "persistent")}
    script = "from app.config import DATABASE_PATH, TRACE_DIRECTORY; from app.runs.repository import RunRepository; r=RunRepository(DATABASE_PATH); r.initialize(); print(DATABASE_PATH); print(TRACE_DIRECTORY); print(r.data_directory)"
    result = subprocess.run([sys.executable, "-c", script], env=environment, capture_output=True, text=True, check=True)
    lines = result.stdout.splitlines()
    assert lines == [str(tmp_path / "persistent" / "reprobe.db"), str(tmp_path / "persistent" / "traces"), str(tmp_path / "persistent" / "runs")]
    assert (tmp_path / "persistent" / "reprobe.db").is_file()


def test_https_cookie_policy_and_public_health(client):
    assert client[0].get("/health").json() == {"ok": True}
    for scheme, expected in [("http", True), ("https", False)]:
        request = Request({"type": "http", "scheme": scheme, "server": ("localhost", 8000), "path": "/", "headers": []})
        assert is_local_request(request) is expected


def test_wss_control_keeps_same_origin_check(client, monkeypatch):
    connection, user, manager = client
    run_id = connection.post("/api/runs", json={"task": "Test"}).json()["run"]["id"]
    wait_status(connection, run_id, "waiting_for_input")
    async def control():
        pass
    session = manager._contexts[UUID(run_id)].session
    session.take_control = control
    session.release_control = control
    monkeypatch.setattr(routes, "read_websocket_user", lambda ws: user)
    path = f"wss://testserver/api/runs/{run_id}/control"
    with connection.websocket_connect(path, headers={"origin": "https://testserver"}) as socket:
        socket.send_json({"type": "not-an-action"})
        assert socket.receive_json()["applied"] is False
    with pytest.raises(WebSocketDisconnect):
        with connection.websocket_connect(path, headers={"origin": "https://other.test"}):
            pass


def test_invalid_controller_endpoint_fails_closed_and_stops(client, monkeypatch, tmp_path):
    connection, _, manager = client
    remote, log = controller(tmp_path)
    script = tmp_path / "sandboxctl.py"
    script.write_text(script.read_text().replace("ws://127.0.0.1:31000/", "ws://remote.example.test:31000/"))
    manager._sandbox_controller = remote
    monkeypatch.setattr("app.runs.service.build_agent_runtime", lambda *a, **kw: pytest.fail("Invalid endpoint must not reach agent"))
    run = connection.post("/api/runs", json={"task": json.dumps({"url": "https://target.example.test"})}).json()["run"]
    assert run["status"] == "failed"
    assert "invalid endpoint" in run["error"]
    assert [json.loads(line)["args"][0] for line in log.read_text().splitlines()] == ["start", "stop"]


def test_cancel_during_sandbox_start_never_launches_agent(client, monkeypatch, tmp_path):
    from navgent.evidence import Assertion, ReproBrief, ReproStep
    connection, _, manager = client
    remote, log = controller(tmp_path)
    script = tmp_path / "sandboxctl.py"
    script.write_text(script.read_text().replace("if args[0] == 'start':", "if args[0] == 'start':\n    import time; time.sleep(30)"))
    manager._sandbox_controller = remote
    async def analyze(*args):
        return type("Analysis", (), {"frames": [], "brief": ReproBrief(
            steps=[ReproStep(instruction="Open target", source="written step 1")],
            assertion=Assertion(check="Check title", expected="Title", reported_actual="Wrong", look_in="page"),
            unknowns=[],
        )})()
    monkeypatch.setattr("app.runs.service.analyze_evidence", analyze)
    monkeypatch.setattr("app.runs.service.build_agent_runtime", lambda *a, **kw: pytest.fail("Cancelled startup must not launch agent"))
    run_id = connection.post("/api/reproductions", data={"target_url": "https://target.example.test", "expected": "Title", "steps_text": "Open target"}).json()["run"]["id"]
    for _ in range(200):
        if log.is_file() and log.read_text().strip():
            break
        time.sleep(.01)
    assert log.is_file()
    response = connection.post(f"/api/runs/{run_id}/cancel")
    assert response.json()["run"]["status"] == "cancelled"
    assert [json.loads(line)["args"][0] for line in log.read_text().splitlines()] == ["start", "stop"]
