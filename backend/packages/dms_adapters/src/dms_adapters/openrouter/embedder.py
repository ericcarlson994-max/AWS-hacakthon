from __future__ import annotations

from collections.abc import Sequence

from dms_adapters.openrouter.client import OpenRouterClient, OpenRouterError


class OpenRouterEmbedder:
    def __init__(self, client: OpenRouterClient, model: str, batch_size: int = 32) -> None:
        self.client = client
        self.model = model
        self.batch_size = max(1, batch_size)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        items = list(texts)
        vectors: list[list[float]] = []
        for start in range(0, len(items), self.batch_size):
            batch = items[start : start + self.batch_size]
            payload = self.client.post_json("/embeddings", {"model": self.model, "input": batch})
            data = sorted(payload.get("data") or [], key=lambda item: item.get("index", 0))
            if len(data) != len(batch):
                raise OpenRouterError(f"expected {len(batch)} embeddings, got {len(data)}")
            vectors.extend([float(x) for x in item["embedding"]] for item in data)
        return vectors
