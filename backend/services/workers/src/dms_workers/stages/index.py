from __future__ import annotations

from dms_core.enrich.titles import suggest_title
from dms_core.models import DocumentRow, Job, VersionRow
from dms_core.ports import Container
from dms_core.versioning.merkle import merkle_root
from dms_workers.indexing import fill_missing_embeddings, reindex_document
from dms_workers.stages.common import chunk_version, load_job_context


def apply_preliminary_title(c: Container, doc: DocumentRow, version: VersionRow) -> None:
    if doc.title_source != "default":
        return
    suggestion = suggest_title(version.embedded_title, list(version.blocks or []), version.original_filename)
    if suggestion.source == "default":
        return
    c.repo.update_document(
        doc.id,
        title=suggestion.title,
        title_source=suggestion.source,
        title_confidence=suggestion.confidence,
    )


def index_version(c: Container, doc: DocumentRow, version: VersionRow) -> int:
    chunks, _ = fill_missing_embeddings(c, chunk_version(c, doc, version))
    c.repo.upsert_chunks(chunks)
    chunk_ids = [chunk.id for chunk in chunks]
    c.repo.update_version(version.id, chunk_manifest=chunk_ids, merkle_root=merkle_root(chunk_ids))
    apply_preliminary_title(c, doc, version)
    return reindex_document(c, doc.id)


def run(c: Container, job: Job) -> None:
    doc, version = load_job_context(c, job)
    index_version(c, doc, version)
    c.repo.set_status(doc.id, "INDEXED")
    c.jobs.enqueue(doc.id, version.id, "enrich")
