"""Verify encrypted credentials reach only the runs and domains that may use them."""

import asyncio
import json
import logging
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.sessions import get_current_user
from app.credentials.agent_provider import CredentialServiceProvider
from app.credentials.cipher import (
    LocalAesGcmCredentialCipher,
    UnavailableCredentialCipher,
)
from app.credentials.exceptions import (
    CredentialDomainDeniedError,
    CredentialNotFoundError,
)
from app.credentials.repository import CredentialRepository
from app.credentials.service import CredentialService
from app.main import app
from app.runs.repository import RunRepository
from app.runs.runtime import build_agent_runtime
from app.runs.sandbox import SandboxController
from app.runs.service import RunManager
from app.server import routes
from navgent.browser.models import Bounds, Element
from navgent.browser_agent.tools import build_browser_tools
from navgent.events import RunCompletedEvent, SessionStatusEvent
from navgent.evidence.models import Assertion, EvidenceAnalysis, ReproBrief, ReproStep
from navgent.settings import AgentSettings


class CredentialSession:
    recording_paths = ()

    def __init__(self, settings, *, credential_provider, selected_credential_ids):
        self.settings = settings
        self.provider = credential_provider
        self.selected_ids = selected_credential_ids
        self.queue = asyncio.Queue()
        self.closed = asyncio.Event()

    async def start(self, task):
        await self.queue.put(RunCompletedEvent("Signed in using the selected account."))
        await self.queue.put(SessionStatusEvent("ready_for_follow_up"))

    async def events(self):
        while True:
            event = await self.queue.get()
            if event is None:
                return
            yield event

    async def screen_frames(self):
        while not self.closed.is_set():
            await self.closed.wait()
            yield b""

    def get_latest_frame(self):
        return None

    async def close(self):
        self.closed.set()
        await self.queue.put(None)


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("REPROBE_PREVIEW", "true")
    repository = RunRepository(tmp_path / "runs.db")
    credentials = CredentialRepository(tmp_path / "credentials.db")
    service = CredentialService(credentials, LocalAesGcmCredentialCipher(b"k" * 32))
    manager = RunManager(repository, credential_service=service, sandbox_controller=SandboxController(mode="local"))
    sessions = []

    def build_session(settings, **kwargs):
        session = CredentialSession(settings, **kwargs)
        sessions.append(session)
        return session

    async def analyze(report, settings):
        return EvidenceAnalysis(
            brief=ReproBrief(
                steps=[ReproStep(instruction="Sign in and open the cart", source="written step 1")],
                assertion=Assertion(check="Read the cart", expected="Cart opens", reported_actual="", look_in="page"),
                unknowns=[],
            ),
            frames=[],
        )

    monkeypatch.setattr("app.runs.runtime.BrowserAgentSession", build_session)
    monkeypatch.setattr("app.runs.service.analyze_evidence", analyze)
    monkeypatch.setattr(routes, "repository", repository)
    monkeypatch.setattr(routes, "credential_repository", credentials)
    monkeypatch.setattr(routes, "credential_service", service)
    monkeypatch.setattr(routes, "run_manager", manager)
    monkeypatch.setattr(routes, "user_repository", SimpleNamespace(initialize=lambda: None))
    user = SimpleNamespace(id=uuid4(), email="credentials@example.test")
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as connection:
        yield SimpleNamespace(http=connection, user=user, credentials=credentials, service=service,
                              sessions=sessions, manager=manager, directory=tmp_path)
    app.dependency_overrides.clear()


def create_credential(client, name="Staging account"):
    response = client.http.post("/api/credentials", json={
        "name": name,
        "login": "test-login",
        "password": "  test-password  ",
        "email": "test@example.test",
        "allowed_domains": ["staging.example.test"],
        "is_default": True,
    })
    assert response.status_code == 201, response.text
    return response.json()


def finished_run(client, run_id):
    for _ in range(200):
        response = client.http.get(f"/api/runs/{run_id}")
        assert response.status_code == 200, response.text
        run = response.json()["run"]
        if run["status"] in {"succeeded", "failed", "cancelled", "timed_out"}:
            return run
        time.sleep(0.01)
    pytest.fail(f"Run did not finish: {run}")


def test_save_edit_and_delete_preserve_secrets_and_enforce_ownership(client):
    saved = create_credential(client)
    credential_id = UUID(saved["id"])
    stored = client.credentials.get_owned(credential_id, client.user.id)
    assert b"test-password" not in stored.encrypted_payload
    listing = client.http.get("/api/credentials")
    assert listing.status_code == 200
    for value in ("test-login", "test-password", "test@example.test"):
        assert value not in listing.text

    updated = client.http.patch(f"/api/credentials/{credential_id}", json={"name": "Renamed account", "email": None})
    assert updated.status_code == 200
    assert updated.json()["available_fields"] == ["login", "password"]
    secret = client.service.resolve_for_domain(credential_id, client.user.id, "staging.example.test")
    assert secret.login == "test-login"
    assert secret.password == "  test-password  "
    assert secret.email is None
    with pytest.raises(CredentialDomainDeniedError):
        client.service.resolve_for_domain(credential_id, client.user.id, "unrelated.example.test")

    owner_id = client.user.id
    client.user.id = uuid4()
    assert client.http.get("/api/credentials").json() == {"credentials": []}
    assert client.http.patch(f"/api/credentials/{credential_id}", json={"name": "Stolen"}).status_code == 404
    assert client.http.delete(f"/api/credentials/{credential_id}").status_code == 404
    client.user.id = owner_id
    assert client.http.delete(f"/api/credentials/{credential_id}").status_code == 204
    assert client.http.get("/api/credentials").json() == {"credentials": []}
    with pytest.raises(CredentialNotFoundError):
        client.service.resolve_for_domain(credential_id, owner_id, "staging.example.test")


def test_multipart_selection_reaches_runtime_and_reruns(client, caplog):
    selected = create_credential(client)
    other = create_credential(client, "Unselected account")
    response = client.http.post("/api/reproductions", data={
        "target_url": "https://staging.example.test",
        "expected": "Cart opens",
        "steps_text": "Sign in and open the cart",
        "credential_ids": [selected["id"], selected["id"]],
    })
    assert response.status_code == 202, response.text
    run_id = response.json()["run"]["id"]
    run = finished_run(client, run_id)
    assert run["status"] == "succeeded"
    assert run["credential_ids"] == [selected["id"]]
    session = client.sessions[0]
    assert session.selected_ids == (UUID(selected["id"]),)
    metadata = asyncio.run(session.provider.list_selected())
    offered_ids = []
    for item in metadata:
        offered_ids.append(item.id)
    assert offered_ids == [UUID(selected["id"])]
    secret = asyncio.run(session.provider.resolve(UUID(selected["id"]), "staging.example.test"))
    assert secret.password == "  test-password  "
    with pytest.raises(ValueError, match="not selected"):
        asyncio.run(session.provider.resolve(UUID(other["id"]), "staging.example.test"))
    with pytest.raises(CredentialDomainDeniedError):
        asyncio.run(session.provider.resolve(UUID(selected["id"]), "unrelated.example.test"))
    events = client.http.get(f"/api/runs/{run_id}/events")
    assert "test-password" not in events.text
    assert "test-password" not in str(run)
    assert "test-password" not in caplog.text

    rerun = client.http.post(f"/api/runs/{run_id}/rerun")
    assert rerun.status_code == 201, rerun.text
    repeated = finished_run(client, rerun.json()["run"]["id"])
    assert repeated["status"] == "succeeded"
    assert client.sessions[1].selected_ids == session.selected_ids
    assert client.http.delete(f"/api/credentials/{selected['id']}").status_code == 204
    revoked = client.http.post(f"/api/runs/{run_id}/rerun")
    assert revoked.status_code == 409
    assert "no longer available" in revoked.json()["detail"]


def test_runs_without_selection_do_not_receive_defaults(client):
    create_credential(client)
    response = client.http.post("/api/runs", json={"task": "Open the cart"})
    assert response.status_code == 202, response.text
    run = finished_run(client, response.json()["run"]["id"])
    assert run["credential_ids"] == []
    assert client.sessions[0].provider is None


def test_unavailable_storage_and_validation_do_not_reflect_secrets(client, monkeypatch):
    unavailable = CredentialService(client.credentials, UnavailableCredentialCipher())
    monkeypatch.setattr(routes, "credential_service", unavailable)
    response = client.http.post("/api/credentials", json={
        "name": "Account", "allowed_domains": ["staging.example.test"], "password": "private-password",
    })
    assert response.status_code == 503
    assert "private-password" not in response.text
    invalid = client.http.post("/api/credentials", json={
        "name": "Account", "allowed_domains": [], "password": "private-password",
    })
    assert invalid.status_code == 422
    assert "private-password" not in invalid.text


def test_provider_lists_only_matching_domains_without_decrypting(client, monkeypatch):
    matching = create_credential(client)
    other = create_credential(client, "Different host")
    client.http.patch(f"/api/credentials/{other['id']}", json={"allowed_domains": ["other.example.test"]})
    decrypt = Mock(side_effect=AssertionError("Listing must not decrypt credentials"))
    monkeypatch.setattr(client.service, "_decrypt", decrypt)
    provider = CredentialServiceProvider(
        client.service, client.user.id, (UUID(matching["id"]), UUID(other["id"])), "staging.example.test",
    )
    offered = asyncio.run(provider.list_selected())
    offered_ids = []
    for item in offered:
        offered_ids.append(item.id)
    assert offered_ids == [UUID(matching["id"])]
    decrypt.assert_not_called()


@pytest.mark.parametrize("page_host", ["other.example.test", "www.staging.example.test", "staging.example.test.attacker.test"])
def test_provider_never_decrypts_for_a_host_other_than_the_run_target(client, monkeypatch, page_host):
    saved = create_credential(client)
    credential_id = UUID(saved["id"])
    client.http.patch(f"/api/credentials/{credential_id}", json={"allowed_domains": ["*.example.test"]})
    resolve = Mock(side_effect=AssertionError("A different host must not resolve a secret"))
    monkeypatch.setattr(client.service, "resolve_for_domain", resolve)
    provider = CredentialServiceProvider(client.service, client.user.id, (credential_id,), "staging.example.test")
    with pytest.raises(CredentialDomainDeniedError, match="target host"):
        asyncio.run(provider.resolve(credential_id, page_host))
    resolve.assert_not_called()


def test_credential_values_reach_only_the_browser_fill(client, monkeypatch, caplog):
    saved = create_credential(client)
    credential_id = UUID(saved["id"])
    provider = CredentialServiceProvider(client.service, client.user.id, (credential_id,), "staging.example.test")
    fills = []
    events = []
    caplog.set_level(logging.DEBUG)
    bounds = Bounds(0, 0, 0, 0, 0, 0, 0, 0)

    class Browser:
        current_hostname = "staging.example.test"
        page = SimpleNamespace(url="https://staging.example.test")

        def get_stored_element(self, index):
            return Element(index, "password", "input", "Password", "type=password", 0, 0, bounds)

        async def fill(self, index, value):
            fills.append((index, value))

        async def fill_credential(self, index, target_host, read_value):
            fills.append((index, await read_value(target_host)))

        async def wait_for_page_to_settle(self):
            return self.page.url

        def take_performed_clicks(self):
            return []

    monkeypatch.setattr("navgent.browser_agent.tools.publish_custom_event", lambda kind, payload: events.append((kind, payload)))
    tools = {}
    for tool in build_browser_tools(Browser(), provider):
        tools[tool.name] = tool.coroutine
    result = asyncio.run(tools["execute_steps"](reason="Sign in with the saved account", brief_step=1, steps=[{
        "action": "fill_credential", "credential_id": str(credential_id), "field": "password", "element_index": 1,
    }]))
    assert json.loads(result)["ok"] is True
    assert fills == [(1, "  test-password  ")]
    assert "test-password" not in result
    assert "test-password" not in json.dumps(events)
    assert "test-password" not in caplog.text
    for _, payload in events:
        assert payload["value"] == ""

    def unreadable(*args):
        raise ValueError("payload contains test-password")

    monkeypatch.setattr(client.service, "resolve_for_domain", unreadable)
    failed = asyncio.run(tools["execute_steps"](reason="Sign in with the saved account", brief_step=1, steps=[{
        "action": "fill_credential", "credential_id": str(credential_id), "field": "password", "element_index": 1,
    }]))
    assert "could not be read" in failed
    assert "test-password" not in failed
    assert "test-password" not in json.dumps(events)
    assert "test-password" not in caplog.text


def test_sandbox_calls_receive_only_the_run_host_and_no_credentials(client, monkeypatch, caplog):
    saved = create_credential(client)
    calls = []
    monkeypatch.setenv("REPROBE_CREDENTIAL_KEY", "encryption-key-must-stay-in-app")
    monkeypatch.setenv("CREDENTIAL_PASSWORD", "test-password")

    async def launch(*args, **kwargs):
        calls.append({"args": args, "env": kwargs["env"]})
        if args[1] == "start":
            payload = {
                "container": "reprobe-sandbox", "ws_endpoint": "ws://127.0.0.1:31000/",
                "runtime": "gVisor", "allowed_hosts": [args[-1]],
                "limits": {"cpus": 1, "memory_mb": 1024, "pids": 256, "time_limit_seconds": 600},
            }
        else:
            payload = {"stopped": True}

        class Process:
            returncode = 0

            async def communicate(self):
                return json.dumps(payload).encode(), b""

        return Process()

    monkeypatch.setattr("app.runs.sandbox.asyncio.create_subprocess_exec", launch)
    client.manager._sandbox_controller = SandboxController("docker", ("sandboxctl",))
    response = client.http.post("/api/reproductions", data={
        "target_url": "https://staging.example.test/cart", "expected": "Cart opens",
        "steps_text": "Sign in and open the cart", "credential_ids": [saved["id"]],
    })
    assert response.status_code == 202, response.text
    run_id = response.json()["run"]["id"]
    assert finished_run(client, run_id)["status"] == "succeeded"
    arguments = []
    for call in calls:
        arguments.append(call["args"])
    assert arguments == [
        ("sandboxctl", "start", "--run", run_id, "--host", "staging.example.test"),
        ("sandboxctl", "stop", "--run", run_id),
    ]
    session = client.sessions[0]
    offered = asyncio.run(session.provider.list_selected())
    offered_ids = []
    for item in offered:
        offered_ids.append(item.id)
    assert offered_ids == [UUID(saved["id"])]
    secret = asyncio.run(session.provider.resolve(UUID(saved["id"]), calls[0]["args"][-1]))
    assert secret.password == "  test-password  "
    for call in calls:
        assert set(call["env"]) <= {"PATH", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL"}
    output = client.http.get(f"/api/runs/{run_id}/events").text + str(calls) + caplog.text
    for path in Path(client.directory).rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            assert b"test-password" not in content
            assert b"encryption-key-must-stay-in-app" not in content
    assert "test-password" not in output
    assert "encryption-key-must-stay-in-app" not in output


@pytest.mark.parametrize("target_host", ["www.staging.example.test", "other.example.test"])
def test_credentials_outside_target_allowlist_are_never_offered_or_decrypted(client, monkeypatch, target_host):
    saved = create_credential(client)
    credential_id = UUID(saved["id"])
    decrypt = Mock(side_effect=AssertionError("The target host must match before decryption"))
    monkeypatch.setattr(client.service, "_decrypt", decrypt)
    provider = CredentialServiceProvider(client.service, client.user.id, (credential_id,), target_host)
    assert asyncio.run(provider.list_selected()) == ()
    with pytest.raises(CredentialDomainDeniedError, match="not allowed"):
        asyncio.run(provider.resolve(credential_id, target_host))
    decrypt.assert_not_called()


def test_runtime_disables_credential_traces_and_requires_the_sandbox_host(client, monkeypatch):
    saved = create_credential(client)
    trace_path = client.directory / "browser.zip"
    monkeypatch.setattr("app.runs.runtime.read_agent_settings", lambda _: AgentSettings(trace_path=trace_path))
    options = {
        "thread_id": uuid4(), "user_id": client.user.id, "recording_dir": client.directory,
        "credential_ids": (UUID(saved["id"]),), "credential_service": client.service,
        "allowed_hosts": ("staging.example.test",), "credential_host": "staging.example.test",
    }
    session = build_agent_runtime(**options)
    assert session.settings.trace_path is None
    options["credential_host"] = "other.example.test"
    with pytest.raises(ValueError, match="sandbox's target host"):
        build_agent_runtime(**options)
    options["credential_host"] = None
    with pytest.raises(ValueError, match="target URL is required"):
        build_agent_runtime(**options)
    ordinary = build_agent_runtime(uuid4(), client.user.id, client.directory)
    assert ordinary.settings.trace_path == trace_path


def test_invalid_decrypted_payload_does_not_reflect_values(client, monkeypatch):
    saved = create_credential(client)
    monkeypatch.setattr(client.service._cipher, "decrypt", lambda *args: b'{"password": ["private-payload"]}')
    response = client.http.patch(f"/api/credentials/{saved['id']}", json={"name": "Renamed"})
    assert response.status_code == 422
    assert "could not be read" in response.text
    assert "private-payload" not in response.text


def test_saved_exact_domains_preserve_www_and_require_explicit_wildcards(client):
    saved = create_credential(client)
    credential_id = UUID(saved["id"])
    response = client.http.patch(f"/api/credentials/{credential_id}", json={
        "allowed_domains": ["https://WWW.staging.example.test/"],
    })
    assert response.status_code == 200
    assert response.json()["allowed_domains"] == ["www.staging.example.test"]
    exact = CredentialServiceProvider(client.service, client.user.id, (credential_id,), "www.staging.example.test")
    assert len(asyncio.run(exact.list_selected())) == 1
    secret = asyncio.run(exact.resolve(credential_id, "www.staging.example.test"))
    assert secret.login == "test-login"
    other = CredentialServiceProvider(client.service, client.user.id, (credential_id,), "staging.example.test")
    assert asyncio.run(other.list_selected()) == ()
    with pytest.raises(CredentialDomainDeniedError):
        asyncio.run(other.resolve(credential_id, "staging.example.test"))
