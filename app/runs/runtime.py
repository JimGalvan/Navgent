import logging
from dataclasses import replace
from pathlib import Path
from uuid import UUID

from app.config import read_agent_settings
from app.credentials.agent_provider import CredentialServiceProvider
from app.credentials.service import CredentialService
from app.runs import constants
from navgent import BrowserAgentSession

logging.getLogger("dotenv.main").setLevel(logging.ERROR)


def build_agent_runtime(
        thread_id: UUID,
        user_id: UUID | None,
        recording_dir: Path,
        credential_ids: tuple[UUID, ...] = (),
        credential_service: CredentialService | None = None,
        headless: bool | None = None,
        max_runtime_seconds: float = constants.DEFAULT_MAX_RUNTIME_SECONDS,
        sensitive_input_window_seconds: float = constants.DEFAULT_SENSITIVE_INPUT_WINDOW_SECONDS,
        browser_ws_endpoint: str | None = None,
        allowed_hosts: tuple[str, ...] = (),
        asset_hosts: tuple[str, ...] = (),
        credential_host: str | None = None,
) -> BrowserAgentSession:
    settings = replace(
        read_agent_settings(thread_id),
        recording_dir=recording_dir,
        max_runtime_seconds=max_runtime_seconds,
        sensitive_input_window_seconds=sensitive_input_window_seconds,
        browser_ws_endpoint=browser_ws_endpoint,
        allowed_hosts=allowed_hosts,
        asset_hosts=asset_hosts,
    )
    if headless is not None:
        settings = replace(settings, headless=headless)
    credential_provider = None
    if credential_service and credential_ids and user_id:
        if not credential_host:
            raise ValueError("A target URL is required to use saved credentials")
        if allowed_hosts and allowed_hosts != (credential_host,):
            raise ValueError("Credentials must use the sandbox's target host")
        settings = replace(settings, trace_path=None, credential_host=credential_host)
        credential_provider = CredentialServiceProvider(credential_service, user_id, credential_ids, credential_host)
    return BrowserAgentSession(
        settings, credential_provider=credential_provider, selected_credential_ids=credential_ids,
    )
