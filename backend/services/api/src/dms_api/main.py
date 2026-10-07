from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from dms_api.auth import router as auth_router
from dms_api.deps import container_for_app
from dms_api.errors import ApiError, code_for_status, error_body
from dms_api.routers import ask, departments, documents, folders, health, search, tags
from dms_core.config import get_settings
from dms_core.ports import Container

logger = logging.getLogger(__name__)


def prepare_dependencies(app: FastAPI) -> None:
    try:
        container = container_for_app(app)
    except Exception:
        logger.exception("container could not be built at startup")
        return
    for name, step in (("blob bucket", container.blobs.ensure_bucket), ("search indexes", container.index.ensure_indexes)):
        try:
            step()
        except Exception as error:
            logger.warning("could not ensure %s: %s", name, error)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    prepare_dependencies(app)
    yield


async def http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    if isinstance(exc, ApiError):
        code, message = exc.code, exc.message
    else:
        code, message = code_for_status(exc.status_code), str(exc.detail)
    headers = getattr(exc, "headers", None)
    return JSONResponse(status_code=exc.status_code, content=error_body(code, message), headers=headers)


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    parts = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error.get("loc", ()))
        parts.append(f"{location}: {error.get('msg', 'invalid')}" if location else str(error.get("msg", "invalid")))
    message = "; ".join(parts) or "Invalid request"
    return JSONResponse(status_code=422, content=error_body("validation_error", message))


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content=error_body("internal_error", "Internal server error"))


def create_app(container: Container | None = None, container_factory: Callable[[], Container] | None = None) -> FastAPI:
    app = FastAPI(title="GovDocs Search API", version="0.1.0", lifespan=lifespan)
    app.state.container = container
    app.state.container_factory = container_factory
    app.state.service_cache = {}
    settings = container.settings if container is not None else get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_origin_regex=settings.cors_origin_regex or None,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)
    for router in (
        health.router,
        auth_router,
        departments.router,
        folders.router,
        documents.router,
        search.router,
        ask.router,
        tags.router,
    ):
        app.include_router(router)
    return app


app = create_app()
