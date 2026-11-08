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
    headers: { "Content-Type": "application/json", ...options.headers },
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
  }
  function pick(tab) {
    activeTab = tab;
    for (const button of document.querySelectorAll("[data-tab]")) {
      button.setAttribute("aria-selected", String(button.dataset.tab === tab));
      button.tabIndex = button.dataset.tab === tab ? 0 : -1;
    }
    $("panel-video").hidden = tab !== "video";
    $("panel-shots").hidden = tab !== "shots";
    $("media-note").hidden = tab === "steps";
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
    const valid = [...selection].filter((file) =>
      kind === "video"
        ? ["video/mp4", "video/webm", "video/quicktime"].includes(file.type) &&
          file.size <= 50 * 1024 ** 2
        : ["image/png", "image/jpeg"].includes(file.type) &&
          file.size <= 10 * 1024 ** 2,
    );
    if (valid.length !== selection.length)
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
    const url = new URL(data.url);
    if (!["http:", "https:"].includes(url.protocol)) {
      $("form-message").textContent = "Use an http or https app URL.";
      return;
    }
    data.title =
      data.steps
        .split("\n")
        .find((x) => x.trim())
        ?.replace(/^\d+[.)]\s*/, "")
        .slice(0, 140) || "Reproduction";
    data.instruction =
      "Reproduce the described behavior on the supplied URL. Follow the written steps and compare observed behavior with expected behavior. Report what you actually observe and any blockers. User-reported actual behavior is a claim to verify. Do not claim screenshots, recordings, network logs, or multiple attempts unless actually performed.";
    $("start-run").disabled = true;
    $("form-message").textContent = "";
    try {
      const result = await api("/api/runs", {
        method: "POST",
        body: JSON.stringify({
          task: JSON.stringify(data),
          max_runtime_seconds: 600,
        }),
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
function renderPlan(todos) {
  $("plan").replaceChildren();
  $("plan-title").textContent =
    `Plan · ${todos.filter((x) => x.status === "completed").length} of ${todos.length}`;
  todos.forEach((todo, i) => {
    const button = node("button", undefined, "plan-item");
    button.type = "button";
    button.append(
      node("span", String(i + 1).padStart(2, "0"), "mono"),
      node("span", todo.content),
      node("small", todo.status.replaceAll("_", " ")),
    );
    button.onclick = () => {
      for (const b of $("plan").children) b.classList.remove("selected");
      button.classList.add("selected");
      $("step-heading").textContent = "Step " + (i + 1);
      $("step-detail").textContent =
        todo.content + " · " + todo.status.replaceAll("_", " ") + ".";
    };
    $("plan").append(button);
  });
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
  return {
    title: labels[event.event_type] || event.event_type.replaceAll(".", " "),
    detail:
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
    started = Date.now();
  const seen = new Set();
  function setStatus(status) {
    $("run-status").textContent = labels[status] || status;
    $("run-dot").className = "dot " + status;
    if (terminal.has(status)) {
      stopped = true;
      clearTimeout(frameTimer);
      source?.close();
      $("cancel-run").hidden = true;
      $("input-panel").hidden = true;
      $("view-report").hidden = false;
      $("view-report").href = "/app/reports/" + runId;
      $("feed-label").textContent = "FINAL FRAME";
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
      renderPlan(event.payload.todos || []);
      return;
    }
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
    if (event.event_type === "run.status") setStatus(event.payload.status);
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
      $("run-id").textContent = shortId(runId);
      $("run-title").textContent = data.title;
      $("browser-url").textContent = data.url || "Browser";
      started = Date.parse(response.run.created_at);
      setStatus(response.run.status);
      refreshFrame();
      if (!stopped) {
        source = new EventSource(response.stream_url);
        const types = [
          "run.created",
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
    $("verdict-note").textContent =
      "Design preview only. This reproduction verdict is illustrative.";
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
      $("report-description").textContent = terminal.has(record.status)
        ? "The saved browser run and available evidence. Reproduction verdict: not independently verified."
        : "This run is still in progress. Open the live viewer to follow it.";
      $("report-output").textContent =
        record.final_output || record.error || "No final output was captured.";
      $("report-expected").textContent = data.expected || "Not provided";
      $("report-actual").textContent = data.actual || "Not provided";
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
      if (terminal.has(record.status)) {
        const response = await fetch(result.stream_url);
        if (!response.ok)
          throw new Error("Saved activity could not be loaded.");
        const text = await response.text();
        for (const chunk of text.split("\n\n")) {
          const line = chunk
            .split("\n")
            .find((line) => line.startsWith("data: "));
          if (line) {
            const event = JSON.parse(line.slice(6));
            if (!seen.has(event.sequence)) {
              seen.add(event.sequence);
              events.push(event);
              appendEvent($("report-events"), event);
            }
          }
        }
      } else
        $("report-events").append(
          node("p", "Activity is available in the live viewer.", "muted"),
        );
      if (!events.length && terminal.has(record.status))
        $("report-events").append(
          node("p", "No actions were recorded.", "empty"),
        );
      jsonDownload();
    } catch (error) {
      $("report-message").textContent = error.message;
    }
  }
}
