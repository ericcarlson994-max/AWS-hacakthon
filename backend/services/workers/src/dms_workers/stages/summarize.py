from __future__ import annotations

from dms_core.models import Job
from dms_core.ports import Container
from dms_core.raptor.build import build_tree, root_of
from dms_workers.indexing import manifest_chunks, reindex_document
from dms_workers.stages.common import load_job_context


def run(c: Container, job: Job) -> None:
    doc, version = load_job_context(c, job)
    chunks = manifest_chunks(c, version)
    nodes = build_tree(
        doc.id,
        version.version_no,
        chunks,
        c.llm,
        c.embedder,
        model=c.settings.llm_fast_model,
        small_doc_chunks=c.settings.raptor_small_doc_chunks,
        max_depth=c.settings.raptor_max_depth,
    )
    c.repo.replace_raptor_nodes(doc.id, version.version_no, nodes)
    root = root_of(nodes)
    c.repo.update_document(doc.id, root_summary=root.summary_text if root else None)
    reindex_document(c, doc.id)
    c.repo.set_status(doc.id, "READY")
