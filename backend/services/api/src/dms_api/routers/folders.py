from __future__ import annotations

import logging

from fastapi import APIRouter, Response, status

from dms_api.auth import ContainerDep, CurrentUser
from dms_api.errors import ApiError, forbidden, not_found
from dms_api.schemas import CreateFolderRequest, FolderOut, PatchFolderRequest
from dms_core.access.guard import WRITER_ROLES, can_write
from dms_core.folders import INBOX_FOLDER_ID, FolderConflict, FolderCycle, normalize_folder_name
from dms_core.models import Folder, User
from dms_core.ports import Container

logger = logging.getLogger(__name__)
router = APIRouter(tags=["folders"])


def require_writer(user: User) -> None:
    if not any(membership.role in WRITER_ROLES for membership in user.departments):
        raise forbidden("Contributor role required to manage folders")


def folder_out(container: Container, user: User, folder_id: str) -> FolderOut:
    for folder in container.repo.list_folders(user.department_ids):
        if folder.id == folder_id:
            return FolderOut(**folder.model_dump())
    raise not_found("Folder not found")


def existing_folder(container: Container, folder_id: str) -> Folder:
    folder = container.repo.get_folder(folder_id)
    if folder is None:
        raise not_found("Folder not found")
    return folder


def valid_name(name: str | None) -> str:
    clean = normalize_folder_name(name)
    if not clean:
        raise ApiError(400, "bad_request", "Folder name must not be empty")
    return clean


def conflict(name: str) -> ApiError:
    return ApiError(409, "conflict", f"A folder named '{name}' already exists here")


@router.get("/folders", response_model=list[FolderOut])
def list_folders(user: CurrentUser, container: ContainerDep) -> list[FolderOut]:
    return [FolderOut(**folder.model_dump()) for folder in container.repo.list_folders(user.department_ids)]


@router.post("/folders", response_model=FolderOut, status_code=status.HTTP_201_CREATED)
def create_folder(body: CreateFolderRequest, user: CurrentUser, container: ContainerDep) -> FolderOut:
    require_writer(user)
    name = valid_name(body.name)
    parent_id = body.parent_id or None
    if parent_id is not None:
        existing_folder(container, parent_id)
    try:
        folder = container.repo.create_folder(name, parent_id)
    except FolderConflict:
        raise conflict(name)
    except KeyError:
        raise not_found("Parent folder not found")
    return folder_out(container, user, folder.id)


@router.patch("/folders/{folder_id}", response_model=FolderOut)
def patch_folder(folder_id: str, body: PatchFolderRequest, user: CurrentUser, container: ContainerDep) -> FolderOut:
    require_writer(user)
    folder = existing_folder(container, folder_id)
    set_parent = "parent_id" in body.model_fields_set
    name = valid_name(body.name) if body.name is not None else None
    parent_id = (body.parent_id or None) if set_parent else folder.parent_id
    if folder.id == INBOX_FOLDER_ID and ((name is not None and name != folder.name) or parent_id != folder.parent_id):
        raise ApiError(400, "bad_request", "The Inbox folder cannot be renamed or moved")
    if set_parent and parent_id is not None:
        existing_folder(container, parent_id)
        if parent_id == folder.id or parent_id in container.repo.folder_descendants(folder.id):
            raise ApiError(400, "bad_request", "A folder cannot be moved into itself or its subfolders")
    try:
        container.repo.update_folder(folder.id, name=name, parent_id=parent_id, set_parent=set_parent)
    except FolderConflict:
        raise conflict(name or folder.name)
    except FolderCycle:
        raise ApiError(400, "bad_request", "A folder cannot be moved into itself or its subfolders")
    except KeyError:
        raise not_found("Folder not found")
    return folder_out(container, user, folder.id)


@router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_folder(folder_id: str, user: CurrentUser, container: ContainerDep) -> Response:
    require_writer(user)
    if folder_id == INBOX_FOLDER_ID:
        raise ApiError(400, "bad_request", "The Inbox folder cannot be deleted")
    folder = existing_folder(container, folder_id)
    folder_ids = [folder.id, *container.repo.folder_descendants(folder.id)]
    documents = container.repo.list_folder_documents(folder_ids)
    blocked = [document for document in documents if not can_write(user, document)]
    if blocked:
        raise ApiError(
            409,
            "forbidden_contents",
            f"This folder contains {len(blocked)} document(s) you do not have permission to delete",
        )
    for document in documents:
        container.repo.soft_delete_document(document.id)
        try:
            container.index.delete_document(str(document.id))
        except Exception:
            logger.exception("could not remove %s from the search index", document.id)
    container.repo.delete_folder(folder.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
