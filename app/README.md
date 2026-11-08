# Reprobe web application

All application code, local dependencies, test output, and runtime data are contained in `app/`. Configuration is shared with the agent through the repository-root `.env`. The root agent, project configuration, and migration documents are unchanged by this work.

## Run locally

From the Navgent repository root, using Python 3.12 or newer:

```powershell
uv venv app/.venv --python .venv/Scripts/python.exe
uv pip install --python app/.venv/Scripts/python.exe -r app/requirements.txt
uv sync
$env:REPROBE_PREVIEW = 'true'
$env:PYTHONDONTWRITEBYTECODE = '1'
app/.venv/Scripts/python.exe -B -m uvicorn app.main:app --host 127.0.0.1 --port 8787
```

Preview mode permits startup before WorkOS is configured. It exposes sample screens at `/preview/new`, `/preview/live`, `/preview/report`, and `/preview/reports`. It does not authenticate a sample user or permit access to protected run APIs. Public registration and login pages are always available, but submitting them requires real WorkOS configuration.

For real accounts, add the settings listed in `app/.env.example` to the existing repository-root `.env`, provide a fresh WorkOS application/environment, and set `REPROBE_PREVIEW=false`. Preserve existing agent settings. Variables already set in the process environment take precedence over the file; restart the server after changing configuration. WorkOS email/password authentication must be enabled; configure its password-reset URL as `http://localhost:8787/reset-password` for local development. WorkOS handles email delivery and verification. The optional hosted callback is `/callback`.

Set `OPENAI_API_KEY` for Navgent's configured model provider in the same root `.env`. No separate `app/.env` is loaded. Install Playwright Chromium if needed with `app/.venv/Scripts/python.exe -B -m playwright install chromium` before executing real runs. To keep browser binaries inside the application directory, set `PLAYWRIGHT_BROWSERS_PATH` to the absolute path of `app/.cache/browsers` during installation and server startup.

Accounts are provided through WorkOS. Local user mappings, run records, and events use `app/.data/reprobe.db`; completed browser JPEG frames use `app/.data/evidence/`. Uploaded files and evidence key frames use `app/.data/runs/<run-id>/uploads/` and `app/.data/runs/<run-id>/evidence/`. Fresh databases are initialized automatically, and existing run databases receive the additional evidence columns on startup. This web runner uses a single server process; do not launch it with multiple workers.

## Implemented

- Landing page, registration/login, verification and password recovery, reproduction form, live viewer, report history, and evidence report.
- Local, licensed Geist fonts extracted from the supplied mock; shared responsive styles based on its charcoal/lime design.
- Adapted account/session, run orchestration, persistence, frame streaming, ownership, retry, and input-handling code from the previous web application. Source license is included in `app/LICENSE`.
- Navgent session integration for reproduction briefs, typed plan/action events, browser frames, cancellation, questions and verification codes.
- Completed-run cleanup and persistent final frames. Execution completion is presented separately from any independently verified reproduction verdict.
- Combined written steps, ordered screenshots and recording uploads. The backend reads the evidence before starting a browser, and the live viewer shows the reading phase and the resulting plan with sources.
- Saved reproduction briefs, planned assertions, unknowns and labeled JPEG key frames. Reruns validate and reuse the saved brief and copy the evidence to the new run without another model call. Reports distinguish submitted evidence and reported actual behavior from browser observations.

## Evidence input and configuration

The form submits multipart data to `POST /api/reproductions`: `target_url`, `expected`, `actual`, `steps_text`, optional repeated `screenshots` files and one optional `video`. `max_runtime_seconds` defaults to 600; optional repeated `credential_ids` select saved target-site credentials. The original JSON `POST /api/runs` endpoint remains available for direct agent tasks.

Uploads are saved before analysis. Screenshots accept PNG, JPEG, WebP, GIF, BMP and TIFF, up to 10 files of 10 MB each. Recordings accept MP4, WebM and MOV, up to 50 MB and two minutes. The backend checks these limits, bounds total request size before multipart parsing, and rejects unreadable or overly expensive recordings. The pipeline selects up to six screenshot frames and ten video frames.

Set `REPROBE_EVIDENCE_MODEL` in the existing root `.env` to override `AgentSettings.evidence_model` (default `openai:gpt-5-nano`), alongside `REPROBE_STRONG_MODEL` and `REPROBE_FAST_MODEL`. Evidence analysis runs on the application backend, usually in a few seconds to around 30 seconds, with a 90-second timeout. Model errors, invalid briefs and unreadable media fail the run as "Couldn't read the evidence" without starting a browser. Error reports omit provider request contents and image data URLs.

The run record exposes `bug_report`, `repro_brief` and `evidence_frames`. The owner can fetch key frames at `GET /api/runs/<run-id>/evidence/<1-based-number>.jpg`. Live events include `evidence.ready` and `evidence.failed`, and run status includes `reading_evidence`. Stop remains available while analysis is pending.

The live viewer and report use the latest `reproduction.verdict` event. The run's `verdict` includes the expected and observed values, a reason, and an optional brief step. A completed run without an event reads as inconclusive. Failed, cancelled and timed-out runs show their execution status.

Action events retain their value, reason, brief step and visible form fields. The Live screen advances the evidence plan from brief step numbers and shows the latest form snapshot. Reports pair each input action with the previous completed input's fields and mark changed lines. Observed verdict quotes appear on separate lines. Password actions preserve the agent's empty value.

The owner can fetch the ordered saved event history at `GET /api/runs/<run-id>/events`. The Live screen reads this history before subscribing to updates, and ignores repeated event sequences during reconnects.

After the browser closes, the app saves the tab-ordered list of WebM filenames in `recordings`. The report plays the first video and links each tab's download at `GET /api/runs/<run-id>/recordings/<1-based-number>.webm`. Only the run owner can access these files. Reruns reuse the submitted evidence and generate their own recordings and verdict.

## Boundaries and next agent integration

The preview verdict and sample checkout are illustrative. HAR, annotation and generated-script downloads remain in development.

Evidence plans start automatically after analysis; editing the brief before execution is not implemented. The submitted URL remains separate from the model output and is always used to build the reproduction task.

The app consumes only public session methods. Navgent currently chooses its own file-tool workspace under `navgent/`; per-run workspace injection should be added by the agent owner before enabling agent file-tool use for multiple users. The web runner does not provide an isolated execution sandbox or network allowlist. Keep real execution on trusted test targets during development.

Saved target-site credentials use the ported credential endpoints and optional encryption key. They are separate from the Reprobe account password; no credential-manager interface is exposed in this first build. Browser takeover endpoints are retained, but interactive mouse/keyboard control is not yet exposed in the new viewer.

## Verify

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
app/.venv/Scripts/python.exe -B -m pytest -c app/pytest.ini app/tests tests/app --basetemp=app/.cache/test-runs
```

The local regression checks use fake sessions, real application routes and temporary SQLite databases. They exercise accounts, input requests, completion, persisted events/frames, account separation, origin checks, evidence uploads, analysis failure, cancellation, and reruns without paid model calls or WorkOS requests. The evidence tests patch `navgent.evidence.pipeline.build_evidence_model`, while still decoding real images and generated MP4, WebM and MOV clips. UI checks require Playwright Chromium and verify media submission, evidence plans, reading/error states and report layouts.

Separate opt-in scripts perform real external tests when explicitly approved:

- `python -B -m app.tests.account_smoke` creates or reuses one synthetic WorkOS test account, verifies through WorkOS's test API, checks protected workspace access, logs out, and logs in again. It requires a test key and can trigger verification email. Credentials stay in ignored `app/.data/account-smoke.json`. This does not verify real inbox delivery.
- `python -B -m app.tests.live_smoke` checks a real Navgent session through the application adapter against a local buggy cart.
- `python -B -m app.tests.signed_in_smoke` uses the approved test account to create a real run through the authenticated HTTP API, consume its event stream, and check the saved screenshot, report, and history.

On 2026-11-07 the real tests verified account creation, verification, protected access, fresh login, and a signed-in Navgent run. The agent clicked the cart's Remove button and observed the stale $42 total instead of the expected $30. The run completed and its screenshot/report/history were available. Test results remain under ignored `app/.data/`.

The initial `example.com` test address was routed to SSO by the configured WorkOS environment after account creation. The same temporary account was moved to the `reprobe.test` domain for password-flow testing. The app now explains SSO-required rejections explicitly; it does not override WorkOS policies.
