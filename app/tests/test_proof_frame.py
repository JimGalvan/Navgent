"""Finding stills retain the observed moment, ownership and raw recordings."""

import io
import sqlite3
from uuid import uuid4

import cv2
import numpy as np
from PIL import Image

from app.runs.repository import RunRepository
from app.tests.test_annotated_recordings import event, finding, make_video, run_record
from app.tests.test_application import client as client


def test_proof_frame_uses_finding_moment_and_survives_reload(client):
    connection, user, manager = client
    run = run_record(user_id=user.id)
    manager._repository.save_run(run)
    source = make_video(manager._evidence.run_directory(run) / "recording" / "tab-a.webm")
    original = source.read_bytes()
    manager._repository.save_event(event(run, 1, "reproduction.finding", **finding()))
    base = f"/api/runs/{run.id}"
    info = connection.get(base + "/proof-frame")
    assert info.status_code == 200, info.text
    assert info.json()["step_number"] == 3
    assert info.json()["expected"] == "$30"
    assert info.json()["observed"] == "$42"
    assert 1000 <= info.json()["time_ms"] < 1200
    response = connection.get(info.json()["image_url"])
    assert response.status_code == 200
    image = Image.open(io.BytesIO(response.content))
    r, g, b = image.getpixel((160, 70))
    assert r > 180 and r > g + 50 and r > b + 50
    assert source.read_bytes() == original
    # A replaced verdict must never reuse the preceding finding's rectangle.
    run.reported_verdict.verdict_id = "replacement"
    manager._repository.save_run(run)
    assert connection.get(base + "/proof-frame").status_code == 404
    assert connection.get(base + "/proof-frame.jpg").status_code == 404
    user.id = uuid4()
    assert connection.get(base + "/proof-frame").status_code == 404
    assert connection.get(base + "/proof-frame.jpg").status_code == 404


def test_proof_still_is_not_the_last_video_frame(client):
    connection, user, manager = client
    run = run_record(user_id=user.id)
    manager._repository.save_run(run)
    directory = manager._evidence.run_directory(run) / "recording"
    directory.mkdir(parents=True)
    source = directory / "tab-a.webm"
    video = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"VP80"), 25, (320, 180))
    assert video.isOpened()
    try:
        for index in range(80):
            video.write(np.full((180, 320, 3), 255 if index < 40 else 0, dtype=np.uint8))
    finally:
        video.release()
    manager._repository.save_event(event(run, 1, "reproduction.finding", **finding()))
    response = connection.get(f"/api/runs/{run.id}/proof-frame.jpg")
    assert response.status_code == 200
    image = Image.open(io.BytesIO(response.content))
    assert min(image.getpixel((20, 160))) > 230  # The observed white page, not the later black page.


def test_legacy_bug_identity_is_preserved_per_user_and_task(tmp_path):
    repository = RunRepository(tmp_path / "runs.db")
    repository.initialize()
    user = uuid4()
    first = run_record(user_id=user)
    second = run_record(user_id=user)
    other = run_record(user_id=uuid4())
    for run in [first, second, other]:
        repository.save_run(run)
    with sqlite3.connect(tmp_path / "runs.db") as connection:
        connection.execute("ALTER TABLE runs DROP COLUMN bug_id")
    repository.initialize()
    assert repository.get_run(first.id).bug_id == repository.get_run(second.id).bug_id
    assert repository.get_run(first.id).bug_id != repository.get_run(other.id).bug_id
    identity = repository.get_run(first.id).bug_id
    repository.initialize()
    assert repository.get_run(first.id).bug_id == identity
