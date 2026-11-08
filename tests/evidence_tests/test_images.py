import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from navgent.evidence import images
from navgent.evidence.constants import MAX_IMAGE_SIDE, MAX_SCREENSHOTS
from navgent.evidence.models import Frame

RED = (0, 0, 255)
BLUE = (255, 0, 0)
WHITE = (255, 255, 255)


def decode(frame: Frame) -> np.ndarray:
    return cv2.imdecode(np.frombuffer(frame.jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)


def write_image(path: Path, width: int, height: int) -> Path:
    cv2.imwrite(str(path), np.full((height, width, 3), 200, dtype=np.uint8))
    return path


def solid(color: tuple[int, int, int], count: int) -> list[np.ndarray]:
    return [np.full((180, 320, 3), color, dtype=np.uint8)] * count


def write_video(path: Path, video_frames: list[np.ndarray], fps: int = 10) -> Path:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (320, 180))
    for image in video_frames:
        writer.write(image)
    writer.release()
    return path


def labels_of(frames: list[Frame]) -> list[str]:
    labels = []
    for frame in frames:
        labels.append(frame.label)
    return labels


class ScreenshotTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)

    def test_large_screenshot_is_shrunk_to_the_longest_side_limit(self) -> None:
        path = write_image(self.folder / "wide.png", 3000, 1500)
        frames = images.load_screenshots((path,))
        height, width = decode(frames[0]).shape[:2]
        self.assertEqual(frames[0].label, "screenshot 1")
        self.assertEqual(width, MAX_IMAGE_SIDE)
        self.assertEqual(height, MAX_IMAGE_SIDE // 2)

    def test_tall_screenshot_is_shrunk_by_its_height(self) -> None:
        path = write_image(self.folder / "tall.png", 800, 2400)
        height, width = decode(images.load_screenshots((path,))[0]).shape[:2]
        self.assertEqual(height, MAX_IMAGE_SIDE)
        self.assertLess(width, MAX_IMAGE_SIDE)

    def test_small_screenshot_keeps_its_size(self) -> None:
        path = write_image(self.folder / "small.png", 640, 360)
        height, width = decode(images.load_screenshots((path,))[0]).shape[:2]
        self.assertEqual((width, height), (640, 360))

    def test_screenshots_are_capped_and_keep_the_first_and_last(self) -> None:
        paths = []
        for number in range(1, 9):
            paths.append(write_image(self.folder / f"{number}.png", 100, 100))
        frames = images.load_screenshots(tuple(paths))
        self.assertEqual(len(frames), MAX_SCREENSHOTS)
        self.assertEqual(frames[0].label, "screenshot 1")
        self.assertEqual(frames[-1].label, "screenshot 8")

    def test_unreadable_screenshot_is_rejected(self) -> None:
        path = self.folder / "notes.png"
        path.write_bytes(b"not an image")
        with self.assertRaisesRegex(ValueError, "notes.png is not a supported image"):
            images.load_screenshots((path,))


class VideoTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)

    def test_video_keeps_changed_frames_and_the_last_sample(self) -> None:
        path = write_video(self.folder / "clip.avi", solid(RED, 30) + solid(BLUE, 60))
        frames = images.extract_video_frames(path)
        self.assertEqual(labels_of(frames), ["video 00:00", "video 00:03", "video 00:08"])

    def test_static_video_keeps_the_first_and_last_sample(self) -> None:
        path = write_video(self.folder / "static.avi", solid(RED, 25))
        frames = images.extract_video_frames(path)
        self.assertEqual(labels_of(frames), ["video 00:00", "video 00:02"])

    def test_small_change_like_a_ticked_checkbox_is_kept(self) -> None:
        blank = np.full((180, 320, 3), WHITE, dtype=np.uint8)
        ticked = blank.copy()
        ticked[80:92, 150:162] = 0
        path = write_video(self.folder / "tick.avi", [blank] * 20 + [ticked] * 10)
        frames = images.extract_video_frames(path)
        self.assertEqual(labels_of(frames), ["video 00:00", "video 00:02"])

    def test_video_samples_one_frame_per_second(self) -> None:
        path = write_video(self.folder / "clip.avi", solid(RED, 35))
        samples = []
        for seconds, _ in images.sample_video(path):
            samples.append(round(seconds, 1))
        self.assertEqual(samples, [0.0, 1.0, 2.0, 3.0])

    def test_unreadable_video_is_rejected(self) -> None:
        path = self.folder / "clip.mp4"
        path.write_bytes(b"not a video")
        with self.assertRaisesRegex(ValueError, "clip.mp4 is not a supported video"):
            images.extract_video_frames(path)


class HelperTests(unittest.TestCase):
    def test_pick_evenly_keeps_the_first_and_last_frames(self) -> None:
        frames = []
        for number in range(20):
            frames.append(Frame(label=str(number), jpeg=b""))
        picked = images.pick_evenly(frames, 5)
        self.assertEqual(labels_of(picked), ["0", "5", "10", "14", "19"])

    def test_pick_evenly_returns_short_lists_unchanged(self) -> None:
        frames = [Frame(label="only", jpeg=b"")]
        self.assertEqual(images.pick_evenly(frames, 5), frames)

    def test_timestamps_use_minutes_and_seconds(self) -> None:
        self.assertEqual(images.format_timestamp(0.4), "00:00")
        self.assertEqual(images.format_timestamp(75.9), "01:15")
