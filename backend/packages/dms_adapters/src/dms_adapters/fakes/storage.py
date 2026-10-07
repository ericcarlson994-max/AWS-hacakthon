from __future__ import annotations

from collections.abc import Callable
from typing import Any


class FakeBlobStore:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, sha256: str, data: bytes, content_type: str) -> None:
        self.objects[sha256] = (data, content_type)

    def get(self, sha256: str) -> bytes:
        return self.objects[sha256][0]

    def exists(self, sha256: str) -> bool:
        return sha256 in self.objects

    def ensure_bucket(self) -> None:
        return None


Responder = Callable[[str, dict[str, Any]], dict[str, Any]]


def empty_response(index: str, body: dict[str, Any]) -> dict[str, Any]:
    return {"took": 1, "hits": {"total": {"value": 0}, "hits": []}, "aggregations": {}, "suggest": {}}


class FakeSearchIndex:
    def __init__(self, responder: Responder | None = None) -> None:
        self.chunks: dict[str, dict[str, Any]] = {}
        self.titles: dict[str, dict[str, Any]] = {}
        self.queries: list[tuple[str, dict[str, Any]]] = []
        self.responder: Responder = responder or empty_response
        self.ensured = False

    def ensure_indexes(self) -> None:
        self.ensured = True

    def drop_indexes(self) -> None:
        self.chunks.clear()
        self.titles.clear()

    def upsert_chunks(self, docs: list[dict[str, Any]]) -> None:
        for d in docs:
            self.chunks[d["chunk_id"]] = d

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        for cid in chunk_ids:
            self.chunks.pop(cid, None)

    def delete_document(self, document_id: str) -> None:
        for cid in [k for k, v in self.chunks.items() if v.get("document_id") == document_id]:
            del self.chunks[cid]
        self.titles.pop(document_id, None)

    def upsert_title(self, doc: dict[str, Any]) -> None:
        self.titles[doc["document_id"]] = doc

    def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:
        self.queries.append((index, body))
        return self.responder(index, body)

    def msearch(self, requests: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
        return [self.search(i, b) for i, b in requests]

    def refresh(self) -> None:
        return None

    def ping(self) -> bool:
        return True
