from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from dms_agent.service import AgentService
from dms_api.auth import CurrentUser
from dms_api.deps import get_agent_service, get_ask_service
from dms_api.schemas import AskRequest
from dms_core.answer.service import AskService
from dms_core.models import User

router = APIRouter(tags=["ask"])


async def ask_events(
    ask_service: AskService, agent_service: AgentService, user: User, body: AskRequest
) -> AsyncIterator[dict[str, str]]:
    try:
        if body.mode == "agent":
            events = agent_service.stream(user, body.question, body.filters, body.history)
        else:
            events = ask_service.stream(user, body.question, body.filters)
        async for event in events:
            yield {"event": event.event, "data": json.dumps(event.data, ensure_ascii=False, default=str)}
    except Exception as error:
        message = str(error) or error.__class__.__name__
        yield {"event": "error", "data": json.dumps({"message": message})}


@router.post("/ask")
async def ask(
    body: AskRequest,
    user: CurrentUser,
    ask_service: Annotated[AskService, Depends(get_ask_service)],
    agent_service: Annotated[AgentService, Depends(get_agent_service)],
) -> EventSourceResponse:
    return EventSourceResponse(ask_events(ask_service, agent_service, user, body))
