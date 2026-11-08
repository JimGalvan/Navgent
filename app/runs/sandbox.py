"""App-side client for the root-owned sandbox controller; no Docker privileges."""

import asyncio
import json
import math
import os
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, Field


class SandboxError(RuntimeError):
    pass


class SandboxInfo(BaseModel):
    container: str = Field(min_length=1, max_length=128)
    ws_endpoint: str
    runtime: str = Field(min_length=1, max_length=64)
    allowed_hosts: list[str]
    limits: dict[str, float] = Field(default_factory=dict)

    def public(self) -> dict:
        return self.model_dump(exclude={"ws_endpoint"})


class SandboxController:
    def __init__(self, mode: str | None = None, command: tuple[str, ...] | None = None):
        self.mode = (mode if mode is not None else os.getenv("REPROBE_SANDBOX", "local")).strip().lower()
        if self.mode not in {"local", "docker"}:
            raise SandboxError("REPROBE_SANDBOX must be local or docker.")
        self.command = command or ("sudo", "-n", "/usr/local/bin/sandboxctl")

    @property
    def enabled(self) -> bool:
        return self.mode == "docker"

    async def _invoke(self, *args: str) -> dict:
        # Neither the helper nor its child processes need the app's provider keys.
        environment = {key: value for key, value in os.environ.items()
                       if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL"}}
        try:
            process = await asyncio.create_subprocess_exec(
                *self.command, *args, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=environment,
            )
        except OSError as error:
            raise SandboxError("The sandbox controller is unavailable. Check its installation and permissions.") from error
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout=60)
        except TimeoutError as error:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise SandboxError(f"Sandbox {args[0]} timed out. Check the sandbox service and try again.") from error
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if process.returncode:
            raise SandboxError(f"Sandbox {args[0]} failed. Check the sandbox service and try again.")
        try:
            result = json.loads(output)
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (ValueError, UnicodeError) as error:
            raise SandboxError("The sandbox controller returned an invalid response.") from error

    async def start(self, run_id: UUID, host: str) -> SandboxInfo | None:
        if not self.enabled:
            return None
        try:
            result = await self._invoke("start", "--run", str(run_id), "--host", host)
            info = SandboxInfo.model_validate(result)
            endpoint = urlsplit(info.ws_endpoint)
            if (endpoint.scheme not in {"ws", "wss"} or endpoint.hostname not in {"127.0.0.1", "localhost", "::1"}
                    or not endpoint.port or endpoint.username or endpoint.password
                    or info.allowed_hosts != [host]
                    or any(not math.isfinite(info.limits.get(key, 0)) or info.limits.get(key, 0) <= 0
                           for key in ("cpus", "memory_mb", "pids", "time_limit_seconds"))):
                raise ValueError()
            return info
        except (ValueError, UnicodeError) as error:
            raise SandboxError("The sandbox controller returned an invalid endpoint or host restriction.") from error

    async def stop(self, run_id: UUID) -> None:
        if self.enabled:
            result = await self._invoke("stop", "--run", str(run_id))
            if result.get("stopped") is not True:
                raise SandboxError("Sandbox cleanup was not confirmed. The sandbox reaper must retry it.")

    async def reap(self) -> None:
        if self.enabled:
            await self._invoke("reap")
