"""Opt-in real-provider smoke check. Run from the repository root."""

import asyncio
import json
import os
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

from app.auth.sessions import get_client, verify_auth_configuration
from app.runs.repository import RunRepository
from app.runs.service import RunManager


def safe_error(value):
    text = str(value)
    for name, secret in os.environ.items():
        if any(part in name.upper() for part in ("KEY", "PASSWORD", "TOKEN", "SECRET")) and len(secret) > 6:
            text = text.replace(secret, "[redacted]")
    return text[:1000]


async def check():
    verify_auth_configuration()
    try:
        await asyncio.to_thread(get_client().user_management.list_users, limit=1)
        print("WorkOS API connection verified", flush=True)
    except Exception as error:
        response = getattr(error, "response", None)
        print("WorkOS API check failed; status:", getattr(response, "status_code", "connection error"), flush=True)

    handler = partial(SimpleHTTPRequestHandler, directory=str(Path(__file__).parent / "fixtures"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/stale-cart.html"
    repository = RunRepository(Path(__file__).parents[1] / ".data" / "live-smoke.db")
    repository.initialize()
    manager = RunManager(repository)
    owner = uuid4()
    try:
        task = json.dumps({
            "title": "Local smoke check: cart total after removing a discounted item",
            "url": url,
            "steps": "1. Open the URL. 2. Click Remove Insulated Bottle. 3. Read subtotal, discount, and total. Compare the displayed total to 50% of the remaining $60 item.",
            "expected": "The total should become $30.00.",
            "actual": "The reported bug is that the total stays $42.00.",
            "instruction": "Use browser tools only, not file tools. Verify the page yourself. Report the exact observed values and whether the bug was reproduced. Do not make purchases or visit other hosts."
        })
        run = await manager.create_run(task, max_runtime_seconds=180, user_id=owner)
        print("Started real Navgent run:", run.id, flush=True)
        event_types = []
        async with asyncio.timeout(210):
            async for event in manager.stream_events(run.id, owner):
                event_types.append(event.event_type)
                if event.event_type != "agent.message.delta":
                    print("Event:", event.event_type, flush=True)
        for _ in range(40):
            if run.id not in manager._contexts:
                break
            await asyncio.sleep(.1)
        record = repository.get_run(run.id)
        result = {
            "run_id": str(run.id), "status": record.status.value,
            "output": safe_error(record.final_output or ""),
            "error": safe_error(record.error or ""),
            "event_types": sorted(set(event_types)),
            "frame_available": bool(manager.get_latest_frame(run.id, owner)),
            "session_closed": run.id not in manager._contexts,
        }
        output = Path(__file__).parents[1] / ".data" / "live-smoke-result.json"
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result), flush=True)
    finally:
        await manager.shutdown()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    try:
        asyncio.run(check())
    except Exception as error:
        print("Live smoke check failed:", safe_error(error), flush=True)
        raise SystemExit(1) from None
