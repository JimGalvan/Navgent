from datetime import datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.credentials.models import CredentialModel
from app.credentials.schemas import CredentialRecord
from app.database.engine import build_engine, build_session_factory
from app.database.models import Base


class CredentialRepository:
    def __init__(self, database_path: Path):
        self._database_path = database_path
        self._engine = build_engine(database_path)
        self._session_factory = build_session_factory(self._engine)

    def initialize(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        Base.metadata.create_all(self._engine, tables=[CredentialModel.__table__])

    def save(self, credential: CredentialRecord) -> None:
        try:
            with self._session_factory.begin() as session:
                session.merge(self._build_model(credential))
        except IntegrityError as exception:
            raise ValueError("A credential with that name already exists") from exception

    def get_owned(self, credential_id: UUID, user_id: UUID) -> CredentialRecord | None:
        statement = select(CredentialModel).where(
            CredentialModel.id == credential_id,
            CredentialModel.user_id == user_id,
            CredentialModel.revoked_at.is_(None),
        )
        with self._session_factory() as session:
            credential = session.scalars(statement).one_or_none()

        if not credential:
            return None

        return CredentialRecord.model_validate(credential, from_attributes=True)

    def list_for_user(self, user_id: UUID) -> list[CredentialRecord]:
        statement = (
            select(CredentialModel)
            .where(CredentialModel.user_id == user_id, CredentialModel.revoked_at.is_(None))
            .order_by(
                CredentialModel.is_default.desc(),
                CredentialModel.name.collate("NOCASE"),
                CredentialModel.created_at,
            )
        )
        with self._session_factory() as session:
            stored_credentials = session.scalars(statement).all()

        credentials = []
        for stored_credential in stored_credentials:
            credentials.append(
                CredentialRecord.model_validate(stored_credential, from_attributes=True)
            )
        return credentials

    def revoke(self, credential_id: UUID, user_id: UUID, revoked_at: datetime) -> bool:
        statement = (
            update(CredentialModel)
            .where(
                CredentialModel.id == credential_id,
                CredentialModel.user_id == user_id,
                CredentialModel.revoked_at.is_(None),
            )
            .values(encrypted_payload=None, revoked_at=revoked_at, updated_at=revoked_at)
        )
        with self._session_factory.begin() as session:
            result = session.execute(statement)
        return result.rowcount == 1

    @staticmethod
    def _build_model(credential: CredentialRecord) -> CredentialModel:
        return CredentialModel(
            id=credential.id,
            user_id=credential.user_id,
            name=credential.name,
            allowed_domains=credential.allowed_domains,
            login_hint=credential.login_hint,
            encrypted_payload=credential.encrypted_payload,
            available_fields=credential.available_fields,
            is_default=credential.is_default,
            preferred_verification=credential.preferred_verification,
            created_at=credential.created_at,
            updated_at=credential.updated_at,
            revoked_at=credential.revoked_at,
        )
