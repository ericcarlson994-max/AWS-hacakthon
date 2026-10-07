from __future__ import annotations

from fastapi import FastAPI, Request

from dms_agent.service import AgentService
from dms_core.answer.service import AskService
from dms_core.ports import Container
from dms_core.search.service import SearchService


def container_for_app(app: FastAPI) -> Container:
    container = getattr(app.state, "container", None)
    if container is None:
        factory = getattr(app.state, "container_factory", None)
        if factory is None:
            from dms_adapters.container import build_container

            factory = build_container
        container = factory()
        app.state.container = container
    return container


def get_container(request: Request) -> Container:
    return container_for_app(request.app)


def _service_cache(request: Request) -> dict[tuple[int, str], object]:
    cache = getattr(request.app.state, "service_cache", None)
    if cache is None:
        cache = {}
        request.app.state.service_cache = cache
    return cache


def get_search_service(request: Request) -> SearchService:
    container = get_container(request)
    cache = _service_cache(request)
    key = (id(container), "search")
    service = cache.get(key)
    if not isinstance(service, SearchService):
        service = SearchService(container.index, container.embedder, container.repo, container.settings)
        cache[key] = service
    return service


def get_ask_service(request: Request) -> AskService:
    container = get_container(request)
    cache = _service_cache(request)
    key = (id(container), "ask")
    service = cache.get(key)
    if not isinstance(service, AskService):
        service = AskService(get_search_service(request), container.llm, container.repo, container.settings)
        cache[key] = service
    return service


def get_agent_service(request: Request) -> AgentService:
    container = get_container(request)
    cache = _service_cache(request)
    key = (id(container), "agent")
    service = cache.get(key)
    if not isinstance(service, AgentService):
        service = AgentService(container, get_search_service(request), get_ask_service(request))
        cache[key] = service
    return service
