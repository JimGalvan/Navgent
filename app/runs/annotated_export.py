"""Render marks into an MP4; retain the original WebM as evidence."""

import hashlib
import json
import math
import os
import subprocess
import threading
from pathlib import Path

import cv2
import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

from app.runs.annotations import AnnotationTrack

RED = "#ff6b5e"
LIME = "#c6f24e"
DARK = "#0c0c0d"
RENDER_VERSION = 1


class ExportBusyError(RuntimeError):
    pass


class ExportFailedError(RuntimeError):
    pass


def _font(size):
    for name in ("segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def _wrap(text, draw, font, max_width):
    """Wrap even a long URL or an unspaced quote without clipping it."""
    lines, line = [], ""
    for word in text.split():
        candidate = (line + " " + word).strip()
        if draw.textlength(candidate, font=font) <= max_width:
            line = candidate
            continue
        if line:
            lines.append(line)
            line = ""
        for char in word:
            if line and draw.textlength(line + char, font=font) > max_width:
                lines.append(line)
                line = ""
            line += char
    if line:
        lines.append(line)
    return lines


def draw_marks(image: Image.Image, track: AnnotationTrack, time_ms: float, font=None) -> None:
    draw = ImageDraw.Draw(image)
    w, h = image.size
    font_size = max(12, round(w / 1365 * 18))
    font = font or _font(font_size)
    for click in track.clicks:
        age = time_ms - click.time_ms
        if not 0 <= age < track.click_duration_ms:
            continue
        sx, sy = w / click.viewport_width, h / click.viewport_height
        x, y = click.x * sx, click.y * sy
        radius = max(8, 10 * sx) + 16 * sx * age / track.click_duration_ms
        box = (x - radius, y - radius, x + radius, y + radius)
        draw.ellipse(box, outline=DARK, width=max(4, round(6 * sx)))
        draw.ellipse(box, outline=LIME, width=max(2, round(3 * sx)))
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=LIME)
    label_bottom = 0
    for finding in track.findings:
        if not finding.start_ms <= time_ms < finding.end_ms:
            continue
        sx, sy = w / finding.viewport_width, h / finding.viewport_height
        x, y, fw, fh = finding.x * sx, finding.y * sy, finding.width * sx, finding.height * sy
        draw.rectangle((x, y, x + fw, y + fh), outline=RED, width=max(2, round(3 * sx)))
        pad, gap = 8, 6
        line_height = font_size + 5
        max_width = min(420 * sx, w - 4 * pad)
        lines = _wrap(f"{finding.number} · {finding.explanation}", draw, font, max_width)
        max_lines = max(1, min(3, int((h - 32) / line_height)))
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            last = lines[-1]
            while last and draw.textlength(last + "…", font=font) > max_width:
                last = last[:-1]
            lines[-1] = last + "…"
        lw = min(w - 2 * pad, max(draw.textlength(line, font=font) for line in lines) + 2 * pad)
        lh = len(lines) * line_height + 2 * pad
        lx = max(pad, min(x, w - lw - pad))
        ly = y - lh - gap if y >= lh + gap + pad else y + fh + gap
        ly = max(pad, min(max(ly, label_bottom), h - lh - pad))
        draw.rectangle((lx, ly, lx + lw, ly + lh), fill=RED)
        for index, line in enumerate(lines):
            draw.text((lx + pad, ly + pad + index * line_height), line, font=font, fill=DARK)
        label_bottom = ly + lh + gap


class AnnotatedRecordingExporter:
    def __init__(self):
        # Bound CPU and prevent two requests writing the same cached file.
        self._lock = threading.Lock()

    @staticmethod
    def destination(source: Path, track: AnnotationTrack) -> Path:
        stat = source.stat()
        digest = hashlib.sha256(json.dumps({
            "version": RENDER_VERSION, "size": stat.st_size, "mtime": stat.st_mtime_ns,
            "track": track.model_dump(),
        }, sort_keys=True).encode()).hexdigest()[:20]
        return source.parent.parent / "exports" / f"{source.stem}-{digest}.mp4"

    def prepare(self, source: Path, track: AnnotationTrack) -> Path:
        target = self.destination(source, track)
        if target.is_file():
            return target
        if not self._lock.acquire(blocking=False):
            raise ExportBusyError("Another annotated video is being prepared. Try again shortly.")
        try:
            if target.is_file():
                return target
            target.parent.mkdir(parents=True, exist_ok=True)
            self._render(source, target, track)
            return target
        finally:
            self._lock.release()

    @staticmethod
    def _render(source: Path, target: Path, track: AnnotationTrack) -> None:
        capture = cv2.VideoCapture(str(source))
        partial = target.with_suffix(".partial.mp4")
        process = None
        try:
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = capture.get(cv2.CAP_PROP_FPS)
            if not capture.isOpened() or not (0 < width <= 4096 and 0 < height <= 4096
                                             and math.isfinite(fps) and 1 <= fps <= 120):
                raise ExportFailedError("This recording could not be read. Download the original WebM instead.")
            process = subprocess.Popen([
                imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
                "-f", "rawvideo", "-vcodec", "rawvideo", "-pix_fmt", "rgb24",
                "-s", f"{width}x{height}", "-r", str(fps), "-i", "pipe:0",
                "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-threads", "2", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(partial),
            ], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            font = _font(max(12, round(width / 1365 * 18)))
            frames = 0
            while True:
                readable, frame = capture.read()
                if not readable:
                    break
                if frames / fps > 1810:
                    raise ExportFailedError("This recording is too long to export.")
                image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                draw_marks(image, track, frames / fps * 1000, font)
                process.stdin.write(image.tobytes())
                frames += 1
            process.stdin.close()
            if process.wait(timeout=60) != 0 or frames == 0:
                raise ExportFailedError("The annotated video could not be created. Try again or download the original WebM.")
            partial.replace(target)
        except ExportFailedError:
            raise
        except (OSError, subprocess.SubprocessError, ValueError, cv2.error) as error:
            raise ExportFailedError("The annotated video could not be created. Try again or download the original WebM.") from error
        finally:
            capture.release()
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()
            partial.unlink(missing_ok=True)
