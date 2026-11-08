"""Opt-in account smoke check against WorkOS's test environment only."""

import json
import os
import secrets
from pathlib import Path

import httpx
from dotenv import load_dotenv
from workos.exceptions import BaseRequestException

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

from app.auth.sessions import get_client


def check():
    if not os.environ.get("WORKOS_API_KEY", "").startswith("sk_test_"):
        raise RuntimeError("Account smoke checks require a WorkOS test key")
    directory = Path(__file__).resolve().parents[1] / ".data"
    directory.mkdir(exist_ok=True)
    credentials_path = directory / "account-smoke.json"
    if credentials_path.exists():
        credentials = json.loads(credentials_path.read_text())
    else:
        credentials = {"email": f"reprobe-smoke-{secrets.token_hex(5)}@reprobe.test", "password": secrets.token_urlsafe(30)}
        credentials_path.write_text(json.dumps(credentials), encoding="utf-8")
    manager = get_client().user_management
    users = manager.list_users(email=credentials["email"], limit=1).data
    with httpx.Client(base_url="http://127.0.0.1:8787", timeout=30) as client:
        action = "login" if users else "register"
        response = client.post("/api/auth/" + action, json=credentials)
        print("Local", action, "status:", response.status_code, flush=True)
        if response.is_success:
            print("Next page:", response.json().get("redirect"), flush=True)
        try:
            users = manager.list_users(email=credentials["email"], limit=1).data
            if not users:
                manager.create_user(**credentials)
            manager.authenticate_with_password(**credentials)
            print("Provider authentication succeeded", flush=True)
        except BaseRequestException as error:
            data = error.response_json or {}
            print("Provider response keys:", sorted(data), flush=True)
            print("Provider status:", error.response.status_code, flush=True)
            for name in ("code", "error", "message"):
                value = str(data.get(name, ""))
                value = value.replace(credentials["password"], "[redacted]")
                print("Provider", name + ":", value[:400], flush=True)
            if data.get("email_verification_id") and data.get("pending_authentication_token"):
                verification = manager.get_email_verification(data["email_verification_id"])
                # Only this script's fresh sandbox account is verified through the test API.
                client.cookies.set("reprobe_pending", data["pending_authentication_token"], domain="127.0.0.1", path="/")
                result = client.post("/api/auth/verify", json={"email": credentials["email"], "code": verification.code})
                print("Local verification status:", result.status_code, flush=True)
                if result.is_success:
                    response = result
        if response.is_success and response.json().get("redirect") == "/app":
            profile = client.get("/api/auth/me")
            print("Authenticated profile status:", profile.status_code, flush=True)
            print("Protected workspace status:", client.get("/app").status_code, flush=True)
            client.get("/logout", follow_redirects=False)
            login = client.post("/api/auth/login", json=credentials)
            print("Fresh login status:", login.status_code, flush=True)
            print("Fresh login profile status:", client.get("/api/auth/me").status_code, flush=True)


if __name__ == "__main__":
    check()
