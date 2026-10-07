from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from strands import tool

from dms_core.access.guard import can_read
from dms_core.models import DOCTYPES, Chunk, Citation, DocumentRow, SearchFilters, SearchHit, User
from dms_core.ports import Container
from dms_core.search.service import SearchService

SNIPPET_CHARS = 700
QUOTE_CHARS = 300
BUDGET_MESSAGE = "Tool call limit reached. Answer now using only the sources you already have."
NOT_FOUND = "Document not found or you do not have access to it."
MAX_CHANGED_PASSAGES = 6


@dataclass
class AgentContext:
    user: User
    container: Container
    search: SearchService
    max_tool_calls: int = 8
    scope: SearchFilters | None = None
    sources: list[SearchHit] = field(default_factory=list)
    tool_calls: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def take_budget(self) -> bool:
        with self.lock:
            self.tool_calls += 1
            return self.tool_calls <= self.max_tool_calls

    def register(self, hit: SearchHit) -> int:
        with self.lock:
            for number, existing in enumerate(self.sources, start=1):
                if existing.chunk_id == hit.chunk_id:
                    return number
            self.sources.append(hit)
            return len(self.sources)

    def citations(self, numbers: list[int]) -> list[Citation]:
        result: list[Citation] = []
        for number in sorted(set(numbers)):
            if 1 <= number <= len(self.sources):
                hit = self.sources[number - 1]
                result.append(
                    Citation(
                        n=number,
                        document_id=hit.document_id,
                        title=hit.title or "Untitled document",
                        chunk_id=hit.chunk_id,
                        page=hit.page,
                        quote=hit.text[:QUOTE_CHARS],
                    )
                )
        return result

    def readable(self, document_id: str) -> DocumentRow | None:
        try:
            parsed = UUID(str(document_id).strip())
        except ValueError:
            return None
        row = self.container.repo.get_document(parsed)
        if row is None or not can_read(self.user, row):
            return None
        return row


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"json": {"type": "object", "properties": properties, "required": required}}


def _scoped_filters(scope: SearchFilters | None, doctype: str | None) -> SearchFilters | None:
    requested = doctype if doctype in DOCTYPES else None
    if scope is None:
        return SearchFilters(doctype=[requested]) if requested else None
    filters = scope.model_copy(deep=True)
    if requested:
        if filters.doctype and requested not in filters.doctype:
            return None
        filters.doctype = [requested]
    return filters


def _scope_ids(scope: SearchFilters | None) -> list[UUID] | None:
    if scope is None or not scope.document_ids:
        return None
    parsed: list[UUID] = []
    for value in scope.document_ids:
        try:
            parsed.append(UUID(str(value).strip()))
        except ValueError:
            continue
    return list(dict.fromkeys(parsed))


def _titles(context: AgentContext, ids: list[UUID]) -> dict[UUID, str]:
    rows = context.container.repo.get_documents(ids) if ids else []
    return {row.id: row.title for row in rows if can_read(context.user, row)}


def _change_source(context: AgentContext, row: DocumentRow, chunk: Chunk, label: str) -> str:
    number = context.register(
        SearchHit(
            chunk_id=chunk.id,
            document_id=row.id,
            score=1.0,
            text=chunk.text,
            page=chunk.page_from,
            heading_path=list(chunk.heading_path),
            title=f"{row.title} ({label})",
        )
    )
    section = " > ".join(chunk.heading_path)
    return f"[{number}] {label}" + (f" | section={section}" if section else "") + "\n" + chunk.text.strip()[:SNIPPET_CHARS]


def build_tools(context: AgentContext) -> list[Any]:
    repo = context.container.repo

    @tool(
        name="search_documents",
        description=(
            "Hybrid semantic and keyword search over the government documents the user can access. "
            "Returns numbered sources [n] with title, document_id, page, section and text. "
            "Cite these numbers in the final answer. Run separate searches for separate topics."
        ),
        inputSchema=_schema(
            {
                "query": {"type": "string", "description": "Search query in English, Malay or Chinese"},
                "doctype": {"type": "string", "enum": list(DOCTYPES), "description": "Optional document type filter"},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 10, "description": "Number of passages, default 6"},
            },
            ["query"],
        ),
    )
    def search_documents(query: str, doctype: str | None = None, top_k: int = 6) -> str:
        if not context.take_budget():
            return BUDGET_MESSAGE
        filters = _scoped_filters(context.scope, doctype)
        if filters is None and context.scope is not None:
            return "No matching passages found within the selected documents."
        hits = context.search.retrieve(context.user, query, k=max(1, min(int(top_k or 6), 10)), filters=filters)
        if not hits:
            return "No matching passages found."
        superseded_ids = [hit.document_id for hit in hits]
        rows = {row.id: row for row in repo.get_documents(list(dict.fromkeys(superseded_ids)))}
        newer = _titles(context, [row.superseded_by for row in rows.values() if row.superseded_by])
        lines: list[str] = []
        for hit in hits:
            number = context.register(hit)
            row = rows.get(hit.document_id)
            header = [f"[{number}] {hit.title or 'Untitled document'}", f"document_id={hit.document_id}"]
            if row is not None and row.doctype:
                header.append(f"type={row.doctype}")
            if hit.page is not None:
                header.append(f"page={hit.page}")
            if hit.heading_path:
                header.append("section=" + " > ".join(hit.heading_path))
            if hit.level > 0:
                header.append("document summary")
            if row is not None and row.meta.effective_date:
                header.append(f"effective={row.meta.effective_date}")
            if row is not None and row.superseded_by:
                header.append(f"SUPERSEDED by '{newer.get(row.superseded_by, 'a newer document')}' ({row.superseded_by})")
            lines.append(" | ".join(header) + "\n" + hit.text.strip()[:SNIPPET_CHARS])
        return "\n\n".join(lines)

    @tool(
        name="get_document",
        description=(
            "Get one document's metadata and summary: title, type, department, reference number, effective date, "
            "what it supersedes or is superseded by, and its summary as a citable source [n]."
        ),
        inputSchema=_schema({"document_id": {"type": "string", "description": "Document UUID"}}, ["document_id"]),
    )
    def get_document(document_id: str) -> str:
        if not context.take_budget():
            return BUDGET_MESSAGE
        row = context.readable(document_id)
        if row is None:
            return NOT_FOUND
        info: dict[str, Any] = {
            "document_id": str(row.id),
            "title": row.title,
            "doctype": row.doctype,
            "department_id": row.department_id,
            "status": row.status,
            "reference_no": row.meta.reference_no,
            "effective_date": row.meta.effective_date,
            "agency": row.meta.agency,
            "supersedes_reference": row.meta.supersedes_ref,
            "tags": [tag.name for tag in repo.get_document_tags(row.id)],
        }
        if row.superseded_by:
            newer = context.readable(str(row.superseded_by))
            info["superseded_by"] = {"document_id": str(row.superseded_by), "title": newer.title if newer else None}
        if row.meta.supersedes_ref:
            older = repo.find_document_by_reference(row.department_id, row.meta.supersedes_ref, exclude_id=row.id)
            if older is not None and can_read(context.user, older):
                info["supersedes"] = {"document_id": str(older.id), "title": older.title}
        if row.root_summary:
            number = context.register(
                SearchHit(
                    chunk_id=f"{row.id}:summary",
                    document_id=row.id,
                    score=1.0,
                    text=row.root_summary,
                    level=1,
                    title=row.title,
                )
            )
            info["summary_source"] = f"[{number}] {row.root_summary}"
        return json.dumps(info, ensure_ascii=False)

    @tool(
        name="get_document_versions",
        description=(
            "List a document's version history with upload time, filename and change statistics, plus the exact "
            "passages added and removed in the latest version as citable sources [n]. Use for questions about what changed."
        ),
        inputSchema=_schema({"document_id": {"type": "string", "description": "Document UUID"}}, ["document_id"]),
    )
    def get_document_versions(document_id: str) -> str:
        if not context.take_budget():
            return BUDGET_MESSAGE
        row = context.readable(document_id)
        if row is None:
            return NOT_FOUND
        history = sorted(repo.list_versions(row.id), key=lambda version: version.version_no)
        versions = [
            {
                "version_no": version.version_no,
                "uploaded_at": version.created_at.isoformat(),
                "filename": version.original_filename,
                "merkle_root": (version.merkle_root or "")[:12],
                "changes": version.delta_stats.model_dump() if version.delta_stats else None,
            }
            for version in history
        ]
        result: dict[str, Any] = {"document_id": str(row.id), "title": row.title, "versions": versions}
        if len(history) >= 2:
            previous, latest = history[-2], history[-1]
            old_ids = list(previous.chunk_manifest or [])
            new_ids = list(latest.chunk_manifest or [])
            added = [chunk_id for chunk_id in new_ids if chunk_id not in set(old_ids)]
            removed = [chunk_id for chunk_id in old_ids if chunk_id not in set(new_ids)]
            chunks = {chunk.id: chunk for chunk in repo.get_chunks(added + removed)}
            result["latest_change"] = {
                "from_version": previous.version_no,
                "to_version": latest.version_no,
                "added_passages": [
                    _change_source(context, row, chunks[chunk_id], f"added in v{latest.version_no}")
                    for chunk_id in added
                    if chunk_id in chunks
                ][:MAX_CHANGED_PASSAGES],
                "removed_passages": [
                    _change_source(context, row, chunks[chunk_id], f"removed in v{latest.version_no}")
                    for chunk_id in removed
                    if chunk_id in chunks
                ][:MAX_CHANGED_PASSAGES],
            }
        return json.dumps(result, ensure_ascii=False)

    @tool(
        name="list_documents",
        description=(
            "List documents the user can access, optionally filtered by type, tag or department. "
            "Use to enumerate e.g. all circulars or all SOPs before reading them."
        ),
        inputSchema=_schema(
            {
                "doctype": {"type": "string", "enum": list(DOCTYPES)},
                "tag": {"type": "string"},
                "department_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            [],
        ),
    )
    def list_documents(
        doctype: str | None = None, tag: str | None = None, department_id: str | None = None, limit: int = 20
    ) -> str:
        if not context.take_budget():
            return BUDGET_MESSAGE
        allowed = context.user.department_ids
        departments = [department_id] if department_id in allowed else allowed
        scoped_ids = _scope_ids(context.scope)
        limit_value = max(1, min(int(limit or 20), 50))
        if scoped_ids is not None:
            wanted_tag = (tag or "").strip().lower()
            matching = [
                row
                for row in repo.get_documents(scoped_ids)
                if can_read(context.user, row)
                and row.department_id in departments
                and row.status == "READY"
                and (doctype not in DOCTYPES or row.doctype == doctype)
                and (not wanted_tag or any(ref.name.lower() == wanted_tag for ref in repo.get_document_tags(row.id)))
            ]
            rows, total = matching[:limit_value], len(matching)
        else:
            rows, total = repo.list_documents(
                department_ids=departments,
                doctype=doctype if doctype in DOCTYPES else None,
                tag=tag or None,
                status="READY",
                page=1,
                page_size=limit_value,
            )
        items = [
            {
                "document_id": str(row.id),
                "title": row.title,
                "doctype": row.doctype,
                "department_id": row.department_id,
                "effective_date": row.meta.effective_date,
                "superseded": row.superseded_by is not None,
            }
            for row in rows
        ]
        return json.dumps({"total": total, "documents": items}, ensure_ascii=False)

    return [search_documents, get_document, get_document_versions, list_documents]
