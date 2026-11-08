# Reprobe app integration for Vultr

The app manages per-run sandbox lifecycle through the root-owned `/usr/local/bin/sandboxctl` supplied by the infrastructure work. It does not run Docker itself or modify the agent package. Infrastructure provisioning, the VM firewall, the image and reaper timer remain separate deployment work.

## Configuration

Load configuration through the service's environment before Python imports the app. For production set `REPROBE_SANDBOX=docker` and `REPROBE_DATA_DIR=/var/lib/reprobe`. Unset sandbox mode, or `local`, preserves local Chromium execution; an unknown mode fails configuration rather than silently running locally. Local mode never calls the controller.

The data directory contains `reprobe.db` (accounts, credentials, runs and events), `traces/`, `evidence/` (final frames), and `runs/<id>/` (uploads, analyzed evidence and recordings). The service account needs write access there. Existing data is not automatically moved; stop the service, back up the old directory, move its contents with ownership preserved, and set the new directory before restart. Keep one app worker because active-run state lives in memory.

Provider and WorkOS keys stay in the app service environment. The controller subprocess receives only basic process environment variables; no provider keys are forwarded by the app. The root-owned helper must not pass keys, mount the app filesystem, or expose its Playwright port publicly.

## Controller contract

The app uses an argument list, never a shell:

```text
sudo -n /usr/local/bin/sandboxctl start --run <UUID> --host <target-host>
sudo -n /usr/local/bin/sandboxctl stop --run <UUID>
sudo -n /usr/local/bin/sandboxctl reap
```

Start returns a JSON object with `container`, loopback-only `ws_endpoint`, `runtime`, `allowed_hosts` containing exactly the requested host, and positive `limits` for `cpus`, `memory_mb`, `pids`, and `time_limit_seconds`. Stop must return `{"stopped": true, ...}`. The target is taken from the stored submission URL, including on environment reruns; it is never inferred from agent output or uploaded evidence. Raw task runs in Docker mode need a saved JSON `url` field.

The app starts the sandbox before constructing the browser session and passes the endpoint and host restriction to `AgentSettings`. It closes the browser and transfers recordings before stopping the sandbox. Completion, failure, cancellation, timeouts and app shutdown all use cleanup. A partially failed startup also receives a stop attempt. Startup calls reap; deployment must additionally install the independent hard timeout and periodic reaper because process termination can prevent app cleanup.

Run events record `sandbox.starting`, `sandbox.started`, `sandbox.destroyed`, or `sandbox.cleanup_failed`. A failed cleanup never claims destruction. The Live screen and report show recorded runtime, resource limits, allowed host and lifecycle state in a collapsed Sandbox disclosure below the primary evidence. `sandbox.request_blocked` events from Navgent are saved normally and labeled with their host and brief step in the log.

The app client validates the controller response; the root helper and VM network rules enforce containment. Chromium hostname restrictions alone are not a network boundary. End-to-end gVisor and firewall verification must take place on the VM.

## Serve behind Caddy

```sh
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1
```

Run Caddy on the same VM, terminating TLS and reverse-proxying to `127.0.0.1:8000`. Its upstream must preserve the public Host and forwarded scheme and support WebSocket upgrades and streaming (SSE and MJPEG). Register the public HTTPS callback with WorkOS. Proxy headers are trusted only from loopback; do not expose the app port directly.

`GET /health` is public and returns `{"ok": true}`. The existing `/api/health` remains available. HTTPS requests get Secure session and pending-authentication cookies, including HTTPS on localhost. Control WebSockets preserve authentication, ownership and same-origin checks; a mismatched Origin is rejected.

## Licensing

`app/LICENSE` uses the repository's MIT text from `main`, naming Copyright (c) 2026 Jim Galvan, in accordance with the project's stated licensing decision. The font licenses in `app/server/static/fonts/LICENSE.txt` are retained unchanged (SIL Open Font License and their attribution). No third-party notices are removed.

## Verification and deployment checks

Local tests use a fake controller executable and fake agent sessions, without Docker, paid models or WorkOS requests. They cover lifecycle and endpoint wiring, failed start, cancellation, cleanup errors, local mode, persisted events, data relocation and HTTPS behavior. Desktop UI fixtures verify the sandbox disclosure and blocked-request labels.

Implementation verification: 98 backend tests and 30 desktop browser tests passed, including cancellation during controller startup, cleanup after a disconnected browser, and rejection of an invalid remote endpoint. Lint and whitespace checks passed. Sandbox panels in both report and live desktop captures were visually inspected. Mobile cases remain outside this task's scope.

Before calling production ready, verify on the VM: successful `reap`, an actual gVisor browser run, readable saved WebM after sandbox removal, blocked off-target access, authenticated streaming/control through Caddy, correct HTTPS cookies, and removal of the container and per-run firewall rules. A successful local test is not evidence that these infrastructure checks have passed.
