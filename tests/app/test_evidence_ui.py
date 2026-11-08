"""Browser checks use local fixtures and replay public run events, without providers."""

import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import cv2
import numpy as np
import pytest
from playwright.sync_api import expect, sync_playwright

PROJECT_DIRECTORY = Path(__file__).resolve().parents[2]
STATIC_DIRECTORY = PROJECT_DIRECTORY / "app" / "server" / "static"
SCREENSHOT_DIRECTORY = PROJECT_DIRECTORY / "app" / ".cache" / "evidence-ui"
RUN_ID = "48f40743-aa2b-4e89-ad39-0572c61fb579"
BRIEF = {
    "steps": [
        {"instruction": "Open the cart", "source": "written step 1"},
        {"instruction": "Apply SAVE50", "source": "screenshot 2"},
        {"instruction": "Remove the bottle", "source": "video 00:07"},
        {"instruction": "Compare the total with the remaining items", "source": "inferred"},
    ],
    "assertion": {
        "check": "Compare the cart total with its remaining line items",
        "expected": "$30.00", "reported_actual": "$42.00", "look_in": "network",
    },
    "unknowns": ["The evidence does not show whether the user is signed in."],
}


def evidence_image():
    image = np.full((280, 520, 3), 240, dtype=np.uint8)
    cv2.putText(image, "Cart total: $42.00", (32, 140), cv2.FONT_HERSHEY_SIMPLEX, 1, (30, 30, 30), 2)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return encoded.tobytes()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture(scope="module")
def recorded_tab(browser, tmp_path_factory):
    context = browser.new_context(record_video_dir=tmp_path_factory.mktemp("recorded-tab"))
    tab = context.new_page()
    tab.set_content("<h1>Cart total: $42.00</h1>")
    tab.screenshot()
    video = tab.video
    context.close()
    return video.path().read_bytes()


@pytest.fixture(params=[1440, 390], ids=["desktop", "mobile"])
def surface(browser, request):
    context = browser.new_context(viewport={"width": request.param, "height": 1000})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script("""
        window.EventSource = class extends EventTarget {
            constructor() { super(); window.testRunStream = this; }
            close() {}
        };
    """)
    record = {
        "id": RUN_ID, "status": "succeeded", "error": None,
        "created_at": "2026-11-07T12:00:00Z", "updated_at": "2026-11-07T12:01:00Z",
        "task": json.dumps({"title": "Cart total after removing a discounted item", "url": "https://shop.example.test/cart"}),
        "repro_brief": BRIEF,
        "evidence_frames": [{"filename": "frame-01.jpg", "label": "screenshot 2"}, {"filename": "frame-02.jpg", "label": "video 00:07"}],
        "final_output": "The browser run finished. See the saved evidence for the result.",
    }
    state = SimpleNamespace(run=record, uploads=[], frame=True, video=None, events=[])

    def handle(route):
        path = urlsplit(route.request.url).path
        if path == "/api/auth/me":
            route.fulfill(json={"email": "evidence@example.test"})
        elif path == "/api/runs":
            route.fulfill(json={"runs": []})
        elif path == "/api/reproductions":
            state.uploads.append((route.request.headers, route.request.post_data_buffer))
            state.run.update(status="reading_evidence", repro_brief=None, evidence_frames=[])
            route.fulfill(status=202, json={"run": state.run})
        elif path == f"/api/runs/{RUN_ID}":
            route.fulfill(json={"run": state.run, "stream_url": f"/api/runs/{RUN_ID}/stream", "screen_url": f"/api/runs/{RUN_ID}/screen.jpg"})
        elif path == f"/api/runs/{RUN_ID}/stream":
            route.fulfill(content_type="text/event-stream", body="")
        elif path == f"/api/runs/{RUN_ID}/events":
            route.fulfill(json=state.events)
        elif "/recordings/" in path and state.video:
            route.fulfill(content_type="video/webm", body=state.video)
        elif "/evidence/" in path or path.endswith("screen.jpg") and state.frame:
            route.fulfill(content_type="image/jpeg", body=evidence_image())
        elif path.endswith("screen.jpg"):
            route.fulfill(status=204)
        elif path.startswith("/static/"):
            route.fulfill(path=STATIC_DIRECTORY / path.removeprefix("/static/"))
        elif path.startswith("/app/reports/"):
            route.fulfill(path=STATIC_DIRECTORY / "report.html")
        elif path.startswith("/app/runs/"):
            route.fulfill(path=STATIC_DIRECTORY / "live.html")
        elif path == "/app":
            route.fulfill(path=STATIC_DIRECTORY / "new.html")
        else:
            route.fulfill(status=404)

    page.route("http://reprobe.test/**", handle)
    yield SimpleNamespace(page=page, state=state, width=request.param)
    context.close()
    assert errors == []


def capture(surface, name):
    page = surface.page
    page.evaluate("document.fonts.ready")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    SCREENSHOT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=SCREENSHOT_DIRECTORY / f"{name}-{surface.width}.png", full_page=True)


def send_event(page, event_type, payload, sequence):
    event = {"event_type": event_type, "payload": payload, "sequence": sequence, "created_at": "2026-11-07T12:00:00Z"}
    page.evaluate("event => window.testRunStream.dispatchEvent(new MessageEvent(event.event_type, {data: JSON.stringify(event)}))", event)


def action_event(sequence, phase, action, target, **payload):
    return dict(sequence=sequence, event_type="browser.action." + phase,
                payload=dict(action=action, target=target, **payload), created_at="2026-11-07T12:00:00Z")


def typing_events():
    return [
        action_event(1, "started", "type", "First Name", value="Demo", reason="Enter the first name.", brief_step=2),
        action_event(2, "completed", "type", "First Name", value="Demo", reason="Enter the first name.", brief_step=2,
                     fields=["First Name: Demo", "Last Name: (empty)"]),
        action_event(3, "started", "type", "Last Name", value="Tester", reason="Check the last-name defect.", brief_step=3),
        action_event(4, "completed", "type", "Last Name", value="Tester", reason="Check the last-name defect.", brief_step=3,
                     fields=["First Name: r", "Last Name: (empty)"]),
        action_event(5, "completed", "type", "Password", value="", fields=["First Name: r", "Last Name: (empty)"]),
        action_event(6, "failed", "click", "Continue", reason="Check validation.", error="Last Name is required"),
    ]


def test_live_replays_action_progress_fields_and_reconnects_without_regressing(surface):
    surface.state.run["status"] = "running"
    surface.state.events = typing_events()[:4]
    page = surface.page
    page.goto(f"http://reprobe.test/app/runs/{RUN_ID}")
    current = page.locator('#plan [aria-current="step"]')
    expect(current).to_contain_text("Remove the bottle")
    expect(page.locator('#plan [data-status="completed"]')).to_have_count(2)
    expect(page.locator("#activity")).to_contain_text('type "Tester" into Last Name')
    expect(page.locator("#activity")).to_contain_text("Check the last-name defect.")
    expect(page.locator("#form-state")).to_contain_text("First Name: r")
    page.wait_for_function("Boolean(window.testRunStream)")
    for event in surface.state.events:
        send_event(page, event["event_type"], event["payload"], event["sequence"])
    send_event(page, "browser.action.started", dict(action="click", target="Continue", brief_step=None), 7)
    send_event(page, "browser.action.started", dict(action="click", target="Back", brief_step=1), 8)
    expect(current).to_contain_text("Remove the bottle")
    expect(page.locator("#activity .event-row")).to_have_count(6)
    page.reload()
    expect(current).to_contain_text("Remove the bottle")
    expect(page.locator("#form-state")).to_contain_text("First Name: r")
    expect(page.locator("#browser-screen")).to_be_visible()
    expect(page.locator("#frame-strip img")).to_have_count(1)
    capture(surface, "live-browser")


@pytest.mark.parametrize("status", ["running", "succeeded"])
def test_report_pairs_input_snapshots_and_splits_observed_quotes(surface, status):
    surface.state.run["status"] = status
    surface.state.events = typing_events()
    surface.state.run["verdict"] = dict(
        verdict="reproduced", expected="First Name: Demo; Last Name: Tester", step_number=3,
        observed="First Name: r; Last Name: (empty); Error: Last Name is required",
        reason="Typing into Last Name changed First Name.",
    )
    page = surface.page
    page.goto(f"http://reprobe.test/app/reports/{RUN_ID}")
    rows = page.locator("#action-log .action-row")
    expect(rows).to_have_count(4)
    expect(rows.nth(0).locator(".field-snapshot").first).to_contain_text("No field values captured")
    before, after = rows.nth(1).locator(".field-snapshot").all()
    expect(before).to_contain_text("First Name: Demo")
    expect(after).to_contain_text("First Name: r")
    expect(before.locator(".field-changed")).to_have_count(1)
    expect(after.locator(".field-changed")).to_have_count(1)
    expect(rows.nth(1)).to_contain_text("Step 3")
    expect(rows.nth(1)).to_contain_text("Check the last-name defect.")
    expect(rows.nth(2).locator(".action-title")).to_have_text("type into Password")
    expect(rows.nth(3)).to_contain_text("Failed")
    expect(rows.nth(3)).to_contain_text("Last Name is required")
    expect(page.locator(".observed-quote")).to_have_count(3)
    expect(page.locator(".observed-quote").first).to_have_text("First Name: r")
    capture(surface, "report-input-changes")
    page.reload()
    expect(page.locator("#action-log .action-row")).to_have_count(4)
    expect(page.locator("#action-log .action-row").nth(1).locator(".field-changed")).to_have_count(2)


def test_old_actions_and_empty_password_values_render_without_fallback(surface):
    surface.state.events = [
        action_event(1, "started", "type", "Password"),
        action_event(2, "completed", "type", "Password"),
        action_event(3, "completed", "click", "Continue"),
    ]
    page = surface.page
    surface.state.run["status"] = "running"
    page.goto(f"http://reprobe.test/app/runs/{RUN_ID}")
    expect(page.locator("#activity")).to_contain_text("type into Password")
    expect(page.locator("#activity")).not_to_contain_text('""')
    surface.state.run["status"] = "succeeded"
    page.goto(f"http://reprobe.test/app/reports/{RUN_ID}")
    expect(page.locator("#action-log .action-row")).to_have_count(2)
    expect(page.locator("#action-log .action-title").first).to_have_text("type into Password")
    expect(page.locator("#action-log .action-title").last).to_have_text("click · Continue")


def test_media_only_submission_sends_all_selected_evidence(surface):
    page = surface.page
    page.goto("http://reprobe.test/app")
    page.locator("#target-url").fill("https://shop.example.test/cart")
    page.locator("#expected").fill("The total should drop to $30.00")
    page.locator("#actual").fill("The total stays at $42.00")
    page.locator("#start-run").click()
    expect(page.locator("#form-message")).to_contain_text("Add written steps")
    assert surface.state.uploads == []
    page.locator("#video-files").set_input_files({"name": "recording.webm", "mimeType": "video/webm", "buffer": b"video upload fixture"})
    page.locator("#shot-files").set_input_files({"name": "cart.jpg", "mimeType": "image/jpeg", "buffer": evidence_image()})
    expect(page.locator("#media-note")).to_contain_text("1 screenshot and 1 recording")
    expect(page.locator("#form-message")).to_be_empty()
    capture(surface, "new-evidence")
    page.locator("#start-run").click()
    expect(page).to_have_url(f"http://reprobe.test/app/runs/{RUN_ID}")
    assert len(surface.state.uploads) == 1
    headers, body = surface.state.uploads[0]
    assert headers["content-type"].startswith("multipart/form-data;")
    assert b'name="target_url"' in body
    assert b"https://shop.example.test/cart" in body
    assert b'filename="cart.jpg"' in body
    assert b'filename="recording.webm"' in body
    assert b'name="steps_text"\r\n\r\n\r\n' in body


def test_live_reading_phase_and_sources_survive_browser_progress(surface):
    page = surface.page
    surface.state.run.update(status="reading_evidence", repro_brief=None, evidence_frames=[])
    surface.state.frame = False
    page.goto(f"http://reprobe.test/app/runs/{RUN_ID}")
    expect(page.locator("#run-status")).to_have_text("Reading evidence")
    expect(page.locator("#screen-waiting")).to_contain_text("before starting the browser")
    capture(surface, "live-reading")
    send_event(page, "evidence.ready", {"brief": BRIEF}, 1)
    send_event(page, "run.status", {"status": "running"}, 2)
    send_event(page, "task.todos", {"todos": [{"content": "Navigate to the cart", "status": "in_progress"}]}, 3)
    expect(page.locator("#plan")).to_contain_text("screenshot 2")
    expect(page.locator("#plan")).to_contain_text("video 00:07")
    expect(page.locator("#execution-plan")).to_contain_text("Navigate to the cart")
    page.locator("#plan .plan-item").nth(2).click()
    expect(page.locator("#step-detail")).to_contain_text("Remove the bottle · video 00:07")
    capture(surface, "live-plan")


def test_report_shows_planned_assertion_reported_values_unknowns_and_frames(surface):
    page = surface.page
    page.goto(f"http://reprobe.test/app/reports/{RUN_ID}")
    expect(page.locator("#report-brief")).to_be_visible()
    expect(page.locator("#report-steps li")).to_have_count(4)
    expect(page.locator("#report-steps")).to_contain_text("video 00:07")
    expect(page.locator("#report-actual")).to_have_text("$42.00")
    expect(page.get_by_text("User-reported actual", exact=True)).to_be_visible()
    expect(page.locator("#assertion-check")).to_have_text(BRIEF["assertion"]["check"])
    expect(page.locator("#assertion-look-in")).to_have_text("Network")
    expect(page.locator("#report-unknowns")).to_contain_text("whether the user is signed in")
    expect(page.locator("#key-frames img")).to_have_count(2)
    page.locator("#key-frames img").last.scroll_into_view_if_needed()
    page.wait_for_function("[...document.querySelectorAll('#key-frames img')].every(img => img.complete && img.naturalWidth > 0)")
    capture(surface, "report-evidence")


def test_failed_analysis_has_a_clear_state_on_reopening(surface):
    page = surface.page
    surface.state.run.update(status="failed", error="Couldn't read the evidence. Choose a readable file.", repro_brief=None, evidence_frames=[])
    surface.state.frame = False
    page.goto(f"http://reprobe.test/app/runs/{RUN_ID}")
    expect(page.locator("#run-status")).to_have_text("Failed")
    expect(page.locator("#screen-waiting")).to_contain_text("Check your files and steps")
    expect(page.locator("#run-message")).to_contain_text("Choose a readable file")
    expect(page.locator("#cancel-run")).to_be_hidden()
    expect(page.locator("#view-report")).to_be_visible()
    capture(surface, "live-evidence-error")


def test_verdict_updates_live_and_hides_the_step_for_not_reproduced(surface):
    page = surface.page
    surface.state.run["status"] = "running"
    page.goto(f"http://reprobe.test/app/runs/{RUN_ID}")
    page.wait_for_function("Boolean(window.testRunStream)")
    verdict = {"verdict": "reproduced", "expected": "$30", "observed": "$42",
               "step_number": 3, "reason": "The total stayed at $42."}
    send_event(page, "reproduction.verdict", verdict, 1)
    panel = page.locator("#verdict")
    expect(panel).to_contain_text("Remove the bottle")
    expect(panel.locator(".bad")).to_have_text("$42")
    verdict.update(verdict="not_reproduced", observed="$30", reason="The total updated.")
    send_event(page, "reproduction.verdict", verdict, 2)
    expect(panel.locator("h2")).to_have_text("Not reproduced")
    expect(panel).not_to_contain_text("Step 3")
    expect(panel.locator(".bad")).to_have_count(0)
    send_event(page, "run.status", {"status": "timed_out", "verdict": None}, 3)
    expect(panel).to_be_hidden()
    expect(page.locator("#run-status")).to_have_text("Timed out")


def test_report_plays_the_first_recording_and_links_every_tab(surface, recorded_tab):
    surface.state.video = recorded_tab
    surface.state.run.update(
        verdict=dict(verdict="reproduced", expected="$30", observed="$42", step_number=3,
                     reason="The bottle disappeared but its price remained in the total."),
        recordings=["first.webm", "second.webm"],
    )
    page = surface.page
    page.goto(f"http://reprobe.test/app/reports/{RUN_ID}")
    panel = page.locator("#verdict")
    expect(panel.locator("h2")).to_have_text("Reproduced")
    expect(panel).to_contain_text("Step 3")
    expect(panel).to_contain_text("Remove the bottle")
    expect(panel).to_contain_text(surface.state.run["verdict"]["reason"])
    expect(panel.locator(".bad")).to_have_text("$42")
    expect(panel.get_by_text("$30", exact=True)).to_be_visible()
    video = page.locator("#recording-player")
    expect(video).to_be_visible()
    page.wait_for_function("document.querySelector('video').videoWidth > 0")
    assert video.evaluate("v => v.controls && v.currentSrc.endsWith('/recordings/1.webm')")
    video.evaluate("async v => { v.muted = true; await v.play(); }")
    page.wait_for_function("document.querySelector('video').currentTime > 0")
    links = page.locator("#recording-downloads a")
    expect(links).to_have_count(2)
    for i, link in enumerate(links.all(), start=1):
        expect(link).to_have_text(f"WebM video · tab {i}")
        expect(link).to_have_attribute("download", f"recording-{i}.webm")
        expect(link).to_have_attribute("href", f"/api/runs/{RUN_ID}/recordings/{i}.webm")
    capture(surface, "report-verdict")
    surface.state.run["verdict"].update(verdict="not_reproduced", observed="$30")
    page.reload()
    expect(panel.locator("h2")).to_have_text("Not reproduced")
    expect(panel).not_to_contain_text("Step 3")
    expect(panel.locator(".bad")).to_have_count(0)
