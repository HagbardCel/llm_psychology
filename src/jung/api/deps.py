"""Shared HTTP dependencies and response helpers for /api/v1."""

from __future__ import annotations

from typing import Protocol

from fastapi import Request
from starlette.responses import JSONResponse

from jung.api.contracts import ErrorResponse
from jung.application import TherapyApplication
from jung.events import EventStream


class ApiRuntime(Protocol):
    application: TherapyApplication


class WebSocketRuntime(ApiRuntime, Protocol):
    events: EventStream


class ApiNotReady(RuntimeError):
    pass


def get_runtime_from_state(state: object) -> ApiRuntime:
    if not getattr(state, "ready", False) or getattr(state, "runtime", None) is None:
        raise ApiNotReady
    return state.runtime  # type: ignore[return-value]


def get_runtime(request: Request) -> ApiRuntime:
    return get_runtime_from_state(request.app.state.api)


def get_websocket_runtime(state: object) -> WebSocketRuntime:
    runtime = get_runtime_from_state(state)
    if not hasattr(runtime, "events"):
        raise ApiNotReady
    return runtime  # type: ignore[return-value]


def build_error_response(*, status: int, body: ErrorResponse) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=body.model_dump(mode="json"),
        headers={"X-Request-ID": str(body.request_id)},
    )
