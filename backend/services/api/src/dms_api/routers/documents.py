from __future__ import annotations

import logging
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status

from dms_api.auth import ContainerDep, CurrentUser
from dms_api.errors import ApiError, forbidden, not_found
from dms_api.schemas import (
    AddTagRequest,
    DocumentDetail,
    DocumentList,
    DocumentSummary,
    DuplicateOut,
    NewVersionResponse,
    PatchDocumentRequest,
    StageStatus,
    StatusResponse,
    TagRef,
    UpdateTagRequest,
    UploadResponse,
    VersionOut,
)
from dms_core.access.guard import WRITER_ROLES, can_read, can_write
from dms_core.dedup.exact import sha256_hex
from dms_core.enrich.tags import recompute_centroid
from dms_core.extract.filetype import UnsupportedFileType, detect_mime
from dms_core.folders import INBOX_FOLDER_ID
from dms_core.models import DOCTYPES, DocumentRow, Job, User, VersionRow
from dms_core.ports import Container

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_PAGE_SIZE = 200
STAGE_ORDER = ("extract", "index", "enrich", "summarize", "delta")
TAG_STATUSES = ("suggested", "confirmed")
DEFAULT_FILENAME = "upload"

logger = logging.getLogger(__name__)
router = APIRouter(tags=["documents"])


def readable_document(container: Container, user: User, document_id: UUID) -> DocumentRow:
    document = container.repo.get_document(document_id)
    if document is None or not can_read(user, document):
        raise not_found()
    return document


def writable_document(container: Container, user: User, document_id: UUID) -> DocumentRow:
    document = readable_document(container, user, document_id)
    if not can_write(user, document):
        raise forbidden("Contributor role required in this department")
    return document


async def read_upload(file: UploadFile) -> bytes:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise ApiError(413, "payload_too_large", "File exceeds the 50 MB limit")
    if not data:
        raise ApiError(400, "empty_file", "Uploaded file is empty")
    return data


def detect_upload_mime(data: bytes, filename: str) -> str:
    try:
        return detect_mime(data, filename)
    except UnsupportedFileType as error:
        raise ApiError(415, "unsupported_media_type", str(error))


def version_out(version: VersionRow) -> VersionOut:
    return VersionOut(
        version_no=version.version_no,
        created_at=version.created_at,
        uploaded_by=version.uploaded_by,
        original_filename=version.original_filename,
        merkle_root=version.merkle_root,
        delta_stats=version.delta_stats,
    )


def summary_fields(container: Container, document: DocumentRow, current: VersionRow | None) -> dict[str, object]:
    return {
        "id": document.id,
        "title": document.title,
        "doctype": document.doctype,
        "department_id": document.department_id,
        "status": document.status,
        "tags": container.repo.get_document_tags(document.id),
        "meta": document.meta,
        "superseded_by": document.superseded_by,
        "created_at": document.created_at,
        "current_version_no": current.version_no if current else None,
        "folder_id": document.folder_id,
        "updated_at": document.updated_at,
        "size_bytes": current.size_bytes if current else None,
        "original_filename": current.original_filename if current else None,
        "created_by": document.created_by,
        "page_count": current.page_count if current else None,
    }


def document_summary(container: Container, document: DocumentRow) -> DocumentSummary:
    current = container.repo.get_current_version(document.id)
    return DocumentSummary(**summary_fields(container, document, current))


def duplicate_out(container: Container, user: User, document: DocumentRow) -> DuplicateOut | None:
    if document.duplicate_of is None or document.duplicate_tier is None:
        return None
    original = container.repo.get_document(document.duplicate_of)
    if original is None or not can_read(user, original):
        return None
    return DuplicateOut(document_id=original.id, title=original.title, tier=document.duplicate_tier)


def document_detail(container: Container, user: User, document: DocumentRow) -> DocumentDetail:
    current = container.repo.get_current_version(document.id)
    versions = container.repo.list_versions(document.id)
    return DocumentDetail(
        **summary_fields(container, document, current),
        title_source=document.title_source,
        title_confidence=document.title_confidence,
        root_summary=document.root_summary,
        duplicate=duplicate_out(container, user, document),
        versions=[version_out(v) for v in versions],
        mime_type=current.mime_type if current else None,
        status_detail=document.status_detail,
    )


def create_exact_duplicate(
    container: Container,
    user: User,
    department_id: str,
    folder_id: str,
    original: DocumentRow,
    original_version: VersionRow,
    filename: str,
    mime_type: str,
    size_bytes: int,
) -> UploadResponse:
    repo = container.repo
    document = repo.create_document(
        department_id=department_id, created_by=user.id, title=original.title, folder_id=folder_id
    )
    repo.update_document(
        document.id,
        title_source=original.title_source,
        title_confidence=original.title_confidence,
        doctype=original.doctype,
        meta=original.meta,
        root_summary=original.root_summary,
        duplicate_of=original.id,
        duplicate_tier="exact",
    )
    version = repo.create_version(
        document_id=document.id,
        blob_sha256=original_version.blob_sha256,
        original_filename=filename,
        mime_type=mime_type,
        size_bytes=size_bytes,
        uploaded_by=user.id,
    )
    repo.update_version(
        version.id,
        blocks=original_version.blocks,
        chunk_manifest=original_version.chunk_manifest,
        merkle_root=original_version.merkle_root,
        page_count=original_version.page_count,
        embedded_title=original_version.embedded_title,
    )
    repo.set_status(document.id, "READY")
    return UploadResponse(
        document_id=document.id,
        version_id=version.id,
        status="READY",
        duplicate=DuplicateOut(document_id=original.id, title=original.title, tier="exact"),
    )


def require_folder(container: Container, folder_id: str) -> str:
    if container.repo.get_folder(folder_id) is None:
        raise not_found("Folder not found")
    return folder_id


def find_readable_duplicate(container: Container, user: User, sha256: str) -> tuple[DocumentRow, VersionRow] | None:
    existing = container.repo.find_version_by_sha(sha256)
    if existing is None:
        return None
    original = container.repo.get_document(existing.document_id)
    if original is None or not can_read(user, original):
        return None
    return original, existing


@router.post("/documents", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    user: CurrentUser,
    container: ContainerDep,
    file: Annotated[UploadFile, File()],
    department_id: Annotated[str, Form()],
    folder_id: Annotated[str | None, Form()] = None,
) -> UploadResponse:
    if user.role_in(department_id) not in WRITER_ROLES:
        raise forbidden("Contributor role required in this department")
    target_folder = require_folder(container, folder_id or INBOX_FOLDER_ID)
    data = await read_upload(file)
    filename = file.filename or DEFAULT_FILENAME
    mime_type = detect_upload_mime(data, filename)
    sha256 = sha256_hex(data)
    duplicate = find_readable_duplicate(container, user, sha256)
    if duplicate is not None:
        original, original_version = duplicate
        return create_exact_duplicate(
            container, user, department_id, target_folder, original, original_version, filename, mime_type, len(data)
        )
    container.blobs.put(sha256, data, mime_type)
    document = container.repo.create_document(
        department_id=department_id, created_by=user.id, folder_id=target_folder
    )
    version = container.repo.create_version(
        document_id=document.id,
        blob_sha256=sha256,
        original_filename=filename,
        mime_type=mime_type,
        size_bytes=len(data),
        uploaded_by=user.id,
    )
    container.jobs.enqueue(document.id, version.id, "extract")
    return UploadResponse(document_id=document.id, version_id=version.id, status="UPLOADED", duplicate=None)


@router.get("/documents", response_model=DocumentList)
def list_documents(
    user: CurrentUser,
    container: ContainerDep,
    department_id: Annotated[str | None, Query()] = None,
    doctype: Annotated[str | None, Query()] = None,
    tag: Annotated[str | None, Query()] = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    sort: Annotated[str, Query()] = "-created_at",
    folder_id: Annotated[str | None, Query()] = None,
    recursive: Annotated[bool, Query()] = False,
) -> DocumentList:
    if department_id is not None and department_id not in user.department_ids:
        raise forbidden("You are not a member of that department")
    folder_ids: list[str] | None = None
    if folder_id is not None:
        require_folder(container, folder_id)
        folder_ids = [folder_id, *container.repo.folder_descendants(folder_id)] if recursive else [folder_id]
    department_ids = [department_id] if department_id else user.department_ids
    if not department_ids:
        return DocumentList(items=[], total=0, page=page)
    rows, total = container.repo.list_documents(
        department_ids=department_ids,
        doctype=doctype,
        tag=tag,
        status=status_filter,
        page=page,
        page_size=page_size,
        sort=sort,
        folder_ids=folder_ids,
    )
    items = [document_summary(container, row) for row in rows if can_read(user, row)]
    return DocumentList(items=items, total=total, page=page)


@router.get("/documents/{document_id}", response_model=DocumentDetail)
def get_document(document_id: UUID, user: CurrentUser, container: ContainerDep) -> DocumentDetail:
    document = readable_document(container, user, document_id)
    return document_detail(container, user, document)


def latest_jobs_by_stage(jobs: list[Job]) -> list[Job]:
    latest: dict[str, Job] = {}
    for job in sorted(jobs, key=lambda j: j.id):
        latest[job.stage] = job
    return [latest[stage] for stage in STAGE_ORDER if stage in latest]


@router.get("/documents/{document_id}/status", response_model=StatusResponse)
def get_status(document_id: UUID, user: CurrentUser, container: ContainerDep) -> StatusResponse:
    document = readable_document(container, user, document_id)
    stages = [
        StageStatus(stage=job.stage, status=job.status, updated_at=job.updated_at or job.created_at)
        for job in latest_jobs_by_stage(
            [j for j in container.repo.list_jobs(document.id) if j.version_id in (None, document.current_version_id)]
        )
    ]
    return StatusResponse(status=document.status, status_detail=document.status_detail, stages=stages)


def content_disposition(filename: str) -> str:
    ascii_name = filename.encode("ascii", "ignore").decode().replace('"', "").replace("\\", "") or DEFAULT_FILENAME
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


@router.get("/documents/{document_id}/file")
def download_file(
    document_id: UUID,
    user: CurrentUser,
    container: ContainerDep,
    version_no: Annotated[int | None, Query()] = None,
) -> Response:
    document = readable_document(container, user, document_id)
    if version_no is None:
        version = container.repo.get_current_version(document.id)
    else:
        version = container.repo.get_version_by_no(document.id, version_no)
    if version is None:
        raise not_found("Version not found")
    try:
        data = container.blobs.get(version.blob_sha256)
    except KeyError:
        raise not_found("File not found")
    return Response(
        content=data,
        media_type=version.mime_type,
        headers={"Content-Disposition": content_disposition(version.original_filename)},
    )


def trigger_reindex(container: Container, document_id: UUID) -> None:
    try:
        from dms_workers.indexing import reindex_document
    except ImportError:
        return
    try:
        reindex_document(container, document_id)
    except Exception:
        logger.exception("reindex failed for %s", document_id)


@router.patch("/documents/{document_id}", response_model=DocumentDetail)
def patch_document(
    document_id: UUID, body: PatchDocumentRequest, user: CurrentUser, container: ContainerDep
) -> DocumentDetail:
    document = writable_document(container, user, document_id)
    updates: dict[str, object] = {}
    if body.title is not None:
        title = " ".join(body.title.split())
        if not title:
            raise ApiError(422, "validation_error", "Title must not be empty")
        updates.update(title=title, title_source="user", title_confidence=1.0)
    if body.doctype is not None:
        doctype = body.doctype.strip().lower()
        if doctype not in DOCTYPES:
            raise ApiError(422, "validation_error", f"doctype must be one of {', '.join(DOCTYPES)}")
        updates["doctype"] = doctype
    if "folder_id" in body.model_fields_set and body.folder_id != document.folder_id:
        updates["folder_id"] = require_folder(container, body.folder_id) if body.folder_id else INBOX_FOLDER_ID
    if updates:
        document = container.repo.update_document(document.id, **updates)
        if set(updates) - {"folder_id"}:
            trigger_reindex(container, document.id)
    return document_detail(container, user, document)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: UUID, user: CurrentUser, container: ContainerDep) -> Response:
    document = writable_document(container, user, document_id)
    container.repo.soft_delete_document(document.id)
    try:
        container.index.delete_document(str(document.id))
    except Exception:
        logger.exception("could not remove %s from the search index", document.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def refresh_tag_centroid(container: Container, tag_id: int) -> None:
    vectors = [container.repo.document_embedding(doc_id) for doc_id in container.repo.confirmed_tag_document_ids(tag_id)]
    centroid = recompute_centroid(vectors)
    if centroid is not None:
        container.repo.set_tag_centroid(tag_id, centroid)


def attached_tag(container: Container, document_id: UUID, tag_id: int) -> TagRef:
    for ref in container.repo.get_document_tags(document_id):
        if ref.id == tag_id:
            return ref
    raise not_found("Tag is not attached to this document")


@router.post("/documents/{document_id}/tags", response_model=list[TagRef])
def add_tag(document_id: UUID, body: AddTagRequest, user: CurrentUser, container: ContainerDep) -> list[TagRef]:
    document = writable_document(container, user, document_id)
    name = " ".join(body.name.split())
    if not name:
        raise ApiError(422, "validation_error", "Tag name must not be empty")
    tag = container.repo.get_or_create_tag(name, document.department_id)
    container.repo.set_document_tag(document.id, tag.id, "user", "confirmed")
    refresh_tag_centroid(container, tag.id)
    trigger_reindex(container, document.id)
    return container.repo.get_document_tags(document.id)


@router.put("/documents/{document_id}/tags/{tag_id}", response_model=list[TagRef])
def update_tag(
    document_id: UUID, tag_id: int, body: UpdateTagRequest, user: CurrentUser, container: ContainerDep
) -> list[TagRef]:
    document = writable_document(container, user, document_id)
    if body.status not in TAG_STATUSES:
        raise ApiError(422, "validation_error", f"status must be one of {', '.join(TAG_STATUSES)}")
    existing = attached_tag(container, document.id, tag_id)
    container.repo.set_document_tag(document.id, tag_id, existing.source, body.status, existing.similarity)
    refresh_tag_centroid(container, tag_id)
    trigger_reindex(container, document.id)
    return container.repo.get_document_tags(document.id)


@router.delete("/documents/{document_id}/tags/{tag_id}", response_model=list[TagRef])
def remove_tag(document_id: UUID, tag_id: int, user: CurrentUser, container: ContainerDep) -> list[TagRef]:
    document = writable_document(container, user, document_id)
    attached_tag(container, document.id, tag_id)
    container.repo.remove_document_tag(document.id, tag_id)
    refresh_tag_centroid(container, tag_id)
    trigger_reindex(container, document.id)
    return container.repo.get_document_tags(document.id)


@router.post(
    "/documents/{document_id}/versions", response_model=NewVersionResponse, status_code=status.HTTP_202_ACCEPTED
)
async def upload_version(
    document_id: UUID, user: CurrentUser, container: ContainerDep, file: Annotated[UploadFile, File()]
) -> NewVersionResponse:
    document = writable_document(container, user, document_id)
    data = await read_upload(file)
    filename = file.filename or DEFAULT_FILENAME
    mime_type = detect_upload_mime(data, filename)
    sha256 = sha256_hex(data)
    if not container.blobs.exists(sha256):
        container.blobs.put(sha256, data, mime_type)
    version = container.repo.create_version(
        document_id=document.id,
        blob_sha256=sha256,
        original_filename=filename,
        mime_type=mime_type,
        size_bytes=len(data),
        uploaded_by=user.id,
    )
    container.repo.set_status(document.id, "UPLOADED")
    container.jobs.enqueue(document.id, version.id, "extract")
    return NewVersionResponse(version_id=version.id, version_no=version.version_no, status="UPLOADED")


@router.get("/documents/{document_id}/versions", response_model=list[VersionOut])
def list_versions(document_id: UUID, user: CurrentUser, container: ContainerDep) -> list[VersionOut]:
    document = readable_document(container, user, document_id)
    return [version_out(v) for v in container.repo.list_versions(document.id)]
