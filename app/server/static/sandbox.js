// Display only persisted lifecycle data supplied by the run controller.
export function renderSandbox(events) {
  const panel = document.getElementById("sandbox-panel");
  if (!panel) return;
  const lifecycle = events.filter(event => event.event_type.startsWith("sandbox."));
  if (!lifecycle.length) return;
  panel.hidden = false;
  const latest = lifecycle.filter(event => event.event_type !== "sandbox.request_blocked").at(-1);
  const started = lifecycle.findLast(event => event.event_type === "sandbox.started");
  const names = {"sandbox.starting": "Starting", "sandbox.started": "Running", "sandbox.destroyed": "Destroyed", "sandbox.cleanup_failed": "Cleanup needs attention"};
  document.getElementById("sandbox-status").textContent = names[latest?.event_type] || "Recorded";
  const data = started?.payload || latest?.payload || {};
  const limits = data.limits || {};
  const values = [
    ["Runtime", data.runtime], ["CPU", limits.cpus == null ? null : `${limits.cpus} vCPU`],
    ["Memory", limits.memory_mb == null ? null : `${limits.memory_mb} MB`],
    ["Time cap", limits.time_limit_seconds == null ? null : `${limits.time_limit_seconds} seconds`],
    ["Allowed host", data.allowed_hosts?.join(", ")],
  ];
  const host = document.getElementById("sandbox-values");
  host.replaceChildren();
  for (const [label, value] of values) {
    if (value == null) continue;
    const term = document.createElement("dt");
    term.textContent = label;
    const description = document.createElement("dd");
    description.textContent = value;
    host.append(term, description);
  }
}
