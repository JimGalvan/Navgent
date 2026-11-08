"""Exercise real video seeking, canvas scaling and the export controls."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import imageio_ffmpeg
import pytest
from playwright.sync_api import expect, sync_playwright

from app.runs.annotations import AnnotationTrack, annotation_tracks
from app.runs.proof import render_proof_frame
from app.tests.test_annotated_recordings import (
    click,
    event,
    finding,
    run_record,
)

STATIC = Path(__file__).resolve().parents[1] / "server" / "static"
CAPTURES = Path(__file__).resolve().parents[1] / ".cache" / "annotated-ui"
VIEWPORT = {"width": 1365, "height": 768}
CLICK_X, CLICK_Y = 205, 228
FIND_X, FIND_Y = 1150, 258


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture(scope="module")
def clip(browser, tmp_path_factory):
    directory = tmp_path_factory.mktemp("overlay-clip")
    page = browser.new_page(viewport=VIEWPORT)
    page.set_content("""<!doctype html><html><head><style>
        * {box-sizing:border-box} body {margin:0;background:#f6f6f4;color:#111;font:18px Arial,sans-serif}
        header {height:80px;border-bottom:1px solid #ddd;background:white;padding:25px 48px;font-weight:bold;font-size:24px}
        header span {float:right;font-size:18px;font-weight:normal} h1 {margin:40px 48px;font-size:28px}
        .item {position:absolute;left:48px;top:180px;width:680px;background:white;border:1px solid #ddd;padding:24px;}
        .item strong {display:block;margin-bottom:8px}.item span {float:right;font-weight:bold}
        button {margin:12px 0 0 72px;background:white;border:1px solid #bbb;padding:7px 16px}
        .summary {position:absolute;left:820px;top:110px;width:497px;height:210px;background:white;border:1px solid #ddd;padding:24px}
        h2 {margin:0 0 20px;font-size:22px}.row {display:flex;justify-content:space-between;margin:15px 0}
        .total {position:absolute;left:844px;top:245px;width:449px;border-top:1px solid #ddd;padding-top:13px;font-size:24px;font-weight:bold}
        .amount {position:absolute;left:1150px;top:258px;font-size:24px;font-weight:bold}
        </style></head><body><header>northwind supply <span>Cart (1)</span></header><h1>Your cart</h1>
        <div class="item"><span>$60.00</span><strong>Trail Pack 30L</strong>Moss · qty 1<br><button>Remove item</button></div>
        <div class="summary"><h2>Summary</h2><div class="row">Subtotal <span>$60.00</span></div><div class="row">SAVE50 <span>−$30.00</span></div></div>
        <div class="total">Total</div><div class="amount">$42.00</div></body></html>""")
    image = directory / "cart.png"
    page.screenshot(path=image)
    page.close()
    video = directory / "tab-a.webm"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
                    "-loop", "1", "-i", str(image), "-t", "3.2", "-r", "25", "-c:v", "libvpx-vp9",
                    "-threads", "1", "-an", str(video)], check=True, timeout=30, stderr=subprocess.PIPE)
    return video.read_bytes()


@pytest.fixture(params=[1440, 390], ids=["desktop", "mobile"])
def surface(browser, clip, request, tmp_path):
    context = browser.new_context(viewport={"width": request.param, "height": 1000},
                                  device_scale_factor=2 if request.param == 390 else 1)
    page = context.new_page()
    run = run_record()
    run.task = json.dumps({"title": "Cart total after removing a discounted item", "expected": "$30.00"})
    click_payload = click()
    click_payload.update(x=CLICK_X, y=CLICK_Y, viewport_width=1365, viewport_height=768)
    finding_payload = finding(x=FIND_X, y=FIND_Y, width=110, height=28, viewport_width=1365, viewport_height=768)
    records = [event(run, 1, "browser.click", **click_payload), event(run, 2, "reproduction.finding", **finding_payload)]
    state = SimpleNamespace(run=run, tracks=[t.model_dump() for t in annotation_tracks(run, records)],
                            exports=[], fail_export=False, annotations_fail=False, proof_enabled=False, errors=[])
    page.on("pageerror", lambda error: state.errors.append(str(error)))

    def handle(route):
        path = urlsplit(route.request.url).path
        if path == "/api/auth/me":
            route.fulfill(json={"email": "recordings@example.test"})
        elif path == f"/api/runs/{run.id}":
            route.fulfill(json={"run": run.model_dump(mode="json"), "screen_url": f"/api/runs/{run.id}/screen.jpg"})
        elif path.endswith("/annotations"):
            if state.annotations_fail:
                route.fulfill(status=500, json={"detail": "Unavailable"})
            else:
                route.fulfill(json=state.tracks)
        elif path.endswith("/proof-frame"):
            if not state.proof_enabled:
                route.fulfill(status=404, json={"detail": "No finding frame"})
            else:
                route.fulfill(json={"image_url": f"/api/runs/{run.id}/proof-frame.jpg", "recording_number": 1,
                                    "time_ms": 1100, "step_number": 3, "explanation": "Shows $42.00. Expected $30.00.",
                                    "expected": "$30.00", "observed": "$42.00"})
        elif path.endswith("/proof-frame.jpg"):
            source = tmp_path / "proof-source.webm"
            source.write_bytes(clip)
            track = AnnotationTrack.model_validate(state.tracks[0])
            route.fulfill(content_type="image/jpeg", body=render_proof_frame(source, track, track.findings[0]))
        elif path.endswith("/events"):
            route.fulfill(json=[e.model_dump(mode="json") for e in records])
        elif path.endswith("screen.jpg"):
            route.fulfill(status=204)
        elif path.endswith("/annotated-export"):
            state.exports.append(path)
            route.fulfill(status=422 if state.fail_export else 200,
                          json={"detail": "The video could not be created. Try again."} if state.fail_export
                          else {"download_url": f"/api/runs/{run.id}/recordings/1/annotated.mp4"})
        elif path.endswith(".webm"):
            byte_range = route.request.headers.get("range")
            if byte_range:
                first, last = byte_range.removeprefix("bytes=").split("-", 1)
                start, end = int(first or 0), int(last or len(clip) - 1)
                route.fulfill(status=206, content_type="video/webm", body=clip[start:end + 1],
                              headers={"Accept-Ranges": "bytes", "Content-Range": f"bytes {start}-{end}/{len(clip)}"})
            else:
                route.fulfill(content_type="video/webm", body=clip, headers={"Accept-Ranges": "bytes"})
        elif path.startswith("/static/"):
            route.fulfill(path=STATIC / path.removeprefix("/static/"))
        elif path.startswith("/app/reports/"):
            route.fulfill(path=STATIC / "report.html")
        else:
            route.fulfill(status=404)

    page.route("http://reprobe.test/**", handle)
    state.page = page
    state.width = request.param
    state.open = lambda: page.goto(f"http://reprobe.test/app/reports/{run.id}")
    yield state
    context.close()
    assert state.errors == []


def seek(page, seconds):
    page.locator("#recording-player").evaluate("(video, time) => { video.pause(); video.currentTime = time; }", seconds)
    page.wait_for_function("!document.querySelector('video').seeking && document.querySelector('video').readyState >= 2")


def canvas_pixel(page, x, y):
    return page.locator("#recording-overlay").evaluate("""(canvas, point) => {
        const x = Math.round(canvas.width * point[0] / 1365);
        const y = Math.round(canvas.height * point[1] / 768);
        return [...canvas.getContext('2d').getImageData(x, y, 1, 1).data];
    }""", [x, y])


def test_seek_toggle_tab_switch_and_responsive_markers(surface):
    surface.open()
    page = surface.page
    expect(page.locator("#recording-caption")).to_contain_text("1 click · 1 finding")
    page.wait_for_function("document.querySelector('video').readyState >= 2")
    seek(page, .4)
    page.wait_for_function("document.querySelector('#recording-overlay').width > 0")
    assert canvas_pixel(page, CLICK_X, CLICK_Y) == [198, 242, 78, 255], page.evaluate("""() => {
        const v = document.querySelector('video'), c = document.querySelector('canvas');
        const data = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
        return JSON.stringify({time: v.currentTime, duration: v.duration, seeking: v.seeking, w: c.width, h: c.height,
                alphaPixels: [...data].filter((v,i) => i%4 === 3 && v > 0).length,
                vw: v.videoWidth, vh: v.videoHeight, checked: document.querySelector('#recording-marks').checked});
    }""")
    seek(page, .9)
    assert canvas_pixel(page, CLICK_X, CLICK_Y)[3] == 0
    page.locator(".finding-jump").click()
    page.wait_for_function("!document.querySelector('video').seeking")
    assert page.locator("video").evaluate("video => video.currentTime") == pytest.approx(1, abs=.04)
    assert canvas_pixel(page, FIND_X, FIND_Y + 10)[3] > 0
    page.locator("#recording-marks").uncheck()
    assert canvas_pixel(page, FIND_X, FIND_Y + 10)[3] == 0
    page.locator("#recording-marks").check()
    assert canvas_pixel(page, FIND_X, FIND_Y + 10)[3] > 0
    seek(page, 3.15)
    assert canvas_pixel(page, FIND_X, FIND_Y + 10)[3] > 0  # The final frame still lies inside the finding's interval.
    page.locator("#recording-tab").select_option("2")
    expect(page.locator("#recording-player")).to_have_attribute("src", f"/api/runs/{surface.run.id}/recordings/2.webm")
    expect(page.locator("#recording-marks-label")).to_be_hidden()
    expect(page.locator(".finding-jump")).to_have_count(0)
    expect(page.locator("#recording-caption")).to_contain_text("No click or finding markers")
    page.locator("#recording-tab").select_option("1")
    expect(page.locator(".finding-jump")).to_have_count(1)
    page.locator(".finding-jump").click()
    page.wait_for_function("!document.querySelector('video').seeking")
    page.evaluate("document.fonts.ready")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    CAPTURES.mkdir(parents=True, exist_ok=True)
    page.locator("#recording-section").screenshot(path=CAPTURES / f"recording-{surface.width}.png")


def test_export_failure_retry_and_download(surface):
    surface.open()
    page = surface.page
    surface.fail_export = True
    page.locator(".annotated-export").first.click()
    expect(page.locator(".export-status").first).to_contain_text("could not be created")
    expect(page.locator(".annotated-export").first).to_be_enabled()
    surface.fail_export = False
    page.locator(".annotated-export").first.click()
    expect(page.get_by_role("link", name="Download annotated MP4 · tab 1")).to_be_visible()
    assert len(surface.exports) == 2


def test_old_runs_and_missing_annotation_data_keep_original_playback(surface):
    surface.tracks = []
    surface.open()
    expect(surface.page.locator("#recording-section")).to_be_visible()
    expect(surface.page.locator("#recording-caption")).to_contain_text("No click or finding markers")
    expect(surface.page.locator("#recording-marks-label")).to_be_hidden()
    expect(surface.page.get_by_role("link", name="WebM video · tab 1")).to_be_visible()
    surface.annotations_fail = True
    surface.page.reload()
    expect(surface.page.locator("#recording-caption")).to_contain_text("Markers could not be loaded")


def test_playback_speed_reduced_motion_and_fullscreen_keep_marks(surface):
    surface.open()
    page = surface.page
    page.emulate_media(reduced_motion="reduce")
    expect(page.locator("#recording-caption")).to_contain_text("1 click")
    page.wait_for_function("document.querySelector('video').readyState >= 2")
    seek(page, .3)
    before = page.locator("canvas").evaluate("c => c.toDataURL()")
    seek(page, .6)
    assert page.locator("canvas").evaluate("c => c.toDataURL()") == before
    page.locator(".finding-jump").click()
    page.wait_for_function("!document.querySelector('video').seeking")
    if page.evaluate("document.fullscreenEnabled"):
        page.locator("#recording-fullscreen").click()
        page.wait_for_function("document.fullscreenElement?.id === 'recording-stage'")
        page.wait_for_function("document.querySelector('canvas').getBoundingClientRect().width > 0")
        assert canvas_pixel(page, FIND_X, FIND_Y + 10)[3] > 0
        page.evaluate("document.exitFullscreen()")
        page.wait_for_function("document.fullscreenElement === null")
    page.locator("video").evaluate("video => { video.playbackRate = 2; video.currentTime = .9; }")
    page.wait_for_function("!document.querySelector('video').seeking")
    page.locator("video").evaluate("video => video.play()")
    page.wait_for_function("document.querySelector('video').currentTime > 1.1")
    assert canvas_pixel(page, FIND_X, FIND_Y + 10)[3] > 0
    page.locator("video").evaluate("video => video.pause()")


def test_report_proof_tabs_and_step_markers_seek_the_saved_media_position(surface):
    surface.open()
    page = surface.page
    expect(page.locator("#proof-video")).to_have_attribute("aria-selected", "true")
    expect(page.locator("#proof-frame")).to_be_disabled()
    # The fixture's finding has a known media position and a brief-step reference.
    jump = page.get_by_role("button", name="Jump to step 3, tab 1, 0:01", exact=True)
    expect(jump).to_be_visible()
    page.locator("#recording-tab").select_option("2")
    jump.click()
    expect(page.locator("#recording-tab")).to_have_value("1")
    page.wait_for_function("!document.querySelector('video').seeking && document.querySelector('video').currentTime >= .99")
    assert page.locator("video").evaluate("video => video.currentTime") == pytest.approx(1, abs=.04)


def test_finding_frame_explains_observation_and_links_to_the_recorded_step(surface):
    surface.proof_enabled = True
    surface.run.repro_brief = {
        "steps": [{"instruction": title, "source": f"written step {index}"}
                  for index, title in enumerate(["Open the cart", "Remove the bottle", "Check the total"], 1)],
        "assertion": {"check": "Compare the cart total", "expected": "$30.00", "reported_actual": "$42.00", "look_in": "page"},
        "unknowns": [],
    }
    surface.open()
    page = surface.page
    expect(page.locator("#proof-frame")).to_have_text("Finding frame")
    expect(page.locator("#proof-frame")).to_have_attribute("aria-selected", "true")
    expect(page.locator("#evidence img")).to_be_visible()
    expect(page.locator("#proof-explanation")).to_contain_text("Shows $42.00. Expected $30.00.")
    expect(page.locator("#proof-explanation")).to_contain_text("Expected$30.00")
    expect(page.locator("#proof-explanation")).to_contain_text("Observed$42.00")
    expect(page.locator("#evidence-caption")).to_contain_text("Recorded finding · tab 1 · 0:01")
    page.get_by_role("button", name="Show step 3", exact=True).click()
    expect(page.locator('.report-step[data-step="3"]')).to_have_attribute("open", "")
    expect(page.locator('.report-step[data-step="3"] summary')).to_be_focused()
    CAPTURES.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=CAPTURES / f"finding-proof-{surface.width}.png", full_page=True)
    page.locator("#proof-video").click()
    expect(page.locator("#recording-section")).to_be_visible()
    expect(page.locator("#proof-video")).to_have_attribute("aria-selected", "true")
    expect(page.locator("#download-proof")).to_have_attribute("download", f"{surface.run.id}-finding.jpg")
