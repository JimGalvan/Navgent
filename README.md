# Reprobe

Reprobe reproduces web bugs on its own and comes back with proof.

You give it a bug report: written steps, screenshots or a screen recording, plus the page URL and what should have happened. An agent turns that into a numbered reproduction brief, opens a real browser inside a disposable gVisor sandbox on Vultr, follows the steps, checks the result on the page, and returns a verdict with a recording of everything it did.

**Live demo:** https://144-202-90-160.sslip.io (sign up with email, then start a reproduction)

Built for the Vultr hackathon on lablab.ai, challenge "Blast Radius Zero": an agent that does real work in a real browser while every action stays inside an isolated sandbox.

## What it does

1. **Reads the evidence.** Steps, screenshots and video frames go to a vision model in one structured call. It returns a `ReproBrief`: numbered steps, each with its source ("written step 3", "screenshot 2", "video 00:07"), the assertion to check, and anything it couldn't work out. Text inside screenshots is treated as evidence, never as instructions, and the target URL always comes from the form, never from the model.
2. **Starts a sandbox.** The app asks a root-owned helper for a fresh gVisor container that runs only Chromium. The container can reach the target host, plus a short fixed list of public CDNs for page assets, and nothing else.
3. **Runs the brief.** The agent (Navgent, built on LangChain deepagents and Playwright) drives that Chromium from the VM over the Playwright protocol. It types key by key like a person, follows the steps in order (each action carries its brief step number and can't go backwards), and reads form values as well as page text.
4. **Checks the assertion.** The agent ends with `report_verdict`: `reproduced`, `not_reproduced` or `inconclusive`, with the expected value, the observed value and the step where it showed. The tool rejects any observed value that isn't on the page word for word, so the agent can't invent evidence.
5. **Returns proof and destroys the sandbox.** The report shows the verdict, expected vs. observed, the action log with values, a WebM recording of each tab with click markers, and the sandbox's lifecycle. Then the container is removed and its firewall rule deleted.

While a run is going you can watch the browser live, take over the mouse and keyboard, answer the agent's questions, or cancel.

### Demo scenario

SauceDemo's `problem_user` has a deliberate checkout bug. Typing in Last Name overwrites First Name one keystroke at a time, so Continue fails with "Last Name is required".

On the public deployment, with Chromium in a gVisor sandbox and every model call on Vultr, Reprobe returns:

```text
verdict:  reproduced
expected: The checkout overview page opens.
observed: Error: Last Name is required; First Name: h; Last Name: (empty); Zip/Postal Code: 12345
```

The run takes about 20 seconds, including starting and destroying the sandbox.

To see the sandbox block something, point a run at a site that loads third-party scripts, such as `https://www.python.org/`. The live log lists each blocked host, for example `analytics.python.org`, `ajax.googleapis.com` and `console.python.org`, while the target page still loads.

## Vultr services

| Service | What we use it for |
| --- | --- |
| **Vultr Cloud Compute** | One VM runs everything: the web app, the agent, Docker with gVisor, and Caddy for HTTPS. Plan `vhp-4c-8gb-amd` (4 vCPU, 8 GB, NVMe), region Seattle (`sea`), Ubuntu 24.04. Created and managed with `vultr-cli`. |
| **Vultr Firewall** | Firewall group `reprobe`: only TCP 22, 80 and 443 are open to the internet. |
| **Vultr Serverless Inference** | Every LLM and vision call, through the OpenAI-compatible endpoint `https://api.vultrinference.com/v1`. No other model provider is configured on the server. |

### Models

| Role | Model | Why |
| --- | --- | --- |
| Agent loop (strong) | `glm-5.3` | Tool calling for long agentic runs. Passed our tool-loop check and reproduced the demo bug every time. |
| Evidence and page navigation (fast) | `glm-5.3-flash` | Multimodal, so it reads screenshots and video frames, and returns a valid `ReproBrief` with JSON-schema structured output. |

Both run in Vultr's Seattle region, next to the VM. A demo run uses about 120k input tokens (most of them cached) and about 600 output tokens, roughly $0.10 at list price.

`navgent/shared/llm.py` maps a `vultr:<model>` setting to LangChain's `ChatOpenAI` with Vultr's base URL and key. It uses the Chat Completions API and a reasoning effort Vultr accepts (`low` for the agent, `minimal` for the fast model). `examples/vultr_smoke.py` checks a model in three steps: a two-tool agent loop, a structured brief from a screenshot, and the full SauceDemo reproduction.

## Architecture

```text
                 Internet
                    │ 443
┌───────────────────▼───────────────────────────────────────────────┐
│ Vultr Cloud Compute VM, Seattle (Ubuntu 24.04)                    │
│                                                                   │
│  Caddy (HTTPS) ──► uvicorn 127.0.0.1:8000, user "reprobe"         │
│                    FastAPI app + Navgent agent                    │
│                    keys in /etc/reprobe/reprobe.env (root:reprobe)│
│                    data in /var/lib/reprobe (SQLite, uploads, WebM)│
│                        │                       │                  │
│     sudo sandboxctl start / stop / reap        │ HTTPS            │
│                        │                       ▼                  │
│                        │        Vultr Serverless Inference        │
│                        ▼        (glm-5.3, glm-5.3-flash)          │
│  Docker, runtime runsc (gVisor)                                   │
│  ┌─────────────────────────────────────────┐                      │
│  │ reprobe-sbx-<run id>                    │◄── ws://127.0.0.1:<port>
│  │ playwright run-server + Chromium        │    Playwright protocol
│  │ 1.5 CPU, 1.5 GB, 256 pids, 15 min max   │    from the agent
│  │ read-only root, tmpfs only, no env vars,│                      │
│  │ no mounts, no capabilities              │                      │
│  └──────────────────┬──────────────────────┘                      │
│     iptables: this sandbox → target IP on 80/443, all else dropped│
└─────────────────────┼─────────────────────────────────────────────┘
                      ▼
               target site only
```

**Only Chromium is in the sandbox.** The agent, its prompts and the inference key stay on the VM, and the sandbox only receives Playwright commands. That keeps every secret out of the sandbox. A hostile page can at most attack a Chromium that has nothing worth stealing, can reach nothing but the site it is already on, and is thrown away after the run.

**The app can't run Docker.** The `reprobe` user isn't in the `docker` group, since that would be the same as root. Its only extra privilege is one sudo rule for `/usr/local/bin/sandboxctl`, a root-owned script that validates its inputs and owns every container flag and firewall rule. The agent can't widen its own sandbox.

**Recordings survive the sandbox.** Playwright's server records each tab inside the container and streams the WebM back to the VM when it's saved, so nothing worth keeping is left in the container when it's destroyed.

### One run, step by step

1. The app calls `sandboxctl start --run <id> --host <target host>`. The host always comes from the submitted URL.
2. `sandboxctl` refuses hosts that aren't public hostnames, and hosts that resolve to private, loopback or metadata addresses. It resolves the target on the VM, picks a free sandbox IP and inserts one ACCEPT rule (sandbox IP → target IP, ports 80 and 443). It also pins each host on the CDN list to one public address and adds an HTTPS-only rule (port 443) for each. Then it starts the container and returns the endpoint and limits as JSON.
3. The agent connects, runs the brief and closes the browser. Recordings land in `/var/lib/reprobe/runs/<id>/recording/`.
4. The app calls `sandboxctl stop`, which removes the container and deletes its rule. It does this on completion, failure, cancel, timeout and shutdown. A systemd timer runs `sandboxctl reap` every five minutes to catch anything a crash left behind.

The run log records `sandbox.starting`, `sandbox.started`, `sandbox.destroyed` (or `sandbox.cleanup_failed`), and one `sandbox.request_blocked` per blocked host. The Live and Report screens show the runtime, limits, allowed host and lifecycle.

## Containment

| Requirement | How it's enforced | Checked on the VM |
| --- | --- | --- |
| Process isolation | Each run gets its own container under gVisor (`--runtime runsc`), a user-space kernel between Chromium and the host. It runs as `pwuser` with `--cap-drop ALL` and `no-new-privileges`. | `docker inspect` shows `runtime=runsc`, and dmesg inside shows "Starting gVisor..." |
| No keys or credentials inside | The container gets no env file, no `-e`, no mounts and no app files. Only Chromium runs there. | The env has only `PATH HOSTNAME LANG LC_ALL PLAYWRIGHT_BROWSERS_PATH HOME`, and there are 0 mounts. |
| Memory and CPU caps | `--memory 1536m --memory-swap 1536m --cpus 1.5 --pids-limit 256` | 1 GB allocates fine. A 4 GB allocation gets the whole sandbox killed by the kernel (`Memory cgroup out of memory: Killed process ... (gvisor_sentry)`) and removed. |
| Time cap | The agent's 600 s run limit, plus `timeout 900` as the container's entrypoint, plus the reaper (16 min) | The entrypoint and timer are installed, and `reap` removes old sandboxes and leftover rules (unit-tested). |
| Network limited to the target | (1) iptables in `DOCKER-USER`: the sandbox IP may reach only the target IP on 80/443 and the pinned CDN addresses on 443, and the sandbox subnet is otherwise dropped. A rule on `INPUT` stops new connections to the VM. (2) The target and the CDNs are pinned with `--add-host` and DNS points at nothing, so no other name resolves. (3) Chromium's `--host-resolver-rules` allows only the target and the CDNs. (4) Inside the browser, CDN requests are limited to GETs for scripts, stylesheets, fonts and images, and any request whose URL carries a saved credential value is refused. Containers can't talk to each other (ICC off). | The target returns 200. `example.com` by name fails to resolve. `1.1.1.1` by IP, the metadata address `169.254.169.254`, and the VM's SSH (via the bridge or the public IP) all time out. The target on port 8080 times out. |
| Destroy after each task | `--rm`, a read-only root, and memory-only `/tmp` and home (tmpfs), so there's no volume to wipe. `stop` removes the container and its rules. | After `stop`: 0 containers and 0 run rules. |

Blocked requests aren't silent. When a page tries to load something from another host, Navgent reports `sandbox.request_blocked` with the host and brief step, and the agent is told not to work around it.

**Known limits.**
- Only ports 80 and 443 on the target are allowed.
- Pages may load assets from a fixed list of public CDNs: `cdn.jsdelivr.net`, `unpkg.com`, `cdnjs.cloudflare.com`, `cdn.tailwindcss.com`, `code.jquery.com`, `ajax.googleapis.com`, `fonts.googleapis.com`, `fonts.gstatic.com` and `esm.sh`. The list lives in `ASSET_HOSTS` in both `navgent/browser/constants.py` and `deploy/sandbox/sandboxctl.py`. Any other host is blocked and reported.
- The firewall allows the target's IP, not its name. On shared hosting (SauceDemo is on GitHub Pages), a hand-built request to another site on the same IP could get through. With DNS off and Chromium's resolver rule, the browser can't make such a request by name.
- For a site that needs a login, the agent types the test login into that site, as a person would. Reprobe's own keys never enter the sandbox.

## Saved logins

Apps that need a sign-in can use a saved test login, so nobody has to paste a password into a bug report.

- **Saving.** Under Manage credentials you give a login a name and its allowed domains (`*.example.com` allows subdomains), then a login, password or contact details. Saved values stay hidden in the UI, even when you edit.
- **Storage.** Each login is encrypted with AES-256-GCM before it reaches SQLite, and bound to its own record. The key (`REPROBE_CREDENTIAL_KEY`) is generated on the VM and kept in `/etc/reprobe/reprobe.env`, apart from the database. Deleting a login wipes its encrypted value.
- **Selection.** The New screen only offers logins whose allowed domains match the app URL's host.
- **During a run.** The agent only sees each login's name, allowed domains, a masked login hint and which fields exist, never a value. When a step needs one, `fill_credential` asks the app, which checks the run's target host and the login's allowed domains, then decrypts the value. Navgent types it only after confirming the field is on the target host and has focus, masks the field before typing, and leaves it out of later page reads and form snapshots.
- **Afterwards.** Values are redacted from run events, and browser tracing is turned off for runs that use a saved login. No stored secret is ever placed in the sandbox: the value only reaches it as keystrokes into the target site's own field.

## Repository layout

```text
navgent/                 the agent
  evidence/              steps, screenshots and video → ReproBrief (one structured call)
  browser_agent/         reproduction agent, tools, report_verdict, step order, form-value checks
  browser/               BrowserManager (local launch or remote Playwright server), recording,
                         host allowlist and blocked-request reporting
  shared/llm.py          model builders, including the vultr: provider
  session.py             BrowserAgentSession: events, live frames, takeover, cancel, recordings
app/                     FastAPI web app: WorkOS accounts, SQLite, runs, evidence uploads,
                         New / Live / Report screens, sandbox lifecycle (app/runs/sandbox.py)
deploy/
  sandbox/Dockerfile     the browser image (Playwright 1.64.1, Chromium, ffmpeg)
  sandbox/sandboxctl.py  root-owned sandbox controller: setup, start, stop, reap
  host/                  bootstrap, sandbox installer, systemd units, sudoers, Caddyfile,
                         app deploy script, env push script
examples/                run_task.py, analyze_evidence.py, vultr_smoke.py
tests/                   agent and sandbox tests; app tests in tests/app and app/tests
```

## Run it locally

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run playwright install chromium
```

Create a `.env` in the repo root:

```text
VULTR_INFERENCE_API_KEY=...        # from your Vultr Serverless Inference subscription
REPROBE_STRONG_MODEL=vultr:glm-5.3
REPROBE_FAST_MODEL=vultr:glm-5.3-flash
REPROBE_EVIDENCE_MODEL=vultr:glm-5.3-flash
```

Check the models, then reproduce the demo bug from the command line:

```bash
uv run python examples/vultr_smoke.py tools vultr:glm-5.3
uv run python examples/vultr_smoke.py evidence vultr:glm-5.3-flash
uv run python examples/vultr_smoke.py reproduce --strong vultr:glm-5.3 --fast vultr:glm-5.3-flash --runs 1
```

To run the web app locally, add the WorkOS settings from `app/.env.example` to the same `.env`, then:

```bash
uv venv app/.venv --python 3.12
uv pip install --python app/.venv/bin/python -r app/requirements.txt   # app\.venv\Scripts\python.exe on Windows
app/.venv/bin/python -m playwright install chromium
app/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8787 --workers 1
```

With `REPROBE_SANDBOX` unset or `local`, Chromium runs on your machine instead of in a sandbox.

To try the sandbox image without the VM (Docker, without gVisor or the firewall):

```bash
docker build -t reprobe-browser:1.64.1 deploy/sandbox
docker run --rm -d --name sbx --read-only --tmpfs /tmp --tmpfs /home/pwuser:mode=1777 --cap-drop ALL -p 127.0.0.1:3000:3000 reprobe-browser:1.64.1
uv run python examples/vultr_smoke.py reproduce --strong vultr:glm-5.3 --fast vultr:glm-5.3-flash --ws-endpoint ws://127.0.0.1:3000/
```

## Deploy to Vultr

Everything below was used for the live deployment.

1. **Inference.** Create a Serverless Inference subscription in the Vultr console and copy its API key. It's different from the account API key.
2. **VM.** With `vultr-cli` and your account key in `VULTR_API_KEY`:
   ```bash
   vultr-cli ssh-key create --name reprobe-laptop --key "$(cat ~/.ssh/id_ed25519.pub)"
   vultr-cli firewall group create --description reprobe
   vultr-cli firewall rule create <group id> --protocol tcp --port 22  --ip-type v4 --subnet 0.0.0.0 --size 0
   vultr-cli firewall rule create <group id> --protocol tcp --port 80  --ip-type v4 --subnet 0.0.0.0 --size 0
   vultr-cli firewall rule create <group id> --protocol tcp --port 443 --ip-type v4 --subnet 0.0.0.0 --size 0
   vultr-cli instance create --region sea --plan vhp-4c-8gb-amd --os 2284 --label reprobe --host reprobe \
       --ssh-keys <ssh key id> --firewall-group <group id>
   ```
3. **Host setup.** Copy the repo to the VM and, as root, run `bash deploy/host/bootstrap.sh`. It installs Docker, gVisor, Caddy and uv, creates the `reprobe` user, and turns off SSH password login.
4. **Sandbox.** As root, run `bash deploy/host/install-sandbox.sh`. It builds the browser image and installs `sandboxctl`, its sudo rule, the network and firewall setup service, and the reap timer.
5. **Config.** From your machine, run `uv run python deploy/host/push_env.py root@<vm ip>`. It writes `/etc/reprobe/reprobe.env` with the inference and WorkOS keys and the production settings (`REPROBE_SANDBOX=docker`, `REPROBE_DATA_DIR=/var/lib/reprobe`), without printing any value.
6. **App.** Send the source as `/root/reprobe-src.tar`, then run `bash deploy/host/deploy-app.sh <host name>`. It installs the app venv, the `reprobe` systemd service and the Caddy site, then waits for `/health`. Without a domain, `<ip-with-dashes>.sslip.io` works and Caddy gets a Let's Encrypt certificate for it.
7. **WorkOS.** Register `https://<host name>/callback` as a redirect URI.

## Tests

```bash
uv run pytest --ignore=tests/app                                         # agent, sandbox controller, remote browser
app/.venv/bin/python -m pytest -c app/pytest.ini tests/app app/tests     # web app
```

The agent suite includes real-browser tests against a local Playwright server. They check that recordings come back to the client, that hosts outside the allowlist fail, and that blocked requests are reported once per host with their brief step. `tests/deploy_tests` checks `sandboxctl`'s input validation, private-address refusal, exact container flags, rule order and cleanup.

## License

MIT. See [LICENSE](LICENSE). The bundled fonts keep their own SIL Open Font License in `app/server/static/fonts/LICENSE.txt`.
