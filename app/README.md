# Reprobe web application

All application code, local dependencies, test output, and runtime data are contained in `app/`. Configuration is shared with the agent through the repository-root `.env`. The root agent, project configuration, and migration documents are unchanged by this work.

## Run locally

From the Navgent repository root, using Python 3.12 or newer:

```powershell
uv venv app/.venv --python .venv/Scripts/python.exe
uv pip install --python app/.venv/Scripts/python.exe -r app/requirements.txt
$env:REPROBE_PREVIEW = 'true'
$env:PYTHONDONTWRITEBYTECODE = '1'
app/.venv/Scripts/python.exe -B -m uvicorn app.main:app --host 127.0.0.1 --port 8787
```

Preview mode permits startup before WorkOS is configured. It exposes sample screens at `/preview/new`, `/preview/live`, `/preview/report`, and `/preview/reports`. It does not authenticate a sample user or permit access to protected run APIs. Public registration and login pages are always available, but submitting them requires real WorkOS configuration.

For real accounts, add the settings listed in `app/.env.example` to the existing repository-root `.env`, provide a fresh WorkOS application/environment, and set `REPROBE_PREVIEW=false`. Preserve existing agent settings. Variables already set in the process environment take precedence over the file; restart the server after changing configuration. WorkOS email/password authentication must be enabled; configure its password-reset URL as `http://localhost:8787/reset-password` for local development. WorkOS handles email delivery and verification. The optional hosted callback is `/callback`.

Set `OPENAI_API_KEY` for Navgent's configured model provider in the same root `.env`. No separate `app/.env` is loaded. Install Playwright Chromium if needed with `app/.venv/Scripts/python.exe -B -m playwright install chromium` before executing real runs. To keep browser binaries inside the application directory, set `PLAYWRIGHT_BROWSERS_PATH` to the absolute path of `app/.cache/browsers` during installation and server startup.

Accounts are provided through WorkOS. Local user mappings, run records, and events use `app/.data/reprobe.db`; completed JPEG frames use `app/.data/evidence/`. Fresh databases are initialized automatically. This initial web runner uses a single server process; do not launch it with multiple workers.

## Implemented

- Landing page, registration/login, verification and password recovery, reproduction form, live viewer, report history, and evidence report.
- Local, licensed Geist fonts extracted from the supplied mock; shared responsive styles based on its charcoal/lime design.
- Adapted account/session, run orchestration, persistence, frame streaming, ownership, retry, and input-handling code from the previous web application. Source license is included in `app/LICENSE`.
- Navgent session integration for written tasks, typed plan/action events, browser frames, cancellation, questions and verification codes.
- Completed-run cleanup and persistent final frames. Execution completion is presented separately from any independently verified reproduction verdict.
- Local-only video/image selection and preview, including ordering screenshots. Media is not uploaded or interpreted in this build. Written steps are required for execution.

## Boundaries and next agent integration

The preview verdict and sample checkout are illustrative. Real reports show actual run output/events and available frames, with no confirmed verdict until structured assertion evidence exists. Recording, HAR, annotation and generated-script downloads are unavailable rather than simulated in real runs. Arbitrary pause/resume, remote sandboxing and telemetry are not implemented.

Claude's upcoming media agents can integrate through an application endpoint that accepts ordered media and returns editable steps. The current run adapter accepts written steps as a JSON task with URL, expected behavior, and user-reported actual behavior. Keep those inputs separate from independently observed evidence. Production media upload storage, limits, and ownership checks should be implemented with that endpoint.

Useful follow-up agent contracts are structured assertion results and supported evidence-capture hooks. The app consumes only public session methods. Navgent currently chooses its own file-tool workspace under `navgent/`; per-run workspace injection should be added by the agent owner before enabling agent file-tool use for multiple users. The web runner does not provide an isolated execution sandbox or network allowlist. Keep real execution on trusted test targets during development.

Saved target-site credentials use the ported credential endpoints and optional encryption key. They are separate from the Reprobe account password; no credential-manager interface is exposed in this first build. Browser takeover endpoints are retained, but interactive mouse/keyboard control is not yet exposed in the new viewer.

## Verify

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
app/.venv/Scripts/python.exe -B -m pytest -c app/pytest.ini app/tests --basetemp=app/.cache/test-runs
```

The 25 local regression checks use a fake session, real application routes and temporary SQLite databases. They exercise signup responses, verification handoff, login, input requests, completion, persisted events/frames, account separation, unconfigured auth, and origin checks without making paid model calls or contacting WorkOS.

Separate opt-in scripts perform real external tests when explicitly approved:

- `python -B -m app.tests.account_smoke` creates or reuses one synthetic WorkOS test account, verifies through WorkOS's test API, checks protected workspace access, logs out, and logs in again. It requires a test key and can trigger verification email. Credentials stay in ignored `app/.data/account-smoke.json`. This does not verify real inbox delivery.
- `python -B -m app.tests.live_smoke` checks a real Navgent session through the application adapter against a local buggy cart.
- `python -B -m app.tests.signed_in_smoke` uses the approved test account to create a real run through the authenticated HTTP API, consume its event stream, and check the saved screenshot, report, and history.

On 2026-11-07 the real tests verified account creation, verification, protected access, fresh login, and a signed-in Navgent run. The agent clicked the cart's Remove button and observed the stale $42 total instead of the expected $30. The run completed and its screenshot/report/history were available. Test results remain under ignored `app/.data/`.

The initial `example.com` test address was routed to SSO by the configured WorkOS environment after account creation. The same temporary account was moved to the `reprobe.test` domain for password-flow testing. The app now explains SSO-required rejections explicitly; it does not override WorkOS policies.
