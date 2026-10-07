from __future__ import annotations

from uuid import UUID

from dms_core.dedup import minhash_lsh
from dms_core.dedup.semantic import cosine
from dms_core.enrich.doctype import resolve_doctype
from dms_core.enrich.metadata import parse_enrichment, to_document_meta
from dms_core.enrich.prompts import enrichment_messages
from dms_core.enrich.tags import match_llm_tags, suggest_tags
from dms_core.enrich.titles import suggest_title
from dms_core.folders import INBOX_FOLDER_ID, auto_folder_candidates
from dms_core.models import Chunk, DocumentRow, EnrichmentResult, Job, TitleSuggestion, VersionRow
from dms_core.ports import Container
from dms_workers.indexing import manifest_chunks, reindex_document
from dms_workers.stages.common import load_job_context

LLM_TITLE_CONFIDENCE = 0.7


def choose_title(
    c: Container, doc: DocumentRow, version: VersionRow, result: EnrichmentResult
) -> TitleSuggestion | None:
    if doc.title_source == "user":
        return None
    heuristic = suggest_title(version.embedded_title, list(version.blocks or []), version.original_filename)
    if heuristic.confidence < c.settings.title_llm_threshold and result.title:
        return TitleSuggestion(title=result.title, source="llm", confidence=LLM_TITLE_CONFIDENCE)
    return heuristic


def apply_supersedes(c: Container, doc: DocumentRow, supersedes_ref: str | None) -> UUID | None:
    if not supersedes_ref:
        return None
    previous = c.repo.find_document_by_reference(doc.department_id, supersedes_ref, exclude_id=doc.id)
    if previous is None:
        return None
    if previous.superseded_by != doc.id:
        c.repo.update_document(previous.id, superseded_by=doc.id)
        reindex_document(c, previous.id)
    return previous.id


def apply_tags(c: Container, doc: DocumentRow, llm_tag_names: list[str]) -> None:
    department_tags = c.repo.list_tags([doc.department_id])
    if not department_tags:
        return
    existing = {ref.id for ref in c.repo.get_document_tags(doc.id)}
    document_vector = c.repo.document_embedding(doc.id)
    for tag, similarity in suggest_tags(document_vector, department_tags, c.settings.tag_similarity_threshold):
        if tag.id not in existing:
            c.repo.set_document_tag(doc.id, tag.id, "ai", "suggested", similarity)
            existing.add(tag.id)
    for tag in match_llm_tags(llm_tag_names, department_tags):
        if tag.id not in existing:
            c.repo.set_document_tag(doc.id, tag.id, "ai", "suggested", None)
            existing.add(tag.id)


def auto_file(c: Container, doc: DocumentRow) -> DocumentRow:
    if doc.folder_id not in (None, INBOX_FOLDER_ID):
        return doc
    for folder_id in auto_folder_candidates(doc.doctype, doc.department_id, doc.meta):
        if c.repo.get_folder(folder_id) is not None:
            return c.repo.update_document(doc.id, folder_id=folder_id)
    if doc.folder_id is None and c.repo.get_folder(INBOX_FOLDER_ID) is not None:
        return c.repo.update_document(doc.id, folder_id=INBOX_FOLDER_ID)
    return doc


def save_document_minhash(c: Container, doc_id: UUID, chunks: list[Chunk]) -> tuple[bytes, list[tuple[int, str]]]:
    full_text = "\n\n".join(chunk.text for chunk in chunks)
    minhash = minhash_lsh.signature(full_text, c.settings.minhash_perm)
    signature_bytes = minhash_lsh.serialize(minhash)
    band_keys = minhash_lsh.bands(minhash, c.settings.minhash_bands)
    c.repo.save_minhash(doc_id, signature_bytes, band_keys)
    return signature_bytes, band_keys


def detect_duplicates(c: Container, doc: DocumentRow, chunks: list[Chunk]) -> None:
    signature_bytes, band_keys = save_document_minhash(c, doc.id, chunks)
    if doc.duplicate_tier == "exact":
        return
    candidates = c.repo.find_minhash_candidates(band_keys, doc.id)
    if not candidates:
        return
    scored = sorted(
        ((candidate_id, minhash_lsh.jaccard(signature_bytes, candidate_signature)) for candidate_id, candidate_signature in candidates),
        key=lambda pair: pair[1],
        reverse=True,
    )
    best_id, best_score = scored[0]
    if best_score >= c.settings.near_dup_jaccard:
        c.repo.update_document(doc.id, duplicate_of=best_id, duplicate_tier="near")
        return
    document_vector = c.repo.document_embedding(doc.id)
    if not document_vector:
        return
    for candidate_id, _ in scored:
        candidate_vector = c.repo.document_embedding(candidate_id)
        if candidate_vector and cosine(document_vector, candidate_vector) >= c.settings.semantic_dup_threshold:
            c.repo.update_document(doc.id, duplicate_of=candidate_id, duplicate_tier="semantic")
            return


def enrich_document(c: Container, doc: DocumentRow, version: VersionRow) -> EnrichmentResult:
    chunks = manifest_chunks(c, version)
    taxonomy = [tag.name for tag in c.repo.list_tags([doc.department_id])]
    sample = "\n\n".join(chunk.text for chunk in chunks)
    raw = c.llm.complete(
        enrichment_messages(sample, version.original_filename, taxonomy),
        model=c.settings.llm_fast_model,
        json_mode=True,
    )
    result = parse_enrichment(raw)
    result.doctype = resolve_doctype(result.doctype, result.title or doc.title, version.original_filename, sample)
    updates: dict[str, object] = {"doctype": result.doctype, "meta": to_document_meta(result)}
    title = choose_title(c, doc, version, result)
    if title is not None and title.source != "default":
        updates.update(title=title.title, title_source=title.source, title_confidence=title.confidence)
    doc = c.repo.update_document(doc.id, **updates)
    doc = auto_file(c, doc)
    apply_supersedes(c, doc, result.supersedes_ref)
    apply_tags(c, doc, result.tags)
    detect_duplicates(c, doc, chunks)
    return result


def run(c: Container, job: Job) -> None:
    doc, version = load_job_context(c, job)
    enrich_document(c, doc, version)
    reindex_document(c, doc.id)
    c.repo.set_status(doc.id, "ENRICHED")
    c.jobs.enqueue(doc.id, version.id, "summarize")
