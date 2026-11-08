from pathlib import Path
from uuid import UUID

from sqlalchemy import inspect, select, text

from app.database.engine import build_engine, build_session_factory
from app.database.models import Base
from app.runs.models import RunEventModel, RunModel
from app.runs.schemas import RunEvent, RunRecord


class RunRepository:
    def __init__(self, database_path: Path):
        self._database_path = database_path
        self._engine = build_engine(database_path)
        self._session_factory = build_session_factory(self._engine)

    def initialize(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        Base.metadata.create_all(
            self._engine, tables=[RunModel.__table__, RunEventModel.__table__]
        )
        columns = set()
        for column in inspect(self._engine).get_columns("runs"):
            columns.add(column["name"])
        additions = {
            "bug_report": "JSON",
            "repro_brief": "JSON",
            "evidence_frames": "JSON NOT NULL DEFAULT '[]'",
            "reported_verdict": "JSON",
            "recordings": "JSON NOT NULL DEFAULT '[]'",
            "recording_metadata": "JSON NOT NULL DEFAULT '[]'",
        }
        with self._engine.begin() as connection:
            for name, definition in additions.items():
                if name not in columns:
                    connection.execute(text(f"ALTER TABLE runs ADD COLUMN {name} {definition}"))
            if "reported_verdict" not in columns:
                connection.execute(text("""
                    UPDATE runs SET reported_verdict = (
                        SELECT payload FROM run_events WHERE run_id = runs.id
                        AND event_type = 'reproduction.verdict' ORDER BY sequence DESC LIMIT 1
                    )
                """))

    @property
    def data_directory(self) -> Path:
        return self._database_path.parent / "runs"

    def save_run(self, run: RunRecord) -> None:
        with self._session_factory.begin() as session:
            session.merge(self._build_run_model(run))

    def get_run(self, run_id: UUID) -> RunRecord | None:
        with self._session_factory() as session:
            run = session.get(RunModel, run_id)

        if not run:
            return None

        return RunRecord.model_validate(run, from_attributes=True)

    def list_runs_for_user(self, user_id: UUID, limit: int) -> list[RunRecord]:
        statement = (
            select(RunModel)
            .where(RunModel.user_id == user_id)
            .order_by(RunModel.created_at.desc(), RunModel.id.desc())
            .limit(limit)
        )
        with self._session_factory() as session:
            stored_runs = session.scalars(statement).all()

        runs = []
        for stored_run in stored_runs:
            runs.append(RunRecord.model_validate(stored_run, from_attributes=True))
        return runs

    def save_event(self, event: RunEvent, *, updated_run: RunRecord | None = None) -> None:
        with self._session_factory.begin() as session:
            if updated_run is not None:
                session.merge(self._build_run_model(updated_run))
            session.add(
                RunEventModel(
                    id=event.id,
                    run_id=event.run_id,
                    sequence=event.sequence,
                    event_type=event.event_type,
                    payload=event.payload,
                    created_at=event.created_at,
                )
            )

    def list_events(
        self,
        run_id: UUID,
        after_sequence: int = 0,
    ) -> list[RunEvent]:
        statement = (
            select(RunEventModel)
            .where(RunEventModel.run_id == run_id, RunEventModel.sequence > after_sequence)
            .order_by(RunEventModel.sequence)
        )
        with self._session_factory() as session:
            stored_events = session.scalars(statement).all()

        events = []
        for stored_event in stored_events:
            events.append(RunEvent.model_validate(stored_event, from_attributes=True))
        return events

    @staticmethod
    def _build_run_model(run: RunRecord) -> RunModel:
        frames = []
        for frame in run.evidence_frames:
            frames.append(frame.model_dump())
        return RunModel(
            id=run.id,
            thread_id=run.thread_id,
            user_id=run.user_id,
            credential_ids=RunRepository._stringify_ids(run.credential_ids),
            task=run.task,
            bug_report=run.bug_report.model_dump() if run.bug_report else None,
            repro_brief=run.repro_brief,
            evidence_frames=frames,
            reported_verdict=run.reported_verdict.model_dump() if run.reported_verdict else None,
            recordings=run.recordings,
            recording_metadata=[item.model_dump() for item in run.recording_metadata],
            status=run.status.value,
            max_runtime_seconds=run.max_runtime_seconds,
            final_output=run.final_output,
            error=run.error,
            follow_up_expires_at=run.follow_up_expires_at,
            created_at=run.created_at,
            updated_at=run.updated_at,
        )

    @staticmethod
    def _stringify_ids(ids: list[UUID]) -> list[str]:
        strings = []
        for item in ids:
            strings.append(str(item))
        return strings
