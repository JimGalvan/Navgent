from sqlalchemy.orm import Mapped, mapped_column

from app.database.models import Base


class UserModel(Base):
    __tablename__ = "users"

    workos_user_id: Mapped[str] = mapped_column(unique=True)
    email: Mapped[str]
