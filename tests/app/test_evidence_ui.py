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
FORM_BRIEF = {
    "steps": [
        {"instruction": "Open the checkout form", "source": "written step 1"},
        {"instruction": "Type Demo into First Name", "source": "written step 2"},
        {"instruction": "Type Tester into Last Name", "source": "video 00:07"},
        {"instruction": "Click Continue", "source": "written step 4"},
    ],
    "assertion": {
        "check": "Typing into Last Name leaves First Name unchanged",
        "expected": "First Name: Demo; Last Name: Tester",
        "reported_actual": "First Name: r; Last Name: (empty)",
        "look_in": "page",
    },
    "unknowns": [],
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


def action_event(sequence, phase, action, target, created_at="2026-11-07T12:00:00Z", **payload):
    return dict(sequence=sequence, event_type="browser.action." + phase,
                payload=dict(action=action, target=target, **payload), created_at=created_at)


def typing_events():
    return [
        action_event(1, "started", "type", "First Name", value="Demo", reason="Enter the first name.", brief_step=2),
        action_event(2, "completed", "type", "First Name", value="Demo", reason="Enter the first name.", brief_step=2,
                     fields=["First Name: Demo", "Last Name: (empty)"]),
        action_event(3, "started", "type", "Last Name", value="Tester", reason="Check the last-name defect.", brief_step=3),
        action_event(4, "completed", "type", "Last Name", value="Tester", reason="Check the last-name defect.", brief_step=3,
                     fields=["First Name: r", "Last Name: (empty)"]),
        action_event(5, "completed", "type", "Password", value="", brief_step=3, fields=["First Name: r", "Last Name: (empty)"]),
        action_event(6, "failed", "click", "Continue", reason="Check validation.", brief_step=4, error="Last Name is required"),
    ]


def test_live_replays_action_progress_fields_and_reconnects_without_regressing(surface):
    surface.state.run["status"] = "running"
    surface.state.events = typing_events()[:4]
    page = surface.page
    page.goto(f"http://reprobe.test/app/runs/{RUN_ID}")
    current = page.locator('#plan [aria-current="step"]')
    expect(current).to_contain_text("Remove the bottle")
    expect(page.locator("#plan-title")).to_have_text("Plan · 2 of 4")
    expect(page.locator('#plan [data-status="completed"]')).to_have_count(2)
    expect(page.locator("#activity")).to_contain_text('type "Tester" into Last Name')
    expect(page.locator("#activity")).to_contain_text("Check the last-name defect.")
    expect(page.locator("#form-state")).to_contain_text("First Name: r")
    expect(page.locator("#latest-action")).to_contain_text('type "Tester" into Last Name')
    expect(page.locator("#step-detail")).to_contain_text("Check the last-name defect.")
    page.wait_for_function("Boolean(window.testRunStream)")
    for event in surface.state.events:
        send_event(page, event["event_type"], event["payload"], event["sequence"])
    send_event(page, "browser.action.started", dict(action="click", target="Continue"), 7)
    send_event(page, "browser.action.started", dict(action="click", target="Back", brief_step=1), 8)
    expect(current).to_contain_text("Remove the bottle")
    expect(page.locator("#activity .event-row")).to_have_count(6)
    page.reload()
    expect(current).to_contain_text("Remove the bottle")
    expect(page.locator("#form-state")).to_contain_text("First Name: r")
    expect(page.locator("#browser-screen")).to_be_visible()
    expect(page.locator("#frame-strip img")).to_have_count(1)
    capture(surface, "live-browser")


def test_plan_uses_one_timeline_checkmarks_recorded_durations_and_forward_steps(surface):
    page = surface.page
    surface.state.run["status"] = "running"
    surface.state.events = [
        action_event(1, "started", "click", "Cart", brief_step=1, created_at="2026-11-07T12:00:00Z"),
        action_event(2, "completed", "click", "Cart", brief_step=1, created_at="2026-11-07T12:00:08.200Z"),
        action_event(3, "started", "type", "Coupon", value="SAVE50", reason="Apply the reported discount.", brief_step=2,
                     created_at="2026-11-07T12:00:08.300Z"),
    ]
    page.goto(f"http://reprobe.test/app/runs/{RUN_ID}")
    expect(page.locator("#plan .plan-item")).to_have_count(4)
    expect(page.locator("#execution-plan")).to_have_count(0)
    first = page.locator("#plan .plan-item").first
    expect(first.locator(".plan-marker svg")).to_have_count(1)
    expect(first.locator(".plan-marker")).to_have_text("")
    expect(first.locator(".plan-time")).to_have_text("8.2s")
    current = page.locator('#plan [aria-current="step"]')
    expect(current.locator(".plan-time")).to_have_text("now")
    assert current.evaluate("element => getComputedStyle(element).borderLeftWidth") == "2px"
    expect(page.locator("#step-detail")).to_contain_text("Apply the reported discount.")
    expect(page.locator("#step-detail")).to_contain_text("Source: screenshot 2")
    page.wait_for_function("Boolean(window.testRunStream)")
    send_event(page, "task.todos", {"todos": [{"content": "A separate task list", "status": "in_progress"}]}, 4)
    expect(page.locator("#plan .plan-item")).to_have_count(4)
    expect(page.locator("#plan")).not_to_contain_text("A separate task list")
    first.focus()
    send_event(page, "browser.action.completed", dict(action="type", target="Coupon", brief_step=2, fields=[]), 5)
    expect(first).to_be_focused()
    capture(surface, "single-plan-timeline")
    page.reload()
    expect(first.locator(".plan-time")).to_have_text("8.2s")
    expect(current).to_contain_text("Apply SAVE50")


def test_plan_rebuilds_the_highest_step_when_actions_precede_the_brief(surface):
    page = surface.page
    surface.state.run.update(status="running", repro_brief=None)
    surface.state.events = [
        action_event(1, "started", "type", "Last Name", brief_step=3, reason="Enter the reported last name."),
        action_event(2, "completed", "click", "Back", brief_step=1),
        action_event(3, "completed", "click", "Continue"),
    ]
    page.goto(f"http://reprobe.test/app/runs/{RUN_ID}")
    page.wait_for_function("Boolean(window.testRunStream)")
    ready = dict(sequence=4, event_type="evidence.ready", payload={"brief": BRIEF}, created_at="2026-11-07T12:00:00Z")
    send_event(page, ready["event_type"], ready["payload"], ready["sequence"])
    expect(page.locator('#plan [aria-current="step"]')).to_contain_text("Remove the bottle")
    expect(page.locator('#plan [data-status="completed"]')).to_have_count(2)
    surface.state.events.append(ready)
    page.reload()
    expect(page.locator('#plan [aria-current="step"]')).to_contain_text("Remove the bottle")
    expect(page.locator("#step-detail")).to_contain_text("Enter the reported last name.")


@pytest.mark.parametrize("status", ["running", "succeeded"])
def test_report_pairs_input_snapshots_and_splits_observed_quotes(surface, status):
    surface.state.run["status"] = status
    surface.state.run["repro_brief"] = FORM_BRIEF
    surface.state.run["task"] = json.dumps({
        "title": "Typing Last Name changes First Name", "url": "https://www.saucedemo.com/checkout-step-one.html",
    })
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
    expect(rows.nth(1).locator("xpath=ancestor::details/summary")).to_contain_text("Type Tester into Last Name")
    expect(rows.nth(1)).to_contain_text("Check the last-name defect.")
    groups = page.locator("#action-log .action-group")
    expect(groups).to_have_count(3)
    expect(groups.nth(0).locator("xpath=ancestor::details/summary")).to_contain_text("Type Demo into First Name")
    expect(groups.nth(1).locator("xpath=ancestor::details/summary")).to_contain_text("Type Tester into Last Name")
    expect(groups.nth(1).locator(".action-row")).to_have_count(2)
    expect(groups.nth(2).locator("xpath=ancestor::details/summary")).to_contain_text("Click Continue")
    expect(rows.nth(2).locator(".action-title")).to_have_text("type into Password")
    expect(rows.nth(3)).to_contain_text("Failed")
    expect(rows.nth(3)).to_contain_text("Last Name is required")
    expect(page.locator(".observed-quote")).to_have_count(3)
    expect(page.locator(".observed-quote").first).to_have_text("First Name: r")
    capture(surface, "report-input-changes")
    page.reload()
    expect(page.locator("#action-log .action-row")).to_have_count(4)
    expect(page.locator("#action-log .action-row").nth(1).locator(".field-changed")).to_have_count(2)


def test_input_comparisons_use_only_the_previous_completed_input_snapshot(surface):
    surface.state.events = [
        action_event(1, "completed", "fill", "First Name", fields=["First Name: Demo"]),
        action_event(2, "completed", "click", "Continue"),
        action_event(3, "failed", "type", "Last Name", error="Field not found"),
        action_event(4, "completed", "select", "Country", fields=["First Name: Demo", "Country: Canada"]),
        action_event(5, "completed", "type", "Old field"),
        action_event(6, "completed", "type", "Last Name", fields=["First Name: r"]),
    ]
    page = surface.page
    page.goto(f"http://reprobe.test/app/reports/{RUN_ID}")
    rows = page.locator("#action-log .action-row")
    expect(rows.nth(3).locator(".field-snapshot").first).to_contain_text("First Name: Demo")
    expect(rows.nth(3).locator(".field-snapshot").last.locator(".field-changed")).to_have_count(1)
    expect(rows.nth(5).locator(".field-snapshot").first).to_contain_text("No field values captured")


def test_old_actions_and_empty_password_values_render_without_fallback(surface):
    surface.state.events = [
        action_event(1, "started", "type", "Password", value=""),
        action_event(2, "completed", "type", "Password", value=""),
        action_event(3, "completed", "click", "Continue"),
    ]
    page = surface.page
    surface.state.run["status"] = "running"
    page.goto(f"http://reprobe.test/app/runs/{RUN_ID}")
    expect(page.locator("#activity")).to_contain_text("type into Password")
    expect(page.locator("#activity")).not_to_contain_text('""')
    expect(page.locator("#activity")).not_to_contain_text("undefined")
    expect(page.locator("body")).not_to_contain_text("secret_sauce")
    surface.state.run["status"] = "succeeded"
    page.goto(f"http://reprobe.test/app/reports/{RUN_ID}")
    expect(page.locator("#action-log .action-row")).to_have_count(2)
    expect(page.locator("#action-log .action-title").first).to_have_text("type into Password")
    expect(page.locator("#action-log .action-title").last).to_have_text("click · Continue")
    expect(page.locator("body")).not_to_contain_text("secret_sauce")


def test_media_only_submission_sends_all_selected_evidence(surface):
    page = surface.page
    page.goto("http://reprobe.test/app")
    page.locator("#target-url").fill("https://shop.example.test/cart")
    page.locator("#expected").fill("The total should drop to $30.00")
    page.locator("#actual").fill("The total stays at $42.00")
    page.locator("#start-run").click()
    expect(page.locator("#evidence-help")).to_contain_text("Provide at least one")
    expect(page.locator("#evidence-error")).to_contain_text("Add written steps")
    expect(page.locator("#steps")).to_be_focused()
    expect(page.locator("#steps")).to_have_attribute("aria-invalid", "true")
    assert surface.state.uploads == []
    page.locator("#video-files").set_input_files({"name": "recording.webm", "mimeType": "video/webm", "buffer": b"video upload fixture"})
    page.locator("#shot-files").set_input_files({"name": "cart.jpg", "mimeType": "image/jpeg", "buffer": evidence_image()})
    expect(page.locator("#media-note")).to_contain_text("1 screenshot and 1 recording")
    expect(page.locator("#evidence-error")).to_be_hidden()
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


def test_rejected_upload_names_the_file_and_keeps_accepted_evidence(surface):
    page = surface.page
    page.goto("http://reprobe.test/app")
    page.locator("#shot-files").set_input_files([
        {"name": "cart.jpg", "mimeType": "image/jpeg", "buffer": evidence_image()},
        {"name": "notes.pdf", "mimeType": "application/pdf", "buffer": b"not an image"},
    ])
    expect(page.locator("#evidence-error")).to_contain_text("notes.pdf: unsupported format")
    expect(page.locator("#file-list")).to_contain_text("cart.jpg")
    expect(page.locator("#file-list")).not_to_contain_text("notes.pdf")
    capture(surface, "evidence-rejection")


def test_live_sandbox_events_update_status_and_label_blocked_requests(surface):
    surface.state.run["status"] = "running"
    page = surface.page
    page.goto(f"http://reprobe.test/app/runs/{RUN_ID}")
    page.wait_for_function("window.testRunStream !== undefined")
    send_event(page, "sandbox.starting", {"allowed_hosts": ["shop.example.test"]}, 40)
    expect(page.locator("#sandbox-status")).to_have_text("Starting")
    send_event(page, "sandbox.started", {"runtime": "gVisor (runsc)", "allowed_hosts": ["shop.example.test"],
        "limits": {"cpus": 1.5, "memory_mb": 1536, "pids": 256, "time_limit_seconds": 900}}, 41)
    expect(page.locator("#sandbox-status")).to_have_text("Running")
    send_event(page, "sandbox.request_blocked", {"host": "other.example.test", "brief_step": 2}, 42)
    expect(page.locator("#activity")).to_contain_text("Blocked by sandbox: other.example.test")
    expect(page.locator("#activity")).to_contain_text("Step 2")
    expect(page.locator("#sandbox-status")).to_have_text("Running")
    send_event(page, "sandbox.destroyed", {"duration_seconds": 21}, 43)
    expect(page.locator("#sandbox-status")).to_have_text("Destroyed")
    page.locator("#sandbox-panel summary").click()
    expect(page.locator("#sandbox-values")).to_contain_text("gVisor (runsc)")
    expect(page.locator("#sandbox-values")).to_contain_text("shop.example.test")
    send_event(page, "run.status", {"status": "succeeded", "verdict": None}, 44)
    capture(surface, "sandbox-live")


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
    expect(page.locator("#plan .plan-item")).to_have_count(4)
    expect(page.locator("#execution-plan")).to_have_count(0)
    expect(page.locator("#plan")).not_to_contain_text("screenshot 2")
    page.locator("#plan .plan-item").nth(2).click()
    expect(page.locator("#step-detail")).to_contain_text("Remove the bottle")
    expect(page.locator("#step-detail")).to_contain_text("Source: video 00:07")
    capture(surface, "live-plan")


def test_report_shows_planned_assertion_reported_values_unknowns_and_frames(surface):
    page = surface.page
    page.goto(f"http://reprobe.test/app/reports/{RUN_ID}")
    expect(page.locator("#report-brief")).to_be_visible()
    expect(page.locator("#report-steps li")).to_have_count(4)
    expect(page.locator("#report-steps")).to_contain_text("video 00:07")
    expect(page.locator("#report-actual")).to_have_text("$42.00")
    page.locator("#comparison-section summary").click()
    page.locator("#report-brief summary").click()
    page.locator("#key-frames-section summary").click()
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
    expect(page.locator("#run-status")).to_have_text("Reproduced")
    expect(panel.locator("h2")).to_have_text("Checks")
    expect(panel).to_contain_text("Step 3")
    expect(panel).to_contain_text(surface.state.run["verdict"]["reason"])
    expect(panel.locator(".bad")).to_have_text("$42")
    expect(panel.get_by_text("$30", exact=True)).to_be_visible()
    page.locator("#proof-frame").click()
    expect(page.locator("#evidence-section")).to_be_visible()
    expect(page.locator("#recording-section")).to_be_hidden()
    page.locator("#proof-frame").press("ArrowLeft")
    expect(page.locator("#proof-video")).to_be_focused()
    expect(page.locator("#proof-video")).to_have_attribute("aria-selected", "true")
    page.locator("#proof-video").press("End")
    expect(page.locator("#proof-frame")).to_be_focused()
    page.locator("#proof-frame").press("Home")
    expect(page.locator("#proof-video")).to_be_focused()
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
    expect(page.locator("#run-status")).to_have_text("Not reproduced")
    expect(panel).not_to_contain_text("Step 3")
    expect(panel.locator(".bad")).to_have_count(0)
