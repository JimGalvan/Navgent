"""Exercise saved credential management and multipart run selection in a browser."""

from email import policy
from email.parser import BytesParser
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

STATIC = Path(__file__).resolve().parents[1] / "server" / "static"
CAPTURES = Path(__file__).resolve().parents[1] / ".cache" / "credentials"
DEFAULT_ID = "00000000-0000-4000-8000-000000000001"
OTHER_ID = "00000000-0000-4000-8000-000000000002"
NEW_ID = "00000000-0000-4000-8000-000000000003"


def metadata(credential_id, name, default=False):
    return {
        "id": credential_id,
        "name": name,
        "allowed_domains": ["staging.example.test"],
        "login_hint": "t***r",
        "available_fields": ["login", "password"],
        "is_default": default,
        "preferred_verification": ["sms", "email"],
    }


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture(params=[1440, 390], ids=["desktop", "mobile"])
def surface(browser, request):
    context = browser.new_context(viewport={"width": request.param, "height": 1000})
    page = context.new_page()
    state = SimpleNamespace(
        page=page,
        width=request.param,
        credentials=[metadata(DEFAULT_ID, "Staging account", True), metadata(OTHER_ID, "Other account")],
        writes=[],
        run_fields=[],
        list_error=False,
        save_error=False,
        credential_reads=0,
        errors=[],
    )
    page.on("pageerror", lambda error: state.errors.append(str(error)))

    def handle(route):
        path = urlsplit(route.request.url).path
        method = route.request.method
        if path == "/api/auth/me":
            route.fulfill(json={"email": "tester@example.test"})
        elif path == "/api/runs":
            route.fulfill(json={"runs": []})
        elif path == "/api/credentials" and method == "GET":
            state.credential_reads += 1
            if state.list_error:
                route.fulfill(status=503, json={"detail": "Please try again."})
            else:
                route.fulfill(json={"credentials": state.credentials})
        elif path.startswith("/api/credentials"):
            body = route.request.post_data_json if method != "DELETE" else None
            state.writes.append((method, path, body))
            if state.save_error:
                route.fulfill(status=503, json={"detail": "Credential storage is unavailable until REPROBE_CREDENTIAL_KEY is configured"})
                return
            credential_id = NEW_ID if method == "POST" else path.rsplit("/", 1)[1]
            if method == "DELETE":
                remaining = []
                for item in state.credentials:
                    if item["id"] != credential_id:
                        remaining.append(item)
                state.credentials = remaining
                route.fulfill(status=204)
                return
            saved = metadata(credential_id, body["name"], body["is_default"])
            saved["allowed_domains"] = body["allowed_domains"]
            saved["preferred_verification"] = body["preferred_verification"]
            if method == "POST":
                saved["available_fields"] = []
                for field in ("login", "password", "email", "first_name", "last_name", "phone"):
                    if body.get(field):
                        saved["available_fields"].append(field)
                state.credentials.append(saved)
            route.fulfill(json=saved)
        elif path == "/api/reproductions":
            content_type = route.request.headers["content-type"]
            content = b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + route.request.post_data_buffer
            multipart = BytesParser(policy=policy.default).parsebytes(content)
            for part in multipart.iter_parts():
                name = part.get_param("name", header="content-disposition")
                state.run_fields.append((name, part.get_content()))
            route.fulfill(status=429, json={"detail": "No browser capacity. Try again."})
        elif path.startswith("/static/"):
            route.fulfill(path=STATIC / path.removeprefix("/static/"))
        else:
            route.fulfill(path=STATIC / "new.html")

    page.route("http://reprobe.test/**", handle)
    yield state
    context.close()
    assert state.errors == []


def open_manager(surface):
    page = surface.page
    page.goto("http://reprobe.test/app")
    page.locator("#target-url").fill("https://staging.example.test")
    page.get_by_role("button", name="Manage credentials", exact=True).click()
    expect(page.locator("#credential-manager")).to_be_visible()


def capture(surface, name):
    page = surface.page
    page.evaluate("document.fonts.ready")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    CAPTURES.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=CAPTURES / f"{name}-{surface.width}.png", full_page=True)


def test_default_selection_is_sent_with_reproduction(surface):
    page = surface.page
    page.goto("http://reprobe.test/app")
    page.locator("#target-url").fill("https://staging.example.test")
    picker = page.locator("#credential-picker")
    expect(picker.get_by_role("checkbox", name="Staging account")).to_be_checked()
    expect(picker.get_by_role("checkbox", name="Other account")).not_to_be_checked()
    picker.get_by_role("checkbox", name="Staging account").uncheck()
    picker.get_by_role("checkbox", name="Other account").check()
    page.locator("#steps").fill("Sign in and open the cart")
    page.locator("#expected").fill("The cart opens")
    page.get_by_role("button", name="Start reproduction").click()
    expect(page.locator("#form-message")).to_contain_text("No browser capacity")
    selected = []
    for name, value in surface.run_fields:
        if name == "credential_ids":
            selected.append(value)
        assert name not in {"password", "login"}
    assert selected == [OTHER_ID]
    expect(page.locator("#credential-selection")).to_be_enabled()
    expect(picker.get_by_role("checkbox", name="Other account")).to_be_checked()
    capture(surface, "picker")


def test_create_edit_remove_fields_and_close_clear_secret_inputs(surface):
    open_manager(surface)
    page = surface.page
    page.locator("#credential-name").fill("Checkout contact")
    page.locator("#credential-domains").fill("staging.example.test, *.example.test")
    page.locator("#credential-password").fill("  saved password  ")
    page.locator(".credential-contact summary").click()
    page.locator("#credential-email").fill("checkout@example.test")
    page.locator("#credential-first-name").fill("Ada")
    page.locator("#credential-verification").select_option("sms")
    page.locator("#credential-fallback").select_option("email")
    page.locator("#credential-default").check()
    page.get_by_role("button", name="Save credential", exact=True).click()
    expect(page.locator("#credential-message")).to_have_text("Credential saved and selected for this run.")
    saved = surface.writes[-1][2]
    assert saved["password"] == "  saved password  "
    assert saved["email"] == "checkout@example.test"
    assert saved["first_name"] == "Ada"
    assert saved["allowed_domains"] == ["staging.example.test", "*.example.test"]
    assert saved["preferred_verification"] == ["sms", "email"]
    assert saved["is_default"] is True
    expect(page.locator("#credential-picker").get_by_role("checkbox", name="Checkout contact")).to_be_checked()
    expect(page.locator("#credential-password")).to_have_value("")
    page.get_by_role("button", name="Edit Checkout contact").click()
    expect(page.locator("#credential-password")).to_have_value("")
    expect(page.locator("#credential-email")).to_have_value("")
    page.locator("#credential-name").fill("Updated contact")
    page.locator("#credential-remove-options").get_by_role("checkbox", name="First name", exact=True).check()
    page.get_by_role("button", name="Save changes").click()
    expect(page.locator("#credential-message")).to_have_text("Credential saved and selected for this run.")
    method, path, updated = surface.writes[-1]
    assert method == "PATCH"
    assert path.endswith(NEW_ID)
    assert updated["first_name"] is None
    assert "password" not in updated
    assert "email" not in updated
    page.locator("#credential-password").fill("unsaved password")
    capture(surface, "manager")
    page.get_by_role("button", name="Close", exact=True).click()
    expect(page.locator("#credential-manager")).to_be_hidden()
    expect(page.locator("#credential-password")).to_have_value("")
    expect(page.locator("#credential-manage")).to_be_focused()
    storage = page.evaluate("JSON.stringify([Object.entries(localStorage), Object.entries(sessionStorage)])")
    for value in ("saved password", "unsaved password", "checkout@example.test"):
        assert value not in storage


def test_delete_revokes_selection_and_cancel_preserves_it(surface):
    open_manager(surface)
    page = surface.page
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.get_by_role("button", name="Delete Staging account").click()
    assert surface.writes == []
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Delete Staging account").click()
    expect(page.locator("#credential-message")).to_have_text("Credential deleted.")
    expect(page.locator("#credential-name")).to_be_focused()
    expect(page.locator("#credential-picker").get_by_role("checkbox", name="Staging account")).to_have_count(0)
    assert surface.writes[-1] == ("DELETE", f"/api/credentials/{DEFAULT_ID}", None)


def test_empty_state_and_unavailable_storage_can_be_retried(surface):
    surface.credentials = []
    surface.list_error = True
    page = surface.page
    page.goto("http://reprobe.test/app")
    expect(page.locator("#credential-load-message")).to_contain_text("Could not load")
    surface.list_error = False
    page.get_by_role("button", name="Retry loading credentials").click()
    expect(page.locator("#credential-picker")).to_contain_text("No saved credentials")
    page.get_by_role("button", name="Manage credentials", exact=True).click()
    page.locator("#credential-name").fill("Test account")
    page.locator("#credential-domains").fill("staging.example.test")
    page.get_by_role("button", name="Save credential", exact=True).click()
    expect(page.locator("#credential-message")).to_contain_text("Add at least one")
    page.locator("#credential-login").fill("tester")
    surface.save_error = True
    page.get_by_role("button", name="Save credential", exact=True).click()
    expect(page.locator("#credential-message")).to_contain_text("Credential storage is not set up yet")
    expect(page.locator("#credential-message")).not_to_contain_text("REPROBE_CREDENTIAL_KEY")
    expect(page.locator("#credential-login")).to_have_value("tester")
    surface.save_error = False
    page.get_by_role("button", name="Save credential", exact=True).click()
    expect(page.locator("#credential-message")).to_contain_text("Credential saved")


def test_preview_does_not_read_or_write_credentials(surface):
    page = surface.page
    page.goto("http://reprobe.test/preview/new")
    expect(page.locator("#credential-picker")).to_contain_text("after you log in")
    expect(page.locator("#credential-manage")).to_be_disabled()
    expect(page.locator("#start-run")).to_be_enabled()
    assert surface.credential_reads == 0
    assert surface.writes == []


def test_picker_offers_only_credentials_matching_the_target_host(surface):
    surface.credentials[1]["allowed_domains"] = ["*.other.test"]
    page = surface.page
    page.goto("http://reprobe.test/app")
    picker = page.locator("#credential-picker")
    expect(picker).to_contain_text("Add an app URL")
    expect(picker.get_by_role("checkbox")).to_have_count(0)
    page.locator("#target-url").fill("https://staging.example.test/cart")
    expect(picker.get_by_role("checkbox", name="Staging account")).to_be_checked()
    expect(picker.get_by_role("checkbox", name="Other account")).to_have_count(0)
    page.locator("#target-url").fill("https://login.other.test")
    expect(picker.get_by_role("checkbox", name="Staging account")).to_have_count(0)
    expect(picker.get_by_role("checkbox", name="Other account")).to_be_visible()
    page.locator("#target-url").fill("https://staging.example.test.attacker.test")
    expect(picker.get_by_role("checkbox")).to_have_count(0)
    expect(picker).to_contain_text("No saved credentials match")
    page.locator("#target-url").fill("https://www.staging.example.test")
    expect(picker.get_by_role("checkbox")).to_have_count(0)
