from __future__ import annotations

from dms_adapters.fakes.ai import FakeEmbedder, FakeLlm, FakeVisionOcr
from dms_adapters.fakes.jobs import FakeJobQueue
from dms_adapters.fakes.repo import FakeRepo
from dms_adapters.fakes.storage import FakeBlobStore, FakeSearchIndex
from dms_adapters.opensearch.index import OpenSearchIndex
from dms_adapters.openrouter.client import OpenRouterClient
from dms_adapters.openrouter.embedder import OpenRouterEmbedder
from dms_adapters.openrouter.llm import OpenRouterLlm
from dms_adapters.openrouter.vision_ocr import OpenRouterVisionOcr
from dms_adapters.postgres.db import Database
from dms_adapters.postgres.jobs import PostgresJobQueue
from dms_adapters.postgres.repo import PostgresRepo
from dms_adapters.storage.s3_store import S3BlobStore
from dms_core.config import Settings, get_settings
from dms_core.ports import Container, Embedder, Llm, VisionOcr


def uses_fake_ai(settings: Settings) -> bool:
    return settings.fake_ai or not settings.openrouter_api_key.strip()


def build_ai_adapters(settings: Settings) -> tuple[Embedder, Llm, VisionOcr]:
    if uses_fake_ai(settings):
        return FakeEmbedder(settings.embed_dim), FakeLlm(), FakeVisionOcr()
    client = OpenRouterClient(settings)
    return (
        OpenRouterEmbedder(client, settings.embed_model, settings.embed_batch_size),
        OpenRouterLlm(client, settings.llm_fast_model),
        OpenRouterVisionOcr(client, settings.vision_ocr_model),
    )


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or get_settings()
    database = Database.from_settings(settings)
    embedder, llm, ocr = build_ai_adapters(settings)
    return Container(
        settings=settings,
        repo=PostgresRepo(settings, database),
        jobs=PostgresJobQueue(settings, database),
        blobs=S3BlobStore(settings),
        index=OpenSearchIndex(settings),
        embedder=embedder,
        llm=llm,
        ocr=ocr,
    )


def build_fake_container(settings: Settings | None = None) -> Container:
    settings = settings or Settings(fake_ai=True)
    repo = FakeRepo()
    return Container(
        settings=settings,
        repo=repo,
        jobs=FakeJobQueue(repo),
        blobs=FakeBlobStore(),
        index=FakeSearchIndex(),
        embedder=FakeEmbedder(settings.embed_dim),
        llm=FakeLlm(),
        ocr=FakeVisionOcr(),
    )
