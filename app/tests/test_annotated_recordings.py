"""Recording contracts, ownership and actual encoded overlay pixels."""

import sqlite3
import subprocess
from pathlib import Path
from uuid import uuid4

import cv2
import imageio_ffmpeg
import pytest
from PIL import Image

from app.runs.annotated_export import (
    AnnotatedRecordingExporter,
    ExportBusyError,
    ExportFailedError,
    draw_marks,
)
from app.runs.annotations import annotation_tracks
from app.runs.repository import RunRepository
from app.runs.schemas import (
    RecordingMetadata,
    RunEvent,
    RunRecord,
    RunStatus,
    RunVerdict,
)
from app.tests.test_application import client as client


def run_record(**kwargs):
    return RunRecord(task="Compare cart total", max_runtime_seconds=600, status=RunStatus.SUCCEEDED,
                     recordings=["tab-a.webm", "tab-b.webm"],
                     reported_verdict=RunVerdict(verdict_id="current", verdict="reproduced",
                                                expected="$30", observed="$42", reason="Stale total", step_number=3),
                     **kwargs)


def event(run, sequence, kind, **payload):
    return RunEvent(run_id=run.id, sequence=sequence, event_type=kind, payload=payload)


def click(**kwargs):
    return dict(click_id=kwargs.pop("click_id", "click-1"), action="click", brief_step=2,
                recording_id="tab-a", x=40, y=60, viewport_width=320, viewport_height=180,
                wall_time_ms=1200, recording_time_ms=200, **kwargs)


def finding(**kwargs):
    result = dict(annotation_id="finding-1", verdict_id="current", number=1,
                  explanation="Shows $42.00. Expected $30.00.", brief_step=3, recording_id="tab-a",
                  x=160, y=60, width=90, height=30, viewport_width=320, viewport_height=180,
                  start_wall_time_ms=2000, end_wall_time_ms=2200,
                  start_recording_time_ms=1000, end_recording_time_ms=1200)
    result.update(kwargs)
    return result


def make_video(path: Path, seconds=3.2, size="320x180"):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"color=c=white:s={size}:r=25:d={seconds}",
                    "-c:v", "libvpx-vp9", "-threads", "1", "-an", str(path)],
                   check=True, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return path


def test_tracks_filter_verdicts_tabs_invalid_geometry_and_duplicates():
    run = run_record()
    events = [event(run, 1, "browser.click", **click()),
              event(run, 2, "browser.click", **click()),
              event(run, 3, "reproduction.finding", **finding(verdict_id="old")),
              event(run, 4, "reproduction.finding", **finding()),
              event(run, 5, "reproduction.finding", **finding(annotation_id="bad", width=900)),
              event(run, 6, "reproduction.finding", **finding(annotation_id="off", recording_id=None))]
    later = click(click_id="click-2")
    later.update(recording_time_ms=2200)
    events.append(event(run, 7, "browser.click", **later))
    tracks = annotation_tracks(run, events)
    assert len(tracks[0].clicks) == 2
    assert len(tracks[0].findings) == 1
    assert tracks[0].findings[0].end_ms == 2200
    assert tracks[1].clicks == tracks[1].findings == []
    run.reported_verdict.verdict_id = "new"
    assert annotation_tracks(run, events)[0].findings == []
    run.reported_verdict.verdict_id = "current"
    run.reported_verdict.verdict = "not_reproduced"
    assert annotation_tracks(run, events)[0].findings == []


def test_only_own_recording_click_cuts_off_finding_and_cap_is_three_seconds():
    run = run_record()
    other_click = click(click_id="other")
    other_click.update(recording_id="tab-b", recording_time_ms=1500)
    events = [event(run, 1, "reproduction.finding", **finding()),
              event(run, 2, "browser.click", **other_click)]
    assert annotation_tracks(run, events)[0].findings[0].end_ms == 4000


@pytest.mark.parametrize("invalid", [None, -5, float("nan"), float("inf"), True, "200"])
def test_invalid_media_time_is_not_replaced_with_event_arrival_time(invalid):
    run = run_record()
    payload = click()
    payload["recording_time_ms"] = invalid
    assert annotation_tracks(run, [event(run, 1, "browser.click", **payload)])[0].clicks == []


def test_recording_origin_fallback_and_old_verdict_compatibility(tmp_path):
    run = run_record(recording_metadata=[RecordingMetadata(id="tab-a", width=320, height=180,
                                                          start_wall_time_ms=1000)])
    payload = click()
    payload["recording_time_ms"] = None
    tracks = annotation_tracks(run, [event(run, 1, "browser.click", **payload)])
    assert tracks[0].clicks[0].time_ms == 200
    repository = RunRepository(tmp_path / "runs.db")
    repository.initialize()
    repository.save_run(run)
    restored = repository.get_run(run.id)
    assert restored.verdict.verdict_id == "current"
    assert restored.recording_metadata == run.recording_metadata
    old = RunVerdict(verdict="reproduced", expected="30", observed="42", reason="Mismatch", step_number=None)
    assert old.verdict_id == ""
    assert "verdict_id" not in old.model_dump()
    # Upgrade an existing database without changing its recordings or verdicts.
    with sqlite3.connect(tmp_path / "runs.db") as db:
        db.execute("ALTER TABLE runs DROP COLUMN recording_metadata")
    repository.initialize()
    assert repository.get_run(run.id).recording_metadata == []
    assert repository.get_run(run.id).recordings == run.recordings


def test_rendered_frames_show_click_and_finding_only_in_their_intervals(tmp_path):
    run = run_record()
    track = annotation_tracks(run, [event(run, 1, "browser.click", **click()),
                                   event(run, 2, "reproduction.finding", **finding())])[0]
    plain = Image.new("RGB", (320, 180), "white")
    draw_marks(plain, track, 0)
    assert plain.getpixel((160, 60)) == (255, 255, 255)
    draw_marks(plain, track, 1100)
    assert plain.getpixel((160, 60)) == (255, 107, 94)
    source = make_video(tmp_path / "recording" / "tab-a.webm")
    exporter = AnnotatedRecordingExporter()
    target = exporter.prepare(source, track)
    assert target.suffix == ".mp4"
    assert exporter.prepare(source, track) == target
    video = cv2.VideoCapture(str(target))
    try:
        assert video.get(cv2.CAP_PROP_FPS) == 25
        assert video.get(cv2.CAP_PROP_FRAME_COUNT) == 80
        video.set(cv2.CAP_PROP_POS_FRAMES, 10)
        ok, frame = video.read()
        assert ok
        b, g, r = map(int, frame[60, 40])
        assert g > 190 and g > b + 80 and r > 120
        video.set(cv2.CAP_PROP_POS_FRAMES, 23)
        ok, frame = video.read()
        assert ok and min(frame[60, 40]) > 220
        video.set(cv2.CAP_PROP_POS_FRAMES, 28)
        ok, frame = video.read()
        assert ok
        b, g, r = map(int, frame[60, 160])
        assert r > 180 and r > g + 50 and r > b + 50
        video.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ok, frame = video.read()
        assert ok and min(frame[60, 160]) > 220
    finally:
        video.release()


def test_export_failure_cleans_up_and_does_not_change_original(tmp_path):
    source = tmp_path / "recording" / "tab-a.webm"
    source.parent.mkdir()
    source.write_bytes(b"unreadable recording")
    track = annotation_tracks(run_record(), [])[0]
    exporter = AnnotatedRecordingExporter()
    with pytest.raises(ExportFailedError):
        exporter.prepare(source, track)
    assert source.read_bytes() == b"unreadable recording"
    assert list((tmp_path / "exports").iterdir()) == []
    exporter._lock.acquire()
    try:
        with pytest.raises(ExportBusyError):
            exporter.prepare(source, track)
    finally:
        exporter._lock.release()


def test_native_viewport_export_pads_odd_width_without_moving_marks(tmp_path):
    run = run_record()
    payload = finding(x=1150, y=258, width=110, height=28, viewport_width=1365, viewport_height=768,
                      start_recording_time_ms=200, end_recording_time_ms=400)
    track = annotation_tracks(run, [event(run, 1, "reproduction.finding", **payload)])[0]
    # yuv444p preserves an odd source width; H.264 delivery adds one black column.
    source = tmp_path / "recording" / "tab-a.webm"
    source.parent.mkdir()
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "color=c=white:s=1366x768:r=25:d=1",
                    "-vf", "format=yuv444p,crop=1365:768:0:0", "-c:v", "libvpx-vp9", "-threads", "1", str(source)],
                   check=True, timeout=30, stderr=subprocess.PIPE)
    target = AnnotatedRecordingExporter().prepare(source, track)
    capture = cv2.VideoCapture(str(target))
    try:
        assert capture.get(cv2.CAP_PROP_FRAME_WIDTH) == 1366
        assert capture.get(cv2.CAP_PROP_FRAME_HEIGHT) == 768
        assert capture.get(cv2.CAP_PROP_FRAME_COUNT) == 25
        capture.set(cv2.CAP_PROP_POS_FRAMES, 10)
        ok, frame = capture.read()
        assert ok
        b, g, r = map(int, frame[268, 1150])
        assert r > 180 and r > g + 50 and r > b + 50
    finally:
        capture.release()


def test_annotation_and_export_endpoints_are_owner_only_and_survive_reload(client):
    connection, user, manager = client
    run = run_record(user_id=user.id)
    manager._repository.save_run(run)
    source = make_video(manager._evidence.run_directory(run) / "recording" / "tab-a.webm")
    manager._repository.save_event(event(run, 1, "browser.click", **click()))
    manager._repository.save_event(event(run, 2, "reproduction.finding", **finding()))
    base = f"/api/runs/{run.id}"
    tracks = connection.get(base + "/annotations")
    assert tracks.status_code == 200
    assert tracks.json()[0]["findings"][0]["explanation"].startswith("Shows $42")
    assert connection.get(base).json()["run"]["verdict"]["verdict_id"] == "current"
    assert connection.get(base + "/recordings/1/annotated.mp4").status_code == 404
    assert connection.post(base + "/recordings/1/annotated-export", headers={"Origin": "https://other.test"}).status_code == 403
    response = connection.post(base + "/recordings/1/annotated-export")
    assert response.status_code == 200, response.text
    download = connection.get(response.json()["download_url"])
    assert download.status_code == 200
    assert download.headers["content-type"] == "video/mp4"
    assert "attachment" in download.headers["content-disposition"]
    assert connection.get(base + "/recordings/1.webm").content == source.read_bytes()
    assert connection.post(base + "/recordings/0/annotated-export").status_code == 404
    assert connection.post(base + "/recordings/99/annotated-export").status_code == 404
    user.id = uuid4()
    assert connection.get(base + "/annotations").status_code == 404
    assert connection.post(base + "/recordings/1/annotated-export").status_code == 404
    assert connection.get(base + "/recordings/1/annotated.mp4").status_code == 404


def test_public_session_events_and_recording_metadata_are_saved(client, monkeypatch):
    import time

    from app.tests.test_application import FakeSession
    from navgent import (
        BrowserClickEvent,
        Recording,
        ReproductionFindingEvent,
        ReproductionVerdictEvent,
    )
    from navgent.events import RunCompletedEvent, SessionStatusEvent

    connection, _, manager = client

    class AnnotationSession(FakeSession):
        def __init__(self, directory):
            super().__init__()
            self.directory = directory
            self.recording_paths = []
            self.recordings = []

        async def start(self, task):
            for item in [SessionStatusEvent("running"), BrowserClickEvent(**click()),
                         ReproductionVerdictEvent("reproduced", "$30", "$42", 3, "Mismatch", verdict_id="current"),
                         ReproductionFindingEvent(**finding()), RunCompletedEvent("Compared the total."),
                         SessionStatusEvent("ready_for_follow_up")]:
                await self.queue.put(item)

        async def close(self):
            if not self.closed.is_set():
                self.directory.mkdir(parents=True, exist_ok=True)
                path = self.directory / "tab-a.webm"
                path.write_bytes(b"recording fixture")
                self.recording_paths = [path]
                self.recordings = [Recording("tab-a", path, 320, 180, 1000)]
            await super().close()

    monkeypatch.setattr("app.runs.service.build_agent_runtime", lambda *a, **kw: AnnotationSession(kw["recording_dir"]))
    run_id = connection.post("/api/runs", json={"task": "Compare the cart total"}).json()["run"]["id"]
    base = f"/api/runs/{run_id}"
    for _ in range(100):
        saved = connection.get(base).json()["run"]
        if saved["status"] == "succeeded":
            break
        time.sleep(.01)
    assert saved["status"] == "succeeded"
    assert saved["recording_metadata"] == [{"id": "tab-a", "width": 320, "height": 180, "start_wall_time_ms": 1000}]
    assert saved["verdict"]["verdict_id"] == "current"
    events = connection.get(base + "/events").json()
    assert {item["event_type"] for item in events} >= {"browser.click", "reproduction.finding"}
    assert connection.get(base + "/annotations").json()[0]["findings"][0]["id"] == "finding-1"
    assert "browser.click" in connection.get(base + "/stream").text
