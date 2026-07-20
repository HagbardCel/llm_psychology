"""Environment-backed settings for the /api/v1 HTTP server."""

from __future__ import annotations

import ipaddress
import math
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from jung._env import parse_bool, parse_positive_finite_float
from jung.config import ApplicationSettings, load_application_settings

_VALID_LOG_LEVELS = frozenset(
    {"critical", "error", "warning", "info", "debug", "trace"}
)


@dataclass(frozen=True, slots=True)
class ApiSettings:
    application: ApplicationSettings
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "info"
    allowed_origins: tuple[str, ...] = ()
    allow_remote_bind: bool = False
    websocket_send_timeout: float = 5.0
    websocket_close_timeout: float = 2.0


def _parse_origins(raw: str | None) -> tuple[str, ...]:
    if raw is None or not raw.strip():
        return ()
    origins: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        origin = part.strip()
        if not origin:
            continue
        if origin == "*":
            raise ValueError("wildcard CORS origin is not allowed")
        if origin in seen:
            continue
        seen.add(origin)
        origins.append(origin)
    return tuple(origins)


def _validate_positive_finite_number(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number greater than zero")

    try:
        finite = math.isfinite(float(value))
    except OverflowError:
        finite = False

    if not finite or value <= 0:
        raise ValueError(f"{name} must be a finite number greater than zero")


def validate_api_settings(settings: ApiSettings) -> ApiSettings:
    host = settings.host.strip()
    if not host:
        raise ValueError("host must be non-empty")

    port = settings.port
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port must be an integer between 1 and 65535")

    _validate_positive_finite_number(
        "websocket_send_timeout",
        settings.websocket_send_timeout,
    )
    _validate_positive_finite_number(
        "websocket_close_timeout",
        settings.websocket_close_timeout,
    )

    log_level = settings.log_level.strip().lower()
    if log_level not in _VALID_LOG_LEVELS:
        raise ValueError(f"invalid log level: {settings.log_level!r}")

    origins: list[str] = []
    seen: set[str] = set()
    for origin in settings.allowed_origins:
        trimmed = origin.strip()
        if not trimmed:
            raise ValueError("empty CORS origin entries are not allowed")
        if trimmed == "*":
            raise ValueError("wildcard CORS origin is not allowed")
        if trimmed in seen:
            continue
        seen.add(trimmed)
        origins.append(trimmed)

    return ApiSettings(
        application=settings.application,
        host=host,
        port=settings.port,
        log_level=log_level,
        allowed_origins=tuple(origins),
        allow_remote_bind=settings.allow_remote_bind,
        websocket_send_timeout=settings.websocket_send_timeout,
        websocket_close_timeout=settings.websocket_close_timeout,
    )


def validate_bind_host(settings: ApiSettings) -> None:
    host = settings.host.strip()
    if host == "localhost":
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    if settings.allow_remote_bind:
        return
    raise ValueError(
        "JUNG_API_HOST must be a loopback address unless "
        "JUNG_API_ALLOW_REMOTE_BIND=true. The API has no authentication or "
        "transport encryption."
    )


def load_api_settings() -> ApiSettings:
    load_dotenv()
    data_dir = os.environ.get("JUNG_DATA_DIR", "./data").strip() or "./data"
    database_path = Path(data_dir) / "jung.db"

    host = os.environ.get("JUNG_API_HOST", "127.0.0.1")
    port_raw = os.environ.get("JUNG_API_PORT", "8000")
    log_level = os.environ.get("JUNG_API_LOG_LEVEL", "info")
    origins = _parse_origins(os.environ.get("JUNG_API_ALLOWED_ORIGINS"))
    allow_remote_bind = parse_bool(
        "JUNG_API_ALLOW_REMOTE_BIND",
        os.environ.get("JUNG_API_ALLOW_REMOTE_BIND"),
        default=False,
    )
    websocket_send_timeout = parse_positive_finite_float(
        "JUNG_WS_SEND_TIMEOUT",
        os.environ.get("JUNG_WS_SEND_TIMEOUT"),
        default=5.0,
    )
    websocket_close_timeout = parse_positive_finite_float(
        "JUNG_WS_CLOSE_TIMEOUT",
        os.environ.get("JUNG_WS_CLOSE_TIMEOUT"),
        default=2.0,
    )

    try:
        port = int(port_raw)
    except ValueError as exc:
        raise ValueError(f"invalid JUNG_API_PORT: {port_raw!r}") from exc

    settings = ApiSettings(
        application=load_application_settings(
            os.environ,
            database_path=database_path,
        ),
        host=host,
        port=port,
        log_level=log_level,
        allowed_origins=origins,
        allow_remote_bind=allow_remote_bind,
        websocket_send_timeout=websocket_send_timeout,
        websocket_close_timeout=websocket_close_timeout,
    )
    return validate_api_settings(settings)
