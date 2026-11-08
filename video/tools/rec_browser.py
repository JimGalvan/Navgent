"""Open a Chrome app window for recording, controllable over CDP on 127.0.0.1.

The window renders at device scale 1, so the page can be sized to exactly 1920x1080
even on a scaled display. The profile lives outside the repo.

Usage:
  python video/tools/rec_browser.py open --profile <dir> [--url https://...]
  python video/tools/rec_browser.py size
"""

import argparse
import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CDP_PORT = 9333
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"
DEFAULT_URL = "https://144-202-90-160.sslip.io/"
WIDTH = 1920
HEIGHT = 1080


def open_window(profile: Path, url: str) -> None:
    profile.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            CHROME,
            f"--user-data-dir={profile}",
            f"--remote-debugging-port={CDP_PORT}",
            "--remote-debugging-address=127.0.0.1",
            "--force-device-scale-factor=1",
            "--window-position=0,0",
            f"--window-size={WIDTH + 16},{HEIGHT + 40}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate",
            "--hide-crash-restore-bubble",
            f"--app={url}",
        ],
        creationflags=subprocess.DETACHED_PROCESS,
    )
    print(f"Chrome window opened on {url}")


def size_page() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(CDP_URL)
        page = browser.contexts[0].pages[0]
        session = page.context.new_cdp_session(page)
        window = session.send("Browser.getWindowForTarget")
        state = session.send("Browser.getWindowBounds", {"windowId": window["windowId"]})["bounds"]["windowState"]
        if state != "normal":
            session.send("Browser.setWindowBounds", {"windowId": window["windowId"], "bounds": {"windowState": "normal"}})
            page.wait_for_timeout(500)
        session.send("Browser.setWindowBounds", {"windowId": window["windowId"], "bounds": {"windowState": "fullscreen"}})
        page.wait_for_timeout(800)
        for attempt in range(3):
            inner = page.evaluate("[window.innerWidth, window.innerHeight, window.devicePixelRatio]")
            if inner[0] == WIDTH and inner[1] == HEIGHT:
                break
            bounds = session.send("Browser.getWindowBounds", {"windowId": window["windowId"]})["bounds"]
            session.send("Browser.setWindowBounds", {
                "windowId": window["windowId"],
                "bounds": {
                    "width": bounds["width"] + WIDTH - inner[0],
                    "height": bounds["height"] + HEIGHT - inner[1],
                },
            })
            page.wait_for_timeout(400)
        inner = page.evaluate("[window.innerWidth, window.innerHeight, window.devicePixelRatio]")
        print(f"page is {inner[0]}x{inner[1]} at device scale {inner[2]}")
        browser.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["open", "size"])
    parser.add_argument("--profile", default="")
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args()

    if args.command == "open":
        if not args.profile:
            raise SystemExit("--profile is required, and it must be outside the repo")
        open_window(Path(args.profile), args.url)
    else:
        size_page()


if __name__ == "__main__":
    main()
