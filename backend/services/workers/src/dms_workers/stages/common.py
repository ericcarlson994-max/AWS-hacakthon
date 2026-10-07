from __future__ import annotations

from dms_core.chunking.structure_chunker import chunk_blocks
from dms_core.models import Chunk, DocumentRow, Job, VersionRow
from dms_core.ports import Container


def load_job_context(c: Container, job: Job) -> tuple[DocumentRow, VersionRow]:
    doc = c.repo.get_document(job.document_id)
    if doc is None:
        raise LookupError(f"document {job.document_id} not found")
    version = c.repo.get_version(job.version_id) if job.version_id else c.repo.get_current_version(doc.id)
    if version is None:
        raise LookupError(f"no version for document {doc.id}")
    return doc, version


def chunk_version(c: Container, doc: DocumentRow, version: VersionRow) -> list[Chunk]:
    if version.blocks is None:
        raise ValueError(f"version {version.id} has not been extracted")
    settings = c.settings
    return chunk_blocks(
        doc.id,
        list(version.blocks),
        target_tokens=settings.chunk_target_tokens,
        max_tokens=settings.chunk_max_tokens,
        overlap_ratio=settings.chunk_overlap_ratio,
    )
