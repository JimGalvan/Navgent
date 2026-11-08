"""Run the camera for one Reprobe take in the recording window.

live:   waits for the run to start (or clicks Start with --click-start), logs every change,
        and scrolls to the Sandbox panel when it turns Running and to Form state when the
        times are set, coming back up each time.
report: walks the finished report: verdict, finding frame, checks, sandbox details.

Usage:
  python video/tools/take.py live <events.jsonl> [--click-start]
  python video/tools/take.py report
"""

import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP_URL = "http://127.0.0.1:9333"
END_WORDS = ("Completed", "Failed", "Stopped", "Cancelled", "Timed out")
LIMIT_SECONDS = 720
HOLD_MS = 2600

READ_STATE = """() => {
  const text = id => (document.getElementById(id)?.innerText || "").trim();
  return {
    url: location.pathname,
    status: text("run-status"),
    sandbox: text("sandbox-status"),
    browser_url: text("browser-url"),
    plan_items: document.querySelectorAll("#plan .plan-item").length,
    form_state: text("form-state"),
  };
}"""

SCROLL_TO = """id => {
  const el = document.getElementById(id);
  if (!el) return false;
  const box = el.getBoundingClientRect();
  window.scrollTo({ top: window.scrollY + box.top - innerHeight * 0.35, behavior: "smooth" });
  return true;
}"""

SCROLL_TOP = "() => window.scrollTo({ top: 0, behavior: 'smooth' })"


def connect(playwright):
    browser = playwright.chromium.connect_over_cdp(CDP_URL)
    return browser, browser.contexts[0].pages[0]


def open_sandbox_panel(page) -> None:
    is_open = page.evaluate("() => document.getElementById('sandbox-panel')?.open")
    if not is_open:
        page.locator("#sandbox-panel > summary").click()
    page.mouse.move(1900, 540)


def glance(page, element_id: str, log, started: float, label: str, open_details: bool = False) -> None:
    if page.evaluate(SCROLL_TO, element_id):
        note(log, started, {"camera": f"scroll to {label}"})
        page.wait_for_timeout(900)
        if open_details:
            open_sandbox_panel(page)
            page.evaluate(SCROLL_TO, element_id)
        page.wait_for_timeout(HOLD_MS)
        page.evaluate(SCROLL_TOP)
        note(log, started, {"camera": "scroll back up"})
        page.wait_for_timeout(700)


def note(log, started: float, data: dict) -> None:
    moment = round(time.time() - started, 2)
    log.write(json.dumps({"time": moment, **data}) + "\n")
    log.flush()
    print(f"{moment:6.1f}s {json.dumps(data)[:300]}", flush=True)


def live(log_path: Path, click_start: bool) -> None:
    log = log_path.open("w", encoding="utf-8")
    with sync_playwright() as playwright:
        browser, page = connect(playwright)
        page.mouse.move(1900, 540)
        if click_start:
            page.get_by_role("button", name="Start reproduction").click()
        else:
            print("waiting for Start reproduction to be clicked", flush=True)
            page.wait_for_url("**/app/runs/**", timeout=600_000)
        started = time.time()
        note(log, started, {"event": "run page opened"})

        previous = {}
        looked_at_sandbox = False
        looked_at_form = False
        while time.time() - started < LIMIT_SECONDS:
            try:
                state = page.evaluate(READ_STATE)
            except Exception:
                page.wait_for_timeout(300)
                continue
            changes = {}
            for key, value in state.items():
                if previous.get(key) != value:
                    changes[key] = value
            if changes:
                note(log, started, changes)
            previous = state

            if not looked_at_sandbox and state["sandbox"] == "Running":
                looked_at_sandbox = True
                glance(page, "sandbox-panel", log, started, "sandbox", open_details=True)
            if not looked_at_form and "End time: 2:00 PM" in state["form_state"]:
                looked_at_form = True
                glance(page, "form-state-section", log, started, "form state")

            ended = False
            for word in END_WORDS:
                if state["status"].startswith(word):
                    ended = True
            if ended:
                page.wait_for_timeout(3000)
                note(log, started, {"event": "hold after verdict done"})
                break
            page.wait_for_timeout(250)
        log.close()
        browser.close()


def report() -> None:
    started = time.time()

    def mark(label: str) -> None:
        print(f"{time.time() - started:6.1f}s {label}", flush=True)

    with sync_playwright() as playwright:
        browser, page = connect(playwright)
        page.mouse.move(1900, 540)
        page.get_by_role("link", name="View report").click()
        page.wait_for_load_state("networkidle")
        mark("report open, holding on the verdict")
        page.wait_for_timeout(3500)

        for tab_name in ("Finding frame", "Final frame"):
            tab = page.get_by_text(tab_name, exact=True)
            if tab.count():
                tab.first.click()
                page.mouse.move(1900, 540)
                mark(tab_name.lower())
                page.wait_for_timeout(3500)
                break

        page.evaluate(SCROLL_TO, "verdict")
        mark("checks")
        page.wait_for_timeout(3500)

        if page.locator("#bug-history-panel:not([hidden])").count():
            page.evaluate(SCROLL_TO, "bug-history-panel")
            page.wait_for_timeout(900)
            if not page.evaluate("() => document.getElementById('bug-history-panel').open"):
                page.locator("#bug-history-panel > summary").click()
            page.mouse.move(1900, 540)
            page.evaluate(SCROLL_TO, "bug-history-panel")
            mark("run history")
            page.wait_for_timeout(5000)

        page.evaluate(SCROLL_TO, "sandbox-panel")
        page.wait_for_timeout(900)
        open_sandbox_panel(page)
        page.wait_for_timeout(300)
        page.evaluate(SCROLL_TO, "sandbox-panel")
        mark("sandbox details")
        page.wait_for_timeout(3500)

        page.evaluate(SCROLL_TOP)
        mark("back to top, Run again visible")
        page.wait_for_timeout(2000)
        browser.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["live", "report"])
    parser.add_argument("log", nargs="?")
    parser.add_argument("--click-start", action="store_true")
    args = parser.parse_args()

    if args.command == "live":
        if not args.log:
            raise SystemExit("live needs a log path")
        live(Path(args.log), args.click_start)
    else:
        report()


if __name__ == "__main__":
    main()
