from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from dms_core.access.groups import document_groups
from dms_core.models import Chunk, ChunkIndexDoc, DocumentRow, RaptorNode, TagRef, TitleIndexDoc, VersionRow
from dms_core.ports import Container


def embed_in_batches(c: Container, texts: Sequence[str]) -> list[list[float]]:
    batch_size = max(1, c.settings.embed_batch_size)
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        vectors.extend(c.embedder.embed(list(texts[start : start + batch_size])))
    return vectors


def fill_missing_embeddings(c: Container, chunks: list[Chunk]) -> tuple[list[Chunk], int]:
    missing = [chunk for chunk in chunks if not chunk.embedding]
    if not missing:
        return chunks, 0
    vectors = embed_in_batches(c, [chunk.text for chunk in missing])
    filled = {chunk.id: chunk.model_copy(update={"embedding": vector}) for chunk, vector in zip(missing, vectors)}
    return [filled.get(chunk.id, chunk) for chunk in chunks], len(missing)


def tag_names(tags: Sequence[TagRef]) -> list[str]:
    return sorted({tag.name for tag in tags})


def chunk_index_docs(
    c: Container,
    doc: DocumentRow,
    version: VersionRow | None,
    chunks: list[Chunk],
    nodes: list[RaptorNode],
    tags: list[TagRef],
) -> list[dict[str, Any]]:
    groups = document_groups(doc)
    names = tag_names(tags)
    superseded = doc.superseded_by is not None
    version_id = str(version.id) if version else None
    ready_chunks, _ = fill_missing_embeddings(c, chunks)
    summary_nodes = [node for node in nodes if node.level >= 1]
    nodes_without_embedding = [node for node in summary_nodes if not node.embedding]
    node_vectors = dict(
        zip(
            [node.id for node in nodes_without_embedding],
            embed_in_batches(c, [node.summary_text for node in nodes_without_embedding]),
        )
    )
    shared = {
        "document_id": str(doc.id),
        "version_id": version_id,
        "allowed_groups": groups,
        "department_id": doc.department_id,
        "doctype": doc.doctype,
        "tags": names,
        "title": doc.title,
        "effective_date": doc.meta.effective_date,
        "superseded": superseded,
    }
    docs: list[dict[str, Any]] = []
    for chunk in ready_chunks:
        docs.append(
            ChunkIndexDoc(
                chunk_id=chunk.id,
                level=0,
                text=chunk.text,
                heading_path=list(chunk.heading_path),
                page_from=chunk.page_from,
                embedding=list(chunk.embedding or []),
                **shared,
            ).model_dump()
        )
    for node in summary_nodes:
        docs.append(
            ChunkIndexDoc(
                chunk_id=node.id,
                level=node.level,
                text=node.summary_text,
                heading_path=[],
                page_from=None,
                embedding=list(node.embedding or node_vectors.get(node.id, [])),
                **shared,
            ).model_dump()
        )
    return docs


def title_index_doc(doc: DocumentRow, version: VersionRow | None, tags: list[TagRef]) -> dict[str, Any]:
    return TitleIndexDoc(
        document_id=str(doc.id),
        title=doc.title,
        filename=version.original_filename if version else None,
        tags=tag_names(tags),
        doctype=doc.doctype,
        department_id=doc.department_id,
        allowed_groups=document_groups(doc),
        superseded=doc.superseded_by is not None,
    ).model_dump()


def manifest_chunks(c: Container, version: VersionRow | None) -> list[Chunk]:
    if version is None or not version.chunk_manifest:
        return []
    by_id = {chunk.id: chunk for chunk in c.repo.get_chunks(version.chunk_manifest)}
    return [by_id[chunk_id] for chunk_id in version.chunk_manifest if chunk_id in by_id]


def reindex_document(c: Container, document_id: UUID) -> int:
    doc = c.repo.get_document(document_id)
    if doc is None:
        raise LookupError(f"document {document_id} not found")
    version = c.repo.get_current_version(doc.id)
    chunks = manifest_chunks(c, version)
    nodes = c.repo.get_raptor_nodes(doc.id, version.version_no) if version else []
    tags = c.repo.get_document_tags(doc.id)
    docs = chunk_index_docs(c, doc, version, chunks, nodes, tags)
    c.index.delete_document(str(doc.id))
    if docs:
        c.index.upsert_chunks(docs)
    c.index.upsert_title(title_index_doc(doc, version, tags))
    return len(docs)
