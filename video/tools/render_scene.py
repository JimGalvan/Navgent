"""Render a seekable scene page to MP4 with its narration clips.

The page must define window.seek(t), window.DURATION and window.AUDIO_CUES ([{id, at}]).

Usage:
  python video/tools/render_scene.py video/part-1/scene.html video/exports/part-1-draft.mp4 --voice video/voice/part-1
  python video/tools/render_scene.py video/part-1/scene.html video/stills/part-1 --stills 2,12,23,31,40
"""

import argparse
import subprocess
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

WIDTH = 1920
HEIGHT = 1080


def page_url(html: Path, query: str) -> str:
    url = html.resolve().as_uri()
    if query:
        url += "?" + query
    return url


def open_page(playwright, html: Path, query: str):
    browser = playwright.chromium.launch()
    page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
    page.goto(page_url(html, query))
    page.wait_for_load_state("networkidle")
    return browser, page


def save_stills(html: Path, out_dir: Path, times: list[float], query: str, transparent: bool, name: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser, page = open_page(playwright, html, query)
        for t in times:
            page.evaluate(f"seek({t})")
            path = out_dir / f"t{t:05.1f}.png"
            if name:
                path = out_dir / f"{name}.png"
            page.screenshot(path=str(path), omit_background=transparent)
            print(path)
        browser.close()


def render_frames(html: Path, video_path: Path, fps: int, query: str) -> tuple[float, list]:
    encoder = subprocess.Popen(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "image2pipe", "-framerate", str(fps), "-i", "-",
            "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p",
            str(video_path),
        ],
        stdin=subprocess.PIPE,
    )
    with sync_playwright() as playwright:
        browser, page = open_page(playwright, html, query)
        duration = page.evaluate("DURATION")
        cues = page.evaluate("AUDIO_CUES")
        frame_count = int(duration * fps)
        for frame in range(frame_count):
            page.evaluate(f"seek({frame / fps})")
            encoder.stdin.write(page.screenshot(type="png"))
            if frame % (fps * 5) == 0:
                print(f"  {frame / fps:5.1f}s / {duration}s", flush=True)
        browser.close()
    encoder.stdin.close()
    encoder.wait()
    return duration, cues


def mux_voice(video_path: Path, voice_dir: Path, cues: list, duration: float, out_path: Path) -> None:
    command = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video_path)]
    filters = []
    labels = ""
    for index, cue in enumerate(cues, start=1):
        command += ["-i", str(voice_dir / f"{cue['id']}.mp3")]
        delay_ms = int(cue["at"] * 1000)
        filters.append(f"[{index}:a]adelay={delay_ms}|{delay_ms}[v{index}]")
        labels += f"[v{index}]"
    filters.append(f"{labels}amix=inputs={len(cues)}:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11,apad[voice]")
    command += [
        "-filter_complex", ";".join(filters),
        "-map", "0:v", "-map", "[voice]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-t", str(duration),
        str(out_path),
    ]
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("html")
    parser.add_argument("out")
    parser.add_argument("--voice", help="folder with one mp3 per cue id")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--query", default="", help="page query string, e.g. tue=2026-11-17&filed=2026-11-15&draft=0")
    parser.add_argument("--stills", help="comma-separated times to save as PNGs instead of rendering video")
    parser.add_argument("--transparent", action="store_true", help="keep the page background transparent in stills")
    parser.add_argument("--name", default="", help="file name for a single still, without .png")
    args = parser.parse_args()

    html = Path(args.html)
    out = Path(args.out)

    if args.stills:
        times = []
        for value in args.stills.split(","):
            times.append(float(value))
        save_stills(html, out, times, args.query, args.transparent, args.name)
        return

    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        silent = Path(temp) / "silent.mp4"
        duration, cues = render_frames(html, silent, args.fps, args.query)
        if args.voice:
            mux_voice(silent, Path(args.voice), cues, duration, out)
        else:
            out.write_bytes(silent.read_bytes())
    print(out)


if __name__ == "__main__":
    main()
