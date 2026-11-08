"""Opt-in real HTTP/WorkOS/Navgent check using the approved sandbox account."""

import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx


def check():
    directory = Path(__file__).resolve().parents[1] / ".data"
    credentials = json.loads((directory / "account-smoke.json").read_text())
    handler = partial(SimpleHTTPRequestHandler, directory=str(Path(__file__).parent / "fixtures"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with httpx.Client(base_url="http://127.0.0.1:8787", timeout=210) as client:
            login = client.post("/api/auth/login", json=credentials)
            assert login.status_code == 200 and login.json().get("redirect") == "/app", "Login did not complete"
            task = {
                "title": "Signed-in check: stale cart total",
                "url": f"http://127.0.0.1:{server.server_port}/stale-cart.html",
                "steps": "Open the URL, click Remove Insulated Bottle, then read subtotal, discount, and total. Compare the total to 50% of the remaining $60 item.",
                "expected": "The total becomes $30.00.",
                "actual": "The reported bug is a stale total of $42.00.",
                "instruction": "Use browser tools only, not file tools. Report what you actually observe. Do not visit other hosts or make purchases."
            }
            created = client.post("/api/runs", json={"task": json.dumps(task), "max_runtime_seconds": 180})
            assert created.status_code == 202, f"Create run status: {created.status_code}"
            data = created.json()
            run_id = data["run"]["id"]
            print("Signed-in real run started:", run_id, flush=True)
            event_types = []
            with client.stream("GET", data["stream_url"]) as stream:
                stream.raise_for_status()
                for line in stream.iter_lines():
                    if line.startswith("data: "):
                        event = json.loads(line[6:])
                        event_types.append(event["event_type"])
                        if event["event_type"] != "agent.message.delta":
                            print("HTTP event:", event["event_type"], flush=True)
            record = client.get("/api/runs/" + run_id)
            record.raise_for_status()
            run = record.json()["run"]
            frame = client.get(data["screen_url"])
            report = client.get("/app/reports/" + run_id)
            result = {
                "run_id": run_id, "status": run["status"],
                "observed_42_vs_30": "$42" in (run["final_output"] or "") and "$30" in (run["final_output"] or ""),
                "browser_action_completed": "browser.action.completed" in event_types,
                "frame_status": frame.status_code,
                "frame_bytes": len(frame.content),
                "report_status": report.status_code,
                "history_contains_run": any(r["id"] == run_id for r in client.get("/api/runs").json()["runs"]),
            }
            (directory / "signed-in-smoke-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps(result), flush=True)
            assert run["status"] == "succeeded", "Real run did not complete"
            assert result["observed_42_vs_30"] and result["browser_action_completed"]
            assert frame.status_code == 200 and frame.content.startswith(b"\xff\xd8")
            assert report.status_code == 200 and result["history_contains_run"]
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    check()
