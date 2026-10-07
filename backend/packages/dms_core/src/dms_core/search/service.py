from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from uuid import UUID

from dms_core.access.groups import allowed_groups
from dms_core.access.guard import can_read
from dms_core.config import Settings
from dms_core.models import (
    DocumentRow,
    SearchFilters,
    SearchHit,
    SearchResponse,
    SearchResult,
    SuggestDocument,
    SuggestResponse,
    SuggestTag,
    User,
)
from dms_core.ports import Embedder, Repo, SearchIndex
from dms_core.search.facets import document_facets
from dms_core.search.fusion import rrf
from dms_core.search.hybrid_query import build_bm25_body, build_did_you_mean_body, build_knn_body
from dms_core.search.mappings import CHUNKS_INDEX, TITLES_INDEX
from dms_core.search.suggest_query import build_suggest_body

SUGGEST_MIN_CHARS = 2
SUGGEST_DOCUMENT_LIMIT = 8
SUGGEST_TAG_LIMIT = 5
BM25_SIZE = 50
SNIPPET_CHARS = 240
EMBED_CACHE_SIZE = 256


@dataclass
class ChunkCandidate:
    chunk_id: str
    source: dict[str, Any]
    highlight: str | None = None
    score: float = 0.0

    @property
    def document_id(self) -> str:
        return str(self.source.get("document_id", ""))

    @property
    def text(self) -> str:
        return str(self.source.get("text") or "")

    @property
    def snippet(self) -> str:
        return self.highlight or self.text[:SNIPPET_CHARS]


def normalize_query(text: str) -> str:
    return " ".join(text.lower().split())


def hits_of(response: dict[str, Any]) -> list[dict[str, Any]]:
    return list((response or {}).get("hits", {}).get("hits", []) or [])


def chunk_id_of(hit: dict[str, Any]) -> str:
    source = hit.get("_source") or {}
    return str(source.get("chunk_id") or hit.get("_id") or "")


def highlight_of(hit: dict[str, Any]) -> str | None:
    fragments = (hit.get("highlight") or {}).get("text") or []
    return fragments[0] if fragments else None


def parse_uuid(value: Any) -> UUID | None:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (ValueError, TypeError):
        return None


class SearchService:
    def __init__(self, index: SearchIndex, embedder: Embedder, repo: Repo, settings: Settings) -> None:
        self.index = index
        self.embedder = embedder
        self.repo = repo
        self.settings = settings
        self._cached_embedding = lru_cache(maxsize=EMBED_CACHE_SIZE)(self._embed_normalized)

    def _embed_normalized(self, normalized: str) -> tuple[float, ...]:
        return tuple(self.embedder.embed([normalized])[0])

    def embed_query(self, query: str) -> list[float]:
        return list(self._cached_embedding(normalize_query(query)))

    def suggest(self, user: User, q: str) -> SuggestResponse:
        text = (q or "").strip()
        if len(text) < SUGGEST_MIN_CHARS:
            return SuggestResponse(documents=[], tags=[])
        groups = allowed_groups(user)
        response = self.index.search(TITLES_INDEX, build_suggest_body(text, groups, size=SUGGEST_DOCUMENT_LIMIT))
        documents: list[SuggestDocument] = []
        seen_documents: set[UUID] = set()
        for hit in hits_of(response):
            source = hit.get("_source") or {}
            document_id = parse_uuid(source.get("document_id") or hit.get("_id"))
            if document_id is None or document_id in seen_documents:
                continue
            if source.get("department_id") not in groups and not set(source.get("allowed_groups") or []) & set(groups):
                continue
            seen_documents.add(document_id)
            documents.append(
                SuggestDocument(
                    id=document_id,
                    title=str(source.get("title") or ""),
                    doctype=source.get("doctype"),
                    department_id=str(source.get("department_id") or ""),
                )
            )
        aggregated_names = [
            str(bucket.get("key"))
            for bucket in ((response or {}).get("aggregations") or {}).get("tags", {}).get("buckets", [])
        ]
        tags_by_name = {tag.name.lower(): tag for tag in self.repo.list_tags(user.department_ids)}
        needle = text.lower()
        ordered_names = [name.lower() for name in aggregated_names if needle in name.lower()]
        ordered_names += [name for name in tags_by_name if needle in name]
        ordered_names += [name.lower() for name in aggregated_names]
        tags: list[SuggestTag] = []
        seen_tags: set[int] = set()
        for name in ordered_names:
            tag = tags_by_name.get(name)
            if tag is None or tag.id in seen_tags:
                continue
            seen_tags.add(tag.id)
            tags.append(SuggestTag(id=tag.id, name=tag.name))
            if len(tags) >= SUGGEST_TAG_LIMIT:
                break
        return SuggestResponse(documents=documents[:SUGGEST_DOCUMENT_LIMIT], tags=tags)

    def _hybrid(
        self, user: User, query: str, filters: SearchFilters | None, *, leaf_only: bool
    ) -> list[ChunkCandidate]:
        groups = allowed_groups(user)
        vector = self.embed_query(query)
        knn_response, bm25_response = self.index.msearch(
            [
                (CHUNKS_INDEX, build_knn_body(vector, groups, filters, self.settings.knn_k, leaf_only=leaf_only)),
                (CHUNKS_INDEX, build_bm25_body(query, groups, filters, BM25_SIZE, leaf_only=leaf_only)),
            ]
        )
        candidates: dict[str, ChunkCandidate] = {}
        rankings: list[list[str]] = []
        for response in (knn_response, bm25_response):
            ranking: list[str] = []
            for hit in hits_of(response):
                chunk_id = chunk_id_of(hit)
                if not chunk_id:
                    continue
                ranking.append(chunk_id)
                candidate = candidates.get(chunk_id)
                if candidate is None:
                    candidate = ChunkCandidate(chunk_id=chunk_id, source=dict(hit.get("_source") or {}))
                    candidates[chunk_id] = candidate
                highlighted = highlight_of(hit)
                if highlighted and not candidate.highlight:
                    candidate.highlight = highlighted
            rankings.append(ranking)
        fused = rrf(rankings, k=self.settings.rrf_k)
        ordered: list[ChunkCandidate] = []
        for chunk_id, score in fused.items():
            candidate = candidates[chunk_id]
            candidate.score = score
            ordered.append(candidate)
        return ordered

    def _readable_documents(self, user: User, document_ids: list[str]) -> dict[str, DocumentRow]:
        uuids = [parsed for parsed in (parse_uuid(value) for value in document_ids) if parsed is not None]
        if not uuids:
            return {}
        rows = self.repo.get_documents(list(dict.fromkeys(uuids)))
        return {str(row.id): row for row in rows if can_read(user, row)}

    def _did_you_mean(self, user: User, query: str) -> str | None:
        try:
            response = self.index.search(TITLES_INDEX, build_did_you_mean_body(query, allowed_groups(user)))
        except Exception:
            return None
        for entry in ((response or {}).get("suggest") or {}).get("did_you_mean", []) or []:
            for option in entry.get("options", []) or []:
                text = option.get("text")
                if text and normalize_query(text) != normalize_query(query):
                    return str(text)
        return None

    def search(
        self,
        user: User,
        query: str,
        filters: SearchFilters | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> SearchResponse:
        started = time.perf_counter()
        text = (query or "").strip()
        if not text:
            return SearchResponse(results=[], total=0, took_ms=0)
        candidates = self._hybrid(user, text, filters, leaf_only=True)
        best_by_document: dict[str, ChunkCandidate] = {}
        for candidate in candidates:
            if candidate.document_id and candidate.document_id not in best_by_document:
                best_by_document[candidate.document_id] = candidate
        documents = self._readable_documents(user, list(best_by_document))
        results: list[SearchResult] = []
        for document_id, candidate in best_by_document.items():
            row = documents.get(document_id)
            if row is None:
                continue
            score = candidate.score
            if row.superseded_by is not None:
                score *= self.settings.superseded_penalty
            results.append(
                SearchResult(
                    document_id=row.id,
                    title=row.title,
                    doctype=row.doctype,
                    department_id=row.department_id,
                    snippet=candidate.snippet,
                    page=candidate.source.get("page_from"),
                    heading_path=list(candidate.source.get("heading_path") or []),
                    score=score,
                    effective_date=row.meta.effective_date,
                    superseded_by=row.superseded_by,
                    summary=row.root_summary,
                )
            )
        results.sort(key=lambda result: result.score, reverse=True)
        total = len(results)
        page = max(page, 1)
        page_size = max(page_size, 1)
        page_results = results[(page - 1) * page_size : page * page_size]
        tags_by_document = {
            result.document_id: [tag.name for tag in self.repo.get_document_tags(result.document_id)] for result in results
        }
        for result in page_results:
            result.tags = tags_by_document[result.document_id]
        facets = document_facets(
            (result.doctype, result.department_id, tags_by_document[result.document_id]) for result in results
        )
        lexical_match = any(candidate.highlight for candidate in best_by_document.values())
        did_you_mean = None if lexical_match else self._did_you_mean(user, text)
        return SearchResponse(
            results=page_results,
            facets=facets,
            total=total,
            did_you_mean=did_you_mean,
            took_ms=int((time.perf_counter() - started) * 1000),
        )

    def retrieve(
        self, user: User, query: str, k: int = 8, filters: SearchFilters | None = None
    ) -> list[SearchHit]:
        text = (query or "").strip()
        if not text:
            return []
        candidates = self._hybrid(user, text, filters, leaf_only=False)
        documents = self._readable_documents(user, [candidate.document_id for candidate in candidates])
        hits: list[SearchHit] = []
        for candidate in candidates:
            row = documents.get(candidate.document_id)
            if row is None:
                continue
            score = candidate.score
            if row.superseded_by is not None:
                score *= self.settings.superseded_penalty
            hits.append(
                SearchHit(
                    chunk_id=candidate.chunk_id,
                    document_id=row.id,
                    score=score,
                    text=candidate.text,
                    highlight=candidate.highlight,
                    page=candidate.source.get("page_from"),
                    heading_path=list(candidate.source.get("heading_path") or []),
                    level=int(candidate.source.get("level") or 0),
                    title=row.title,
                )
            )
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:k]
