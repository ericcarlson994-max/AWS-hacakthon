from __future__ import annotations

from dms_core.extract.router import extract
from dms_core.models import Job
from dms_core.ports import Container
from dms_workers.stages.common import load_job_context


def run(c: Container, job: Job) -> None:
    doc, version = load_job_context(c, job)
    data = c.blobs.get(version.blob_sha256)
    result = extract(
        data,
        version.original_filename,
        c.ocr,
        ocr_text_threshold=c.settings.ocr_text_threshold,
        render_dpi=c.settings.ocr_render_dpi,
    )
    c.repo.update_version(
        version.id,
        blocks=result.blocks,
        page_count=result.page_count,
        embedded_title=result.embedded_title,
        mime_type=result.mime_type,
    )
    c.repo.set_status(doc.id, "EXTRACTED")
    next_stage = "index" if version.version_no == 1 else "delta"
    c.jobs.enqueue(doc.id, version.id, next_stage)
