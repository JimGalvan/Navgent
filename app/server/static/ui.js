const $ = (id) => document.getElementById(id);
const page = document.body.dataset.page;
const preview = location.pathname.startsWith("/preview");
const terminal = new Set(["succeeded", "failed", "cancelled", "timed_out"]);
const draftKey = "reprobe.draft";
const sample = {
  url: "https://staging.northwind.test/cart",
  steps:
    "1. Open the cart page\n2. Add Trail Pack 30L and Insulated Bottle\n3. Apply coupon SAVE50\n4. Remove the bottle\n5. Check the total",
  expected: "Total drops to $30.00 after removing the bottle.",
  actual: "Total stays at $42.00 until the page is refreshed.",
  title: "Cart total stale after removing discounted item",
};
const samplePlan = [
  "Read the evidence",
  "Plan the reproduction",
  "Open cart page",
  "Add two items",
  "Apply SAVE50",
  "Remove Insulated Bottle",
  "Check the total",
  "Capture evidence",
];
const labels = {
  queued: "Queued",
  reading_evidence: "Reading evidence",
  running: "Running",
  waiting_for_input: "Needs your input",
  ready_for_follow_up: "Saving result",
  succeeded: "Completed",
  failed: "Failed",
  cancelled: "Stopped",
  timed_out: "Timed out",
};
let lastLive = null;
try {
  lastLive = sessionStorage.getItem("reprobe.last-run");
} catch {}
for (const link of document.querySelectorAll("[data-nav]")) {
  if (
    link.dataset.nav === page ||
    (page === "report" && link.dataset.nav === "reports")
  )
    link.classList.add("active");
  if (preview)
    link.href =
      "/preview/" +
      (link.dataset.nav === "reports" ? "reports" : link.dataset.nav);
  else if (link.dataset.nav === "live" && lastLive)
    link.href = "/app/runs/" + lastLive;
}
if (preview) {
  $("preview-banner").hidden = false;
  $("logout").hidden = true;
  for (const link of document.querySelectorAll(
    'a[href="/app"],a[href="/app/reports"]',
  ))
    link.href =
      link.getAttribute("href") === "/app"
        ? "/preview/new"
        : "/preview/reports";
}
$("logout")?.addEventListener("click", () => {
  try {
    sessionStorage.removeItem(draftKey);
    sessionStorage.removeItem("reprobe.last-run");
  } catch {}
});
async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...options.headers,
    },
  });
  const body = await response.json().catch(() => ({}));
  if (response.status === 401 && page !== "account") {
    location.href = "/login";
    throw new Error("Please log in again.");
  }
  if (!response.ok)
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : "Please check the form and try again.",
    );
  return body;
}
function node(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
}
function taskData(task) {
  try {
    const data = JSON.parse(task);
    return {
      title: data.title || data.steps?.split("\n")[0] || "Reproduction",
      ...data,
    };
  } catch {
    return { title: task, steps: task };
  }
}
function shortId(id) {
  return id.startsWith("RUN-") ? id : id.slice(0, 8).toUpperCase();
}
function statusElement(status) {
  const el = node("span", undefined, "status");
  el.append(
    node("span", "", `dot ${status}`),
    node("span", labels[status] || status),
  );
  return el;
}
function showHistory(runs) {
  const host = $("history");
  host.replaceChildren();
  if (!runs.length) {
    host.append(
      node(
        "p",
        "No reproductions yet. Start with a URL and the steps that trigger the bug.",
        "empty",
      ),
    );
    return;
  }
  for (const run of runs) {
    const d = taskData(run.task);
    const a = node("a", undefined, "history-row");
    a.href = preview
      ? "/preview/" + (run.status === "running" ? "live" : "report")
      : `/app/${terminal.has(run.status) ? "reports" : "runs"}/${run.id}`;
    a.append(
      node("span", shortId(run.id), "mono muted"),
      node("span", d.title),
      statusElement(run.status),
      node(
        "time",
        new Date(run.created_at).toLocaleDateString(undefined, {
          month: "short",
          day: "numeric",
        }),
      ),
    );
    host.append(a);
  }
}
async function history() {
  try {
    if (preview) {
      showHistory([
        {
          id: "RUN-0142",
          task: JSON.stringify(sample),
          status: "running",
          created_at: new Date().toISOString(),
        },
        {
          id: "RUN-0141",
          task: JSON.stringify({
            title: "Date picker closes on the first click",
          }),
          status: "succeeded",
          created_at: new Date().toISOString(),
        },
        {
          id: "RUN-0140",
          task: JSON.stringify({ title: "Avatar upload never finishes" }),
          status: "failed",
          created_at: new Date().toISOString(),
        },
      ]);
    } else showHistory((await api("/api/runs")).runs);
  } catch (error) {
    $("history").replaceChildren(node("p", error.message, "message"));
  }
}
if (!preview && ["new", "live", "reports", "report"].includes(page))
  api("/api/auth/me")
    .then((user) => {
      $("account-email").textContent = user.email;
    })
    .catch((error) => {
      const message =
        $("form-message") ||
        $("run-message") ||
        $("history-message") ||
        $("report-message");
      if (message) message.textContent = error.message;
    });
if (page === "account") {
  const path = location.pathname;
  const mode =
    path === "/register"
      ? "register"
      : path === "/verify-email"
        ? "verify"
        : path === "/forgot-password"
          ? "forgot"
          : path === "/reset-password"
            ? "reset"
            : "login";
  const titles = {
    register: "Make room for the evidence.",
    login: "Welcome back.",
    verify: "Check your inbox.",
    forgot: "Let’s get you back in.",
    reset: "Set a new password.",
  };
  const descriptions = {
    register: "Create your Reprobe account with email and password.",
    login: "Log in to your Reprobe workspace.",
    verify: "Enter the verification code sent to your email.",
    forgot: "We’ll send a link to reset your password.",
    reset: "Choose a new password for your account.",
  };
  const actions = {
    register: "Create account",
    login: "Log in",
    verify: "Verify email",
    forgot: "Send reset link",
    reset: "Save new password",
  };
  $("auth-title").textContent = titles[mode];
  $("auth-description").textContent = descriptions[mode];
  $("auth-submit").textContent = actions[mode];
  $("password-field").hidden = ["verify", "forgot"].includes(mode);
  $("password").required = !$("password-field").hidden;
  $("password").autocomplete =
    mode === "register" || mode === "reset"
      ? "new-password"
      : "current-password";
  $("code-field").hidden = mode !== "verify";
  $("code").required = mode === "verify";
  $("forgot-link").hidden = mode !== "login";
  if (mode === "register") {
    $("auth-switch").replaceChildren(node("span", "Already have an account? "));
    const a = node("a", "Log in");
    a.href = "/login";
    $("auth-switch").append(a);
  } else if (mode !== "login") {
    $("auth-switch").replaceChildren();
    const a = node("a", "Back to log in");
    a.href = "/login";
    $("auth-switch").append(a);
  }
  if (["verify", "reset"].includes(mode)) {
    $("email").required = false;
    $("email").closest(".field").hidden = true;
  }
  if (new URLSearchParams(location.search).has("reset"))
    $("auth-message").textContent = "Password updated. You can log in now.";
  $("show-password").onclick = () => {
    const visible = $("password").type === "password";
    $("password").type = visible ? "text" : "password";
    $("show-password").textContent = visible ? "Hide" : "Show";
    $("show-password").setAttribute(
      "aria-label",
      visible ? "Hide password" : "Show password",
    );
  };
  api("/api/capabilities")
    .then((c) => {
      $("auth-config").hidden = c.auth_configured;
    })
    .catch(() => {});
  $("account-form").onsubmit = async (event) => {
    event.preventDefault();
    $("auth-submit").disabled = true;
    $("auth-message").textContent = "";
    try {
      const result = await api("/api/auth/" + mode, {
        method: "POST",
        body: JSON.stringify({
          email: $("email").value || "verification@reprobe.local",
          password: $("password").value,
          code: $("code").value,
          token: new URLSearchParams(location.search).get("token") || "",
        }),
      });
      $("password").value = "";
      $("code").value = "";
      if (result.redirect) location.href = result.redirect;
      else $("auth-message").textContent = result.message;
    } catch (error) {
      $("auth-message").textContent = error.message;
    } finally {
      $("auth-submit").disabled = false;
    }
  };
}
if (page === "new") {
  const fields = {
    url: "target-url",
    steps: "steps",
    expected: "expected",
    actual: "actual",
  };
  const readDraft = () =>
    Object.fromEntries(
      Object.entries(fields).map(([key, id]) => [key, $(id).value]),
    );
  let draft = preview ? sample : {};
  try {
    if (!preview) draft = JSON.parse(sessionStorage.getItem(draftKey) || "{}");
  } catch {}
  for (const [key, id] of Object.entries(fields)) {
    $(id).value = draft[key] || "";
    $(id).addEventListener("input", () => {
      if (!preview)
        try {
          sessionStorage.setItem(draftKey, JSON.stringify(readDraft()));
        } catch {}
    });
  }
  let activeTab = "steps";
  const files = { video: [], shots: [] };
  let objectUrls = [];
  function renderFiles() {
    objectUrls.forEach(URL.revokeObjectURL);
    objectUrls = [];
    $("file-list").replaceChildren();
    const chosen = files[activeTab] || [];
    chosen.forEach((file, i) => {
      const div = node("div", undefined, "file-item");
      const media = document.createElement(
        activeTab === "video" ? "video" : "img",
      );
      const url = URL.createObjectURL(file);
      objectUrls.push(url);
      media.src = url;
      if (activeTab === "video") media.controls = true;
      else media.alt = file.name;
      const remove = node("button", "Remove", "text-button");
      remove.type = "button";
      remove.onclick = () => {
        files[activeTab].splice(i, 1);
        renderFiles();
      };
      div.append(media, node("p", file.name), remove);
      if (activeTab === "shots" && i > 0) {
        const move = node("button", "Move earlier", "text-button");
        move.type = "button";
        move.onclick = () => {
          [chosen[i - 1], chosen[i]] = [chosen[i], chosen[i - 1]];
          renderFiles();
        };
        div.append(move);
      }
      $("file-list").append(div);
    });
    const count = files.shots.length + files.video.length;
    const selected = [];
    if (files.shots.length) selected.push(`${files.shots.length} screenshot${files.shots.length === 1 ? "" : "s"}`);
    if (files.video.length) selected.push("1 recording");
    $("media-note").hidden = count === 0;
    $("media-note").textContent = preview
      ? "Design preview only. Files will not be uploaded or analyzed."
      : `${selected.join(" and ")} selected. All selected media and written steps will be read together. This can take up to 30 seconds.`;
  }
  function pick(tab) {
    activeTab = tab;
    for (const button of document.querySelectorAll("[data-tab]")) {
      button.setAttribute("aria-selected", String(button.dataset.tab === tab));
      button.tabIndex = button.dataset.tab === tab ? 0 : -1;
    }
    $("panel-video").hidden = tab !== "video";
    $("panel-shots").hidden = tab !== "shots";
    renderFiles();
  }
  for (const button of document.querySelectorAll("[data-tab]")) {
    button.onclick = () => pick(button.dataset.tab);
    button.onkeydown = (event) => {
      const tabs = [...document.querySelectorAll("[data-tab]")];
      let index = tabs.indexOf(button);
      if (event.key === "ArrowRight") index = (index + 1) % 3;
      else if (event.key === "ArrowLeft") index = (index + 2) % 3;
      else if (event.key === "Home") index = 0;
      else if (event.key === "End") index = 2;
      else return;
      event.preventDefault();
      pick(tabs[index].dataset.tab);
      tabs[index].focus();
    };
  }
  function accept(kind, selection) {
    $("form-message").textContent = "";
    const valid = [...selection].filter((file) =>
      kind === "video"
        ? /\.(mp4|webm|mov)$/i.test(file.name) &&
          file.size <= 50 * 1024 ** 2
        : /\.(png|jpe?g|webp|gif|bmp|tiff?)$/i.test(file.name) &&
          file.size <= 10 * 1024 ** 2,
    );
    const tooMany = kind === "shots"
      ? files.shots.length + valid.length > 10
      : valid.length > 1;
    if (valid.length !== selection.length || tooMany)
      $("form-message").textContent =
        "Some files were skipped. Check the supported formats and size limits.";
    files[kind] =
      kind === "video"
        ? valid.slice(0, 1)
        : [...files.shots, ...valid].slice(0, 10);
    renderFiles();
  }
  $("video-files").onchange = (e) => accept("video", e.target.files);
  $("shot-files").onchange = (e) => accept("shots", e.target.files);
  for (const drop of document.querySelectorAll("[data-drop]")) {
    drop.ondragover = (e) => e.preventDefault();
    drop.ondrop = (e) => {
      e.preventDefault();
      accept(drop.dataset.drop, e.dataTransfer.files);
    };
  }
  $("reproduction-form").onsubmit = async (event) => {
    event.preventDefault();
    if (preview) {
      location.href = "/preview/live";
      return;
    }
    const data = readDraft();
    if (!data.steps.trim() && !files.shots.length && !files.video.length) {
      $("form-message").textContent = "Add written steps, screenshots or a recording so Navgent can read the evidence.";
      return;
    }
    let url;
    try {
      url = new URL(data.url);
    } catch {
      $("form-message").textContent = "Use a valid http or https app URL.";
      return;
    }
    if (!["http:", "https:"].includes(url.protocol)) {
      $("form-message").textContent = "Use an http or https app URL.";
      return;
    }
    const body = new FormData();
    body.set("target_url", data.url);
    body.set("expected", data.expected);
    body.set("actual", data.actual);
    body.set("steps_text", data.steps);
    body.set("max_runtime_seconds", "600");
    for (const file of files.shots) body.append("screenshots", file);
    for (const file of files.video) body.append("video", file);
    $("start-run").disabled = true;
    $("form-message").textContent = "Uploading evidence…";
    try {
      const result = await api("/api/reproductions", {
        method: "POST",
        body,
      });
      try {
        sessionStorage.setItem("reprobe.last-run", result.run.id);
        sessionStorage.removeItem(draftKey);
      } catch {}
      location.href = "/app/runs/" + result.run.id;
    } catch (error) {
      $("form-message").textContent = error.message;
      $("start-run").disabled = false;
    }
  };
  history();
}
if (page === "reports") history();
const cartMarkup =
  '<div class="demo-cart"><div class="cart-head"><b>northwind supply</b><span>Cart (1)</span></div><div class="cart-content"><div><h2>Your cart</h2><div class="cart-product"><span>Trail Pack 30L<br>Moss · qty 1</span><b>$60.00</b></div></div><div><h2>Summary</h2><div class="cart-product"><span>Subtotal</span><span>$60.00</span></div><div class="cart-product"><span>SAVE50</span><span>−$30.00</span></div><div class="cart-total"><b>Total</b><b class="bad">$42.00</b></div></div></div></div>';
function renderPlan(todos, hostId = "plan", titleId = "plan-title", heading = "Plan") {
  $(hostId).replaceChildren();
  $(titleId).textContent = heading === "Evidence plan"
    ? `${heading} · ${todos.length} steps`
    : `${heading} · ${todos.filter((x) => x.status === "completed").length} of ${todos.length}`;
  todos.forEach((todo, i) => {
    const button = node("button", undefined, "plan-item");
    button.type = "button";
    const copy = node("span", todo.content, "plan-copy");
    if (todo.source) copy.append(node("small", todo.source, "plan-source"));
    button.append(
      node("span", String(i + 1).padStart(2, "0"), "mono"),
      copy,
    );
    if (!todo.source) button.append(node("small", todo.status.replaceAll("_", " ")));
    button.onclick = () => {
      for (const b of $(hostId).children) b.classList.remove("selected");
      button.classList.add("selected");
      $("step-heading").textContent = "Step " + (i + 1);
      $("step-detail").textContent =
        todo.content + " · " + (todo.source || todo.status.replaceAll("_", " ")) + ".";
    };
    $(hostId).append(button);
  });
}
function renderEvidencePlan(brief) {
  const steps = brief.steps.map((step) => ({
    content: step.instruction, source: step.source, status: "pending",
  }));
  renderPlan(steps, "plan", "plan-title", "Evidence plan");
}
function renderReportBrief(run) {
  const brief = run.repro_brief;
  if (brief) {
    $("report-brief").hidden = false;
    $("report-assertion").hidden = false;
    for (const step of brief.steps) {
      const item = node("li");
      item.append(node("p", step.instruction), node("small", step.source));
      $("report-steps").append(item);
    }
    $("assertion-check").textContent = brief.assertion.check;
    $("assertion-look-in").textContent = { page: "Page", network: "Network", console: "Console" }[brief.assertion.look_in];
    $("report-expected").textContent = brief.assertion.expected;
    $("report-actual").textContent = brief.assertion.reported_actual;
    for (const unknown of brief.unknowns) $("report-unknowns").append(node("li", unknown));
    if (!brief.unknowns.length) $("report-unknowns").replaceWith(node("p", "No unknowns were identified in the submitted evidence.", "muted"));
  }
  if (run.evidence_frames?.length) {
    $("key-frames-section").hidden = false;
    run.evidence_frames.forEach((frame, i) => {
      const figure = node("figure");
      const link = node("a");
      link.href = `/api/runs/${run.id}/evidence/${i + 1}.jpg`;
      link.target = "_blank";
      link.rel = "noopener";
      const img = node("img");
      img.src = link.href;
      img.loading = "lazy";
      img.alt = `Submitted evidence: ${frame.label}`;
      link.append(img);
      figure.append(link, node("figcaption", frame.label));
      $("key-frames").append(figure);
    });
  }
}
const verdictLabels = {
  reproduced: "Reproduced",
  not_reproduced: "Not reproduced",
  inconclusive: "Inconclusive",
};
function renderVerdict(verdict, brief) {
  const host = $("verdict");
  host.hidden = !verdict;
  host.replaceChildren();
  if (!verdict) return;
  host.append(node("h2", verdictLabels[verdict.verdict]), node("p", verdict.reason));
  const details = node("dl");
  if (verdict.expected) details.append(node("dt", "Expected"), node("dd", verdict.expected));
  if (verdict.observed) {
    const style = verdict.verdict === "reproduced" ? "bad" : "";
    const quotes = node("dd", undefined, style);
    for (const quote of verdict.observed.split("; ")) quotes.append(node("div", quote, "observed-quote"));
    details.append(node("dt", "Observed"), quotes);
  }
  const step = brief?.steps[verdict.step_number - 1];
  if (verdict.verdict !== "not_reproduced" && step)
    details.append(node("dt", "Step " + verdict.step_number), node("dd", step.instruction));
  if (details.childElementCount) host.append(details);
}
function renderRecordings(run) {
  const downloads = $("recording-downloads");
  for (const [index] of (run.recordings || []).entries()) {
    const number = index + 1;
    const url = `/api/runs/${run.id}/recordings/${number}.webm`;
    if (number === 1) {
      $("recording-player").src = url;
      $("recording-section").hidden = false;
    }
    const link = node("a", `WebM video · tab ${number}`, "download");
    link.href = url;
    link.download = `recording-${number}.webm`;
    downloads.append(link);
  }
}
const inputActions = new Set(["type", "fill", "select"]);
function actionText(payload) {
  const value = payload.value ? " " + JSON.stringify(payload.value) : "";
  const preposition = inputActions.has(payload.action) ? " into " : " · ";
  return (payload.action || "Action") + value + (payload.target ? preposition + payload.target : "");
}
function renderActionLog(host, events) {
  const actions = [];
  let pending = null;
  for (const event of events) {
    if (!event.event_type.startsWith("browser.action.")) continue;
    const payload = event.payload;
    if (event.event_type === "browser.action.started") {
      pending = { payload, outcome: "Started" };
      actions.push(pending);
    } else {
      if (!pending || pending.payload.action !== payload.action || pending.payload.target !== payload.target) {
        pending = {};
        actions.push(pending);
      }
      pending.payload = payload;
      pending.outcome = event.event_type === "browser.action.failed" ? "Failed" : "Completed";
      pending = null;
    }
  }
  host.replaceChildren();
  let previousFields = [];
  for (const { payload, outcome } of actions) {
    const row = node("article", undefined, "action-row");
    if (payload.brief_step) row.append(node("p", "Step " + payload.brief_step, "muted"));
    row.append(node("p", actionText(payload), "action-title"));
    if (payload.reason) row.append(node("p", payload.reason, "muted"));
    row.append(node("p", outcome, "action-outcome"));
    if (payload.error) row.append(node("p", payload.error, "action-error"));
    if (inputActions.has(payload.action)) {
      const after = outcome === "Completed" && Array.isArray(payload.fields) ? payload.fields : null;
      const comparison = node("div", undefined, "field-comparison");
      for (const [label, lines, other] of [["Before", previousFields, after], ["After", after, previousFields]]) {
        const column = node("div", undefined, "field-snapshot");
        column.append(node("h3", label));
        if (lines === null) column.append(node("p", "No snapshot captured", "muted"));
        else if (!lines.length) column.append(node("p", "No field values captured", "muted"));
        else for (const line of lines) {
          const changed = other !== null && !other.includes(line);
          const field = node("div", line, "mono" + (changed ? " field-changed" : ""));
          if (changed) field.append(node("small", " Changed", "change-label"));
          column.append(field);
        }
        comparison.append(column);
      }
      row.append(comparison);
      if (after !== null) previousFields = after;
    }
    host.append(row);
  }
  if (!actions.length) host.append(node("p", "No browser actions were recorded.", "muted"));
}
function eventDescription(event) {
  const p = event.payload || {};
  if (
    event.event_type === "agent.message.delta" ||
    event.event_type === "task.todos"
  )
    return null;
  const labels = {
    "browser.action.started": "Acting",
    "browser.action.completed": "Action completed",
    "browser.action.failed": "Action failed",
    "browser.navigation.started": "Opening page",
    "browser.navigation.completed": "Page loaded",
    "browser.observation": "Observed page",
    "browser.frame.changed": "Frame changed",
    "run.created": "Run created",
    "evidence.ready": "Evidence plan ready",
    "reproduction.verdict": "Verdict reported",
    "evidence.failed": "Couldn't read the evidence",
    "run.completed": "Run output saved",
    "run.failed": "Run failed",
    "run.cancelled": "Run stopped",
    "run.status": "Status",
    "input.required": "Input needed",
    "input.received": "Input received",
    "sensitive_input.required": "Verification needed",
    "sensitive_input.received": "Code submitted",
    "sensitive_input.cancelled": "Code request ended",
    "browser.capture.failed": "Frame capture interrupted",
    "browser.capture.recovered": "Frame capture recovered",
  };
  if (event.event_type.startsWith("browser.action.")) {
    return { title: labels[event.event_type], detail: actionText(p) };
  }
  return {
    title: labels[event.event_type] || event.event_type.replaceAll(".", " "),
    detail:
      verdictLabels[p.verdict] ||
      p.question ||
      p.target ||
      p.url ||
      p.message ||
      p.error ||
      p.status ||
      p.frame_id ||
      "",
  };
}
function appendEvent(host, event) {
  const d = eventDescription(event);
  if (!d) return;
  const row = node("div", undefined, "event-row");
  const date = new Date(event.created_at);
  row.append(
    node(
      "time",
      date.toLocaleTimeString(undefined, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }),
      "muted",
    ),
  );
  const copy = node("div");
  copy.append(node("p", d.title), node("p", d.detail, "muted"));
  if (event.event_type.startsWith("browser.action.")) {
    if (event.payload.reason) copy.append(node("p", event.payload.reason, "action-reason muted"));
    if (event.payload.error) copy.append(node("p", event.payload.error, "action-error"));
  }
  row.append(copy);
  host.append(row);
  return d;
}
if (page === "live") {
  let runId = location.pathname.split("/").pop(),
    source = null,
    stopped = false,
    frameTimer = null,
    frameUrl = null,
    latestRequest = null,
    brief = null,
    evidenceFailed = false,
    currentBriefStep = 0,
    started = Date.now();
  const seen = new Set();
  function advanceBriefStep(step) {
    if (!Number.isInteger(step) || step <= currentBriefStep || !brief?.steps[step - 1]) return;
    currentBriefStep = step;
    for (const [index, item] of [...$("plan").children].entries()) {
      item.dataset.status = index + 1 < step ? "completed" : index + 1 === step ? "in_progress" : "pending";
      if (index + 1 === step) item.setAttribute("aria-current", "step");
      else item.removeAttribute("aria-current");
    }
  }
  function setStatus(status) {
    $("run-status").textContent = labels[status] || status;
    $("run-dot").className = "dot " + status;
    if (status === "reading_evidence") {
      $("feed-label").textContent = "READING EVIDENCE";
      $("screen-waiting").textContent = "Reading your evidence before starting the browser. This usually takes a few seconds, up to 30 seconds.";
      $("latest-action").textContent = "Building a plan from your evidence";
    } else if (status === "running") {
      $("feed-label").textContent = "LIVE";
      $("screen-waiting").textContent = "The browser is starting. The first frame will appear here.";
    }
    if (terminal.has(status)) {
      stopped = true;
      clearTimeout(frameTimer);
      source?.close();
      $("cancel-run").hidden = true;
      $("input-panel").hidden = true;
      $("view-report").hidden = false;
      $("view-report").href = "/app/reports/" + runId;
      $("feed-label").textContent = "FINAL FRAME";
      if (evidenceFailed) {
        $("feed-label").textContent = "EVIDENCE ERROR";
        $("screen-waiting").textContent = "The evidence could not be read. Check your files and steps, then start a new reproduction.";
        $("latest-action").textContent = "The browser did not start";
        $("plan").replaceChildren(node("p", "No plan was created because the evidence could not be read.", "muted"));
        document.querySelector(".step-detail").hidden = true;
        if (!source) $("activity").replaceChildren(node("p", "No browser actions were run.", "muted"));
      }
      refreshFrame();
    }
  }
  async function refreshFrame() {
    if (preview) return;
    try {
      const response = await fetch(`/api/runs/${runId}/screen.jpg`, {
        cache: "no-store",
      });
      if (response.status === 401) {
        location.href = "/login";
        return;
      }
      if (response.ok && response.status !== 204) {
        const next = URL.createObjectURL(await response.blob());
        $("browser-screen").src = next;
        $("browser-screen").hidden = false;
        $("screen-waiting").hidden = true;
        if (frameUrl) URL.revokeObjectURL(frameUrl);
        frameUrl = next;
      }
    } catch {
      $("latest-action").textContent = "Browser feed reconnecting…";
    } finally {
      if (!stopped) frameTimer = setTimeout(refreshFrame, 750);
    }
  }
  function receive(event) {
    if (seen.has(event.sequence)) return;
    seen.add(event.sequence);
    if (event.event_type === "task.todos") {
      if (brief) {
        $("execution-section").hidden = false;
        renderPlan(event.payload.todos || [], "execution-plan", "execution-title", "Browser progress");
      } else renderPlan(event.payload.todos || []);
      return;
    }
    if (event.event_type === "evidence.ready") {
      brief = event.payload.brief;
      renderEvidencePlan(brief);
      const step = currentBriefStep;
      currentBriefStep = 0;
      advanceBriefStep(step);
    }
    if (event.event_type.startsWith("browser.action.")) advanceBriefStep(event.payload.brief_step);
    if (event.event_type === "browser.action.completed" && inputActions.has(event.payload.action) && Array.isArray(event.payload.fields)) {
      $("form-state-section").hidden = false;
      $("form-state").replaceChildren(...event.payload.fields.map(line => node("div", line)));
    }
    if (event.event_type === "evidence.failed") evidenceFailed = true;
    if (event.event_type === "reproduction.verdict") renderVerdict(event.payload, brief);
    if (event.event_type === "run.failed" || event.event_type === "evidence.failed")
      $("run-message").textContent = event.payload.error;
    if (event.event_type === "agent.message.delta") {
      const host = $("agent-output");
      host.textContent = (host.textContent + (event.payload.text || "")).slice(
        -12000,
      );
      return;
    }
    const activity = $("activity");
    if (seen.size === 1) activity.replaceChildren();
    const d = appendEvent(activity, event);
    if (d)
      $("latest-action").textContent =
        d.title + (d.detail ? " · " + d.detail : "");
    while (activity.children.length > 150) activity.firstElementChild.remove();
    activity.scrollTop = activity.scrollHeight;
    if (event.event_type === "run.status") {
      if (terminal.has(event.payload.status)) renderVerdict(event.payload.verdict, brief);
      setStatus(event.payload.status);
    }
    if (event.event_type === "browser.navigation.completed")
      $("browser-url").textContent = event.payload.url;
    if (
      event.event_type === "input.required" ||
      event.event_type === "sensitive_input.required"
    ) {
      latestRequest =
        event.event_type === "sensitive_input.required"
          ? event.payload.request_id
          : null;
      $("input-question").textContent =
        event.payload.question || event.payload.prompt;
      $("input-answer").value = "";
      $("input-answer").style.webkitTextSecurity = latestRequest
        ? "disc"
        : "none";
      $("input-panel").hidden = false;
      $("decline-input").hidden = !latestRequest;
    }
    if (
      [
        "input.received",
        "sensitive_input.received",
        "sensitive_input.cancelled",
      ].includes(event.event_type)
    ) {
      $("input-panel").hidden = true;
      $("input-answer").value = "";
    }
  }
  const clock = setInterval(() => {
    const seconds = Math.max(0, Math.floor((Date.now() - started) / 1000));
    if (!stopped)
      $("elapsed").textContent =
        `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")} / 10:00`;
  }, 1000);
  $("cancel-run").onclick = async () => {
    if (preview) {
      $("run-status").textContent = "Stopped · preview";
      $("cancel-run").disabled = true;
      $("view-report").hidden = false;
      $("view-report").href = "/preview/report";
      stopped = true;
      return;
    }
    $("cancel-run").disabled = true;
    try {
      await api(`/api/runs/${runId}/cancel`, { method: "POST" });
      setStatus("cancelled");
    } catch (error) {
      $("run-message").textContent = error.message;
      $("cancel-run").disabled = false;
    }
  };
  $("input-form").onsubmit = async (event) => {
    event.preventDefault();
    const body = latestRequest
      ? { request_id: latestRequest, code: $("input-answer").value }
      : { answer: $("input-answer").value };
    try {
      await api(
        `/api/runs/${runId}/${latestRequest ? "sensitive-input" : "input"}`,
        { method: "POST", body: JSON.stringify(body) },
      );
      $("input-answer").value = "";
      $("input-panel").hidden = true;
    } catch (error) {
      $("run-message").textContent = error.message;
    }
  };
  $("decline-input").onclick = async () => {
    try {
      await api(`/api/runs/${runId}/sensitive-input/decline`, {
        method: "POST",
      });
      $("input-panel").hidden = true;
    } catch (error) {
      $("run-message").textContent = error.message;
    }
  };
  if (preview) {
    runId = "RUN-0142";
    $("run-id").textContent = runId;
    $("run-title").textContent = sample.title;
    $("run-status").textContent = "Running · sample";
    $("browser-url").textContent = "staging.northwind.test/cart";
    $("elapsed").textContent = "01:42 / 10:00";
    started = Date.now() - 102000;
    $("viewport").innerHTML = cartMarkup;
    renderPlan(
      samplePlan.map((content, i) => ({
        content,
        status: i < 5 ? "completed" : i === 5 ? "in_progress" : "pending",
      })),
    );
    $("activity").replaceChildren();
    for (const [i, detail] of [
      "Cart loaded",
      "Applied coupon SAVE50",
      "Located Remove Insulated Bottle",
      "Clicking Remove and waiting for the page",
    ].entries())
      appendEvent($("activity"), {
        event_type: "browser.observation",
        payload: { message: detail },
        created_at: new Date(Date.now() - (4 - i) * 3000).toISOString(),
      });
    $("latest-action").textContent = "click · Remove Insulated Bottle";
  } else {
    try {
      const response = await api("/api/runs/" + runId);
      const data = taskData(response.run.task);
      brief = response.run.repro_brief;
      renderVerdict(response.run.verdict, brief);
      if (brief) renderEvidencePlan(brief);
      evidenceFailed = response.run.error?.startsWith("Couldn't read the evidence") || false;
      $("run-message").textContent = response.run.error || "";
      $("run-id").textContent = shortId(runId);
      $("run-title").textContent = data.title;
      $("browser-url").textContent = data.url || "Browser";
      started = Date.parse(response.run.created_at);
      setStatus(response.run.status);
      refreshFrame();
      for (const event of await api(`/api/runs/${runId}/events`)) receive(event);
      if (!stopped) {
        source = new EventSource(response.stream_url);
        const types = [
          "run.created",
          "evidence.ready",
          "reproduction.verdict",
          "evidence.failed",
          "run.status",
          "task.todos",
          "browser.frame.changed",
          "browser.tab.changed",
          "browser.navigation.started",
          "browser.navigation.completed",
          "browser.action.started",
          "browser.action.completed",
          "browser.action.failed",
          "browser.observation",
          "browser.capture.failed",
          "browser.capture.recovered",
          "agent.message.delta",
          "input.required",
          "input.received",
          "sensitive_input.required",
          "sensitive_input.received",
          "sensitive_input.cancelled",
          "run.completed",
          "run.failed",
          "run.cancelled",
        ];
        for (const type of types)
          source.addEventListener(type, (e) => {
            try {
              receive(JSON.parse(e.data));
            } catch {
              $("run-message").textContent =
                "An update could not be read. Refresh to reconnect.";
            }
          });
        source.onerror = () => {
          if (!stopped) $("run-status").textContent = "Reconnecting…";
        };
      }
    } catch (error) {
      $("run-message").textContent = error.message;
      stopped = true;
    }
  }
  window.addEventListener("pagehide", () => {
    source?.close();
    stopped = true;
    clearInterval(clock);
    clearTimeout(frameTimer);
    if (frameUrl) URL.revokeObjectURL(frameUrl);
  });
}
if (page === "report") {
  const runId = location.pathname.split("/").pop();
  let record = null;
  const events = [];
  const seen = new Set();
  function jsonDownload() {
    const blob = new Blob([JSON.stringify({ run: record, events }, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    $("download-json").href = url;
    $("download-json").download = "reprobe-" + runId + ".json";
    $("download-json").hidden = false;
    window.addEventListener("pagehide", () => URL.revokeObjectURL(url), {
      once: true,
    });
  }
  if (preview) {
    $("run-status").textContent = "Reproduced · sample evidence";
    $("run-id").textContent = "RUN-0142";
    $("report-title").textContent = "The total stayed behind.";
    $("report-description").textContent =
      "Illustrative report: removing the discounted item leaves the page showing $42.00 instead of $30.00.";
    $("evidence").innerHTML = cartMarkup;
    $("report-output").textContent =
      "Sample result: the discount updated, but the displayed total remained stale. This is fictional preview data, not an executed run.";
    $("report-expected").textContent = sample.expected;
    $("report-actual").textContent = sample.actual;
    renderVerdict({
      verdict: "reproduced", expected: "$30.00", observed: "$42.00",
      reason: "The displayed total stayed at $42.00 after removing the bottle.",
    }, null);
    $("rerun").href = "/preview/new";
    samplePlan.forEach((title, i) =>
      appendEvent($("report-events"), {
        event_type: "browser.observation",
        payload: { message: title },
        created_at: new Date(Date.now() - (8 - i) * 5000).toISOString(),
      }),
    );
  } else {
    try {
      const result = await api("/api/runs/" + runId);
      record = result.run;
      const data = taskData(record.task);
      $("run-id").textContent = shortId(runId);
      $("run-status").textContent = labels[record.status] || record.status;
      $("run-dot").className = "dot " + record.status;
      $("report-title").textContent = data.title;
      $("report-description").hidden = terminal.has(record.status);
      $("report-description").textContent = "Open the live viewer to follow this run.";
      renderVerdict(record.verdict, record.repro_brief);
      renderRecordings(record);
      $("report-output").textContent =
        record.final_output || record.error || "No final output was captured.";
      $("report-expected").textContent = data.expected || "Not provided";
      $("report-actual").textContent = data.actual || "Not provided";
      renderReportBrief(record);
      const rerun = $("rerun");
      if (terminal.has(record.status)) {
        rerun.onclick = async (event) => {
          event.preventDefault();
          rerun.style.pointerEvents = "none";
          try {
            const next = await api(`/api/runs/${runId}/rerun`, {
              method: "POST",
            });
            location.href = "/app/runs/" + next.run.id;
          } catch (error) {
            $("report-message").textContent = error.message;
            rerun.style.pointerEvents = "";
          }
        };
      } else {
        rerun.textContent = "Open live viewer";
        rerun.href = "/app/runs/" + runId;
      }
      const screen = await fetch(result.screen_url, { cache: "no-store" });
      if (screen.ok && screen.status !== 204) {
        const url = URL.createObjectURL(await screen.blob());
        const img = node("img", undefined, "report-image");
        img.src = url;
        img.alt = "Saved final browser frame";
        $("evidence").replaceChildren(img);
        $("download-frame").href = url;
        $("download-frame").download = runId + ".jpg";
        $("download-frame").hidden = false;
        window.addEventListener("pagehide", () => URL.revokeObjectURL(url), {
          once: true,
        });
      } else
        $("evidence").replaceChildren(
          node("p", "No browser frame was saved for this run.", "empty"),
        );
      for (const event of await api(`/api/runs/${runId}/events`)) {
        if (!seen.has(event.sequence)) {
          seen.add(event.sequence);
          events.push(event);
          if (!event.event_type.startsWith("browser.action.")) appendEvent($("report-events"), event);
        }
      }
      renderActionLog($("action-log"), events);
      $("run-events-section").hidden = !$("report-events").childElementCount;
      jsonDownload();
    } catch (error) {
      $("report-message").textContent = error.message;
    }
  }
}
