"""FastAPI application factory, lifespan, and HTTP middleware for /api/v1."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from jung.api.contracts import MappingContext, to_snapshot_response
from jung.api.deps import (
    ApiNotReady,
    ApiRuntime,
    build_error_response,
    get_runtime_from_state,
)
from jung.api.errors import (
    RequestIdError,
    http_status_for_exception,
    new_request_id,
    not_ready_error_response,
    parse_request_id_header,
    to_error_response,
    validation_error_response,
)
from jung.api.routes import router
from jung.api.settings import ApiSettings, validate_api_settings
from jung.composition import Settings as CompositionSettings
from jung.composition import application_context
from jung.domain.errors import DomainError, RevisionConflict

logger = logging.getLogger(__name__)

RuntimeFactory = Callable[
    [CompositionSettings],
    AbstractAsyncContextManager[ApiRuntime],
]


@dataclass
class ApiState:
    runtime: ApiRuntime | None = None
    ready: bool = False


def _request_id_from_request(request: Request) -> UUID:
    request_id = getattr(request.state, "request_id", None)
    if request_id is None:
        return new_request_id()
    return request_id


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiNotReady)
    async def api_not_ready_handler(
        request: Request,
        _exc: ApiNotReady,
    ):
        request_id = _request_id_from_request(request)
        body = not_ready_error_response(request_id=request_id)
        return build_error_response(status=503, body=body)

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request,
        _exc: RequestValidationError,
    ):
        request_id = _request_id_from_request(request)
        body = validation_error_response(request_id=request_id)
        return build_error_response(status=422, body=body)

    @app.exception_handler(RevisionConflict)
    async def revision_conflict_handler(request: Request, exc: RevisionConflict):
        request_id = _request_id_from_request(request)
        context = MappingContext(request_id=request_id)
        wire_snapshot = None
        try:
            runtime = get_runtime_from_state(request.app.state.api)
            snapshot = await runtime.application.get_snapshot()
            wire_snapshot = to_snapshot_response(snapshot, context=context)
        except Exception:
            logger.exception(
                "failed to enrich revision conflict snapshot",
                extra={"request_id": str(request_id)},
            )
        body = to_error_response(
            exc,
            request_id=request_id,
            current_snapshot=wire_snapshot,
        )
        return build_error_response(
            status=http_status_for_exception(exc),
            body=body,
        )

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):
        request_id = _request_id_from_request(request)
        status = http_status_for_exception(exc)

        if status >= 500:
            logger.error(
                "internal domain error",
                exc_info=exc,
                extra={"request_id": str(request_id)},
            )

        body = to_error_response(exc, request_id=request_id)
        return build_error_response(
            status=status,
            body=body,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        request_id = _request_id_from_request(request)
        logger.exception(
            "unhandled API error",
            extra={"request_id": str(request_id)},
        )
        body = to_error_response(exc, request_id=request_id)
        return build_error_response(status=500, body=body)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        header = request.headers.get("X-Request-ID")
        try:
            request_id = parse_request_id_header(header)
        except RequestIdError:
            request_id = new_request_id()
            body = validation_error_response(request_id=request_id)
            return build_error_response(status=422, body=body)

        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = str(request_id)
        return response


def create_app(
    settings: ApiSettings,
    *,
    runtime_factory: RuntimeFactory = application_context,
) -> FastAPI:
    settings = validate_api_settings(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        state: ApiState = app.state.api
        try:
            async with runtime_factory(settings.application) as runtime:
                state.runtime = runtime
                state.ready = True
                try:
                    yield
                finally:
                    state.ready = False
        finally:
            state.runtime = None

    app = FastAPI(
        title="Jung Local Therapist API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
    )
    app.state.api = ApiState()

    _register_exception_handlers(app)
    app.add_middleware(RequestIdMiddleware)

    if settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.allowed_origins),
            allow_credentials=False,
            allow_methods=["GET", "PUT", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "X-Request-ID"],
            expose_headers=["X-Request-ID"],
        )

    app.include_router(router)
    return app


def cli() -> None:
    import uvicorn

    from jung.api.settings import load_api_settings, validate_bind_host

    settings = load_api_settings()
    validate_bind_host(settings)
    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )
