"""One recording timeline shared by playback and the rendered video export."""

import math
from pathlib import Path

from pydantic import BaseModel, Field

from app.runs.schemas import RecordingMetadata, RunEvent, RunRecord

CLICK_DURATION_MS = 650
FINDING_DURATION_MS = 3_000


class ClickMark(BaseModel):
    id: str
    time_ms: float
    x: float
    y: float
    viewport_width: float
    viewport_height: float


class FindingMark(BaseModel):
    id: str
    number: int
    explanation: str
    start_ms: float
    end_ms: float
    x: float
    y: float
    width: float
    height: float
    viewport_width: float
    viewport_height: float
    brief_step: int | None = None


class AnnotationTrack(BaseModel):
    recording_id: str
    number: int
    click_duration_ms: int = CLICK_DURATION_MS
    clicks: list[ClickMark] = Field(default_factory=list)
    findings: list[FindingMark] = Field(default_factory=list)


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    return float(value) if math.isfinite(value) else None


def _time(payload: dict, media_key: str, wall_key: str,
          metadata: RecordingMetadata | None) -> float | None:
    value = _number(payload.get(media_key))
    if value is None and metadata is not None:
        wall = _number(payload.get(wall_key))
        origin = _number(metadata.start_wall_time_ms)
        if wall is not None and origin is not None:
            value = wall - origin
    return value if value is not None and value >= 0 else None


def _geometry(payload: dict, rectangle: bool = False) -> dict | None:
    names = ["x", "y", "viewport_width", "viewport_height"]
    if rectangle:
        names += ["width", "height"]
    values = {name: _number(payload.get(name)) for name in names}
    if any(value is None for value in values.values()):
        return None
    vw, vh = values["viewport_width"], values["viewport_height"]
    if not (0 < vw <= 16384 and 0 < vh <= 16384):
        return None
    if not (0 <= values["x"] <= vw and 0 <= values["y"] <= vh):
        return None
    if rectangle and not (0 < values["width"] <= vw - values["x"] + 0.01
                          and 0 < values["height"] <= vh - values["y"] + 0.01):
        return None
    return values


def annotation_tracks(run: RunRecord, events: list[RunEvent]) -> list[AnnotationTrack]:
    """Skip unpositioned events; never derive timing from server arrival times."""
    metadata = {item.id: item for item in run.recording_metadata}
    tracks = [AnnotationTrack(recording_id=Path(name).stem, number=index)
              for index, name in enumerate(run.recordings, 1)]
    by_id = {track.recording_id: track for track in tracks}
    verdict = run.verdict
    verdict_id = verdict.verdict_id if verdict and verdict.verdict == "reproduced" else None
    seen = set()
    for event in sorted(events, key=lambda item: item.sequence):
        if event.event_type not in {"browser.click", "reproduction.finding"}:
            continue
        p = event.payload
        track = by_id.get(p.get("recording_id"))
        if track is None:
            continue
        finding = event.event_type == "reproduction.finding"
        identifier = p.get("annotation_id" if finding else "click_id")
        if not isinstance(identifier, str) or not identifier or (event.event_type, identifier) in seen:
            continue
        geometry = _geometry(p, rectangle=finding)
        if geometry is None:
            continue
        origin = metadata.get(track.recording_id)
        if not finding:
            time = _time(p, "recording_time_ms", "wall_time_ms", origin)
            if time is None:
                continue
            track.clicks.append(ClickMark(id=identifier, time_ms=time, **geometry))
        else:
            if not verdict_id or p.get("verdict_id") != verdict_id:
                continue
            start = _time(p, "start_recording_time_ms", "start_wall_time_ms", origin)
            end = _time(p, "end_recording_time_ms", "end_wall_time_ms", origin)
            number = p.get("number")
            explanation = p.get("explanation")
            if (start is None or end is None or end < start
                    or type(number) is not int or number < 1
                    or not isinstance(explanation, str) or not explanation.strip()):
                continue
            step = p.get("brief_step")
            track.findings.append(FindingMark(
                id=identifier, number=number, explanation=explanation[:500],
                start_ms=start, end_ms=start + FINDING_DURATION_MS,
                brief_step=step if type(step) is int and step > 0 else None, **geometry,
            ))
        seen.add((event.event_type, identifier))
    for track in tracks:
        track.clicks.sort(key=lambda item: item.time_ms)
        track.findings.sort(key=lambda item: (item.start_ms, item.number))
        for finding in track.findings:
            next_click = next((item.time_ms for item in track.clicks if item.time_ms >= finding.start_ms), None)
            if next_click is not None:
                finding.end_ms = min(finding.end_ms, next_click)
        track.findings = [item for item in track.findings if item.end_ms > item.start_ms]
    return tracks
