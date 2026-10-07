from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from dms_core.enrich.prompts import (
    cluster_summary_messages,
    root_summary_messages,
    single_summary_messages,
)
from dms_core.models import Chunk, RaptorNode
from dms_core.ports import Embedder, Llm
from dms_core.raptor.cluster import cluster_vectors

SUMMARY_MAX_TOKENS = 400


def node_id(document_id: UUID | str, level: int, child_ids: Sequence[str]) -> str:
    digest = hashlib.sha1("|".join(child_ids).encode("utf-8")).hexdigest()[:12]
    return f"{document_id}:r{level}:{digest}"


def root_of(nodes: Sequence[RaptorNode]) -> RaptorNode | None:
    if not nodes:
        return None
    top_level = max(node.level for node in nodes)
    top_nodes = [node for node in nodes if node.level == top_level]
    if len(top_nodes) != 1:
        return None
    return top_nodes[0]


def _summarize(llm: Llm, messages: list[dict[str, Any]], model: str | None) -> str:
    return llm.complete(messages, model=model, max_tokens=SUMMARY_MAX_TOKENS).strip()


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _ensure_chunk_embeddings(chunks: list[Chunk], embedder: Embedder) -> list[Chunk]:
    missing = [chunk for chunk in chunks if not chunk.embedding]
    if not missing:
        return chunks
    vectors = embedder.embed([chunk.text for chunk in missing])
    filled = {chunk.id: chunk.model_copy(update={"embedding": vector}) for chunk, vector in zip(missing, vectors)}
    return [filled.get(chunk.id, chunk) for chunk in chunks]


def _make_node(
    document_id: UUID,
    version_no: int,
    level: int,
    child_ids: list[str],
    summary: str,
    embedding: list[float] | None,
) -> RaptorNode:
    return RaptorNode(
        id=node_id(document_id, level, child_ids),
        document_id=document_id,
        version_no=version_no,
        level=level,
        summary_text=summary,
        embedding=embedding,
        children=child_ids,
    )


def _single_root(
    document_id: UUID,
    version_no: int,
    chunks: list[Chunk],
    llm: Llm,
    embedder: Embedder,
    model: str | None,
) -> list[RaptorNode]:
    ordered = sorted(chunks, key=lambda chunk: chunk.order)
    summary = _summarize(llm, single_summary_messages("\n\n".join(chunk.text for chunk in ordered)), model)
    embedding = embedder.embed([summary])[0]
    return [_make_node(document_id, version_no, 1, [chunk.id for chunk in ordered], summary, embedding)]


def build_tree(
    document_id: UUID,
    version_no: int,
    chunks: list[Chunk],
    llm: Llm,
    embedder: Embedder,
    *,
    model: str | None = None,
    small_doc_chunks: int = 8,
    max_depth: int = 3,
) -> list[RaptorNode]:
    if not chunks:
        return []
    if len(chunks) <= small_doc_chunks or max_depth <= 1:
        return _single_root(document_id, version_no, chunks, llm, embedder, model)
    ordered = _ensure_chunk_embeddings(sorted(chunks, key=lambda chunk: chunk.order), embedder)
    layer_ids = [chunk.id for chunk in ordered]
    layer_texts = [chunk.text for chunk in ordered]
    layer_vectors = [list(chunk.embedding or []) for chunk in ordered]
    all_nodes: list[RaptorNode] = []
    level = 1
    while True:
        is_last_level = level >= max_depth
        groups = [] if is_last_level else cluster_vectors(layer_vectors)
        if is_last_level or len(groups) <= 1 or len(groups) >= len(layer_ids):
            summary = _summarize(llm, root_summary_messages(layer_texts), model)
            embedding = embedder.embed([summary])[0]
            all_nodes.append(_make_node(document_id, version_no, level, list(layer_ids), summary, embedding))
            return all_nodes
        summaries = [
            _summarize(llm, cluster_summary_messages([layer_texts[index] for index in group]), model)
            for group in groups
        ]
        embeddings = embedder.embed(summaries)
        new_nodes = [
            _make_node(document_id, version_no, level, [layer_ids[index] for index in group], summary, embedding)
            for group, summary, embedding in zip(groups, summaries, embeddings)
        ]
        all_nodes.extend(new_nodes)
        layer_ids = [node.id for node in new_nodes]
        layer_texts = summaries
        layer_vectors = [list(node.embedding or []) for node in new_nodes]
        level += 1


def _parent_index(nodes: dict[str, RaptorNode]) -> dict[str, str]:
    parents: dict[str, str] = {}
    for node in nodes.values():
        for child in node.children:
            parents[child] = node.id
    return parents


def refresh_tree(
    existing: list[RaptorNode],
    chunks: list[Chunk],
    dirty_ids: list[str],
    added_chunk_ids: list[str],
    removed_chunk_ids: list[str],
    llm: Llm,
    embedder: Embedder,
    *,
    model: str | None = None,
    small_doc_chunks: int = 8,
    max_depth: int = 3,
    version_no: int | None = None,
) -> tuple[list[RaptorNode], int]:
    target_version = version_no if version_no is not None else (existing[0].version_no if existing else 1)

    def rebuild() -> tuple[list[RaptorNode], int]:
        document_id = chunks[0].document_id if chunks else (existing[0].document_id if existing else None)
        if document_id is None:
            return [], 0
        nodes = build_tree(
            document_id, target_version, chunks, llm, embedder,
            model=model, small_doc_chunks=small_doc_chunks, max_depth=max_depth,
        )
        return nodes, len(nodes)

    if not existing or len(chunks) <= small_doc_chunks or root_of(existing) is None:
        return rebuild()
    if root_of(existing).level == 1:
        return rebuild()

    nodes = {node.id: node.model_copy(deep=True, update={"version_no": target_version}) for node in existing}
    touched: set[str] = {node_key for node_key in dirty_ids if node_key in nodes}

    removed = set(removed_chunk_ids)
    pending_removal = set(removed)
    while pending_removal:
        emptied: set[str] = set()
        for node in nodes.values():
            remaining = [child for child in node.children if child not in pending_removal]
            if len(remaining) != len(node.children):
                node.children = remaining
                touched.add(node.id)
                if not remaining:
                    emptied.add(node.id)
        for node_key in emptied:
            nodes.pop(node_key, None)
            touched.discard(node_key)
        pending_removal = emptied
    if not nodes or root_of(list(nodes.values())) is None:
        return rebuild()

    chunk_by_id = {chunk.id: chunk for chunk in chunks}
    added = [chunk_by_id[chunk_key] for chunk_key in added_chunk_ids if chunk_key in chunk_by_id]
    level_one = [node for node in nodes.values() if node.level == 1]
    if added:
        if not level_one:
            return rebuild()
        added = _ensure_chunk_embeddings(added, embedder)
        missing_level_one = [node for node in level_one if not node.embedding]
        if missing_level_one:
            for node, vector in zip(missing_level_one, embedder.embed([node.summary_text for node in missing_level_one])):
                node.embedding = vector
        for chunk in added:
            best = max(level_one, key=lambda node: _cosine(chunk.embedding or [], node.embedding or []))
            if chunk.id not in best.children:
                best.children.append(chunk.id)
            touched.add(best.id)

    parents = _parent_index(nodes)
    frontier = list(touched)
    while frontier:
        parent = parents.get(frontier.pop())
        if parent and parent not in touched:
            touched.add(parent)
            frontier.append(parent)

    root = root_of(list(nodes.values()))
    order_of_chunk = {chunk.id: chunk.order for chunk in chunks}
    for node in nodes.values():
        if node.level == 1:
            node.children.sort(key=lambda child: order_of_chunk.get(child, 0))

    refreshed: list[RaptorNode] = []
    for node in sorted((nodes[key] for key in touched), key=lambda item: item.level):
        if node.level == 1:
            texts = [chunk_by_id[child].text for child in node.children if child in chunk_by_id]
        else:
            texts = [nodes[child].summary_text for child in node.children if child in nodes]
        if root is not None and node.id == root.id:
            messages = root_summary_messages(texts)
        else:
            messages = cluster_summary_messages(texts)
        node.summary_text = _summarize(llm, messages, model)
        refreshed.append(node)
    if refreshed:
        for node, vector in zip(refreshed, embedder.embed([node.summary_text for node in refreshed])):
            node.embedding = vector

    ordered_nodes = sorted(nodes.values(), key=lambda item: (item.level, item.id))
    return ordered_nodes, len(refreshed)
