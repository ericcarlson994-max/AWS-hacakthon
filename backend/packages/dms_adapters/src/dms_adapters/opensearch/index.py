from __future__ import annotations

from typing import Any

from opensearchpy import OpenSearch, helpers
from opensearchpy.exceptions import NotFoundError

from dms_core.config import Settings
from dms_core.search.mappings import CHUNKS_INDEX, TITLES_INDEX, chunks_index_body, titles_index_body


class OpenSearchIndex:
    def __init__(self, settings: Settings, timeout: int = 30) -> None:
        self.settings = settings
        self.timeout = timeout
        self._client: OpenSearch | None = None

    @property
    def client(self) -> OpenSearch:
        if self._client is None:
            self._client = OpenSearch(
                hosts=[self.settings.opensearch_url],
                use_ssl=self.settings.opensearch_url.startswith("https"),
                verify_certs=False,
                ssl_show_warn=False,
                timeout=self.timeout,
                max_retries=2,
                retry_on_timeout=True,
            )
        return self._client

    def ensure_indexes(self) -> None:
        if not self.client.indices.exists(index=CHUNKS_INDEX):
            self.client.indices.create(index=CHUNKS_INDEX, body=chunks_index_body(self.settings.embed_dim))
        if not self.client.indices.exists(index=TITLES_INDEX):
            self.client.indices.create(index=TITLES_INDEX, body=titles_index_body())

    def drop_indexes(self) -> None:
        for name in (CHUNKS_INDEX, TITLES_INDEX):
            self.client.indices.delete(index=name, ignore=[404])

    def upsert_chunks(self, docs: list[dict[str, Any]]) -> None:
        if not docs:
            return
        actions = [
            {"_op_type": "index", "_index": CHUNKS_INDEX, "_id": doc["chunk_id"], "_source": doc}
            for doc in docs
        ]
        helpers.bulk(self.client, actions, refresh=True)

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        actions = [{"_op_type": "delete", "_index": CHUNKS_INDEX, "_id": chunk_id} for chunk_id in chunk_ids]
        helpers.bulk(self.client, actions, refresh=True, raise_on_error=False)

    def delete_document(self, document_id: str) -> None:
        self.client.delete_by_query(
            index=CHUNKS_INDEX,
            body={"query": {"term": {"document_id": document_id}}},
            params={"refresh": "true", "conflicts": "proceed"},
            ignore=[404],
        )
        self.client.delete(index=TITLES_INDEX, id=document_id, refresh=True, ignore=[404])

    def upsert_title(self, doc: dict[str, Any]) -> None:
        self.client.index(index=TITLES_INDEX, id=doc["document_id"], body=doc, refresh=True)

    def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:
        return self.client.search(index=index, body=body)

    def msearch(self, requests: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
        if not requests:
            return []
        lines: list[dict[str, Any]] = []
        for index, body in requests:
            lines.append({"index": index})
            lines.append(body)
        result = self.client.msearch(body=lines)
        return list(result.get("responses", []))

    def refresh(self) -> None:
        self.client.indices.refresh(index=f"{CHUNKS_INDEX},{TITLES_INDEX}", ignore=[404])

    def ping(self) -> bool:
        try:
            return bool(self.client.ping())
        except Exception:
            return False

    def count(self, index: str, query: dict[str, Any] | None = None) -> int:
        try:
            body = {"query": query} if query else None
            return int(self.client.count(index=index, body=body)["count"])
        except NotFoundError:
            return 0
