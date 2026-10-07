from __future__ import annotations

import threading
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from dms_core.folders import DEFAULT_FOLDERS, INBOX_FOLDER_ID, FolderConflict, FolderCycle, new_folder_id
from dms_core.models import (
    DEFAULT_TITLE,
    Block,
    Chunk,
    Department,
    DepartmentMembership,
    DeltaStats,
    DocStatus,
    DocumentMeta,
    DocumentRow,
    Folder,
    Job,
    RaptorNode,
    TagRef,
    TagRow,
    TagSource,
    TagStatus,
    User,
    VersionRow,
)

UPDATABLE_DOCUMENT_FIELDS = {
    "department_id",
    "title",
    "title_source",
    "title_confidence",
    "doctype",
    "meta",
    "superseded_by",
    "duplicate_of",
    "duplicate_tier",
    "root_summary",
    "minhash",
    "status",
    "status_detail",
    "current_version_id",
    "created_by",
    "folder_id",
}
UPDATABLE_VERSION_FIELDS = {
    "blob_sha256",
    "original_filename",
    "mime_type",
    "size_bytes",
    "page_count",
    "blocks",
    "embedded_title",
    "merkle_root",
    "chunk_manifest",
    "delta_stats",
    "uploaded_by",
}
SORT_KEYS = {"created_at", "updated_at", "title", "status"}


def now() -> datetime:
    return datetime.now(UTC)


def mean_vector(vectors: list[list[float]]) -> list[float] | None:
    if not vectors:
        return None
    size = len(vectors[0])
    return [sum(v[i] for v in vectors) / len(vectors) for i in range(size)]


class FakeRepo:
    def __init__(self) -> None:
        self.departments: dict[str, Department] = {}
        self.users: dict[str, dict[str, str]] = {}
        self.memberships: dict[tuple[str, str], str] = {}
        self.documents: dict[UUID, DocumentRow] = {}
        self.minhash: dict[UUID, bytes] = {}
        self.minhash_bands: dict[UUID, set[tuple[int, str]]] = {}
        self.versions: dict[UUID, VersionRow] = {}
        self.chunks: dict[str, Chunk] = {}
        self.tags: dict[int, TagRow] = {}
        self.document_tags: dict[tuple[UUID, int], TagRef] = {}
        self.raptor_nodes: dict[tuple[UUID, int], list[RaptorNode]] = {}
        self.jobs: dict[int, Job] = {}
        self.folders: dict[str, Folder] = {
            folder_id: Folder(id=folder_id, name=name, parent_id=parent_id)
            for folder_id, name, parent_id in DEFAULT_FOLDERS
        }
        self._next_tag_id = 1
        self._lock = threading.RLock()
        self._last_stamp = datetime.min.replace(tzinfo=UTC)

    def _tick(self) -> datetime:
        stamp = max(now(), self._last_stamp + timedelta(microseconds=1))
        self._last_stamp = stamp
        return stamp

    def ping(self) -> bool:
        return True

    def upsert_department(self, department_id: str, name: str) -> None:
        self.departments[department_id] = Department(id=department_id, name=name)

    def list_departments(self, ids: list[str] | None = None) -> list[Department]:
        values = sorted(self.departments.values(), key=lambda d: d.id)
        if ids is None:
            return [d.model_copy() for d in values]
        wanted = set(ids)
        return [d.model_copy() for d in values if d.id in wanted]

    def upsert_user(self, user_id: str, username: str, display_name: str) -> None:
        self.users[user_id] = {"id": user_id, "username": username, "display_name": display_name}

    def set_membership(self, user_id: str, department_id: str, role: str) -> None:
        if user_id not in self.users:
            raise KeyError(user_id)
        if department_id not in self.departments:
            raise KeyError(department_id)
        self.memberships[(user_id, department_id)] = role

    def _build_user(self, data: dict[str, str] | None) -> User | None:
        if data is None:
            return None
        memberships = [
            DepartmentMembership(id=dept_id, name=self.departments[dept_id].name, role=role)
            for (user_id, dept_id), role in sorted(self.memberships.items())
            if user_id == data["id"] and dept_id in self.departments
        ]
        return User(departments=memberships, **data)

    def get_user(self, user_id: str) -> User | None:
        return self._build_user(self.users.get(user_id))

    def get_user_by_username(self, username: str) -> User | None:
        return self._build_user(next((u for u in self.users.values() if u["username"] == username), None))

    def _live(self, document_id: UUID) -> DocumentRow | None:
        document = self.documents.get(UUID(str(document_id)))
        if document is None or document.deleted_at is not None:
            return None
        return document

    def _folder_count(self, folder_id: str, department_ids: list[str] | None) -> int:
        allowed = set(department_ids) if department_ids is not None else None
        return sum(
            1
            for d in self.documents.values()
            if d.folder_id == folder_id and d.deleted_at is None and (allowed is None or d.department_id in allowed)
        )

    def list_folders(self, department_ids: list[str] | None = None) -> list[Folder]:
        folders = sorted(self.folders.values(), key=lambda f: (f.id != INBOX_FOLDER_ID, f.name.lower(), f.id))
        return [f.model_copy(update={"doc_count": self._folder_count(f.id, department_ids)}) for f in folders]

    def get_folder(self, folder_id: str) -> Folder | None:
        folder = self.folders.get(folder_id)
        return folder.model_copy(update={"doc_count": self._folder_count(folder.id, None)}) if folder else None

    def _check_sibling(self, name: str, parent_id: str | None, exclude_id: str | None = None) -> None:
        for folder in self.folders.values():
            if folder.id != exclude_id and folder.parent_id == parent_id and folder.name.lower() == name.lower():
                raise FolderConflict(name)

    def create_folder(self, name: str, parent_id: str | None = None) -> Folder:
        with self._lock:
            if parent_id is not None and parent_id not in self.folders:
                raise KeyError(parent_id)
            self._check_sibling(name, parent_id)
            folder = Folder(id=new_folder_id(name), name=name, parent_id=parent_id)
            self.folders[folder.id] = folder
            return folder.model_copy()

    def update_folder(
        self, folder_id: str, name: str | None = None, parent_id: str | None = None, *, set_parent: bool = False
    ) -> Folder:
        with self._lock:
            folder = self.folders.get(folder_id)
            if folder is None:
                raise KeyError(folder_id)
            new_name = name if name is not None else folder.name
            new_parent = parent_id if set_parent else folder.parent_id
            if new_parent is not None:
                if new_parent not in self.folders:
                    raise KeyError(new_parent)
                if new_parent == folder_id or new_parent in self.folder_descendants(folder_id):
                    raise FolderCycle(folder_id)
            self._check_sibling(new_name, new_parent, exclude_id=folder_id)
            updated = folder.model_copy(update={"name": new_name, "parent_id": new_parent})
            self.folders[folder_id] = updated
            return self.get_folder(folder_id) or updated

    def folder_descendants(self, folder_id: str) -> list[str]:
        result: list[str] = []
        frontier = [folder_id]
        while frontier:
            current = frontier.pop(0)
            children = sorted(f.id for f in self.folders.values() if f.parent_id == current)
            for child in children:
                if child not in result and child != folder_id:
                    result.append(child)
                    frontier.append(child)
        return result

    def delete_folder(self, folder_id: str) -> None:
        with self._lock:
            if folder_id not in self.folders:
                return
            removed = {folder_id, *self.folder_descendants(folder_id)}
            for key in removed:
                self.folders.pop(key, None)
            for key, document in list(self.documents.items()):
                if document.folder_id in removed:
                    self.documents[key] = document.model_copy(update={"folder_id": None})

    def list_folder_documents(self, folder_ids: list[str]) -> list[DocumentRow]:
        wanted = set(folder_ids)
        rows = [d for d in self.documents.values() if d.deleted_at is None and d.folder_id in wanted]
        rows.sort(key=lambda d: (d.created_at, str(d.id)))
        return [d.model_copy(deep=True) for d in rows]

    def soft_delete_document(self, document_id: UUID) -> None:
        key = UUID(str(document_id))
        document = self.documents.get(key)
        if document is not None and document.deleted_at is None:
            stamp = self._tick()
            self.documents[key] = document.model_copy(update={"deleted_at": stamp, "updated_at": stamp})

    def create_document(
        self,
        *,
        department_id: str,
        created_by: str | None,
        title: str | None = None,
        folder_id: str | None = None,
    ) -> DocumentRow:
        stamp = self._tick()
        document = DocumentRow(
            id=uuid4(),
            department_id=department_id,
            title=title or DEFAULT_TITLE,
            created_by=created_by,
            created_at=stamp,
            updated_at=stamp,
            folder_id=folder_id,
        )
        self.documents[document.id] = document
        return document.model_copy(deep=True)

    def get_document(self, document_id: UUID) -> DocumentRow | None:
        document = self._live(document_id)
        return document.model_copy(deep=True) if document else None

    def get_documents(self, ids: Sequence[UUID]) -> list[DocumentRow]:
        result: list[DocumentRow] = []
        for document_id in dict.fromkeys(UUID(str(i)) for i in ids):
            document = self._live(document_id)
            if document:
                result.append(document.model_copy(deep=True))
        return result

    def list_documents(
        self,
        *,
        department_ids: list[str],
        doctype: str | None = None,
        tag: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
        sort: str = "-created_at",
        folder_ids: list[str] | None = None,
    ) -> tuple[list[DocumentRow], int]:
        allowed = set(department_ids)
        rows = [d for d in self.documents.values() if d.department_id in allowed and d.deleted_at is None]
        if folder_ids is not None:
            wanted_folders = set(folder_ids)
            rows = [d for d in rows if d.folder_id in wanted_folders]
        if doctype:
            rows = [d for d in rows if d.doctype == doctype]
        if status:
            rows = [d for d in rows if d.status == status]
        if tag:
            wanted = tag.lower()
            rows = [d for d in rows if any(ref.name.lower() == wanted for ref in self._document_tag_refs(d.id))]
        descending = sort.startswith("-")
        key = sort.lstrip("-+")
        if key not in SORT_KEYS:
            key = "created_at"
            descending = True

        def sort_key(document: DocumentRow) -> tuple[Any, str]:
            value = getattr(document, key)
            if key == "title":
                value = value.lower()
            return value, str(document.id)

        rows.sort(key=sort_key, reverse=descending)
        page = max(1, page)
        page_size = max(1, page_size)
        start = (page - 1) * page_size
        return [d.model_copy(deep=True) for d in rows[start : start + page_size]], len(rows)

    def list_all_document_ids(self) -> list[UUID]:
        live = [d for d in self.documents.values() if d.deleted_at is None]
        return [d.id for d in sorted(live, key=lambda d: (d.created_at, str(d.id)))]

    def update_document(self, document_id: UUID, **fields: Any) -> DocumentRow:
        unknown = set(fields) - UPDATABLE_DOCUMENT_FIELDS
        if unknown:
            raise ValueError(f"unknown document fields: {sorted(unknown)}")
        key = UUID(str(document_id))
        document = self.documents.get(key)
        if document is None:
            raise KeyError(str(document_id))
        updates = dict(fields)
        if "minhash" in updates:
            value = updates.pop("minhash")
            if value is None:
                self.minhash.pop(key, None)
            else:
                self.minhash[key] = bytes(value)
        if "meta" in updates:
            value = updates["meta"]
            updates["meta"] = (
                value.model_copy() if isinstance(value, DocumentMeta) else DocumentMeta.model_validate(value or {})
            )
        data = document.model_dump()
        data.update(updates)
        data["updated_at"] = self._tick()
        updated = DocumentRow.model_validate(data)
        self.documents[key] = updated
        return updated.model_copy(deep=True)

    def set_status(self, document_id: UUID, status: DocStatus, detail: str | None = None) -> None:
        self.update_document(document_id, status=status, status_detail=detail)

    def find_document_by_reference(
        self, department_id: str, reference_no: str, exclude_id: UUID | None = None
    ) -> DocumentRow | None:
        wanted = reference_no.lower()
        excluded = UUID(str(exclude_id)) if exclude_id else None
        matches = [
            d
            for d in self.documents.values()
            if d.department_id == department_id
            and d.deleted_at is None
            and d.meta.reference_no
            and d.meta.reference_no.lower() == wanted
            and d.id != excluded
        ]
        if not matches:
            return None
        return max(matches, key=lambda d: d.created_at).model_copy(deep=True)

    def create_version(
        self,
        *,
        document_id: UUID,
        blob_sha256: str,
        original_filename: str,
        mime_type: str,
        size_bytes: int,
        uploaded_by: str | None,
    ) -> VersionRow:
        with self._lock:
            key = UUID(str(document_id))
            if key not in self.documents:
                raise KeyError(str(document_id))
            existing = [v.version_no for v in self.versions.values() if v.document_id == key]
            version = VersionRow(
                id=uuid4(),
                document_id=key,
                version_no=max(existing, default=0) + 1,
                blob_sha256=blob_sha256,
                original_filename=original_filename,
                mime_type=mime_type,
                size_bytes=size_bytes,
                uploaded_by=uploaded_by,
                created_at=self._tick(),
            )
            self.versions[version.id] = version
            self.update_document(key, current_version_id=version.id)
            return version.model_copy(deep=True)

    def get_version(self, version_id: UUID) -> VersionRow | None:
        version = self.versions.get(UUID(str(version_id)))
        return version.model_copy(deep=True) if version else None

    def _document_versions(self, document_id: UUID) -> list[VersionRow]:
        key = UUID(str(document_id))
        return sorted((v for v in self.versions.values() if v.document_id == key), key=lambda v: v.version_no)

    def get_version_by_no(self, document_id: UUID, version_no: int) -> VersionRow | None:
        for version in self._document_versions(document_id):
            if version.version_no == version_no:
                return version.model_copy(deep=True)
        return None

    def get_current_version(self, document_id: UUID) -> VersionRow | None:
        document = self.documents.get(UUID(str(document_id)))
        if document and document.current_version_id and document.current_version_id in self.versions:
            return self.versions[document.current_version_id].model_copy(deep=True)
        versions = self._document_versions(document_id)
        return versions[-1].model_copy(deep=True) if versions else None

    def get_previous_version(self, document_id: UUID, version_no: int) -> VersionRow | None:
        earlier = [v for v in self._document_versions(document_id) if v.version_no < version_no]
        return earlier[-1].model_copy(deep=True) if earlier else None

    def list_versions(self, document_id: UUID) -> list[VersionRow]:
        return [v.model_copy(deep=True) for v in self._document_versions(document_id)]

    def find_version_by_sha(self, sha256: str) -> VersionRow | None:
        matches = sorted(
            (v for v in self.versions.values() if v.blob_sha256 == sha256 and self._live(v.document_id) is not None),
            key=lambda v: (v.created_at, v.version_no),
        )
        return matches[0].model_copy(deep=True) if matches else None

    def update_version(self, version_id: UUID, **fields: Any) -> None:
        unknown = set(fields) - UPDATABLE_VERSION_FIELDS
        if unknown:
            raise ValueError(f"unknown version fields: {sorted(unknown)}")
        key = UUID(str(version_id))
        version = self.versions.get(key)
        if version is None:
            return
        updates = dict(fields)
        if updates.get("blocks") is not None:
            updates["blocks"] = [b if isinstance(b, Block) else Block.model_validate(b) for b in updates["blocks"]]
        if updates.get("chunk_manifest") is not None:
            updates["chunk_manifest"] = list(updates["chunk_manifest"])
        if updates.get("delta_stats") is not None and not isinstance(updates["delta_stats"], DeltaStats):
            updates["delta_stats"] = DeltaStats.model_validate(updates["delta_stats"])
        self.versions[key] = version.model_copy(update=updates, deep=True)

    def set_delta_stats(self, version_id: UUID, stats: DeltaStats) -> None:
        self.update_version(version_id, delta_stats=stats)

    def upsert_chunks(self, chunks: Sequence[Chunk]) -> None:
        for chunk in chunks:
            stored = chunk.model_copy(deep=True)
            previous = self.chunks.get(chunk.id)
            if stored.embedding is None and previous is not None:
                stored.embedding = previous.embedding
            self.chunks[chunk.id] = stored

    def get_chunks(self, ids: Sequence[str]) -> list[Chunk]:
        return [self.chunks[i].model_copy(deep=True) for i in dict.fromkeys(ids) if i in self.chunks]

    def get_document_chunks(self, document_id: UUID) -> list[Chunk]:
        key = UUID(str(document_id))
        rows = [c for c in self.chunks.values() if c.document_id == key]
        rows.sort(key=lambda c: (c.order, c.id))
        return [c.model_copy(deep=True) for c in rows]

    def delete_chunks(self, ids: Sequence[str]) -> None:
        for chunk_id in ids:
            self.chunks.pop(chunk_id, None)

    def document_embedding(self, document_id: UUID) -> list[float] | None:
        key = UUID(str(document_id))
        version = self.get_current_version(key)
        manifest = set(version.chunk_manifest or []) if version else set()
        document_chunks = [c for c in self.chunks.values() if c.document_id == key and c.embedding is not None]
        selected = [c.embedding for c in document_chunks if c.id in manifest] if manifest else []
        if not selected:
            selected = [c.embedding for c in document_chunks]
        return mean_vector([list(v) for v in selected if v is not None])

    def save_minhash(self, document_id: UUID, signature: bytes, bands: Sequence[tuple[int, str]]) -> None:
        key = UUID(str(document_id))
        self.minhash[key] = bytes(signature)
        self.minhash_bands[key] = {(int(b), str(k)) for b, k in bands}

    def find_minhash_candidates(
        self, bands: Sequence[tuple[int, str]], exclude_document_id: UUID
    ) -> list[tuple[UUID, bytes]]:
        wanted = {(int(b), str(k)) for b, k in bands}
        excluded = UUID(str(exclude_document_id))
        result: list[tuple[UUID, bytes]] = []
        for document_id, stored in self.minhash_bands.items():
            if document_id == excluded or document_id not in self.minhash or self._live(document_id) is None:
                continue
            if stored & wanted:
                result.append((document_id, self.minhash[document_id]))
        result.sort(key=lambda item: self.documents[item[0]].created_at if item[0] in self.documents else now())
        return result

    def _doc_count(self, tag_id: int) -> int:
        return sum(1 for (_, t) in self.document_tags if t == tag_id)

    def _tag_with_count(self, tag: TagRow) -> TagRow:
        return tag.model_copy(update={"doc_count": self._doc_count(tag.id)}, deep=True)

    def list_tags(self, department_ids: list[str] | None = None) -> list[TagRow]:
        tags = sorted(self.tags.values(), key=lambda t: (t.name, t.id))
        if department_ids is not None:
            allowed = set(department_ids)
            tags = [t for t in tags if t.department_id is None or t.department_id in allowed]
        return [self._tag_with_count(t) for t in tags]

    def get_tag(self, tag_id: int) -> TagRow | None:
        tag = self.tags.get(tag_id)
        return self._tag_with_count(tag) if tag else None

    def get_or_create_tag(self, name: str, department_id: str | None) -> TagRow:
        clean = " ".join(name.split())
        with self._lock:
            for tag in sorted(self.tags.values(), key=lambda t: t.id):
                if tag.name.lower() == clean.lower() and tag.department_id == department_id:
                    return self._tag_with_count(tag)
            tag = TagRow(id=self._next_tag_id, name=clean, department_id=department_id)
            self._next_tag_id += 1
            self.tags[tag.id] = tag
            return self._tag_with_count(tag)

    def set_tag_centroid(self, tag_id: int, centroid: list[float] | None) -> None:
        tag = self.tags.get(tag_id)
        if tag is not None:
            self.tags[tag_id] = tag.model_copy(update={"centroid": list(centroid) if centroid is not None else None})

    def confirmed_tag_document_ids(self, tag_id: int) -> list[UUID]:
        return sorted(
            (d for (d, t), ref in self.document_tags.items() if t == tag_id and ref.status == "confirmed"), key=str
        )

    def _document_tag_refs(self, document_id: UUID) -> list[TagRef]:
        key = UUID(str(document_id))
        refs = [ref for (d, _), ref in self.document_tags.items() if d == key]
        return sorted(refs, key=lambda r: (r.name, r.id))

    def get_document_tags(self, document_id: UUID) -> list[TagRef]:
        return [r.model_copy() for r in self._document_tag_refs(document_id)]

    def set_document_tag(
        self,
        document_id: UUID,
        tag_id: int,
        source: TagSource,
        status: TagStatus,
        similarity: float | None = None,
    ) -> None:
        tag = self.tags.get(tag_id)
        if tag is None:
            raise KeyError(tag_id)
        key = (UUID(str(document_id)), tag_id)
        previous = self.document_tags.get(key)
        if similarity is None and previous is not None:
            similarity = previous.similarity
        self.document_tags[key] = TagRef(id=tag_id, name=tag.name, status=status, source=source, similarity=similarity)

    def remove_document_tag(self, document_id: UUID, tag_id: int) -> None:
        self.document_tags.pop((UUID(str(document_id)), tag_id), None)

    def replace_raptor_nodes(self, document_id: UUID, version_no: int, nodes: Sequence[RaptorNode]) -> None:
        key = UUID(str(document_id))
        self.raptor_nodes[(key, version_no)] = [
            n.model_copy(update={"document_id": key, "version_no": version_no}, deep=True) for n in nodes
        ]

    def get_raptor_nodes(self, document_id: UUID, version_no: int) -> list[RaptorNode]:
        nodes = self.raptor_nodes.get((UUID(str(document_id)), version_no), [])
        return [n.model_copy(deep=True) for n in sorted(nodes, key=lambda n: (n.level, n.id))]

    def list_jobs(self, document_id: UUID) -> list[Job]:
        key = UUID(str(document_id))
        return [j.model_copy() for j in sorted(self.jobs.values(), key=lambda j: j.id) if j.document_id == key]

