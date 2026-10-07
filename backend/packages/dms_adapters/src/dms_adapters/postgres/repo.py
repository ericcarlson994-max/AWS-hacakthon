from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

import numpy as np
from psycopg import errors as pg_errors
from psycopg.types.json import Jsonb

from dms_adapters.postgres.db import Database
from dms_core.config import Settings
from dms_core.folders import FolderConflict, FolderCycle, new_folder_id
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

DOCUMENT_COLUMNS = (
    "id, department_id, title, title_source, title_confidence, doctype, meta, superseded_by, "
    "duplicate_of, duplicate_tier, root_summary, status, status_detail, current_version_id, "
    "created_by, created_at, updated_at, folder_id, deleted_at"
)
QUALIFIED_DOCUMENT_COLUMNS = ", ".join(f"d.{name.strip()}" for name in DOCUMENT_COLUMNS.split(","))
VERSION_COLUMNS = (
    "id, document_id, version_no, blob_sha256, original_filename, mime_type, size_bytes, page_count, "
    "blocks, embedded_title, merkle_root, chunk_manifest, delta_stats, uploaded_by, created_at"
)
FOLDER_ORDER = "ORDER BY (f.id <> 'inbox'), lower(f.name), f.id"
CHUNK_COLUMNS = "id, document_id, ord, text, heading_path, page_from, page_to, token_count, embedding"

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
SORT_COLUMNS = {
    "created_at": "d.created_at",
    "updated_at": "d.updated_at",
    "title": "lower(d.title)",
    "status": "d.status",
}


def to_vector(values: Sequence[float] | None) -> np.ndarray | None:
    if values is None:
        return None
    return np.asarray(list(values), dtype=np.float32)


def from_vector(value: Any) -> list[float] | None:
    if value is None:
        return None
    if hasattr(value, "tolist"):
        return [float(x) for x in value.tolist()]
    if hasattr(value, "to_list"):
        return [float(x) for x in value.to_list()]
    return [float(x) for x in value]


def meta_to_json(value: Any) -> Jsonb:
    if isinstance(value, DocumentMeta):
        return Jsonb(value.model_dump())
    if value is None:
        return Jsonb({})
    return Jsonb(DocumentMeta.model_validate(value).model_dump())


def blocks_to_json(value: Any) -> Jsonb | None:
    if value is None:
        return None
    return Jsonb([b.model_dump() if isinstance(b, Block) else Block.model_validate(b).model_dump() for b in value])


def delta_stats_to_json(value: Any) -> Jsonb | None:
    if value is None:
        return None
    if isinstance(value, DeltaStats):
        return Jsonb(value.model_dump())
    return Jsonb(DeltaStats.model_validate(value).model_dump())


def document_from_row(row: dict[str, Any]) -> DocumentRow:
    data = dict(row)
    data.pop("minhash", None)
    data["meta"] = DocumentMeta.model_validate(data.get("meta") or {})
    return DocumentRow.model_validate(data)


def version_from_row(row: dict[str, Any]) -> VersionRow:
    data = dict(row)
    if data.get("blocks") is not None:
        data["blocks"] = [Block.model_validate(b) for b in data["blocks"]]
    if data.get("delta_stats") is not None:
        data["delta_stats"] = DeltaStats.model_validate(data["delta_stats"])
    return VersionRow.model_validate(data)


def chunk_from_row(row: dict[str, Any]) -> Chunk:
    return Chunk(
        id=row["id"],
        document_id=row["document_id"],
        order=row["ord"],
        text=row["text"],
        heading_path=list(row["heading_path"] or []),
        page_from=row["page_from"],
        page_to=row["page_to"],
        token_count=row["token_count"],
        embedding=from_vector(row["embedding"]),
    )


def raptor_from_row(row: dict[str, Any]) -> RaptorNode:
    return RaptorNode(
        id=row["id"],
        document_id=row["document_id"],
        version_no=row["version_no"],
        level=row["level"],
        summary_text=row["summary_text"],
        embedding=from_vector(row["embedding"]),
        children=list(row["children"] or []),
    )


def tag_from_row(row: dict[str, Any]) -> TagRow:
    return TagRow(
        id=row["id"],
        name=row["name"],
        department_id=row["department_id"],
        centroid=from_vector(row.get("centroid")),
        doc_count=int(row.get("doc_count") or 0),
    )


def parse_sort(sort: str) -> str:
    descending = sort.startswith("-")
    key = sort.lstrip("-+")
    column = SORT_COLUMNS.get(key, "d.created_at")
    if key not in SORT_COLUMNS:
        descending = True
    direction = "DESC" if descending else "ASC"
    return f"{column} {direction}, d.id {direction}"


class PostgresRepo:
    def __init__(self, settings: Settings, database: Database | None = None) -> None:
        self.settings = settings
        self.db = database or Database.from_settings(settings)

    def _fetch_all(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            return list(connection.execute(sql, params).fetchall())

    def _fetch_one(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            return connection.execute(sql, params).fetchone()

    def _execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> None:
        with self.db.connection() as connection:
            connection.execute(sql, params)

    def ping(self) -> bool:
        try:
            row = self._fetch_one("SELECT 1 AS ok")
            return bool(row and row["ok"] == 1)
        except Exception:
            return False

    def upsert_department(self, department_id: str, name: str) -> None:
        self._execute(
            "INSERT INTO departments (id, name) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name",
            (department_id, name),
        )

    def list_departments(self, ids: list[str] | None = None) -> list[Department]:
        if ids is None:
            rows = self._fetch_all("SELECT id, name FROM departments ORDER BY id")
        else:
            rows = self._fetch_all("SELECT id, name FROM departments WHERE id = ANY(%s) ORDER BY id", (list(ids),))
        return [Department(**row) for row in rows]

    def upsert_user(self, user_id: str, username: str, display_name: str) -> None:
        self._execute(
            "INSERT INTO users (id, username, display_name) VALUES (%s, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET username = EXCLUDED.username, display_name = EXCLUDED.display_name",
            (user_id, username, display_name),
        )

    def set_membership(self, user_id: str, department_id: str, role: str) -> None:
        self._execute(
            "INSERT INTO user_departments (user_id, department_id, role) VALUES (%s, %s, %s) "
            "ON CONFLICT (user_id, department_id) DO UPDATE SET role = EXCLUDED.role",
            (user_id, department_id, role),
        )

    def _build_user(self, row: dict[str, Any] | None) -> User | None:
        if row is None:
            return None
        memberships = self._fetch_all(
            "SELECT d.id, d.name, ud.role FROM user_departments ud JOIN departments d ON d.id = ud.department_id "
            "WHERE ud.user_id = %s ORDER BY d.id",
            (row["id"],),
        )
        return User(
            id=row["id"],
            username=row["username"],
            display_name=row["display_name"],
            departments=[DepartmentMembership(**m) for m in memberships],
        )

    def get_user(self, user_id: str) -> User | None:
        return self._build_user(self._fetch_one("SELECT id, username, display_name FROM users WHERE id = %s", (user_id,)))

    def get_user_by_username(self, username: str) -> User | None:
        return self._build_user(
            self._fetch_one("SELECT id, username, display_name FROM users WHERE username = %s", (username,))
        )

    def list_folders(self, department_ids: list[str] | None = None) -> list[Folder]:
        rows = self._fetch_all(
            "SELECT f.id, f.name, f.parent_id, (SELECT count(*) FROM documents d WHERE d.folder_id = f.id "
            "AND d.deleted_at IS NULL AND (%(all)s OR d.department_id = ANY(%(departments)s))) AS doc_count "
            f"FROM folders f {FOLDER_ORDER}",
            {"all": department_ids is None, "departments": list(department_ids or [])},
        )
        return [Folder(**row) for row in rows]

    def get_folder(self, folder_id: str) -> Folder | None:
        row = self._fetch_one(
            "SELECT f.id, f.name, f.parent_id, (SELECT count(*) FROM documents d WHERE d.folder_id = f.id "
            "AND d.deleted_at IS NULL) AS doc_count FROM folders f WHERE f.id = %s",
            (folder_id,),
        )
        return Folder(**row) if row else None

    def create_folder(self, name: str, parent_id: str | None = None) -> Folder:
        if parent_id is not None and self.get_folder(parent_id) is None:
            raise KeyError(parent_id)
        try:
            row = self._fetch_one(
                "INSERT INTO folders (id, name, parent_id) VALUES (%s, %s, %s) RETURNING id, name, parent_id",
                (new_folder_id(name), name, parent_id),
            )
        except pg_errors.UniqueViolation as error:
            raise FolderConflict(name) from error
        assert row is not None
        return Folder(**row)

    def update_folder(
        self, folder_id: str, name: str | None = None, parent_id: str | None = None, *, set_parent: bool = False
    ) -> Folder:
        current = self.get_folder(folder_id)
        if current is None:
            raise KeyError(folder_id)
        new_name = name if name is not None else current.name
        new_parent = parent_id if set_parent else current.parent_id
        if new_parent is not None:
            if self.get_folder(new_parent) is None:
                raise KeyError(new_parent)
            if new_parent == folder_id or new_parent in self.folder_descendants(folder_id):
                raise FolderCycle(folder_id)
        try:
            self._execute(
                "UPDATE folders SET name = %s, parent_id = %s WHERE id = %s", (new_name, new_parent, folder_id)
            )
        except pg_errors.UniqueViolation as error:
            raise FolderConflict(new_name) from error
        updated = self.get_folder(folder_id)
        assert updated is not None
        return updated

    def folder_descendants(self, folder_id: str) -> list[str]:
        rows = self._fetch_all(
            "WITH RECURSIVE tree(id, depth) AS (SELECT id, 1 FROM folders WHERE parent_id = %s "
            "UNION SELECT f.id, t.depth + 1 FROM folders f JOIN tree t ON f.parent_id = t.id WHERE t.depth < 64) "
            "SELECT id, min(depth) AS depth FROM tree WHERE id <> %s GROUP BY id ORDER BY min(depth), id",
            (folder_id, folder_id),
        )
        return [row["id"] for row in rows]

    def delete_folder(self, folder_id: str) -> None:
        self._execute("DELETE FROM folders WHERE id = %s", (folder_id,))

    def list_folder_documents(self, folder_ids: list[str]) -> list[DocumentRow]:
        if not folder_ids:
            return []
        rows = self._fetch_all(
            f"SELECT {DOCUMENT_COLUMNS} FROM documents WHERE folder_id = ANY(%s) AND deleted_at IS NULL "
            "ORDER BY created_at, id",
            (list(folder_ids),),
        )
        return [document_from_row(row) for row in rows]

    def soft_delete_document(self, document_id: UUID) -> None:
        self._execute(
            "UPDATE documents SET deleted_at = now(), updated_at = now() WHERE id = %s AND deleted_at IS NULL",
            (document_id,),
        )

    def create_document(
        self,
        *,
        department_id: str,
        created_by: str | None,
        title: str | None = None,
        folder_id: str | None = None,
    ) -> DocumentRow:
        row = self._fetch_one(
            "INSERT INTO documents (department_id, created_by, title, folder_id) VALUES (%s, %s, %s, %s) "
            f"RETURNING {DOCUMENT_COLUMNS}",
            (department_id, created_by, title or DEFAULT_TITLE, folder_id),
        )
        assert row is not None
        return document_from_row(row)

    def get_document(self, document_id: UUID) -> DocumentRow | None:
        row = self._fetch_one(
            f"SELECT {DOCUMENT_COLUMNS} FROM documents WHERE id = %s AND deleted_at IS NULL", (document_id,)
        )
        return document_from_row(row) if row else None

    def get_documents(self, ids: Sequence[UUID]) -> list[DocumentRow]:
        id_list = list(ids)
        if not id_list:
            return []
        rows = self._fetch_all(
            f"SELECT {DOCUMENT_COLUMNS} FROM documents WHERE id = ANY(%s) AND deleted_at IS NULL", (id_list,)
        )
        by_id = {row["id"]: document_from_row(row) for row in rows}
        return [by_id[i] for i in dict.fromkeys(UUID(str(x)) for x in id_list) if i in by_id]

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
        conditions = ["d.department_id = ANY(%(departments)s)", "d.deleted_at IS NULL"]
        params: dict[str, Any] = {"departments": list(department_ids)}
        if folder_ids is not None:
            conditions.append("d.folder_id = ANY(%(folders)s)")
            params["folders"] = list(folder_ids)
        if doctype:
            conditions.append("d.doctype = %(doctype)s")
            params["doctype"] = doctype
        if status:
            conditions.append("d.status = %(status)s")
            params["status"] = status
        if tag:
            conditions.append(
                "EXISTS (SELECT 1 FROM document_tags dt JOIN tags t ON t.id = dt.tag_id "
                "WHERE dt.document_id = d.id AND lower(t.name) = lower(%(tag)s))"
            )
            params["tag"] = tag
        where = " AND ".join(conditions)
        page = max(1, page)
        page_size = max(1, page_size)
        params["limit"] = page_size
        params["offset"] = (page - 1) * page_size
        with self.db.connection() as connection:
            total_row = connection.execute(f"SELECT count(*) AS total FROM documents d WHERE {where}", params).fetchone()
            rows = connection.execute(
                f"SELECT {QUALIFIED_DOCUMENT_COLUMNS} FROM documents d WHERE {where} "
                f"ORDER BY {parse_sort(sort)} LIMIT %(limit)s OFFSET %(offset)s",
                params,
            ).fetchall()
        total = int(total_row["total"]) if total_row else 0
        return [document_from_row(row) for row in rows], total

    def list_all_document_ids(self) -> list[UUID]:
        return [row["id"] for row in self._fetch_all("SELECT id FROM documents WHERE deleted_at IS NULL ORDER BY created_at, id")]

    def update_document(self, document_id: UUID, **fields: Any) -> DocumentRow:
        unknown = set(fields) - UPDATABLE_DOCUMENT_FIELDS
        if unknown:
            raise ValueError(f"unknown document fields: {sorted(unknown)}")
        assignments: list[str] = []
        params: list[Any] = []
        for name, value in fields.items():
            if name == "meta":
                value = meta_to_json(value)
            assignments.append(f"{name} = %s")
            params.append(value)
        assignments.append("updated_at = now()")
        params.append(document_id)
        row = self._fetch_one(
            f"UPDATE documents SET {', '.join(assignments)} WHERE id = %s RETURNING {DOCUMENT_COLUMNS}",
            params,
        )
        if row is None:
            raise KeyError(str(document_id))
        return document_from_row(row)

    def set_status(self, document_id: UUID, status: DocStatus, detail: str | None = None) -> None:
        self._execute(
            "UPDATE documents SET status = %s, status_detail = %s, updated_at = now() WHERE id = %s",
            (status, detail, document_id),
        )

    def find_document_by_reference(
        self, department_id: str, reference_no: str, exclude_id: UUID | None = None
    ) -> DocumentRow | None:
        row = self._fetch_one(
            f"SELECT {DOCUMENT_COLUMNS} FROM documents WHERE department_id = %s AND deleted_at IS NULL "
            "AND lower(meta->>'reference_no') = lower(%s) AND (%s::uuid IS NULL OR id <> %s::uuid) "
            "ORDER BY created_at DESC LIMIT 1",
            (department_id, reference_no, exclude_id, exclude_id),
        )
        return document_from_row(row) if row else None

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
        with self.db.connection() as connection:
            with connection.transaction():
                connection.execute("SELECT id FROM documents WHERE id = %s FOR UPDATE", (document_id,))
                row = connection.execute(
                    f"INSERT INTO versions (document_id, version_no, blob_sha256, original_filename, mime_type, "
                    f"size_bytes, uploaded_by) VALUES (%s, (SELECT coalesce(max(version_no), 0) + 1 FROM versions "
                    f"WHERE document_id = %s), %s, %s, %s, %s, %s) RETURNING {VERSION_COLUMNS}",
                    (document_id, document_id, blob_sha256, original_filename, mime_type, size_bytes, uploaded_by),
                ).fetchone()
                assert row is not None
                connection.execute(
                    "UPDATE documents SET current_version_id = %s, updated_at = now() WHERE id = %s",
                    (row["id"], document_id),
                )
        return version_from_row(row)

    def get_version(self, version_id: UUID) -> VersionRow | None:
        row = self._fetch_one(f"SELECT {VERSION_COLUMNS} FROM versions WHERE id = %s", (version_id,))
        return version_from_row(row) if row else None

    def get_version_by_no(self, document_id: UUID, version_no: int) -> VersionRow | None:
        row = self._fetch_one(
            f"SELECT {VERSION_COLUMNS} FROM versions WHERE document_id = %s AND version_no = %s",
            (document_id, version_no),
        )
        return version_from_row(row) if row else None

    def get_current_version(self, document_id: UUID) -> VersionRow | None:
        row = self._fetch_one(
            f"SELECT {', '.join('v.' + c.strip() for c in VERSION_COLUMNS.split(','))} FROM versions v "
            "JOIN documents d ON d.current_version_id = v.id WHERE d.id = %s",
            (document_id,),
        )
        if row is None:
            row = self._fetch_one(
                f"SELECT {VERSION_COLUMNS} FROM versions WHERE document_id = %s ORDER BY version_no DESC LIMIT 1",
                (document_id,),
            )
        return version_from_row(row) if row else None

    def get_previous_version(self, document_id: UUID, version_no: int) -> VersionRow | None:
        row = self._fetch_one(
            f"SELECT {VERSION_COLUMNS} FROM versions WHERE document_id = %s AND version_no < %s "
            "ORDER BY version_no DESC LIMIT 1",
            (document_id, version_no),
        )
        return version_from_row(row) if row else None

    def list_versions(self, document_id: UUID) -> list[VersionRow]:
        rows = self._fetch_all(
            f"SELECT {VERSION_COLUMNS} FROM versions WHERE document_id = %s ORDER BY version_no", (document_id,)
        )
        return [version_from_row(row) for row in rows]

    def find_version_by_sha(self, sha256: str) -> VersionRow | None:
        row = self._fetch_one(
            f"SELECT {', '.join('v.' + c.strip() for c in VERSION_COLUMNS.split(','))} FROM versions v "
            "JOIN documents d ON d.id = v.document_id WHERE v.blob_sha256 = %s AND d.deleted_at IS NULL "
            "ORDER BY v.created_at, v.version_no LIMIT 1",
            (sha256,),
        )
        return version_from_row(row) if row else None

    def update_version(self, version_id: UUID, **fields: Any) -> None:
        unknown = set(fields) - UPDATABLE_VERSION_FIELDS
        if unknown:
            raise ValueError(f"unknown version fields: {sorted(unknown)}")
        if not fields:
            return
        assignments: list[str] = []
        params: list[Any] = []
        for name, value in fields.items():
            if name == "blocks":
                value = blocks_to_json(value)
            elif name == "chunk_manifest":
                value = Jsonb(list(value)) if value is not None else None
            elif name == "delta_stats":
                value = delta_stats_to_json(value)
            assignments.append(f"{name} = %s")
            params.append(value)
        params.append(version_id)
        self._execute(f"UPDATE versions SET {', '.join(assignments)} WHERE id = %s", params)

    def set_delta_stats(self, version_id: UUID, stats: DeltaStats) -> None:
        self._execute("UPDATE versions SET delta_stats = %s WHERE id = %s", (delta_stats_to_json(stats), version_id))

    def upsert_chunks(self, chunks: Sequence[Chunk]) -> None:
        if not chunks:
            return
        params = [
            (
                c.id,
                c.document_id,
                c.order,
                c.text,
                list(c.heading_path),
                c.page_from,
                c.page_to,
                c.token_count,
                to_vector(c.embedding),
            )
            for c in chunks
        ]
        with self.db.connection() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    f"INSERT INTO chunks ({CHUNK_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (id) DO UPDATE SET document_id = EXCLUDED.document_id, ord = EXCLUDED.ord, "
                    "text = EXCLUDED.text, heading_path = EXCLUDED.heading_path, page_from = EXCLUDED.page_from, "
                    "page_to = EXCLUDED.page_to, token_count = EXCLUDED.token_count, "
                    "embedding = coalesce(EXCLUDED.embedding, chunks.embedding)",
                    params,
                )

    def get_chunks(self, ids: Sequence[str]) -> list[Chunk]:
        id_list = list(ids)
        if not id_list:
            return []
        rows = self._fetch_all(f"SELECT {CHUNK_COLUMNS} FROM chunks WHERE id = ANY(%s)", (id_list,))
        by_id = {row["id"]: chunk_from_row(row) for row in rows}
        return [by_id[i] for i in dict.fromkeys(id_list) if i in by_id]

    def get_document_chunks(self, document_id: UUID) -> list[Chunk]:
        rows = self._fetch_all(
            f"SELECT {CHUNK_COLUMNS} FROM chunks WHERE document_id = %s ORDER BY ord, id", (document_id,)
        )
        return [chunk_from_row(row) for row in rows]

    def delete_chunks(self, ids: Sequence[str]) -> None:
        id_list = list(ids)
        if id_list:
            self._execute("DELETE FROM chunks WHERE id = ANY(%s)", (id_list,))

    def document_embedding(self, document_id: UUID) -> list[float] | None:
        version = self.get_current_version(document_id)
        manifest = list(version.chunk_manifest or []) if version else []
        with self.db.connection() as connection:
            row = None
            if manifest:
                row = connection.execute(
                    "SELECT avg(embedding) AS mean FROM chunks WHERE document_id = %s AND id = ANY(%s) "
                    "AND embedding IS NOT NULL",
                    (document_id, manifest),
                ).fetchone()
            if row is None or row["mean"] is None:
                row = connection.execute(
                    "SELECT avg(embedding) AS mean FROM chunks WHERE document_id = %s AND embedding IS NOT NULL",
                    (document_id,),
                ).fetchone()
        if row is None or row["mean"] is None:
            return None
        return from_vector(row["mean"])

    def save_minhash(self, document_id: UUID, signature: bytes, bands: Sequence[tuple[int, str]]) -> None:
        band_rows = list(dict.fromkeys((int(band), str(bucket)) for band, bucket in bands))
        with self.db.connection() as connection:
            with connection.transaction():
                connection.execute(
                    "UPDATE documents SET minhash = %s, updated_at = now() WHERE id = %s", (signature, document_id)
                )
                connection.execute("DELETE FROM minhash_bands WHERE document_id = %s", (document_id,))
                if band_rows:
                    with connection.cursor() as cursor:
                        cursor.executemany(
                            "INSERT INTO minhash_bands (band, bucket, document_id) VALUES (%s, %s, %s) "
                            "ON CONFLICT DO NOTHING",
                            [(band, bucket, document_id) for band, bucket in band_rows],
                        )

    def find_minhash_candidates(
        self, bands: Sequence[tuple[int, str]], exclude_document_id: UUID
    ) -> list[tuple[UUID, bytes]]:
        band_list = list(bands)
        if not band_list:
            return []
        rows = self._fetch_all(
            "SELECT d.id, d.minhash FROM documents d WHERE d.id <> %s AND d.minhash IS NOT NULL "
            "AND d.deleted_at IS NULL AND EXISTS ("
            "SELECT 1 FROM minhash_bands b JOIN unnest(%s::int[], %s::text[]) AS q(band, bucket) "
            "ON q.band = b.band AND q.bucket = b.bucket WHERE b.document_id = d.id) ORDER BY d.created_at",
            (exclude_document_id, [int(b) for b, _ in band_list], [str(k) for _, k in band_list]),
        )
        return [(row["id"], bytes(row["minhash"])) for row in rows]

    def list_tags(self, department_ids: list[str] | None = None) -> list[TagRow]:
        base = (
            "SELECT t.id, t.name, t.department_id, t.centroid, "
            "(SELECT count(*) FROM document_tags dt WHERE dt.tag_id = t.id) AS doc_count FROM tags t"
        )
        if department_ids is None:
            rows = self._fetch_all(base + " ORDER BY t.name, t.id")
        else:
            rows = self._fetch_all(
                base + " WHERE t.department_id IS NULL OR t.department_id = ANY(%s) ORDER BY t.name, t.id",
                (list(department_ids),),
            )
        return [tag_from_row(row) for row in rows]

    def get_tag(self, tag_id: int) -> TagRow | None:
        row = self._fetch_one(
            "SELECT t.id, t.name, t.department_id, t.centroid, "
            "(SELECT count(*) FROM document_tags dt WHERE dt.tag_id = t.id) AS doc_count FROM tags t WHERE t.id = %s",
            (tag_id,),
        )
        return tag_from_row(row) if row else None

    def get_or_create_tag(self, name: str, department_id: str | None) -> TagRow:
        clean = " ".join(name.split())
        with self.db.connection() as connection:
            with connection.transaction():
                connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"tag:{clean.lower()}",))
                row = connection.execute(
                    "SELECT id FROM tags WHERE lower(name) = lower(%s) AND department_id IS NOT DISTINCT FROM %s "
                    "ORDER BY id LIMIT 1",
                    (clean, department_id),
                ).fetchone()
                if row is None:
                    row = connection.execute(
                        "INSERT INTO tags (name, department_id) VALUES (%s, %s) RETURNING id",
                        (clean, department_id),
                    ).fetchone()
        assert row is not None
        tag = self.get_tag(row["id"])
        assert tag is not None
        return tag

    def set_tag_centroid(self, tag_id: int, centroid: list[float] | None) -> None:
        self._execute("UPDATE tags SET centroid = %s WHERE id = %s", (to_vector(centroid), tag_id))

    def confirmed_tag_document_ids(self, tag_id: int) -> list[UUID]:
        rows = self._fetch_all(
            "SELECT document_id FROM document_tags WHERE tag_id = %s AND status = 'confirmed' ORDER BY document_id",
            (tag_id,),
        )
        return [row["document_id"] for row in rows]

    def get_document_tags(self, document_id: UUID) -> list[TagRef]:
        rows = self._fetch_all(
            "SELECT t.id, t.name, dt.status, dt.source, dt.similarity FROM document_tags dt "
            "JOIN tags t ON t.id = dt.tag_id WHERE dt.document_id = %s ORDER BY t.name, t.id",
            (document_id,),
        )
        return [TagRef(**row) for row in rows]

    def set_document_tag(
        self,
        document_id: UUID,
        tag_id: int,
        source: TagSource,
        status: TagStatus,
        similarity: float | None = None,
    ) -> None:
        self._execute(
            "INSERT INTO document_tags (document_id, tag_id, source, status, similarity) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (document_id, tag_id) DO UPDATE SET source = EXCLUDED.source, status = EXCLUDED.status, "
            "similarity = coalesce(EXCLUDED.similarity, document_tags.similarity)",
            (document_id, tag_id, source, status, similarity),
        )

    def remove_document_tag(self, document_id: UUID, tag_id: int) -> None:
        self._execute("DELETE FROM document_tags WHERE document_id = %s AND tag_id = %s", (document_id, tag_id))

    def replace_raptor_nodes(self, document_id: UUID, version_no: int, nodes: Sequence[RaptorNode]) -> None:
        with self.db.connection() as connection:
            with connection.transaction():
                connection.execute(
                    "DELETE FROM raptor_nodes WHERE document_id = %s AND version_no = %s", (document_id, version_no)
                )
                if nodes:
                    with connection.cursor() as cursor:
                        cursor.executemany(
                            "INSERT INTO raptor_nodes (id, document_id, version_no, level, summary_text, embedding, "
                            "children) VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO UPDATE SET "
                            "document_id = EXCLUDED.document_id, version_no = EXCLUDED.version_no, "
                            "level = EXCLUDED.level, summary_text = EXCLUDED.summary_text, "
                            "embedding = EXCLUDED.embedding, children = EXCLUDED.children",
                            [
                                (
                                    n.id,
                                    document_id,
                                    version_no,
                                    n.level,
                                    n.summary_text,
                                    to_vector(n.embedding),
                                    list(n.children),
                                )
                                for n in nodes
                            ],
                        )

    def get_raptor_nodes(self, document_id: UUID, version_no: int) -> list[RaptorNode]:
        rows = self._fetch_all(
            "SELECT id, document_id, version_no, level, summary_text, embedding, children FROM raptor_nodes "
            "WHERE document_id = %s AND version_no = %s ORDER BY level, id",
            (document_id, version_no),
        )
        return [raptor_from_row(row) for row in rows]

    def list_jobs(self, document_id: UUID) -> list[Job]:
        rows = self._fetch_all("SELECT * FROM jobs WHERE document_id = %s ORDER BY id", (document_id,))
        return [Job.model_validate(row) for row in rows]
