from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from dms_api.auth import ContainerDep, CurrentUser
from dms_api.errors import forbidden
from dms_api.schemas import TagOut

router = APIRouter(tags=["tags"])


@router.get("/tags", response_model=list[TagOut])
def list_tags(
    user: CurrentUser, container: ContainerDep, department_id: Annotated[str | None, Query()] = None
) -> list[TagOut]:
    if department_id is not None and department_id not in user.department_ids:
        raise forbidden("You are not a member of that department")
    scope = [department_id] if department_id else user.department_ids
    allowed = set(user.department_ids)
    return [
        TagOut(id=t.id, name=t.name, department_id=t.department_id, doc_count=t.doc_count)
        for t in container.repo.list_tags(scope)
        if t.department_id is None or t.department_id in allowed
    ]
