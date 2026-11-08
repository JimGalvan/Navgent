import asyncio
from uuid import UUID

from app.credentials.domains import matches_allowlist
from app.credentials.exceptions import (
    CredentialDomainDeniedError,
    CredentialError,
    CredentialInvalidError,
)
from app.credentials.service import CredentialService
from navgent import CredentialMetadata, CredentialSecret


class CredentialServiceProvider:
    def __init__(
            self,
            credential_service: CredentialService,
            user_id: UUID,
            credential_ids: tuple[UUID, ...],
            target_host: str,
    ):
        self._credential_service = credential_service
        self._user_id = user_id
        self._credential_ids = tuple(credential_ids)
        self._target_host = target_host.encode("idna").decode("ascii").lower()

    async def list_selected(self) -> tuple[CredentialMetadata, ...]:
        selected = await asyncio.to_thread(
            self._credential_service.require_selected, self._credential_ids, self._user_id
        )
        metadata = []
        for item in selected:
            if not matches_allowlist(self._target_host.rstrip("."), item.allowed_domains):
                continue
            preferred = []
            for method in item.preferred_verification:
                preferred.append(method.value)
            metadata.append(CredentialMetadata(
                id=item.id,
                name=item.name,
                allowed_domains=tuple(item.allowed_domains),
                login_hint=item.login_hint,
                is_default=item.is_default,
                available_fields=tuple(item.available_fields),
                preferred_verification=tuple(preferred),
            ))
        return tuple(metadata)

    async def resolve(self, credential_id: UUID, domain: str) -> CredentialSecret:
        if credential_id not in self._credential_ids:
            raise ValueError("Credential is not selected for this run")
        if domain.encode("idna").decode("ascii").lower() != self._target_host:
            raise CredentialDomainDeniedError("Credentials are restricted to this run's target host")
        try:
            selected = await asyncio.to_thread(
                self._credential_service.require_selected, (credential_id,), self._user_id
            )
            if not matches_allowlist(self._target_host.rstrip("."), selected[0].allowed_domains):
                raise CredentialDomainDeniedError("Credential is not allowed on this run's target host")
            secret = await asyncio.to_thread(
                self._credential_service.resolve_for_domain, credential_id, self._user_id, self._target_host
            )
        except CredentialError:
            raise
        except Exception:
            raise CredentialInvalidError("The saved credential could not be read") from None
        return CredentialSecret(
            login=secret.login,
            password=secret.password,
            email=secret.email,
            first_name=secret.first_name,
            last_name=secret.last_name,
            phone=secret.phone,
        )
