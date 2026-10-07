from __future__ import annotations

from dms_core.models import DeltaStats, Job
from dms_core.ports import Container
from dms_core.raptor.build import refresh_tree, root_of
from dms_core.versioning.delta_plan import plan_delta
from dms_workers.indexing import fill_missing_embeddings, reindex_document
from dms_workers.stages import index as index_stage
from dms_workers.stages.common import chunk_version, load_job_context
from dms_workers.stages.enrich import enrich_document, save_document_minhash

REENRICH_ADDED_FRACTION = 0.2


def run(c: Container, job: Job) -> None:
    doc, version = load_job_context(c, job)
    previous = c.repo.get_previous_version(doc.id, version.version_no)
    if previous is None or previous.chunk_manifest is None:
        index_stage.run(c, job)
        return
    new_chunks = chunk_version(c, doc, version)
    new_ids = [chunk.id for chunk in new_chunks]
    previous_nodes = c.repo.get_raptor_nodes(doc.id, previous.version_no)
    plan = plan_delta(list(previous.chunk_manifest), new_ids, previous_nodes)
    reused_embeddings = {
        chunk.id: chunk.embedding for chunk in c.repo.get_chunks(plan.reused) if chunk.embedding
    }
    seeded = [
        chunk.model_copy(update={"embedding": reused_embeddings[chunk.id]}) if chunk.id in reused_embeddings else chunk
        for chunk in new_chunks
    ]
    chunks, reembedded = fill_missing_embeddings(c, seeded)
    c.repo.upsert_chunks(chunks)
    if plan.unchanged and previous_nodes:
        nodes = [node.model_copy(update={"version_no": version.version_no}) for node in previous_nodes]
        refreshed = 0
    else:
        nodes, refreshed = refresh_tree(
            previous_nodes,
            chunks,
            plan.dirty_raptor_nodes,
            plan.added,
            plan.removed,
            c.llm,
            c.embedder,
            model=c.settings.llm_fast_model,
            small_doc_chunks=c.settings.raptor_small_doc_chunks,
            max_depth=c.settings.raptor_max_depth,
            version_no=version.version_no,
        )
    c.repo.replace_raptor_nodes(doc.id, version.version_no, nodes)
    c.repo.update_version(version.id, chunk_manifest=new_ids, merkle_root=plan.new_root)
    c.repo.set_delta_stats(
        version.id,
        DeltaStats(
            added=len(plan.added),
            removed=len(plan.removed),
            reused=len(plan.reused),
            reembedded=reembedded,
            raptor_nodes_refreshed=refreshed,
        ),
    )
    root = root_of(nodes)
    doc = c.repo.update_document(doc.id, root_summary=root.summary_text if root else None)
    refreshed_version = c.repo.get_version(version.id) or version
    added_fraction = len(plan.added) / len(new_ids) if new_ids else 0.0
    if added_fraction > REENRICH_ADDED_FRACTION:
        enrich_document(c, doc, refreshed_version)
    else:
        save_document_minhash(c, doc.id, chunks)
    reindex_document(c, doc.id)
    c.repo.set_status(doc.id, "READY")
