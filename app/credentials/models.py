from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models import Base


class CredentialModel(Base):
    __tablename__ = "credentials"

    user_id: Mapped[UUID]
    name: Mapped[str]
    allowed_domains: Mapped[list[str]] = mapped_column(JSON)
    login_hint: Mapped[str]
    encrypted_payload: Mapped[bytes | None]
    available_fields: Mapped[list[str]] = mapped_column(JSON)
    is_default: Mapped[bool] = mapped_column(default=False)
    preferred_verification: Mapped[list[str]] = mapped_column(JSON)
    revoked_at: Mapped[datetime | None]


Index(
    "idx_credentials_user",
    CredentialModel.user_id,
    CredentialModel.revoked_at,
    CredentialModel.name,
)
Index(
    "idx_credentials_active_name",
    CredentialModel.user_id,
    CredentialModel.name.collate("NOCASE"),
    unique=True,
    sqlite_where=CredentialModel.revoked_at.is_(None),
)
