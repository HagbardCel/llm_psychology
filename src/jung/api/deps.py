"""Shared HTTP dependencies and response helpers for /api/v1."""

from __future__ import annotations

from fastapi import Request
from starlette.responses import JSONResponse

from jung.api.contracts import ErrorResponse
from jung.application import TherapyApplication


class ApiNotReady(RuntimeError):
    pass


def get_application_from_state(state: object) -> TherapyApplication:
    application = getattr(state, "application", None)
    if application is None:
        raise ApiNotReady
    return application


def get_application(request: Request) -> TherapyApplication:
    return get_application_from_state(request.app.state.api)


def get_websocket_application(state: object) -> TherapyApplication:
    return get_application_from_state(state)


def build_error_response(*, status: int, body: ErrorResponse) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=body.model_dump(mode="json"),
        headers={"X-Request-ID": str(body.request_id)},
    )
