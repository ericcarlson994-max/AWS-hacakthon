from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

BlockType = Literal["heading", "paragraph", "table", "cell"]
BlockSource = Literal["text_layer", "ocr", "docx", "xlsx"]
DocStatus = Literal["UPLOADED", "EXTRACTED", "INDEXED", "ENRICHED", "READY", "FAILED"]
Stage = Literal["extract", "index", "enrich", "summarize", "delta"]
JobStatus = Literal["queued", "running", "done", "failed"]
DocType = Literal["policy", "sop", "circular", "guideline", "report", "minutes", "other"]
TitleSource = Literal["metadata", "heading", "filename", "llm", "user", "default"]
DuplicateTier = Literal["exact", "near", "semantic"]
Role = Literal["viewer", "contributor", "admin"]
TagSource = Literal["ai", "user"]
TagStatus = Literal["suggested", "confirmed"]

DOCTYPES: tuple[str, ...] = ("policy", "sop", "circular", "guideline", "report", "minutes", "other")
PUBLIC_DEPARTMENT = "public"
DEFAULT_TITLE = "Untitled document"


class Block(BaseModel):
    type: BlockType
    text: str
    page: int = 1
    level: int | None = None
    bbox: list[float] | None = None
    order: int = 0
    source: BlockSource = "text_layer"
    font_size: float | None = None


class ExtractResult(BaseModel):
    blocks: list[Block]
    page_count: int
    mime_type: str
    embedded_title: str | None = None
    ocr_pages: list[int] = Field(default_factory=list)


class Chunk(BaseModel):
    id: str
    document_id: UUID
    order: int = 0
    text: str
    heading_path: list[str] = Field(default_factory=list)
    page_from: int | None = None
    page_to: int | None = None
    token_count: int = 0
    embedding: list[float] | None = None


class Department(BaseModel):
    id: str
    name: str


class DepartmentMembership(BaseModel):
    id: str
    name: str
    role: Role


class User(BaseModel):
    id: str
    username: str
    display_name: str
    departments: list[DepartmentMembership] = Field(default_factory=list)

    @property
    def department_ids(self) -> list[str]:
        return [d.id for d in self.departments]

    def role_in(self, department_id: str) -> Role | None:
        for d in self.departments:
            if d.id == department_id:
                return d.role
        return None


class DocumentMeta(BaseModel):
    agency: str | None = None
    reference_no: str | None = None
    effective_date: str | None = None
    supersedes_ref: str | None = None
    language: str | None = None


class DocumentRow(BaseModel):
    id: UUID
    department_id: str
    title: str = DEFAULT_TITLE
    title_source: TitleSource = "default"
    title_confidence: float = 0.0
    doctype: DocType | None = None
    meta: DocumentMeta = Field(default_factory=DocumentMeta)
    superseded_by: UUID | None = None
    duplicate_of: UUID | None = None
    duplicate_tier: DuplicateTier | None = None
    root_summary: str | None = None
    status: DocStatus = "UPLOADED"
    status_detail: str | None = None
    current_version_id: UUID | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime
    folder_id: str | None = None
    deleted_at: datetime | None = None


class Folder(BaseModel):
    id: str
    name: str
    parent_id: str | None = None
    doc_count: int = 0


class DeltaStats(BaseModel):
    added: int = 0
    removed: int = 0
    reused: int = 0
    reembedded: int = 0
    raptor_nodes_refreshed: int = 0


class VersionRow(BaseModel):
    id: UUID
    document_id: UUID
    version_no: int
    blob_sha256: str
    original_filename: str
    mime_type: str
    size_bytes: int
    page_count: int | None = None
    blocks: list[Block] | None = None
    embedded_title: str | None = None
    merkle_root: str | None = None
    chunk_manifest: list[str] | None = None
    delta_stats: DeltaStats | None = None
    uploaded_by: str | None = None
    created_at: datetime


class DeltaPlan(BaseModel):
    unchanged: bool
    old_root: str | None = None
    new_root: str
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    reused: list[str] = Field(default_factory=list)
    dirty_raptor_nodes: list[str] = Field(default_factory=list)


class TagRow(BaseModel):
    id: int
    name: str
    department_id: str | None = None
    centroid: list[float] | None = None
    doc_count: int = 0


class TagRef(BaseModel):
    id: int
    name: str
    status: TagStatus
    source: TagSource
    similarity: float | None = None


class RaptorNode(BaseModel):
    id: str
    document_id: UUID
    version_no: int
    level: int
    summary_text: str
    embedding: list[float] | None = None
    children: list[str] = Field(default_factory=list)


class Job(BaseModel):
    id: int
    document_id: UUID
    version_id: UUID | None = None
    stage: Stage
    status: JobStatus = "queued"
    attempts: int = 0
    last_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TitleSuggestion(BaseModel):
    title: str
    source: TitleSource
    confidence: float


class EnrichmentResult(BaseModel):
    title: str | None = None
    doctype: DocType = "other"
    agency: str | None = None
    reference_no: str | None = None
    effective_date: str | None = None
    supersedes_ref: str | None = None
    language: str | None = None
    tags: list[str] = Field(default_factory=list)


class DuplicateInfo(BaseModel):
    document_id: UUID
    title: str
    tier: DuplicateTier


class ChunkIndexDoc(BaseModel):
    chunk_id: str
    document_id: str
    version_id: str | None = None
    level: int = 0
    allowed_groups: list[str]
    department_id: str
    doctype: str | None = None
    tags: list[str] = Field(default_factory=list)
    title: str
    text: str
    heading_path: list[str] = Field(default_factory=list)
    page_from: int | None = None
    effective_date: str | None = None
    superseded: bool = False
    embedding: list[float]


class TitleIndexDoc(BaseModel):
    document_id: str
    title: str
    filename: str | None = None
    tags: list[str] = Field(default_factory=list)
    doctype: str | None = None
    department_id: str
    allowed_groups: list[str]
    superseded: bool = False


class SearchFilters(BaseModel):
    doctype: list[str] = Field(default_factory=list)
    department_id: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    date_from: str | None = None
    date_to: str | None = None
    include_superseded: bool = True
    document_ids: list[str] = Field(default_factory=list)


class SearchHit(BaseModel):
    chunk_id: str
    document_id: UUID
    score: float
    text: str
    highlight: str | None = None
    page: int | None = None
    heading_path: list[str] = Field(default_factory=list)
    level: int = 0
    title: str | None = None


class SearchResult(BaseModel):
    document_id: UUID
    title: str
    doctype: str | None = None
    department_id: str
    snippet: str
    page: int | None = None
    heading_path: list[str] = Field(default_factory=list)
    score: float
    tags: list[str] = Field(default_factory=list)
    effective_date: str | None = None
    superseded_by: UUID | None = None
    summary: str | None = None


class FacetBucket(BaseModel):
    value: str
    count: int


class SearchResponse(BaseModel):
    results: list[SearchResult]
    facets: dict[str, list[FacetBucket]] = Field(default_factory=dict)
    total: int
    did_you_mean: str | None = None
    took_ms: int = 0


class SuggestDocument(BaseModel):
    id: UUID
    title: str
    doctype: str | None = None
    department_id: str


class SuggestTag(BaseModel):
    id: int
    name: str


class SuggestResponse(BaseModel):
    documents: list[SuggestDocument]
    tags: list[SuggestTag]


class Citation(BaseModel):
    n: int
    document_id: UUID
    title: str
    chunk_id: str
    page: int | None = None
    quote: str


class AskEvent(BaseModel):
    event: Literal["token", "step", "citations", "done", "error"]
    data: dict[str, Any] = Field(default_factory=dict)
