"""Cut one video part from a screen recording using an edit list (JSON).

Each segment takes a slice of the source and can speed it up, hold its last frame, zoom into a
region, blur regions, and lay a transparent overlay or a corner label on top. Voice clips are
placed relative to the segment they belong to, so retiming a segment moves its voice with it.

Usage:
  python video/tools/cut.py video/part-2/edit.json video/exports/part-2-draft.mp4
  python video/tools/cut.py video/part-2/edit.json <dir> --stills      (one still per segment)
"""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

FPS = 30
FADE_SECONDS = 0.35


def segment_length(segment: dict) -> float:
    length = (segment["to"] - segment["from"]) / segment.get("speed", 1)
    return length + segment.get("hold", 0)


def video_filter(segment: dict, edit: dict, overlay_inputs: list[str]) -> str:
    steps = []
    label = "[0:v]"
    blur_regions = edit.get("blur", []) + segment.get("blur", [])
    for index, (x, y, w, h) in enumerate(blur_regions):
        steps.append(f"{label}split[b{index}a][b{index}b]")
        steps.append(f"[b{index}b]crop={w}:{h}:{x}:{y},boxblur=10:2:5:2[b{index}c]")
        steps.append(f"[b{index}a][b{index}c]overlay={x}:{y}[b{index}]")
        label = f"[b{index}]"

    chain = []
    if "zoom" in segment:
        x, y, w, h = edit["zooms"][segment["zoom"]]
        chain.append(f"crop={w}:{h}:{x}:{y},scale=1920:1080:flags=lanczos")
    speed = segment.get("speed", 1)
    chain.append(f"setpts=(PTS-STARTPTS)/{speed}")
    chain.append(f"fps={FPS}")
    if segment.get("hold"):
        chain.append(f"tpad=stop_mode=clone:stop_duration={segment['hold']}")
    steps.append(f"{label}{','.join(chain)}[base]")
    label = "[base]"

    for index, name in enumerate(overlay_inputs, start=1):
        steps.append(f"[{index}:v]format=rgba,fade=in:st=0:d={FADE_SECONDS}:alpha=1[o{index}]")
        steps.append(f"{label}[o{index}]overlay=0:0:shortest=1[v{index}]")
        label = f"[v{index}]"

    steps.append(f"{label}format=yuv420p[out]")
    return ";".join(steps)


def render_segment(segment: dict, edit: dict, out_path: Path) -> None:
    overlay_names = []
    if segment.get("overlay"):
        overlay_names.append(segment["overlay"])
    if segment.get("label"):
        overlay_names.append(segment["label"])

    command = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", str(segment["from"]), "-to", str(segment["to"]), "-i", segment.get("source", edit["source"]),
    ]
    for name in overlay_names:
        command += ["-loop", "1", "-i", str(Path(edit["overlay_dir"]) / f"{name}.png")]
    command += [
        "-filter_complex", video_filter(segment, edit, overlay_names),
        "-map", "[out]", "-an",
        "-t", f"{segment_length(segment):.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-r", str(FPS),
        str(out_path),
    ]
    subprocess.run(command, check=True)


def voice_cues(edit: dict) -> list[tuple[str, float]]:
    cues = []
    start = 0.0
    for segment in edit["segments"]:
        for voice_id, offset in segment.get("voice", []):
            cues.append((voice_id, start + offset))
        start += segment_length(segment)
    return cues


def mux(video_path: Path, edit: dict, out_path: Path) -> None:
    cues = voice_cues(edit)
    total = 0.0
    for segment in edit["segments"]:
        total += segment_length(segment)
    command = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video_path)]
    filters = []
    labels = ""
    for index, (voice_id, at) in enumerate(cues, start=1):
        command += ["-i", str(Path(edit["voice_dir"]) / f"{voice_id}.mp3")]
        delay_ms = int(at * 1000)
        filters.append(f"[{index}:a]adelay={delay_ms}|{delay_ms}[a{index}]")
        labels += f"[a{index}]"
    filters.append(f"{labels}amix=inputs={len(cues)}:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11,apad[voice]")
    command += [
        "-filter_complex", ";".join(filters),
        "-map", "0:v", "-map", "[voice]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-t", f"{total:.3f}",
        str(out_path),
    ]
    subprocess.run(command, check=True)


def save_stills(edit: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        for index, segment in enumerate(edit["segments"]):
            clip = Path(temp) / f"{index:02d}.mp4"
            render_segment(segment, edit, clip)
            still = out_dir / f"{index:02d}.png"
            middle = segment_length(segment) / 2
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{middle:.2f}", "-i", str(clip),
                 "-frames:v", "1", "-vf", "scale=960:-1", str(still)],
                check=True,
            )
            print(still, segment.get("note", ""))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("edit")
    parser.add_argument("out")
    parser.add_argument("--stills", action="store_true")
    args = parser.parse_args()

    edit = json.loads(Path(args.edit).read_text(encoding="utf-8"))
    if args.stills:
        save_stills(edit, Path(args.out))
        return

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        clips = []
        for index, segment in enumerate(edit["segments"]):
            clip = Path(temp) / f"{index:02d}.mp4"
            render_segment(segment, edit, clip)
            clips.append(clip)
            print(f"  segment {index:2d} {segment_length(segment):5.1f}s  {segment.get('note', '')}", flush=True)
        listing = Path(temp) / "clips.txt"
        text = ""
        for clip in clips:
            text += f"file '{clip.as_posix()}'\n"
        listing.write_text(text, encoding="utf-8")
        silent = Path(temp) / "silent.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
             "-c", "copy", str(silent)],
            check=True,
        )
        mux(silent, edit, out)
    print(out)


if __name__ == "__main__":
    main()
