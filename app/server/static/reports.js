const byId = id => document.getElementById(id);
const terminal = new Set(["succeeded", "failed", "cancelled", "timed_out"]);
const results = { reproduced: "Reproduced", not_reproduced: "Not reproduced", inconclusive: "Inconclusive" };
const statuses = {
  queued: "Queued", reading_evidence: "Reading evidence", running: "Running",
  waiting_for_input: "Needs your input", ready_for_follow_up: "Saving result",
  succeeded: "Completed", failed: "Failed", cancelled: "Stopped", timed_out: "Timed out",
};

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

export function resultKey(run) {
  // A partial observation does not turn an interrupted run into a reproduced bug.
  if (terminal.has(run.status) && run.status !== "succeeded") return run.status;
  return run.verdict?.verdict || (run.status === "succeeded" ? "inconclusive" : run.status);
}

function resultLabel(run) {
  const key = resultKey(run);
  return results[key] || statuses[key] || key;
}

function taskData(run) {
  try {
    const data = JSON.parse(run.task);
    return data && typeof data === "object" ? data : { title: run.task };
  }
  catch { return { title: run.task }; }
}

function bugKey(run) {
  // Older API fixtures can still fall back to their original exact-task grouping.
  return run.bug_id || run.task;
}

export function groupRuns(runs) {
  const groups = new Map();
  const ordered = [...runs].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
  for (const run of ordered) {
    const key = bugKey(run);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(run);
  }
  return [...groups.values()];
}

function runLink(run) {
  if (location.pathname.startsWith("/preview")) return terminal.has(run.status) ? "/preview/report" : "/preview/live";
  return `/app/${terminal.has(run.status) ? "reports" : "runs"}/${run.id}`;
}

function hostName(run) {
  try { return new URL(taskData(run).url).host; }
  catch { return "No target URL saved"; }
}

function dateLabel(value, withTime = false) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "";
  return date.toLocaleString(undefined, {
    month: "short", day: "numeric", year: "numeric",
    ...(withTime ? { hour: "numeric", minute: "2-digit" } : {}),
  });
}

function runMarker(run, currentId) {
  const label = `${resultLabel(run)} · ${dateLabel(run.created_at, true)}`;
  const link = element("a", undefined, `run-marker ${resultKey(run)}`);
  link.href = runLink(run);
  link.title = label;
  link.setAttribute("aria-label", `${label} · Run ${run.id.slice(0, 8)}`);
  if (run.id === currentId) link.setAttribute("aria-current", "page");
  return link;
}

function historyStory(group) {
  const latest = group[0];
  const label = `${resultLabel(latest)} · ${dateLabel(latest.created_at)}`;
  if (group.length === 1) return label;
  for (const previous of group.slice(1)) {
    if (resultKey(previous) !== resultKey(latest)) {
      return `${group.length} recent runs · ${resultLabel(previous)} ${dateLabel(previous.created_at)} → ${label}`;
    }
  }
  return `${group.length} recent runs · ${label}`;
}

export function renderReports(runs, request) {
  const groups = groupRuns(runs);
  const host = byId("history");
  let filter = "all";
  byId("reports-count").textContent = `${groups.length} bug${groups.length === 1 ? "" : "s"} · ${runs.length} recent run${runs.length === 1 ? "" : "s"}`;
  const buttons = [...byId("report-filters").querySelectorAll("button")];
  for (const button of buttons) {
    const key = button.dataset.filter;
    const count = key === "all" ? groups.length : groups.filter(group => resultKey(group[0]) === key).length;
    button.textContent = `${key === "all" ? "All" : results[key]} ${count}`;
    button.onclick = () => { filter = key; render(); };
  }
  function render() {
    host.replaceChildren();
    for (const button of buttons) button.setAttribute("aria-pressed", String(button.dataset.filter === filter));
    const visible = groups.filter(group => filter === "all" || resultKey(group[0]) === filter);
    if (!visible.length) {
      host.append(element("p", runs.length ? "No bugs match this result. Choose another filter." : "No reproductions yet. Test a bug to start your report history.", "empty"));
      return;
    }
    const list = element("ul", undefined, "bug-list");
    for (const group of visible) {
      const latest = group[0];
      const row = element("li", undefined, "bug-row");
      const dot = element("span", undefined, `dot ${resultKey(latest)}`);
      dot.setAttribute("aria-hidden", "true");
      const identity = element("div", undefined, "bug-identity");
      const title = element("a", taskData(latest).title || "Reproduction");
      title.href = runLink(latest);
      identity.append(title, element("span", hostName(latest), "mono muted"));
      const history = element("div", undefined, "bug-run-history");
      const markers = element("nav", undefined, "run-markers");
      markers.setAttribute("aria-label", `Run history for ${title.textContent}`);
      for (const run of [...group].reverse()) markers.append(runMarker(run));
      history.append(markers, element("span", historyStory(group)));
      const result = element("span", resultLabel(latest), `bug-latest ${resultKey(latest)}`);
      const rerun = element("button", terminal.has(latest.status) ? "Run again" : "Open live viewer", "button secondary");
      rerun.type = "button";
      rerun.setAttribute("aria-label", `${rerun.textContent}: ${title.textContent}`);
      rerun.onclick = async () => {
        if (!terminal.has(latest.status)) { location.href = runLink(latest); return; }
        if (location.pathname.startsWith("/preview")) { location.href = "/preview/new"; return; }
        rerun.disabled = true;
        byId("history-message").textContent = "";
        try {
          const response = await request(`/api/runs/${latest.id}/rerun`, { method: "POST" });
          location.href = `/app/runs/${response.run.id}`;
        } catch (error) {
          byId("history-message").textContent = error.message;
          rerun.disabled = false;
        }
      };
      row.append(dot, identity, history, result, rerun);
      list.append(row);
    }
    host.append(list);
  }
  render();
}

export function renderReportHeader(run, duration) {
  const key = resultKey(run);
  byId("run-status").textContent = resultLabel(run);
  byId("run-dot").className = `dot ${key}`;
  byId("report-result").dataset.result = key;
  byId("run-duration").textContent = duration;
  const date = byId("run-date");
  date.textContent = dateLabel(run.created_at, true);
  date.dateTime = run.created_at;
  byId("run-host").textContent = hostName(run);
}

export async function renderBugHistory(run, request) {
  const host = byId("bug-history");
  const panel = byId("bug-history-panel");
  const summary = byId("bug-history-summary");
  try {
    const response = await request("/api/runs");
    const runs = response.runs.filter(item => item.id !== run.id);
    runs.push(run);
    const group = groupRuns(runs).find(items => items.some(item => item.id === run.id));
    summary.textContent = `Run history · ${group.length} run${group.length === 1 ? "" : "s"}`;
    const list = element("ol", undefined, "history-list");
    for (const item of group) {
      const link = element("a", undefined, `history-result ${resultKey(item)}`);
      link.title = taskData(item).url || "";
      link.href = runLink(item);
      const date = element("time", dateLabel(item.created_at, true));
      date.dateTime = item.created_at;
      link.append(element("span", resultLabel(item), "history-status"), date,
                  element("span", taskData(item).url || "No target URL saved", "history-environment"),
                  element("span", item.id === run.id ? "Viewing" : "View run", "history-view"));
      if (item.id === run.id) link.setAttribute("aria-current", "page");
      const row = element("li");
      row.append(link);
      list.append(row);
    }
    host.replaceChildren(list);
    panel.hidden = group.length < 2;
  } catch {
    panel.hidden = false;
    summary.textContent = "Run history unavailable";
    host.textContent = "Run history unavailable. Reload to try again.";
  }
}

export function renderChecks(verdict, brief) {
  const host = byId("verdict");
  host.replaceChildren(element("h2", "Checks", "section-title"));
  host.hidden = false;
  if (!verdict && !brief?.assertion) {
    host.append(element("p", "No verification check was saved for this run.", "muted"));
    return;
  }
  const scroll = element("div", undefined, "checks-scroll");
  scroll.tabIndex = 0;
  scroll.setAttribute("role", "region");
  scroll.setAttribute("aria-label", "Reproduction check results");
  const table = element("table", undefined, "checks-table");
  const head = table.createTHead().insertRow();
  for (const label of ["Check", "Expected", "Observed", "Result"]) {
    const th = element("th", label);
    th.scope = "col";
    head.append(th);
  }
  const row = table.createTBody().insertRow();
  row.insertCell().textContent = brief?.assertion?.check || "Reproduce the reported bug";
  row.insertCell().textContent = verdict?.expected || brief?.assertion?.expected || "Not recorded";
  const observed = row.insertCell();
  observed.className = verdict?.verdict === "reproduced" ? "bad" : "";
  for (const quote of (verdict?.observed || "No observation recorded").split("; ")) observed.append(element("div", quote, "observed-quote"));
  const result = row.insertCell();
  result.append(element("span", verdict ? results[verdict.verdict] : "Not verified"));
  if (verdict?.verdict === "reproduced" && verdict.step_number) result.append(element("small", `Step ${verdict.step_number}`));
  scroll.append(table);
  host.append(scroll);
  if (verdict?.reason) host.append(element("p", verdict.reason, "check-reason muted"));
}

export function arrangeReportSteps(run, events) {
  const host = byId("action-log");
  const groups = [...host.querySelectorAll(".action-group")];
  host.replaceChildren();
  const steps = run.repro_brief?.steps || [];
  const failedStep = run.verdict?.verdict === "reproduced" ? run.verdict.step_number : null;
  const used = new Set();
  function addStep(group, number, instruction) {
    const actions = events.filter(event => event.payload?.brief_step === number && event.event_type.startsWith("browser.action."));
    const failed = number === failedStep || actions.some(event => event.event_type === "browser.action.failed");
    const completed = actions.some(event => event.event_type === "browser.action.completed");
    const details = element("details", undefined, "report-step");
    if (number) details.dataset.step = String(number);
    details.dataset.result = failed ? "failed" : completed ? "completed" : "unrecorded";
    details.open = number === failedStep;
    const summary = element("summary");
    const marker = element("span", number || "–", "step-number mono");
    const copy = element("span", instruction);
    copy.append(element("small", number === failedStep ? "Bug observed" : failed ? "Action failed" : completed ? "Actions completed" : "No actions recorded"));
    summary.append(marker, copy);
    details.append(summary);
    const body = element("div", undefined, "report-step-body");
    if (group) {
      group.querySelector(".action-group-title")?.remove();
      for (const label of group.querySelectorAll(".action-row > p:first-child")) {
        if (label.textContent === `Step ${number}`) label.remove();
      }
      body.append(group);
      used.add(group);
    }
    else body.append(element("p", "No browser actions were saved for this step.", "muted"));
    if (number && steps[number - 1]?.source) body.append(element("p", `Source: ${steps[number - 1].source}`, "notice"));
    details.append(body);
    host.append(details);
  }
  for (let index = 0; index < steps.length; index++) {
    const number = index + 1;
    addStep(groups.find(group => group.dataset.briefStep === String(number)), number, steps[index].instruction);
  }
  for (const group of groups) {
    if (!used.has(group)) addStep(group, Number(group.dataset.briefStep) || null, group.querySelector("h3")?.textContent || "Browser actions");
  }
  if (!host.childElementCount) host.append(element("p", "No steps or browser actions were saved for this run.", "muted"));
  byId("steps-heading").textContent = `Steps${steps.length ? ` · ${steps.length}` : ""}`;
  renderStepTimeline(run, events);
}

function renderStepTimeline(run, events) {
  const timeline = byId("proof-timeline");
  const positions = new Map();
  for (const event of events) {
    if (!["browser.click", "reproduction.finding"].includes(event.event_type)) continue;
    const payload = event.payload;
    if (!Number.isInteger(payload.brief_step) || payload.brief_step < 1) continue;
    const number = (run.recordings || []).findIndex(name => name.replace(/\.webm$/, "") === payload.recording_id) + 1;
    if (!number) continue;
    const finding = event.event_type === "reproduction.finding";
    let time = finding ? payload.start_recording_time_ms : payload.recording_time_ms;
    if (time === null || time === undefined) {
      const origin = run.recording_metadata?.find(item => item.id === payload.recording_id)?.start_wall_time_ms;
      const wall = finding ? payload.start_wall_time_ms : payload.wall_time_ms;
      if (!Number.isFinite(origin) || !Number.isFinite(wall)) continue;
      time = wall - origin;
    }
    if (!Number.isFinite(time) || time < 0 || positions.has(payload.brief_step)) continue;
    positions.set(payload.brief_step, { number, time });
  }
  timeline.replaceChildren();
  timeline.hidden = !positions.size;
  for (const [step, position] of positions) {
    const seconds = Math.floor(position.time / 1000);
    const label = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
    const button = element("button", `${step} · ${label}`, "step-jump mono");
    button.type = "button";
    button.setAttribute("aria-label", `Jump to step ${step}, tab ${position.number}, ${label}`);
    button.onclick = () => {
      byId("proof-video").click();
      const video = byId("recording-player");
      const tabs = byId("recording-tab");
      const changedTab = tabs.value !== String(position.number);
      if (changedTab) {
        tabs.value = String(position.number);
        tabs.dispatchEvent(new Event("change"));
      }
      const seek = () => { video.pause(); video.currentTime = Math.min(position.time / 1000, video.duration || Infinity); };
      if (!changedTab && video.readyState >= 1) seek();
      else video.addEventListener("loadedmetadata", seek, { once: true });
      const details = byId("action-log").querySelector(`[data-step="${step}"]`);
      if (details) details.open = true;
    };
    timeline.append(button);
  }
}

export function setupProof(run, hasFrame, preferFrame = false) {
  const videoTab = byId("proof-video");
  const frameTab = byId("proof-frame");
  videoTab.disabled = !run.recordings?.length;
  frameTab.disabled = !hasFrame;
  function select(tab) {
    for (const button of [videoTab, frameTab]) {
      const selected = button === tab;
      button.setAttribute("aria-selected", String(selected));
      button.tabIndex = selected ? 0 : -1;
      byId(button.getAttribute("aria-controls")).hidden = !selected;
    }
    if (tab !== videoTab) byId("recording-player").pause();
  }
  for (const button of [videoTab, frameTab]) {
    button.onclick = () => select(button);
    button.onkeydown = event => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const available = [videoTab, frameTab].filter(tab => !tab.disabled);
      const next = event.key === "Home" ? available[0] : event.key === "End" ? available[available.length - 1] : button === videoTab ? frameTab : videoTab;
      if (!next.disabled) { select(next); next.focus(); }
    };
  }
  if (preferFrame && hasFrame) select(frameTab);
  else if (!videoTab.disabled) select(videoTab);
  else {
    select(frameTab);
    // Keep an explicit empty proof state when neither artifact exists.
    frameTab.disabled = !hasFrame;
    byId("evidence-caption").hidden = !hasFrame;
  }
}

export function setupEnvironmentRerun(run, request) {
  const trigger = byId("change-url");
  const form = byId("rerun-form");
  if (!terminal.has(run.status) || !run.bug_report) return;
  trigger.hidden = false;
  const input = byId("rerun-url");
  input.value = run.bug_report.target_url;
  function close() {
    form.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
    trigger.focus();
  }
  trigger.onclick = () => {
    if (!form.hidden) { close(); return; }
    form.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    input.focus();
    input.select();
  };
  byId("rerun-cancel").onclick = close;
  form.onkeydown = event => {
    if (event.key === "Escape" && !byId("rerun-submit").disabled) close();
  };
  input.oninput = () => {
    input.removeAttribute("aria-invalid");
    byId("rerun-message").textContent = "";
  };
  form.onsubmit = async event => {
    event.preventDefault();
    const message = byId("rerun-message");
    const submit = byId("rerun-submit");
    const target = input.value.trim();
    try {
      const url = new URL(target);
      if (!["http:", "https:"].includes(url.protocol) || !url.hostname) throw new Error();
    } catch {
      message.textContent = "Enter an http or https app URL.";
      input.setAttribute("aria-invalid", "true");
      input.focus();
      return;
    }
    submit.disabled = true;
    byId("rerun-cancel").disabled = true;
    trigger.disabled = true;
    input.readOnly = true;
    message.textContent = "Starting a reproduction with the saved evidence…";
    try {
      const result = await request(`/api/runs/${run.id}/rerun`, {
        method: "POST", body: JSON.stringify({ target_url: target }),
      });
      try { sessionStorage.setItem("reprobe.last-run", result.run.id); } catch {}
      location.href = `/app/runs/${result.run.id}`;
    } catch (error) {
      message.textContent = error.message;
      submit.disabled = false;
      byId("rerun-cancel").disabled = false;
      trigger.disabled = false;
      input.readOnly = false;
    }
  };
}

export async function renderFindingProof(run, request) {
  if (run.verdict?.verdict !== "reproduced" || !run.recordings?.length) return false;
  try {
    const proof = await request(`/api/runs/${run.id}/proof-frame`);
    const response = await fetch(proof.image_url, { cache: "no-store" });
    if (!response.ok) throw new Error("The finding frame could not be loaded.");
    const url = URL.createObjectURL(await response.blob());
    const image = element("img", undefined, "report-image");
    image.src = url;
    image.alt = `Annotated finding: ${proof.explanation}`;
    try { await image.decode(); }
    catch (error) { URL.revokeObjectURL(url); throw error; }
    window.addEventListener("pagehide", () => URL.revokeObjectURL(url), { once: true });
    byId("evidence").replaceChildren(image);
    byId("proof-frame").textContent = "Finding frame";
    const seconds = Math.floor(proof.time_ms / 1000);
    byId("evidence-caption").textContent = `Recorded finding · tab ${proof.recording_number} · ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
    const explanation = byId("proof-explanation");
    explanation.hidden = false;
    explanation.replaceChildren(element("p", proof.explanation));
    const values = element("dl", undefined, "proof-values");
    for (const [label, value] of [["Expected", proof.expected], ["Observed", proof.observed]]) {
      const group = element("div");
      group.append(element("dt", label), element("dd", value));
      values.append(group);
    }
    explanation.append(values);
    if (proof.step_number) {
      const step = element("button", `Show step ${proof.step_number}`, "text-button");
      step.type = "button";
      step.setAttribute("aria-controls", "action-log");
      step.onclick = () => {
        const details = byId("action-log").querySelector(`[data-step="${proof.step_number}"]`);
        if (details) {
          details.open = true;
          details.querySelector("summary").focus();
          details.scrollIntoView({ block: "center" });
        }
      };
      explanation.append(step);
    }
    const download = byId("download-proof");
    download.href = url;
    download.download = `${run.id}-finding.jpg`;
    download.hidden = false;
    return true;
  } catch {
    byId("evidence-caption").textContent = "Final browser frame · annotated finding unavailable.";
    return false;
  }
}
