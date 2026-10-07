from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from collections.abc import Callable

from dms_core.models import Job
from dms_core.ports import Container
from dms_workers.stages import delta, enrich, extract, index, summarize

logger = logging.getLogger("dms_workers")

StageRunner = Callable[[Container, Job], None]

STAGES: dict[str, StageRunner] = {
    "extract": extract.run,
    "index": index.run,
    "enrich": enrich.run,
    "summarize": summarize.run,
    "delta": delta.run,
}


def describe_error(error: BaseException) -> str:
    message = str(error).strip()
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


def handle_failure(c: Container, job: Job, error: BaseException) -> None:
    message = describe_error(error)[:2000]
    logger.exception("job %s stage %s failed for document %s", job.id, job.stage, job.document_id)
    will_retry = c.jobs.fail(job, message, c.settings.job_max_attempts)
    if will_retry:
        return
    try:
        c.repo.set_status(job.document_id, "FAILED", f"{job.stage}: {message}")
    except Exception:
        logger.exception("could not mark document %s as failed", job.document_id)


def run_once(c: Container) -> bool:
    job = c.jobs.claim()
    if job is None:
        return False
    runner = STAGES.get(job.stage)
    try:
        if runner is None:
            raise ValueError(f"unknown stage {job.stage}")
        runner(c, job)
    except Exception as error:
        handle_failure(c, job, error)
        return True
    c.jobs.complete(job)
    logger.info("job %s stage %s done for document %s", job.id, job.stage, job.document_id)
    return True


def drain(c: Container, max_jobs: int = 500) -> int:
    processed = 0
    while processed < max_jobs and run_once(c):
        processed += 1
    return processed


def prepare(c: Container) -> None:
    c.blobs.ensure_bucket()
    c.index.ensure_indexes()


def serve(c: Container, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            worked = run_once(c)
        except Exception:
            logger.exception("worker loop error")
            worked = False
        if not worked:
            stop.wait(c.settings.worker_poll_seconds)


def install_signal_handlers(stop: threading.Event) -> None:
    def request_stop(signum: int, frame: object) -> None:
        logger.info("received signal %s, stopping after current job", signum)
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dms_workers.run")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-jobs", type=int, default=500)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    from dms_adapters.container import build_container

    c = build_container()
    prepare(c)
    if args.once:
        processed = drain(c, args.max_jobs)
        logger.info("drained %s jobs", processed)
        return 0
    stop = threading.Event()
    install_signal_handlers(stop)
    logger.info("worker started")
    serve(c, stop)
    logger.info("worker stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
