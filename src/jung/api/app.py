"""FastAPI application factory, lifespan, and HTTP middleware for /api/v1."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from jung.api.deps import (
    ApiNotReady,
    ApiRuntime,
    build_error_response,
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
from jung.api.websocket import router as websocket_router
from jung.composition import application_context
from jung.config import JungSettings, load_settings, validate_bind_host
from jung.diagnostics import diagnostic_context
from jung.domain.errors import DomainError

logger = logging.getLogger(__name__)

RuntimeFactory = Callable[
    [JungSettings],
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


def _log_safe_exception(
    message: str,
    *,
    request_id: UUID,
    exc: Exception,
) -> None:
    logger.error(
        message,
        extra={
            "request_id": str(request_id),
            "exception_type": type(exc).__name__,
        },
    )


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

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):
        request_id = _request_id_from_request(request)
        status = http_status_for_exception(exc)

        if status >= 500:
            _log_safe_exception(
                "internal domain error",
                request_id=request_id,
                exc=exc,
            )

        body = to_error_response(exc, request_id=request_id)
        return build_error_response(
            status=status,
            body=body,
        )


def _log_http_completion(
    request: Request,
    response: Response,
    *,
    request_id: UUID,
    started: float,
) -> None:
    logger.info(
        "HTTP request completed",
        extra={
            "request_id": str(request_id),
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round((time.monotonic() - started) * 1000, 1),
        },
    )


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        started = time.monotonic()
        request_id = new_request_id()

        try:
            header = request.headers.get("X-Request-ID")
            request_id = parse_request_id_header(header)
        except RequestIdError:
            response = build_error_response(
                status=422,
                body=validation_error_response(request_id=request_id),
            )
        else:
            request.state.request_id = request_id
            try:
                with diagnostic_context(request_id=str(request_id)):
                    response = await call_next(request)
            except Exception as exc:
                _log_safe_exception(
                    "unhandled API error",
                    request_id=request_id,
                    exc=exc,
                )
                response = build_error_response(
                    status=500,
                    body=to_error_response(exc, request_id=request_id),
                )

        response.headers["X-Request-ID"] = str(request_id)
        _log_http_completion(
            request,
            response,
            request_id=request_id,
            started=started,
        )
        return response


def create_app(
    settings: JungSettings,
    *,
    runtime_factory: RuntimeFactory = application_context,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        state: ApiState = app.state.api
        runtime_exited = False

        try:
            async with runtime_factory(settings) as runtime:
                state.runtime = runtime
                state.ready = True
                logger.info("api_ready")

                try:
                    yield
                finally:
                    state.ready = False

            runtime_exited = True
        finally:
            state.runtime = None
            if runtime_exited:
                logger.info("api_shutdown_complete")

    app = FastAPI(
        title="Jung Local Therapist API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
    )
    app.state.api = ApiState()
    app.state.api_settings = settings

    _register_exception_handlers(app)
    app.add_middleware(RequestIdMiddleware)

    if settings.api_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.api_allowed_origins),
            allow_credentials=False,
            allow_methods=["GET", "PUT", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "X-Request-ID"],
            expose_headers=["X-Request-ID"],
        )

    app.include_router(router)
    app.include_router(websocket_router)
    return app


def _uvicorn_log_config_with_jung(log_level: str) -> dict[str, Any]:
    """Extend Uvicorn's default logging config with the `jung` logger.

    Uvicorn's `log_level` only updates its own loggers (uvicorn.*), so we
    explicitly configure `jung` at the same level.
    """
    from copy import deepcopy

    from uvicorn.config import LOG_LEVELS, LOGGING_CONFIG

    log_config = deepcopy(LOGGING_CONFIG)
    log_config["loggers"]["jung"] = {
        "handlers": ["default"],
        "level": LOG_LEVELS[log_level],
        "propagate": False,
    }
    return log_config


def cli() -> None:
    import uvicorn

    settings = load_settings()
    validate_bind_host(settings)
    app = create_app(settings)

    log_level = settings.api_log_level.value
    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        log_level=log_level,
        log_config=_uvicorn_log_config_with_jung(log_level),
        access_log=False,
    )


if __name__ == "__main__":
    cli()
