from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from dms_api.deps import get_container
from dms_api.errors import ApiError
from dms_api.schemas import DevLoginRequest, LoginResponse, MembershipOut, UserOut
from dms_core.config import Settings
from dms_core.models import User
from dms_core.ports import Container

JWT_ALGORITHM = "HS256"

bearer_scheme = HTTPBearer(auto_error=False)
router = APIRouter(tags=["auth"])


def issue_token(user: User, settings: Settings) -> str:
    expires = datetime.now(UTC) + timedelta(minutes=settings.jwt_ttl_minutes)
    payload = {"sub": user.id, "username": user.username, "exp": expires}
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_token(token: str, settings: Settings) -> str:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])
    subject = payload.get("sub")
    if not subject:
        raise jwt.InvalidTokenError("missing subject")
    return str(subject)


def unauthorized(message: str = "Missing or invalid token") -> ApiError:
    return ApiError(401, "unauthorized", message)


def current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise unauthorized()
    container = get_container(request)
    try:
        user_id = decode_token(credentials.credentials, container.settings)
        user = container.repo.get_user(user_id)
    except Exception:
        raise unauthorized()
    if user is None:
        raise unauthorized("Unknown user")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
ContainerDep = Annotated[Container, Depends(get_container)]


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        departments=[MembershipOut(id=d.id, name=d.name, role=d.role) for d in user.departments],
    )


@router.post("/auth/dev-login", response_model=LoginResponse)
def dev_login(body: DevLoginRequest, container: ContainerDep) -> LoginResponse:
    user = container.repo.get_user_by_username(body.username.strip())
    if user is None:
        raise ApiError(404, "not_found", f"Unknown user {body.username!r}")
    return LoginResponse(token=issue_token(user, container.settings), user=user_out(user))


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return user_out(user)
