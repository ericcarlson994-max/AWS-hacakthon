from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Request

from dms_api.deps import get_container
from dms_api.schemas import HealthOut

HEALTH_PROBE_KEY = "__health_probe__"

router = APIRouter(tags=["health"])


def probe(check: Callable[[], object]) -> bool:
    try:
        result = check()
    except Exception:
        return False
    return result is not False


@router.get("/health", response_model=HealthOut)
def health(request: Request) -> HealthOut:
    try:
        container = get_container(request)
    except Exception:
        return HealthOut(
            status="degraded",
            deps={"postgres": False, "opensearch": False, "minio": False, "openrouter": False},
        )
    settings = container.settings
    deps = {
        "postgres": probe(container.repo.ping),
        "opensearch": probe(container.index.ping),
        "minio": probe(lambda: container.blobs.exists(HEALTH_PROBE_KEY) or True),
        "openrouter": bool(settings.openrouter_api_key.strip()) or settings.fake_ai,
    }
    core_ok = deps["postgres"] and deps["opensearch"] and deps["minio"]
    return HealthOut(status="ok" if core_ok else "degraded", deps=deps)
