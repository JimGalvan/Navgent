"""Store uploaded evidence and the compact images returned by the pipeline."""

import math
import shutil
import time
from pathlib import Path

import cv2
from starlette.datastructures import UploadFile

from app.runs.schemas import EvidenceFrame, RunRecord
from navgent.evidence import BugReport, EvidenceAnalysis

MAX_SCREENSHOTS = 10
MAX_IMAGE_BYTES = 10 * 1024 ** 2
MAX_VIDEO_BYTES = 50 * 1024 ** 2
MAX_REQUEST_BYTES = MAX_SCREENSHOTS * MAX_IMAGE_BYTES + MAX_VIDEO_BYTES + 1024 ** 2
MAX_VIDEO_SECONDS = 120
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov"}


class EvidenceUploadError(ValueError):
    pass


class RunEvidenceStore:
    def __init__(self, directory: Path):
        self.directory = directory

    def run_directory(self, run: RunRecord) -> Path:
        return self.directory / str(run.id)

    async def save_uploads(
        self, run: RunRecord, screenshots: list[UploadFile], video: UploadFile | None,
    ) -> None:
        if len(screenshots) > MAX_SCREENSHOTS:
            raise EvidenceUploadError(f"Choose up to {MAX_SCREENSHOTS} screenshots.")
        report = run.bug_report
        assert report is not None
        upload_directory = self.run_directory(run) / "uploads"
        upload_directory.mkdir(parents=True, exist_ok=True)
        for number, upload in enumerate(screenshots, start=1):
            extension = Path(upload.filename or "").suffix.lower()
            if extension not in IMAGE_EXTENSIONS:
                raise EvidenceUploadError("Choose a PNG, JPEG, WebP, GIF, BMP or TIFF image.")
            filename = f"screenshot-{number:02d}{extension}"
            await self._save_upload(upload, upload_directory / filename, MAX_IMAGE_BYTES, "Screenshots must be 10 MB or less.")
            report.screenshot_names.append(filename)
        if video is not None:
            extension = Path(video.filename or "").suffix.lower()
            if extension not in VIDEO_EXTENSIONS:
                raise EvidenceUploadError("Choose an MP4, WebM or MOV recording.")
            filename = f"recording{extension}"
            await self._save_upload(video, upload_directory / filename, MAX_VIDEO_BYTES, "Recordings must be 50 MB or less.")
            report.video_name = filename

    @staticmethod
    async def _save_upload(upload: UploadFile, path: Path, limit: int, message: str) -> None:
        size = 0
        try:
            with path.open("wb") as destination:
                while True:
                    chunk = await upload.read(1024 ** 2)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > limit:
                        raise EvidenceUploadError(message)
                    destination.write(chunk)
            if size == 0:
                raise EvidenceUploadError("One of the uploaded files is empty. Choose a readable file.")
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def build_report(self, run: RunRecord) -> BugReport:
        report = run.bug_report
        assert report is not None
        upload_directory = self.run_directory(run) / "uploads"
        screenshots = []
        for filename in report.screenshot_names:
            screenshots.append(upload_directory / filename)
        video_path = upload_directory / report.video_name if report.video_name else None
        return BugReport(
            target_url=report.target_url,
            expected=report.expected,
            actual=report.actual,
            steps_text=report.steps_text,
            screenshot_paths=tuple(screenshots),
            video_path=video_path,
        )

    def save_analysis(self, run: RunRecord, analysis: EvidenceAnalysis) -> None:
        directory = self.run_directory(run) / "evidence"
        directory.mkdir(parents=True, exist_ok=True)
        frames = []
        for number, frame in enumerate(analysis.frames, start=1):
            filename = f"frame-{number:02d}.jpg"
            (directory / filename).write_bytes(frame.jpeg)
            frames.append(EvidenceFrame(filename=filename, label=frame.label))
        run.evidence_frames = frames
        run.repro_brief = analysis.brief.model_dump()

    def copy_evidence(self, source: RunRecord, destination: RunRecord) -> None:
        assert source.bug_report is not None
        source_directory = self.run_directory(source)
        for name in ("uploads", "evidence"):
            if (source_directory / name).is_dir():
                shutil.copytree(source_directory / name, self.run_directory(destination) / name)
        destination.bug_report = source.bug_report.model_copy(deep=True)
        destination.repro_brief = source.repro_brief
        destination.evidence_frames = []
        for frame in source.evidence_frames:
            destination.evidence_frames.append(frame.model_copy())

    def frame_path(self, run: RunRecord, number: int) -> Path | None:
        if number < 1 or number > len(run.evidence_frames):
            return None
        filename = run.evidence_frames[number - 1].filename
        return self.run_directory(run) / "evidence" / filename


def validate_video(path: Path) -> None:
    """Check duration and bound the scan even when video metadata is unreliable."""
    video = cv2.VideoCapture(str(path))
    try:
        fps = video.get(cv2.CAP_PROP_FPS)
        frame_count = video.get(cv2.CAP_PROP_FRAME_COUNT)
        if not video.isOpened():
            raise EvidenceUploadError("The recording could not be read. Choose a playable MP4, WebM or MOV.")
        deadline = time.monotonic() + 10
        decoded_frames = 0
        last_timestamp = 0.0
        while video.grab():
            decoded_frames += 1
            timestamp = video.get(cv2.CAP_PROP_POS_MSEC)
            if math.isfinite(timestamp):
                last_timestamp = max(last_timestamp, timestamp)
            if last_timestamp > MAX_VIDEO_SECONDS * 1000:
                raise EvidenceUploadError("Recordings must be 2 minutes or less.")
            if decoded_frames > 36_000 or time.monotonic() > deadline:
                raise EvidenceUploadError("This recording takes too long to read. Upload a shorter clip.")
            if decoded_frames == 1:
                readable, image = video.retrieve()
                if not readable or image is None:
                    raise EvidenceUploadError("The recording has no readable frames. Choose another file.")
        if decoded_frames == 0:
            raise EvidenceUploadError("The recording has no readable frames. Choose another file.")
        if last_timestamp == 0:
            if not math.isfinite(fps) or fps <= 0 or not math.isfinite(frame_count) or frame_count <= 0:
                raise EvidenceUploadError("The recording's length could not be checked. Choose another file.")
            if frame_count / fps > MAX_VIDEO_SECONDS:
                raise EvidenceUploadError("Recordings must be 2 minutes or less.")
    finally:
        video.release()
