from __future__ import annotations

import threading
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from dms_core.models import Job, Stage


class FakeJobQueue:
    def __init__(self, repo: object | None = None) -> None:
        self.repo = repo
        shared = getattr(repo, "jobs", None) if repo is not None else None
        self.jobs: dict[int, Job] = shared if isinstance(shared, dict) else {}
        self._next_id = max(self.jobs, default=0) + 1
        self._lock = threading.Lock()

    def enqueue(self, document_id: UUID, version_id: UUID | None, stage: Stage) -> Job:
        with self._lock:
            stamp = datetime.now(UTC)
            job = Job(
                id=self._next_id,
                document_id=UUID(str(document_id)),
                version_id=UUID(str(version_id)) if version_id else None,
                stage=stage,
                created_at=stamp,
                updated_at=stamp,
            )
            self._next_id += 1
            self.jobs[job.id] = job
            return job.model_copy()

    def claim(self, stages: Sequence[Stage] | None = None) -> Job | None:
        wanted = set(stages) if stages else None
        with self._lock:
            for job_id in sorted(self.jobs):
                job = self.jobs[job_id]
                if job.status != "queued" or (wanted is not None and job.stage not in wanted):
                    continue
                claimed = job.model_copy(
                    update={"status": "running", "attempts": job.attempts + 1, "updated_at": datetime.now(UTC)}
                )
                self.jobs[job_id] = claimed
                return claimed.model_copy()
        return None

    def complete(self, job: Job) -> None:
        with self._lock:
            stored = self.jobs.get(job.id)
            if stored is not None:
                self.jobs[job.id] = stored.model_copy(
                    update={"status": "done", "last_error": None, "updated_at": datetime.now(UTC)}
                )

    def fail(self, job: Job, error: str, max_attempts: int = 3) -> bool:
        with self._lock:
            stored = self.jobs.get(job.id)
            if stored is None:
                return False
            retry = stored.attempts < max_attempts
            self.jobs[job.id] = stored.model_copy(
                update={
                    "status": "queued" if retry else "failed",
                    "last_error": error,
                    "updated_at": datetime.now(UTC),
                }
            )
            return retry

    def pending(self) -> list[Job]:
        return [j.model_copy() for j in sorted(self.jobs.values(), key=lambda j: j.id) if j.status == "queued"]
