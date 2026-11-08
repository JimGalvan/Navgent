import asyncio
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.sessions import get_current_user
from app.main import app
from app.runs.repository import RunRepository
from app.runs.service import RunManager
from app.server import routes
from navgent.events import InputRequiredEvent, RunCompletedEvent, SessionStatusEvent


class FakeSession:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.closed = asyncio.Event()

    async def start(self, task):
        await self.queue.put(SessionStatusEvent('running'))
        await self.queue.put(InputRequiredEvent('Which account should I use?'))
        await self.queue.put(SessionStatusEvent('waiting_for_input'))

    async def answer(self, answer):
        await self.queue.put(RunCompletedEvent('Observed a stale total.'))
        await self.queue.put(SessionStatusEvent('ready_for_follow_up'))

    async def cancel(self):
        from navgent.events import RunCancelledEvent
        await self.queue.put(RunCancelledEvent())
        await self.queue.put(SessionStatusEvent('cancelled'))

    async def events(self):
        while True:
            event = await self.queue.get()
            if event is None:
                return
            yield event

    async def screen_frames(self):
        yield b'jpeg-test-frame'
        await self.closed.wait()

    def get_latest_frame(self):
        return b'jpeg-test-frame'

    async def close(self):
        self.closed.set()
        await self.queue.put(None)


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv('REPROBE_PREVIEW', 'true')
    repository = RunRepository(tmp_path / 'runs.db')
    repository.initialize()
    manager = RunManager(repository)
    monkeypatch.setattr('app.runs.service.build_agent_runtime', lambda *a, **kw: FakeSession())
    monkeypatch.setattr('app.runs.service.DATABASE_PATH', tmp_path / 'runs.db')
    monkeypatch.setattr(routes, 'DATABASE_PATH', tmp_path / 'runs.db')
    monkeypatch.setattr(routes, 'repository', repository)
    monkeypatch.setattr(routes, 'run_manager', manager)
    user = SimpleNamespace(id=uuid4(), email='one@example.test')
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as connection:
        yield connection, user, manager
    app.dependency_overrides.clear()


@pytest.mark.parametrize('path', ['/', '/login', '/register', '/forgot-password', '/reset-password', '/verify-email', '/preview/new', '/preview/live', '/preview/report', '/preview/reports'])
def test_pages(client, path):
    response = client[0].get(path)
    assert response.status_code == 200
    assert 'Reprobe' in response.text


def test_preview_does_not_authenticate(monkeypatch):
    monkeypatch.setenv('REPROBE_PREVIEW', 'true')
    with TestClient(app) as connection:
        assert connection.get('/preview/live').status_code == 200
        assert connection.get('/api/runs').status_code == 401
        assert connection.get('/app', follow_redirects=False).status_code == 303


def test_mutation_origin(client):
    assert client[0].post('/api/runs', json={'task': 'test'}, headers={'Origin': 'https://other.test'}).status_code == 403


def test_unconfigured_accounts(client, monkeypatch):
    monkeypatch.delenv('WORKOS_API_KEY', raising=False)
    response = client[0].post('/api/auth/login', json={'email': 'a@example.test', 'password': 'private'})
    assert response.status_code == 503
    assert 'private' not in response.text


def test_validation_hides_secrets(client):
    response = client[0].post('/api/auth/login', json={'email': 'not-an-email', 'password': 'private'})
    assert response.status_code == 422
    assert 'private' not in response.text


def test_current_sdk_user_claims():
    from app.auth.sessions import _state_from
    authentication = SimpleNamespace(user=SimpleNamespace(id='user_123', email='one@example.test'))
    state = _state_from(authentication, 'sealed-cookie', False)
    assert state.workos_user_id == 'user_123'
    assert state.email == 'one@example.test'


def test_login_seals_session_without_returning_tokens(client, monkeypatch):
    from cryptography.fernet import Fernet
    from workos.session import Session
    key = Fernet.generate_key().decode()
    monkeypatch.setenv('WORKOS_API_KEY', 'test-key')
    monkeypatch.setenv('WORKOS_CLIENT_ID', 'test-client')
    monkeypatch.setenv('WORKOS_COOKIE_PASSWORD', key)

    class SdkUser:
        id = 'user_example'
        email = 'one@example.test'

        def model_dump(self, **kwargs):
            return {'id': self.id, 'email': self.email}

    authentication = SimpleNamespace(user=SdkUser(), access_token='access-private', refresh_token='refresh-private')
    monkeypatch.setattr('app.auth.password.user_repository', SimpleNamespace(get_or_create_user=lambda *args: None))
    manager = SimpleNamespace(authenticate_with_password=lambda **kwargs: authentication)
    monkeypatch.setattr('app.auth.password.get_client', lambda: SimpleNamespace(user_management=manager))
    response = client[0].post('/api/auth/login', json={'email': 'one@example.test', 'password': 'password-private'})
    assert response.status_code == 200
    assert response.json() == {'redirect': '/app'}
    assert 'access-private' not in response.text
    assert 'refresh-private' not in response.text
    cookie = response.cookies['reprobe_session']
    assert Session.unseal_data(cookie, key)['user']['email'] == 'one@example.test'
    assert 'HttpOnly' in response.headers['set-cookie']


def test_owned_run_input_completion_and_durable_frame(client):
    connection, user, manager = client
    response = connection.post('/api/runs', json={'task': 'Open cart and compare totals'})
    assert response.status_code == 202, response.text
    run_id = response.json()['run']['id']
    for _ in range(30):
        if connection.get('/api/runs/' + run_id).json()['run']['status'] == 'waiting_for_input':
            break
        time.sleep(.01)
    assert connection.post(f'/api/runs/{run_id}/input', json={'answer': 'Use the demo account'}).status_code == 200
    for _ in range(30):
        record = connection.get('/api/runs/' + run_id).json()['run']
        if record['status'] == 'succeeded' and not manager._contexts:
            break
        time.sleep(.01)
    assert record['status'] == 'succeeded'
    assert record['final_output'] == 'Observed a stale total.'
    assert not manager._contexts
    events = connection.get(f'/api/runs/{run_id}/stream')
    assert events.status_code == 200
    assert 'input.required' in events.text
    assert 'run.completed' in events.text
    manager._completed_frames.clear()
    assert connection.get(f'/api/runs/{run_id}/screen.jpg').content == b'jpeg-test-frame'
    user.id = uuid4()
    assert connection.get('/api/runs').json()['runs'] == []
    for suffix in ['', '/stream', '/screen.jpg', '/screen.mjpeg']:
        assert connection.get('/api/runs/' + run_id + suffix).status_code == 404


def test_cancel_finishes_session_and_releases_capacity(client):
    connection, _, manager = client
    response = connection.post('/api/runs', json={'task': 'Open a test page'})
    run_id = response.json()['run']['id']
    response = connection.post(f'/api/runs/{run_id}/cancel')
    assert response.status_code == 200
    assert response.json()['run']['status'] == 'cancelled'
    assert not manager._contexts
    assert not manager._active_run_ids


@pytest.fixture
def account_provider(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv('WORKOS_API_KEY', 'test-key')
    monkeypatch.setenv('WORKOS_CLIENT_ID', 'test-client')
    monkeypatch.setenv('WORKOS_COOKIE_PASSWORD', Fernet.generate_key().decode())
    manager = SimpleNamespace()
    monkeypatch.setattr('app.auth.password.get_client', lambda: SimpleNamespace(user_management=manager))
    return manager


@pytest.mark.parametrize('code_field', ['code', 'error'])
def test_registration_continues_to_verification(client, account_provider, code_field, caplog):
    import httpx
    from workos.exceptions import EmailVerificationRequiredException
    created = []
    account_provider.create_user = lambda **kwargs: created.append(kwargs['email'])

    def authenticate(**kwargs):
        raise EmailVerificationRequiredException(httpx.Response(403), {
            code_field: 'email_verification_required',
            'pending_authentication_token': 'private-pending-token',
            'email_verification_id': 'email_verification_test',
        })

    account_provider.authenticate_with_password = authenticate
    response = client[0].post('/api/auth/register', json={'email': 'new@example.test', 'password': 'private-password'})
    assert created == ['new@example.test']
    assert response.status_code == 200
    assert response.json() == {'redirect': '/verify-email'}
    assert response.cookies['reprobe_pending'] == 'private-pending-token'
    assert 'HttpOnly' in response.headers['set-cookie']
    assert 'private-pending-token' not in response.text + caplog.text
    assert 'private-password' not in response.text + caplog.text


@pytest.mark.parametrize('code,status,expected_status,message', [
    ('password_strength_error', 422, 400, 'stronger password'),
    ('user_already_exists', 409, 400, 'Try logging in'),
    ('invalid_client', 400, 503, 'configuration update'),
    ('sso_required', 400, 400, 'single sign-on'),
])
def test_registration_reports_actionable_errors(client, account_provider, code, status, expected_status, message, caplog):
    import httpx
    from workos.exceptions import BaseRequestException

    def create(**kwargs):
        raise BaseRequestException(httpx.Response(status), {'code': code, 'message': 'private-password'})

    account_provider.create_user = create
    response = client[0].post('/api/auth/register', json={'email': 'new@example.test', 'password': 'private-password'})
    assert response.status_code == expected_status
    assert message in response.json()['detail']
    assert 'private-password' not in response.text + caplog.text


def test_registration_sets_workos_session(client, account_provider, monkeypatch):
    class SdkUser:
        id = 'user_signup_test'
        email = 'signup@example.test'

        def model_dump(self, **kwargs):
            return {'id': self.id, 'email': self.email}

    calls = []
    account_provider.create_user = lambda **kwargs: calls.append('create')
    account_provider.authenticate_with_password = lambda **kwargs: SimpleNamespace(user=SdkUser(), access_token='private-access-token', refresh_token='private-refresh-token')
    monkeypatch.setattr('app.auth.password.user_repository', SimpleNamespace(get_or_create_user=lambda *args: None))
    response = client[0].post('/api/auth/register', json={'email': 'signup@example.test', 'password': 'private-password'})
    assert calls == ['create']
    assert response.status_code == 200
    assert response.json()['redirect'] == '/app'
    assert response.cookies['reprobe_session']
    assert 'private-' not in response.text
