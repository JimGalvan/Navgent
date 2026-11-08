"""Build a proof still from the verified finding's recording, never a later frame."""

import io
import math
from pathlib import Path

import cv2
from PIL import Image
from pydantic import BaseModel

from app.runs.annotated_export import ExportFailedError, draw_marks
from app.runs.annotations import AnnotationTrack, FindingMark


class ProofFrameInfo(BaseModel):
    image_url: str = ""
    recording_number: int
    time_ms: float
    step_number: int | None
    explanation: str
    expected: str
    observed: str


def proof_time(finding: FindingMark) -> float:
    # Allow the recording to capture the observed paint, staying inside its mark.
    return finding.start_ms + min(100, (finding.end_ms - finding.start_ms) / 2)


def render_proof_frame(source: Path, track: AnnotationTrack, finding: FindingMark) -> bytes:
    capture = cv2.VideoCapture(str(source))
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        width = capture.get(cv2.CAP_PROP_FRAME_WIDTH)
        height = capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
        if not (capture.isOpened() and math.isfinite(fps) and 1 <= fps <= 120
                and 0 < width <= 4096 and 0 < height <= 4096):
            raise ExportFailedError("The finding frame could not be read from this recording.")
        position = proof_time(finding)
        if finding.end_ms <= finding.start_ms or position >= capture.get(cv2.CAP_PROP_FRAME_COUNT) / fps * 1000:
            raise ExportFailedError("The finding's moment is outside the saved recording.")
        if not capture.set(cv2.CAP_PROP_POS_MSEC, position):
            raise ExportFailedError("The finding's moment could not be located in the recording.")
        readable, frame = capture.read()
        if not readable:
            raise ExportFailedError("The finding frame could not be read from this recording.")
        image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        # Include only the selected finding: clicks and other moments are unrelated.
        marks = track.model_copy(update={"clicks": [], "findings": [finding]})
        draw_marks(image, marks, position)
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=92)
        return output.getvalue()
    finally:
        capture.release()
