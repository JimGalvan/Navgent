"""Verify report navigation and result history using the public response shapes."""

import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

STATIC = Path(__file__).resolve().parents[1] / "server" / "static"
CAPTURES = Path(__file__).resolve().parents[1] / ".cache" / "report-workspace"


def saved_run(number, result="reproduced", title="Selecting an item opens the wrong product", **inputs):
    return {
        "id": f"00000000-0000-4000-8000-{number:012d}",
        "task": json.dumps({"title": title, "url": "https://store.example.test/products", "steps": "Select an item", **inputs}),
        "status": "succeeded", "created_at": f"2026-11-{number:02d}T12:00:00Z",
        "updated_at": f"2026-11-{number:02d}T12:01:00Z",
        "verdict": {"verdict": result, "expected": "Selected product", "observed": "Different product",
                    "step_number": 2, "reason": "The details page showed a different product."},
        "repro_brief": {"steps": [{"instruction": "Open the catalog", "source": "written step 1"},
                                  {"instruction": "Select an item", "source": "written step 2"}],
                        "assertion": {"check": "Compare the selected product with the details page", "look_in": "page",
                                      "expected": "Selected product", "reported_actual": "Reported wrong item"}, "unknowns": []},
        "recordings": [], "evidence_frames": [], "final_output": "Observed a different product.",
    }


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture(params=[1440, 390], ids=["desktop", "mobile"])
def surface(browser, request):
    context = browser.new_context(viewport={"width": request.param, "height": 1000})
    page = context.new_page()
    state = SimpleNamespace(page=page, runs=[saved_run(7), saved_run(6, "not_reproduced"), saved_run(5)],
                            events=[], posts=[], post_bodies=[], fail_rerun=False, fail_list=False, errors=[], width=request.param)
    page.on("pageerror", lambda error: state.errors.append(str(error)))

    def handle(route):
        path = urlsplit(route.request.url).path
        if path == "/api/auth/me":
            route.fulfill(json={"email": "reports@example.test"})
        elif path == "/api/runs":
            route.fulfill(status=503 if state.fail_list else 200,
                          json={"detail": "Reports are unavailable. Reload to try again."} if state.fail_list else {"runs": state.runs})
        elif path.endswith("/rerun"):
            state.posts.append(path)
            state.post_bodies.append(route.request.post_data_json if route.request.post_data else None)
            route.fulfill(status=409 if state.fail_rerun else 202,
                          json={"detail": "Run capacity reached. Try again shortly."} if state.fail_rerun else {"run": {"id": "next-run"}})
        elif path.endswith("/events"):
            route.fulfill(json=state.events)
        elif path.endswith("screen.jpg"):
            route.fulfill(status=204)
        elif path.startswith("/api/runs/"):
            for run in state.runs:
                if run["id"] == path.split("/")[-1]:
                    route.fulfill(json={"run": run, "screen_url": f"/api/runs/{run['id']}/screen.jpg"})
                    return
            route.fulfill(status=404, json={"detail": "Run not found"})
        elif path.startswith("/static/"):
            route.fulfill(path=STATIC / path.removeprefix("/static/"))
        elif path == "/app/reports":
            route.fulfill(path=STATIC / "reports.html")
        elif path.startswith("/app/reports/"):
            route.fulfill(path=STATIC / "report.html")
        else:
            route.fulfill(body="Live viewer")

    page.route("http://reprobe.test/**", handle)
    yield state
    context.close()
    assert state.errors == []


def capture(surface, name):
    page = surface.page
    page.evaluate("document.fonts.ready")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    CAPTURES.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=CAPTURES / f"{name}-{surface.width}.png", full_page=True)


def test_groups_runs_by_task_and_filters_latest_result(surface):
    surface.runs.extend([saved_run(4, "not_reproduced", title="Discount total is stale"),
                         saved_run(3, title="Selecting an item opens the wrong product", steps="Choose a different category")])
    running = saved_run(8, title="Upload does not finish")
    running.update(status="running", verdict=None)
    surface.runs.append(running)
    surface.page.goto("http://reprobe.test/app/reports")
    page = surface.page
    expect(page.locator(".bug-row")).to_have_count(4)
    expect(page.locator("#reports-count")).to_have_text("4 bugs · 6 recent runs")
    expect(page.locator(".bug-row").first).to_contain_text("Running")
    history = page.locator(".bug-row").nth(1)
    expect(history.locator(".run-marker")).to_have_count(3)
    expect(history.locator(".run-marker").first).to_have_attribute("href", f"/app/reports/{saved_run(5)['id']}")
    expect(history.locator(".run-marker").last).to_have_attribute("href", f"/app/reports/{saved_run(7)['id']}")
    capture(surface, "reports")
    page.get_by_role("button", name="Not reproduced 1", exact=True).click()
    expect(page.locator(".bug-row")).to_have_count(1)
    expect(page.locator(".bug-row")).to_contain_text("Discount total is stale")
    page.get_by_role("button", name="Reproduced 2", exact=True).click()
    expect(page.locator(".bug-row")).to_have_count(2)
    expect(page.get_by_role("button", name="Reproduced 2", exact=True)).to_have_attribute("aria-pressed", "true")
    page.locator(".bug-identity a").first.click()
    expect(page.locator("#report-title")).to_have_text("Selecting an item opens the wrong product")


def test_list_empty_error_and_rerun_retry(surface):
    page = surface.page
    surface.runs = []
    page.goto("http://reprobe.test/app/reports")
    expect(page.locator("#history")).to_contain_text("No reproductions yet")
    page.get_by_role("button", name="Reproduced 0", exact=True).click()
    expect(page.locator("#history")).to_contain_text("No reproductions yet")
    surface.fail_list = True
    page.reload()
    expect(page.locator("#reports-count")).to_contain_text("could not be loaded")
    surface.fail_list = False
    surface.runs = [saved_run(7)]
    surface.fail_rerun = True
    page.reload()
    rerun = page.get_by_role("button", name="Run again:")
    rerun.click()
    expect(page.locator("#history-message")).to_contain_text("Run capacity reached")
    expect(rerun).to_be_enabled()
    surface.fail_rerun = False
    rerun.click()
    expect(page).to_have_url("http://reprobe.test/app/runs/next-run")
    assert len(surface.posts) == 2


def test_report_verdict_checks_history_and_disclosures(surface):
    surface.events = [{"sequence": 1, "event_type": "browser.action.completed", "created_at": "2026-11-07T12:00:30Z",
                       "payload": {"action": "click", "target": "Product", "brief_step": 2}}]
    run = surface.runs[0]
    page = surface.page
    page.goto(f"http://reprobe.test/app/reports/{run['id']}")
    expect(page.locator("#run-status")).to_have_text("Reproduced")
    expect(page.locator("#run-duration")).to_have_text("1m 00s")
    expect(page.locator("#run-host")).to_have_text("store.example.test")
    expect(page.locator("#bug-history a")).to_have_count(3)
    expect(page.locator(".checks-table")).to_contain_text("Different product")
    expect(page.locator(".checks-table")).not_to_contain_text("Reported wrong item")
    expect(page.locator(".report-step")).to_have_count(2)
    expect(page.locator('.report-step[data-step="1"]')).to_contain_text("No actions recorded")
    expect(page.locator('.report-step[data-step="2"]')).to_have_attribute("open", "")
    expect(page.locator("#evidence")).to_contain_text("No browser frame was saved")
    expect(page.locator("#proof-video")).to_be_disabled()
    expect(page.locator("#report-brief")).not_to_have_attribute("open", "")
    page.locator("#comparison-section summary").click()
    expect(page.locator("#report-actual")).to_have_text("Reported wrong item")
    page.locator("#report-brief summary").click()
    expect(page.locator("#report-steps li")).to_have_count(2)
    expect(page.locator("#unknown-count")).to_have_text("0 unknowns")
    capture(surface, "report")


def test_failed_and_unverified_runs_keep_execution_separate(surface):
    run = surface.runs[0]
    run.update(status="failed", verdict=None, error="Could not open the target", repro_brief=None)
    page = surface.page
    page.goto(f"http://reprobe.test/app/reports/{run['id']}")
    expect(page.locator("#run-status")).to_have_text("Failed")
    expect(page.locator("#verdict")).to_contain_text("No verification check")
    expect(page.locator("#action-log")).to_contain_text("No steps or browser actions")
    capture(surface, "failed-report")
    run.update(status="succeeded", verdict={"verdict": "inconclusive", "expected": "", "observed": "", "reason": "No verdict reported", "step_number": None})
    page.reload()
    expect(page.locator("#run-status")).to_have_text("Inconclusive")
    expect(page.locator("#verdict")).to_contain_text("No observation recorded")


def test_environment_rerun_retains_inputs_and_recovers_from_capacity_error(surface):
    run = surface.runs[0]
    run["bug_report"] = {"target_url": "https://store.example.test/products"}
    page = surface.page
    page.goto(f"http://reprobe.test/app/reports/{run['id']}")
    trigger = page.get_by_role("button", name="Run on another URL", exact=True)
    trigger.click()
    expect(page.locator("#rerun-url")).to_be_focused()
    expect(page.locator("#rerun-url")).to_have_value(run["bug_report"]["target_url"])
    page.locator("#rerun-url").fill("https://fixed.example.test/products")
    surface.fail_rerun = True
    page.locator("#rerun-submit").click()
    expect(page.locator("#rerun-message")).to_contain_text("Run capacity reached")
    expect(page.locator("#rerun-submit")).to_be_enabled()
    expect(page.locator("#rerun-url")).to_have_value("https://fixed.example.test/products")
    capture(surface, "environment-rerun")
    page.locator("#rerun-cancel").click()
    expect(page.locator("#rerun-form")).to_be_hidden()
    expect(trigger).to_be_focused()
    trigger.click()
    surface.fail_rerun = False
    page.locator("#rerun-submit").click()
    expect(page).to_have_url("http://reprobe.test/app/runs/next-run")
    assert surface.post_bodies == [{"target_url": "https://fixed.example.test/products"}] * 2


def test_one_bug_spans_multiple_environment_urls(surface):
    for index, run in enumerate(surface.runs):
        run["bug_id"] = "same-bug"
        task = json.loads(run["task"])
        task["url"] = f"https://build-{index}.example.test/products"
        run["task"] = json.dumps(task)
    page = surface.page
    page.goto("http://reprobe.test/app/reports")
    expect(page.locator(".bug-row")).to_have_count(1)
    expect(page.locator("#reports-count")).to_have_text("1 bug · 3 recent runs")
    page.locator(".bug-identity a").click()
    expect(page.locator("#bug-history a")).to_have_count(3)
    expect(page.locator("#bug-history")).to_contain_text("build-0.example.test")
    expect(page.locator("#bug-history")).to_contain_text("build-2.example.test")


def test_report_header_stays_compact_as_history_grows(surface):
    title = "Open SauceDemo in a fresh session."
    surface.runs = [saved_run(number, "reproduced" if number == 8 else "inconclusive", title=title,
                              url="https://www.saucedemo.com") for number in [8, 7, 6, 5]]
    run = surface.runs[0]
    run["bug_report"] = {"target_url": "https://www.saucedemo.com"}
    run["verdict"]["reason"] = "The product details page displays the Fleece Jacket and 49.99, while the expected Backpack and 29.99 are not shown."
    page = surface.page
    page.goto(f"http://reprobe.test/app/reports/{run['id']}")
    panel = page.locator("#bug-history-panel")
    summary = page.locator("#bug-history-summary")
    expect(summary).to_have_text("Run history · 4 runs")
    expect(panel).not_to_have_attribute("open", "")
    expect(page.locator("#bug-history a").first).not_to_be_visible()
    expect(page.locator("#change-url")).to_be_visible()
    page.evaluate("document.fonts.ready")
    original_height = page.locator(".report-summary").bounding_box()["height"]
    def proof_position():
        return page.locator(".proof-layout").evaluate("el => el.getBoundingClientRect().top + scrollY")
    proof_top = proof_position()
    assert page.locator("#run-information").bounding_box()["y"] > proof_top
    assert panel.bounding_box()["y"] > proof_top
    expect(page.locator(".report-summary #run-date")).to_have_count(0)
    expect(page.locator("#run-information")).not_to_have_attribute("open", "")
    if surface.width == 1440:
        assert page.locator("#report-title").evaluate("el => parseFloat(getComputedStyle(el).fontSize)") > page.locator("#report-result").evaluate("el => parseFloat(getComputedStyle(el).fontSize)")
    CAPTURES.mkdir(parents=True, exist_ok=True)
    page.locator(".report-summary").screenshot(path=CAPTURES / f"report-header-{surface.width}.png")
    summary.focus()
    page.keyboard.press("Enter")
    expect(page.locator("#bug-history a").first).to_be_visible()
    expect(page.locator('#bug-history a[aria-current="page"]')).to_contain_text("Viewing")
    expect(page.locator("#bug-history")).to_contain_text("https://www.saucedemo.com")
    assert proof_position() == pytest.approx(proof_top, abs=1)
    panel.screenshot(path=CAPTURES / f"report-history-expanded-{surface.width}.png")
    page.keyboard.press("Enter")
    expect(panel).not_to_have_attribute("open", "")
    page.locator("#run-information summary").click()
    expect(page.locator("#run-duration")).to_be_visible()
    expect(page.locator("#run-date")).to_be_visible()
    expect(page.locator("#run-id")).to_be_visible()
    assert proof_position() == pytest.approx(proof_top, abs=1)
    surface.runs.extend(saved_run(number, "inconclusive", title=title, url="https://www.saucedemo.com") for number in range(9, 25))
    page.reload()
    expect(summary).to_have_text("Run history · 20 runs")
    assert page.locator(".report-summary").bounding_box()["height"] == pytest.approx(original_height, abs=2)
    summary.click()
    page.locator("#bug-history a").last.click()
    expect(page).to_have_url(f"http://reprobe.test/app/reports/{surface.runs[3]['id']}")
    expect(summary).to_have_text("Run history · 20 runs")
    expect(panel).not_to_have_attribute("open", "")
    if surface.width == 1440:
        page.set_viewport_size({"width": 1024, "height": 900})
        page.evaluate("window.scrollTo(0, 0)")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.locator(".report-summary").screenshot(path=CAPTURES / "report-header-1024.png")


def test_single_run_omits_history_and_history_failure_is_disclosed(surface):
    surface.runs = [surface.runs[0]]
    page = surface.page
    page.goto(f"http://reprobe.test/app/reports/{surface.runs[0]['id']}")
    expect(page.locator("#bug-history-panel")).to_be_hidden()
    surface.fail_list = True
    page.reload()
    expect(page.locator("#bug-history-summary")).to_have_text("Run history unavailable")
    page.locator("#bug-history-summary").click()
    expect(page.locator("#bug-history")).to_contain_text("Reload to try again")
