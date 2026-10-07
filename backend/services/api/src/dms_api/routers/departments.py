from __future__ import annotations

from fastapi import APIRouter

from dms_api.auth import ContainerDep, CurrentUser
from dms_api.schemas import DepartmentOut

router = APIRouter(tags=["departments"])


@router.get("/departments", response_model=list[DepartmentOut])
def list_departments(user: CurrentUser, container: ContainerDep) -> list[DepartmentOut]:
    if not user.department_ids:
        return []
    return [DepartmentOut(id=d.id, name=d.name) for d in container.repo.list_departments(user.department_ids)]
