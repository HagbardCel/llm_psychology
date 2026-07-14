"""Environment-backed settings for the /api/v1 HTTP server."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from jung.composition import Settings as CompositionSettings
from jung.composition import build_settings

_VALID_LOG_LEVELS = frozenset(
    {"critical", "error", "warning", "info", "debug", "trace"}
)


@dataclass(frozen=True, slots=True)
class ApiSettings:
    application: CompositionSettings
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "info"
    allowed_origins: tuple[str, ...] = ()
    allow_remote_bind: bool = False


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


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


def validate_api_settings(settings: ApiSettings) -> ApiSettings:
    host = settings.host.strip()
    if not host:
        raise ValueError("host must be non-empty")

    if not 1 <= settings.port <= 65535:
        raise ValueError("port must be between 1 and 65535")

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
        "JUNG_API_ALLOW_REMOTE_BIND=true. Phase 5 has no authentication or "
        "transport encryption."
    )


def load_api_settings() -> ApiSettings:
    load_dotenv()
    data_dir = os.environ.get("JUNG_DATA_DIR", "./data").strip() or "./data"
    database_path = Path(data_dir) / "jung.db"

    llm_base_url = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8080/v1").strip()
    if not llm_base_url:
        raise ValueError("LLM_BASE_URL must be non-empty")

    llm_api_key = os.environ.get("LLM_API_KEY", "")
    default_model = os.environ.get("MODEL_NAME", "local-model").strip()
    if not default_model:
        raise ValueError("MODEL_NAME must be non-empty")

    host = os.environ.get("JUNG_API_HOST", "127.0.0.1")
    port_raw = os.environ.get("JUNG_API_PORT", "8000")
    log_level = os.environ.get("JUNG_API_LOG_LEVEL", "info")
    origins = _parse_origins(os.environ.get("JUNG_API_ALLOWED_ORIGINS"))
    allow_remote_bind = _parse_bool(
        os.environ.get("JUNG_API_ALLOW_REMOTE_BIND", "false")
    )

    try:
        port = int(port_raw)
    except ValueError as exc:
        raise ValueError(f"invalid JUNG_API_PORT: {port_raw!r}") from exc

    settings = ApiSettings(
        application=build_settings(
            database_path=database_path,
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
            default_model=default_model,
        ),
        host=host,
        port=port,
        log_level=log_level,
        allowed_origins=origins,
        allow_remote_bind=allow_remote_bind,
    )
    return validate_api_settings(settings)
