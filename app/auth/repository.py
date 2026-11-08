from pathlib import Path

from sqlalchemy import select

from app.auth.models import UserModel
from app.auth.schemas import User
from app.database.engine import build_engine, build_session_factory
from app.database.models import Base


class UserRepository:
    def __init__(self, database_path: Path):
        self._database_path = database_path
        self._engine = build_engine(database_path)
        self._session_factory = build_session_factory(self._engine)

    def initialize(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        Base.metadata.create_all(self._engine, tables=[UserModel.__table__])

    def get_or_create_user(self, workos_user_id: str, email: str) -> User:
        statement = select(UserModel).where(UserModel.workos_user_id == workos_user_id)
        with self._session_factory.begin() as session:
            user = session.scalars(statement).one_or_none()
            if not user:
                user = UserModel(workos_user_id=workos_user_id)
                session.add(user)
            user.email = email
            session.flush()
            return User.model_validate(user, from_attributes=True)
