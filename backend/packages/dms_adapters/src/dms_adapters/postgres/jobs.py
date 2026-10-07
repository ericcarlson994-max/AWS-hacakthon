from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from dms_adapters.postgres.db import Database
from dms_core.config import Settings
from dms_core.models import Job, Stage


class PostgresJobQueue:
    def __init__(self, settings: Settings, database: Any = None) -> None:
        self.settings = settings
        if database is None:
            self.db = Database.from_settings(settings)
        elif isinstance(database, Database):
            self.db = database
        else:
            self.db = getattr(database, "db")

    def enqueue(self, document_id: UUID, version_id: UUID | None, stage: Stage) -> Job:
        with self.db.connection() as connection:
            row = connection.execute(
                "INSERT INTO jobs (document_id, version_id, stage) VALUES (%s, %s, %s) RETURNING *",
                (document_id, version_id, stage),
            ).fetchone()
        assert row is not None
        return Job.model_validate(row)

    def claim(self, stages: Sequence[Stage] | None = None) -> Job | None:
        stage_filter = ""
        params: list[Any] = []
        if stages:
            stage_filter = "AND stage = ANY(%s)"
            params.append(list(stages))
        with self.db.connection() as connection:
            row = connection.execute(
                "UPDATE jobs SET status = 'running', attempts = attempts + 1, updated_at = now() "
                "WHERE id = (SELECT id FROM jobs WHERE status = 'queued' AND run_after <= now() "
                f"{stage_filter} ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *",
                params,
            ).fetchone()
        return Job.model_validate(row) if row else None

    def complete(self, job: Job) -> None:
        with self.db.connection() as connection:
            connection.execute(
                "UPDATE jobs SET status = 'done', last_error = NULL, updated_at = now() WHERE id = %s", (job.id,)
            )

    def fail(self, job: Job, error: str, max_attempts: int = 3) -> bool:
        with self.db.connection() as connection:
            row = connection.execute(
                "UPDATE jobs SET last_error = %s, updated_at = now(), "
                "status = CASE WHEN attempts < %s THEN 'queued' ELSE 'failed' END, "
                "run_after = CASE WHEN attempts < %s THEN now() + make_interval(secs => power(2, attempts)) "
                "ELSE run_after END WHERE id = %s RETURNING status",
                (error[:4000], max_attempts, max_attempts, job.id),
            ).fetchone()
        return bool(row and row["status"] == "queued")
