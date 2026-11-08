"""Click Start reproduction in the recording window and log the live run until it ends.

Prints a timestamped line whenever the run status, sandbox status, plan size, form state
or browser URL changes, so the footage can be cut without scrubbing.

Usage: python video/tools/watch_run.py <log.jsonl> [--no-click]
"""

import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP_URL = "http://127.0.0.1:9333"
TERMINAL_WORDS = ("Completed", "Reproduced", "Not reproduced", "Inconclusive", "Failed", "Stopped", "Cancelled", "Timed out")
LIMIT_SECONDS = 720

READ_STATE = """() => {
  const text = id => (document.getElementById(id)?.innerText || "").trim();
  return {
    url: location.pathname,
    status: text("run-status"),
    sandbox: text("sandbox-status"),
    browser_url: text("browser-url"),
    plan_items: document.querySelectorAll("#plan .plan-item").length,
    form_state: text("form-state"),
    elapsed: text("elapsed"),
  };
}"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("log")
    parser.add_argument("--no-click", action="store_true")
    args = parser.parse_args()

    log = Path(args.log).open("w", encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(CDP_URL)
        page = browser.contexts[0].pages[0]
        started = time.time()
        if not args.no_click:
            page.get_by_role("button", name="Start reproduction").click()
            print(f"{0.0:6.1f}s clicked Start reproduction", flush=True)

        previous = {}
        while time.time() - started < LIMIT_SECONDS:
            try:
                state = page.evaluate(READ_STATE)
            except Exception:
                page.wait_for_timeout(500)
                continue
            changes = {}
            for key, value in state.items():
                if key != "elapsed" and previous.get(key) != value:
                    changes[key] = value
            if changes:
                moment = time.time() - started
                log.write(json.dumps({"time": round(moment, 2), "elapsed": state["elapsed"], **changes}) + "\n")
                log.flush()
                print(f"{moment:6.1f}s {json.dumps(changes)[:300]}", flush=True)
            previous = state
            ended = False
            for word in TERMINAL_WORDS:
                if state["status"].startswith(word):
                    ended = True
            if ended and "/runs/" in state["url"]:
                break
            page.wait_for_timeout(500)
        log.close()
        browser.close()


if __name__ == "__main__":
    main()
