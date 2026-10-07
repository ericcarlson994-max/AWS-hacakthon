from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from dms_core.models import (
    Citation,
    DeltaStats,
    DocStatus,
    DocumentMeta,
    DuplicateTier,
    FacetBucket,
    Role,
    SearchFilters,
    SearchResponse,
    SearchResult,
    Stage,
    SuggestDocument,
    SuggestResponse,
    SuggestTag,
    TagRef,
    TitleSource,
)

__all__ = [
    "AddTagRequest",
    "AskRequest",
    "ChatTurn",
    "Citation",
    "DepartmentOut",
    "DevLoginRequest",
    "DocumentDetail",
    "DocumentList",
    "DocumentSummary",
    "DuplicateOut",
    "ErrorBody",
    "ErrorResponse",
    "FacetBucket",
    "FolderOut",
    "CreateFolderRequest",
    "PatchFolderRequest",
    "HealthOut",
    "LoginResponse",
    "MembershipOut",
    "NewVersionResponse",
    "PatchDocumentRequest",
    "SearchFilters",
    "SearchRequest",
    "SearchResponse",
    "SearchResult",
    "StageStatus",
    "StatusResponse",
    "SuggestDocument",
    "SuggestResponse",
    "SuggestTag",
    "TagOut",
    "TagRef",
    "UpdateTagRequest",
    "UploadResponse",
    "UserOut",
    "VersionOut",
]


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class HealthOut(BaseModel):
    status: str
    deps: dict[str, bool]


class DevLoginRequest(BaseModel):
    username: str


class MembershipOut(BaseModel):
    id: str
    name: str
    role: Role


class UserOut(BaseModel):
    id: str
    username: str
    display_name: str
    departments: list[MembershipOut]


class LoginResponse(BaseModel):
    token: str
    user: UserOut


class DepartmentOut(BaseModel):
    id: str
    name: str


class DuplicateOut(BaseModel):
    document_id: UUID
    title: str
    tier: DuplicateTier


class UploadResponse(BaseModel):
    document_id: UUID
    version_id: UUID
    status: DocStatus
    duplicate: DuplicateOut | None = None


class DocumentSummary(BaseModel):
    id: UUID
    title: str
    doctype: str | None = None
    department_id: str
    status: DocStatus
    tags: list[TagRef] = Field(default_factory=list)
    meta: DocumentMeta = Field(default_factory=DocumentMeta)
    superseded_by: UUID | None = None
    created_at: datetime
    current_version_no: int | None = None
    folder_id: str | None = None
    updated_at: datetime
    size_bytes: int | None = None
    original_filename: str | None = None
    created_by: str | None = None
    page_count: int | None = None


class VersionOut(BaseModel):
    version_no: int
    created_at: datetime
    uploaded_by: str | None = None
    original_filename: str
    merkle_root: str | None = None
    delta_stats: DeltaStats | None = None


class DocumentDetail(DocumentSummary):
    title_source: TitleSource
    title_confidence: float
    root_summary: str | None = None
    duplicate: DuplicateOut | None = None
    versions: list[VersionOut] = Field(default_factory=list)
    mime_type: str | None = None
    status_detail: str | None = None


class DocumentList(BaseModel):
    items: list[DocumentSummary]
    total: int
    page: int


class StageStatus(BaseModel):
    stage: Stage
    status: str
    updated_at: datetime | None = None


class StatusResponse(BaseModel):
    status: DocStatus
    status_detail: str | None = None
    stages: list[StageStatus]


class PatchDocumentRequest(BaseModel):
    title: str | None = None
    doctype: str | None = None
    folder_id: str | None = None


class FolderOut(BaseModel):
    id: str
    name: str
    parent_id: str | None = None
    doc_count: int = 0


class CreateFolderRequest(BaseModel):
    name: str
    parent_id: str | None = None


class PatchFolderRequest(BaseModel):
    name: str | None = None
    parent_id: str | None = None


class AddTagRequest(BaseModel):
    name: str


class UpdateTagRequest(BaseModel):
    status: str = "confirmed"


class NewVersionResponse(BaseModel):
    version_id: UUID
    version_no: int
    status: DocStatus


class SearchRequest(BaseModel):
    query: str
    filters: SearchFilters | None = None
    page: int = 1
    page_size: int = 10


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AskRequest(BaseModel):
    question: str
    filters: SearchFilters | None = None
    mode: Literal["rag", "agent"] = "rag"
    history: list[ChatTurn] = Field(default_factory=list)


class TagOut(BaseModel):
    id: int
    name: str
    department_id: str | None = None
    doc_count: int = 0
