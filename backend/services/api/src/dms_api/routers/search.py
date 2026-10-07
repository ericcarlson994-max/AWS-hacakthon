from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from dms_api.auth import CurrentUser
from dms_api.deps import get_search_service
from dms_api.schemas import SearchRequest, SearchResponse, SuggestResponse
from dms_core.search.service import SearchService

MAX_PAGE_SIZE = 50

router = APIRouter(tags=["search"])

SearchServiceDep = Annotated[SearchService, Depends(get_search_service)]


@router.get("/suggest", response_model=SuggestResponse)
def suggest(user: CurrentUser, service: SearchServiceDep, q: Annotated[str, Query()] = "") -> SuggestResponse:
    return service.suggest(user, q)


@router.post("/search", response_model=SearchResponse)
def search(body: SearchRequest, user: CurrentUser, service: SearchServiceDep) -> SearchResponse:
    page = max(body.page, 1)
    page_size = min(max(body.page_size, 1), MAX_PAGE_SIZE)
    return service.search(user, body.query, body.filters, page=page, page_size=page_size)
