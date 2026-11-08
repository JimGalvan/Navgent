import logging
import re
import time
from collections import OrderedDict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, SecretStr, field_validator
from starlette.concurrency import run_in_threadpool
from workos.exceptions import BaseRequestException
from httpx import RequestError

from app.auth.sessions import (
    get_client, is_local_request, seal_session_from_auth_response,
    set_session_cookie, user_repository, verify_auth_configuration,
)
from app.config import STATIC_DIRECTORY, read_workos_cookie_password

router = APIRouter()
attempts = OrderedDict()
logger = logging.getLogger(__name__)


class AccountInput(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: SecretStr = Field(default=SecretStr(""), max_length=1024)
    code: SecretStr = Field(default=SecretStr(""), max_length=128)
    token: SecretStr = Field(default=SecretStr(""), max_length=2048)

    @field_validator("email")
    @classmethod
    def email_format(cls, value):
        value = value.strip().lower()
        if value.count("@") != 1 or not all(value.split("@")):
            raise ValueError("Enter a valid email address")
        return value


def guard(request):
    try:
        verify_auth_configuration()
    except RuntimeError:
        raise HTTPException(503, "Account access is awaiting WorkOS configuration.") from None
    key = request.client.host if request.client else "unknown"
    now = time.monotonic()
    history = attempts.pop(key, [])
    history = [stamp for stamp in history if now - stamp < 300]
    attempts[key] = history
    while len(attempts) > 2048:
        attempts.popitem(last=False)
    if len(history) >= 15:
        raise HTTPException(429, "Too many attempts. Try again in five minutes.")
    history.append(now)


async def finish(authentication, request):
    await run_in_threadpool(user_repository.get_or_create_user, authentication.user.id, authentication.user.email)
    sealed = seal_session_from_auth_response(authentication, read_workos_cookie_password())
    response = JSONResponse({"redirect": "/app"})
    set_session_cookie(response, sealed, secure=not is_local_request(request))
    response.delete_cookie("reprobe_pending", path="/")
    return response


@router.get("/register", include_in_schema=False)
@router.get("/verify-email", include_in_schema=False)
@router.get("/forgot-password", include_in_schema=False)
@router.get("/reset-password", include_in_schema=False)
async def account_page():
    return FileResponse(STATIC_DIRECTORY / "account.html", headers={"Cache-Control": "no-store"})


@router.post("/api/auth/{action}")
async def account_action(action: str, body: AccountInput, request: Request):
    if action not in {"login", "register", "verify", "forgot", "reset"}:
        raise HTTPException(404)
    guard(request)
    manager = get_client().user_management
    operation = action
    try:
        if action == "forgot":
            await run_in_threadpool(manager.create_password_reset, body.email)
            return {"message": "If an account exists, a password reset link will arrive shortly."}
        if action == "reset":
            if not body.password.get_secret_value() or not body.token.get_secret_value():
                raise HTTPException(422, "Enter a new password and use a valid reset link.")
            await run_in_threadpool(manager.reset_password, token=body.token.get_secret_value(), new_password=body.password.get_secret_value())
            return {"redirect": "/login?reset=1"}
        if action == "verify":
            pending = request.cookies.get("reprobe_pending")
            if not pending or not body.code.get_secret_value():
                raise HTTPException(400, "This verification session expired. Log in again.")
            authentication = await run_in_threadpool(manager.authenticate_with_email_verification, code=body.code.get_secret_value(), pending_authentication_token=pending)
            return await finish(authentication, request)
        if not body.password.get_secret_value():
            raise HTTPException(422, "Enter your password.")
        if action == "register":
            operation = "create_user"
            await run_in_threadpool(manager.create_user, email=body.email, password=body.password.get_secret_value())
        operation = "authenticate" if action != "verify" else "verify"
        authentication = await run_in_threadpool(manager.authenticate_with_password, email=body.email, password=body.password.get_secret_value())
        return await finish(authentication, request)
    except BaseRequestException as error:
        data = error.response_json or {}
        code = data.get("code") or data.get("error") or "unknown"
        if data.get("pending_authentication_token") and code == "email_verification_required":
            response = JSONResponse({"redirect": "/verify-email"})
            response.set_cookie("reprobe_pending", data["pending_authentication_token"], max_age=600, httponly=True, secure=not is_local_request(request), samesite="lax")
            return response
        if action == "forgot":
            return {"message": "If an account exists, a password reset link will arrive shortly."}
        safe_code = re.sub(r"[^a-zA-Z0-9_-]", "", str(code))[:80]
        logger.warning("Account request failed: operation=%s status=%s code=%s", operation, error.response.status_code, safe_code)
        if code == "email_verification_required":
            raise HTTPException(400, "Email verification is required. Log in again to request a new code.") from None
        if code in {"password_strength_error", "weak_password", "password_too_short", "password_too_weak", "password_leaked"}:
            raise HTTPException(400, "Choose a stronger password: use at least 12 characters and avoid common or previously exposed passwords.") from None
        if code in {"user_already_exists", "email_already_exists", "email_not_unique"} or error.response.status_code == 409:
            raise HTTPException(400, "Could not create this account. Try logging in or resetting your password, or use a different email.") from None
        if code == "sso_required":
            raise HTTPException(400, "This email domain requires single sign-on. Use a different email for password login, or contact the app owner.") from None
        if code in {"invalid_client", "authentication_method_not_allowed"} or error.response.status_code in {401, 403}:
            raise HTTPException(503, "Account access needs a WorkOS configuration update. Please contact the app owner.") from None
        if action == "verify":
            raise HTTPException(400, "That code could not be verified. Check the code or log in again to request a new one.") from None
        if error.response.status_code >= 500:
            raise HTTPException(503, "The account service is temporarily unavailable. Please try again shortly.") from None
        raise HTTPException(400, "Account request could not be completed. Check your details or reset your password.") from None
    except RequestError:
        raise HTTPException(503, "The account service could not be reached. Please try again shortly.") from None
