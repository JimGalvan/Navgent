// Positions and times come from the server's shared playback/export timeline.
const byId = id => document.getElementById(id);
const RED = "#ff6b5e", LIME = "#c6f24e", DARK = "#0c0c0d";

function wrapText(context, text, maxWidth) {
  const lines = [];
  let line = "";
  for (const word of text.split(/\s+/)) {
    const candidate = (line + " " + word).trim();
    if (context.measureText(candidate).width <= maxWidth) {
      line = candidate;
      continue;
    }
    if (line) lines.push(line);
    line = "";
    for (const char of word) {
      if (line && context.measureText(line + char).width > maxWidth) {
        lines.push(line);
        line = "";
      }
      line += char;
    }
  }
  if (line) lines.push(line);
  return lines;
}

function drawMarks(ctx, width, height, track, time, reducedMotion) {
  const fontSize = Math.max(14, width / 1365 * 18);
  ctx.font = `500 ${fontSize}px Geist, system-ui, sans-serif`;
  ctx.textBaseline = "top";
  for (const click of track.clicks) {
    const age = time - click.time_ms;
    if (age < 0 || age >= track.click_duration_ms) continue;
    const sx = width / click.viewport_width, sy = height / click.viewport_height;
    const x = click.x * sx, y = click.y * sy;
    const radius = Math.max(8, 10 * sx) + (reducedMotion ? 0 : 16 * sx * age / track.click_duration_ms);
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.lineWidth = Math.max(4, 6 * sx);
    ctx.strokeStyle = DARK;
    ctx.stroke();
    ctx.lineWidth = Math.max(2, 3 * sx);
    ctx.strokeStyle = LIME;
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fillStyle = LIME;
    ctx.fill();
  }
  let labelBottom = 0;
  for (const mark of track.findings) {
    if (time < mark.start_ms || time >= mark.end_ms) continue;
    const sx = width / mark.viewport_width, sy = height / mark.viewport_height;
    const x = mark.x * sx, y = mark.y * sy, w = mark.width * sx, h = mark.height * sy;
    ctx.strokeStyle = RED;
    ctx.lineWidth = Math.max(2, 3 * sx);
    ctx.strokeRect(x, y, w, h);
    const pad = 8, gap = 6, lineHeight = fontSize + 5;
    const maxWidth = Math.min(Math.max(240, 420 * sx), width - 4 * pad);
    let lines = wrapText(ctx, `${mark.number} · ${mark.explanation}`, maxWidth);
    const maxLines = Math.max(1, Math.min(3, Math.floor((height - 32) / lineHeight)));
    if (lines.length > maxLines) {
      lines = lines.slice(0, maxLines);
      let last = lines[maxLines - 1];
      while (last && ctx.measureText(last + "…").width > maxWidth) last = last.slice(0, -1);
      lines[maxLines - 1] = last + "…";
    }
    const lw = Math.min(width - 2 * pad, Math.max(...lines.map(line => ctx.measureText(line).width)) + 2 * pad);
    const lh = lines.length * lineHeight + 2 * pad;
    const lx = Math.max(pad, Math.min(x, width - lw - pad));
    let ly = y >= lh + gap + pad ? y - lh - gap : y + h + gap;
    ly = Math.max(pad, Math.min(Math.max(ly, labelBottom), height - lh - pad));
    ctx.fillStyle = RED;
    ctx.fillRect(lx, ly, lw, lh);
    ctx.fillStyle = DARK;
    lines.forEach((line, index) => ctx.fillText(line, lx + pad, ly + pad + index * lineHeight));
    labelBottom = ly + lh + gap;
  }
}

function timeLabel(milliseconds) {
  const seconds = Math.floor(milliseconds / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export async function mountRecordings(run, request) {
  if (!run.recordings?.length) return;
  const video = byId("recording-player"), stage = byId("recording-stage");
  const canvas = byId("recording-overlay"), ctx = canvas.getContext("2d");
  const tabs = byId("recording-tab"), marks = byId("recording-marks");
  const findings = byId("recording-findings"), caption = byId("recording-caption");
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  let tracks = [], selected = 1, frameCallback = null, disposed = false;
  const currentTrack = () => tracks.find(track => track.number === selected);
  const originalUrl = number => `/api/runs/${run.id}/recordings/${number}.webm`;

  function draw(mediaTime = video.currentTime) {
    const bounds = video.getBoundingClientRect();
    if (!video.videoWidth || !bounds.width || !bounds.height) return;
    const scale = Math.min(bounds.width / video.videoWidth, bounds.height / video.videoHeight);
    const width = video.videoWidth * scale, height = video.videoHeight * scale;
    const stageBounds = stage.getBoundingClientRect();
    canvas.style.left = `${bounds.left - stageBounds.left + (bounds.width - width) / 2}px`;
    canvas.style.top = `${bounds.top - stageBounds.top + (bounds.height - height) / 2}px`;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    const dpr = devicePixelRatio || 1;
    if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const track = currentTrack();
    if (marks.checked && track && !video.seeking) drawMarks(ctx, width, height, track, mediaTime * 1000, reducedMotion.matches);
  }

  function stopFrames() {
    if (frameCallback === null) return;
    if (video.cancelVideoFrameCallback) video.cancelVideoFrameCallback(frameCallback);
    else cancelAnimationFrame(frameCallback);
    frameCallback = null;
  }
  function nextFrame() {
    if (disposed || video.paused || video.ended) return;
    if (video.requestVideoFrameCallback) {
      frameCallback = video.requestVideoFrameCallback((_, metadata) => {
        frameCallback = null;
        draw(metadata.mediaTime);
        nextFrame();
      });
    } else {
      frameCallback = requestAnimationFrame(() => {
        frameCallback = null;
        draw();
        nextFrame();
      });
    }
  }
  function renderTrack() {
    const track = currentTrack();
    const hasMarks = Boolean(track && (track.clicks.length || track.findings.length));
    byId("recording-marks-label").hidden = !hasMarks;
    caption.textContent = hasMarks
      ? `${track.clicks.length} click${track.clicks.length === 1 ? "" : "s"} · ${track.findings.length} finding${track.findings.length === 1 ? "" : "s"}. ${track.findings.length ? "Select a finding to jump to it." : "Lime pulses mark clicks."}`
      : "No click or finding markers were saved for this tab.";
    findings.replaceChildren();
    for (const mark of track?.findings || []) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "finding-jump";
      button.textContent = `${timeLabel(mark.start_ms)} · ${mark.number}. ${mark.explanation}`;
      button.addEventListener("click", () => {
        marks.checked = true;
        video.currentTime = Math.min(mark.start_ms / 1000, Number.isFinite(video.duration) ? video.duration : Infinity);
        video.pause();
      });
      findings.append(button);
    }
    draw();
  }
  function select(number) {
    stopFrames();
    video.pause();
    selected = number;
    canvas.width = canvas.width; // Clear the preceding tab immediately.
    video.src = originalUrl(number);
    video.setAttribute("aria-label", `Browser recording, tab ${number}`);
    byId("recording-error").textContent = "";
    renderTrack();
  }

  for (let index = 0; index < run.recordings.length; index++) {
    const number = index + 1;
    tabs.add(new Option(`Tab ${number}`, String(number)));
    const row = document.createElement("div");
    row.className = "recording-download-row";
    const original = document.createElement("a");
    original.href = originalUrl(number);
    original.className = "download";
    original.download = `recording-${number}.webm`;
    original.textContent = `WebM video · tab ${number}`;
    row.append(original);
    if (["succeeded", "failed", "cancelled", "timed_out"].includes(run.status)) {
      const exportButton = document.createElement("button");
      exportButton.type = "button";
      exportButton.className = "text-button annotated-export";
      exportButton.dataset.recordingNumber = String(number);
      exportButton.hidden = true;
      exportButton.textContent = `Export annotated MP4 · tab ${number}`;
      const status = document.createElement("span");
      status.className = "notice export-status";
      status.setAttribute("role", "status");
      exportButton.addEventListener("click", async () => {
        exportButton.disabled = true;
        exportButton.textContent = `Preparing MP4 · tab ${number}…`;
        status.textContent = "";
        try {
          const result = await request(`/api/runs/${run.id}/recordings/${number}/annotated-export`, {method: "POST"});
          const download = document.createElement("a");
          download.className = "download";
          download.href = result.download_url;
          download.download = `recording-${number}-annotated.mp4`;
          download.textContent = `Download annotated MP4 · tab ${number}`;
          exportButton.replaceWith(download);
          status.textContent = "Ready to download.";
          download.focus();
        } catch (error) {
          exportButton.disabled = false;
          exportButton.textContent = `Retry annotated MP4 · tab ${number}`;
          status.textContent = error.message;
        }
      });
      row.append(exportButton, status);
    }
    byId("recording-downloads").append(row);
  }
  byId("recording-section").hidden = false;
  byId("recording-tab-label").hidden = run.recordings.length < 2;
  tabs.addEventListener("change", () => select(Number(tabs.value)));
  marks.addEventListener("change", () => draw());
  for (const name of ["loadedmetadata", "loadeddata", "seeked", "seeking", "timeupdate", "ended"]) video.addEventListener(name, () => draw());
  video.addEventListener("pause", () => { stopFrames(); draw(); });
  video.addEventListener("play", () => { stopFrames(); nextFrame(); });
  video.addEventListener("error", () => {
    byId("recording-error").textContent = "This recording could not be played. Try downloading the original WebM.";
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  });
  byId("recording-fullscreen").hidden = !document.fullscreenEnabled;
  byId("recording-fullscreen").addEventListener("click", async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await stage.requestFullscreen();
    } catch {
      byId("recording-error").textContent = "Full screen is unavailable in this browser.";
    }
  });
  const observer = new ResizeObserver(() => draw());
  observer.observe(stage);
  window.addEventListener("pagehide", () => {
    disposed = true;
    stopFrames();
    observer.disconnect();
  }, {once: true});
  document.fonts.ready.then(() => draw());
  select(1);
  try {
    tracks = await request(`/api/runs/${run.id}/annotations`);
    for (const button of document.querySelectorAll(".annotated-export")) {
      const track = tracks.find(item => item.number === Number(button.dataset.recordingNumber));
      button.hidden = !track || !(track.clicks.length || track.findings.length);
    }
    renderTrack();
  } catch {
    caption.textContent = "Markers could not be loaded. Reload to try again; the original recording is available.";
  }
}
