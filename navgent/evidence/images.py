from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np

from navgent.evidence.constants import (
    JPEG_QUALITY,
    MAX_IMAGE_SIDE,
    MAX_SCREENSHOTS,
    MAX_VIDEO_FRAMES,
    MIN_CHANGED_AREA,
    PIXEL_CHANGE_THRESHOLD,
    VIDEO_SAMPLE_INTERVAL_SECONDS,
)
from navgent.evidence.models import Frame


def load_screenshots(paths: tuple[Path, ...]) -> list[Frame]:
    frames = []
    for number, path in enumerate(paths, start=1):
        data = np.frombuffer(path.read_bytes(), dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"{path.name} is not a supported image")
        frames.append(to_frame(image, f"screenshot {number}"))
    return pick_evenly(frames, MAX_SCREENSHOTS)


def extract_video_frames(path: Path) -> list[Frame]:
    frames = []
    previous_gray = None
    last_label = ""
    last_image = None
    for seconds, image in sample_video(path):
        label = f"video {format_timestamp(seconds)}"
        small = shrink(image)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        if previous_gray is None or screen_changed(previous_gray, gray):
            frames.append(to_frame(small, label))
            previous_gray = gray
        last_label = label
        last_image = small
    if last_image is not None and frames[-1].label != last_label:
        frames.append(to_frame(last_image, last_label))
    return pick_evenly(frames, MAX_VIDEO_FRAMES)


def sample_video(path: Path) -> Iterator[tuple[float, np.ndarray]]:
    video = cv2.VideoCapture(str(path))
    if not video.isOpened():
        raise ValueError(f"{path.name} is not a supported video")
    next_sample_seconds = 0.0
    try:
        while video.grab():
            seconds = video.get(cv2.CAP_PROP_POS_MSEC) / 1000
            if seconds < next_sample_seconds:
                continue
            ok, image = video.retrieve()
            if ok:
                yield seconds, image
            next_sample_seconds = seconds + VIDEO_SAMPLE_INTERVAL_SECONDS
    finally:
        video.release()


def to_frame(image: np.ndarray, label: str) -> Frame:
    ok, buffer = cv2.imencode(".jpg", shrink(image), [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise ValueError(f"Could not encode {label}")
    return Frame(label=label, jpeg=buffer.tobytes())


def shrink(image: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    longest_side = max(height, width)
    if longest_side <= MAX_IMAGE_SIDE:
        return image
    scale = MAX_IMAGE_SIDE / longest_side
    size = (round(width * scale), round(height * scale))
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA)


def screen_changed(previous: np.ndarray, current: np.ndarray) -> bool:
    changed_pixels = cv2.absdiff(previous, current) > PIXEL_CHANGE_THRESHOLD
    return changed_pixels.mean() > MIN_CHANGED_AREA


def pick_evenly(frames: list[Frame], limit: int) -> list[Frame]:
    if len(frames) <= limit:
        return frames
    picked = []
    step = (len(frames) - 1) / (limit - 1)
    for position in range(limit):
        picked.append(frames[round(position * step)])
    return picked


def format_timestamp(seconds: float) -> str:
    minutes, remainder = divmod(int(seconds), 60)
    return f"{minutes:02d}:{remainder:02d}"
