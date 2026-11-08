"""Record the recording window's page to MP4 through Chrome's screencast.

Frames arrive only when the page repaints, so each frame keeps its own timestamp
and the MP4 is rebuilt at a constant frame rate from those times.

Usage:
  python video/tools/recorder.py record <out_dir>     (stops when <out_dir>/STOP exists)
  python video/tools/recorder.py build <out_dir> <out.mp4>
"""

import argparse
import base64
import json
import subprocess
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP_URL = "http://127.0.0.1:9333"
FPS = 30


def record(out_dir: Path) -> None:
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    stop_file = out_dir / "STOP"
    if stop_file.exists():
        stop_file.unlink()
    log_path = out_dir / "frames.jsonl"
    log = log_path.open("w", encoding="utf-8")
    count = 0
    started = time.time()

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(CDP_URL)
        page = browser.contexts[0].pages[0]
        session = page.context.new_cdp_session(page)

        def on_frame(event: dict) -> None:
            nonlocal count
            session.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})
            name = f"{count:06d}.jpg"
            (frames_dir / name).write_bytes(base64.b64decode(event["data"]))
            log.write(json.dumps({"file": name, "time": time.time() - started}) + "\n")
            count += 1

        session.on("Page.screencastFrame", on_frame)
        session.send("Page.startScreencast", {
            "format": "jpeg", "quality": 92, "maxWidth": 1920, "maxHeight": 1080, "everyNthFrame": 1,
        })
        print(f"recording to {out_dir}", flush=True)
        while not stop_file.exists():
            page.wait_for_timeout(200)
        session.send("Page.stopScreencast")
        log.write(json.dumps({"file": None, "time": time.time() - started}) + "\n")
        log.close()
        browser.close()
    print(f"stopped after {time.time() - started:.1f}s, {count} frames", flush=True)


def jpeg_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    index = 2
    while index < len(data):
        marker = data[index + 1]
        length = int.from_bytes(data[index + 2:index + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2):
            height = int.from_bytes(data[index + 5:index + 7], "big")
            width = int.from_bytes(data[index + 7:index + 9], "big")
            return width, height
        index += 2 + length
    raise ValueError(f"no frame header in {path}")


def pad_short_frames(frames_dir: Path) -> None:
    """Screencast sometimes sends 1920x1079 frames. Pad them so every frame has the same size."""
    for path in sorted(frames_dir.glob("*.jpg")):
        if jpeg_size(path) == (1920, 1080):
            continue
        padded = path.with_suffix(".pad.jpg")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(path),
             "-vf", "scale=1920:-2:force_original_aspect_ratio=decrease,pad=1920:1080:0:0:color=black", "-q:v", "2", str(padded)],
            check=True,
        )
        padded.replace(path)


def build(out_dir: Path, out_path: Path) -> None:
    pad_short_frames(out_dir / "frames")
    entries = []
    for line in (out_dir / "frames.jsonl").read_text(encoding="utf-8").splitlines():
        entries.append(json.loads(line))

    concat = ""
    for index in range(len(entries) - 1):
        entry = entries[index]
        if entry["file"] is None:
            continue
        duration = entries[index + 1]["time"] - entry["time"]
        concat += f"file 'frames/{entry['file']}'\nduration {duration:.4f}\n"
    last_frame = None
    for entry in entries:
        if entry["file"] is not None:
            last_frame = entry["file"]
    concat += f"file 'frames/{last_frame}'\n"
    list_path = out_dir / "frames.txt"
    list_path.write_text(concat, encoding="utf-8")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(list_path),
            "-fps_mode", "cfr", "-r", str(FPS),
            "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p",
            str(out_path),
        ],
        check=True,
    )
    print(out_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["record", "build"])
    parser.add_argument("out_dir")
    parser.add_argument("out", nargs="?")
    args = parser.parse_args()

    if args.command == "record":
        record(Path(args.out_dir))
    else:
        build(Path(args.out_dir), Path(args.out))


if __name__ == "__main__":
    main()
