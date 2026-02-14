"""Generate WebSocket protocol constants from schemas/ws_protocol.json."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "schemas" / "ws_protocol.json"
BACKEND_PATH = ROOT / "src" / "psychoanalyst_app" / "utils" / "ws_protocol.py"
CONSOLE_PATH = ROOT / "console-ui" / "src" / "websocket_protocol.py"
FRONTEND_PATH = ROOT / "frontend" / "src" / "types" / "ws_protocol.generated.ts"

DEFAULT_CONNECTION_STATES = [
    "connecting",
    "connected",
    "disconnected",
    "reconnecting",
    "error",
]
DEFAULT_ERROR_CODES = [
    "invalid_message_format",
    "missing_required_field",
    "session_not_found",
    "internal_error",
    "rate_limit_exceeded",
]


def _constant_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value).upper()


def _load_spec() -> tuple[str, list[str], list[str], list[str], list[str]]:
    data = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    version = data.get("version")
    message_types = data.get("message_types") or {}
    client_types = message_types.get("client_to_server") or []
    server_types = message_types.get("server_to_client") or []
    connection_states = data.get("connection_states") or DEFAULT_CONNECTION_STATES
    error_codes = data.get("error_codes") or DEFAULT_ERROR_CODES
    if not version or not client_types or not server_types:
        raise ValueError("ws_protocol.json must include version and message_types arrays")
    return (
        version,
        list(client_types),
        list(server_types),
        list(connection_states),
        list(error_codes),
    )


def _render_python(version: str, client_types: list[str], server_types: list[str]) -> str:
    lines = [
        '"""Auto-generated from schemas/ws_protocol.json. Do not edit by hand."""',
        "",
        "from typing import Final",
        "",
        f'WS_PROTOCOL_VERSION: Final[str] = "{version}"',
        "",
        "",
        "class ClientMessageTypes:",
        '    """Message types sent from client to server."""',
        "",
    ]
    for message_type in client_types:
        lines.append(
            f'    {_constant_name(message_type)}: Final[str] = "{message_type}"'
        )
    lines.extend(
        [
            "",
            "",
            "class ServerMessageTypes:",
            '    """Message types sent from server to client."""',
            "",
        ]
    )
    for message_type in server_types:
        lines.append(
            f'    {_constant_name(message_type)}: Final[str] = "{message_type}"'
        )
    lines.append("")
    return "\n".join(lines)


def _render_console(
    version: str,
    client_types: list[str],
    server_types: list[str],
    connection_states: list[str],
    error_codes: list[str],
) -> str:
    lines = [
        '"""',
        "WebSocket Protocol Constants for Console Client.",
        "",
        "AUTO-GENERATED from schemas/ws_protocol.json. Do not edit by hand.",
        '"""',
        "",
        "from typing import Final",
        "",
        "# Protocol Version",
        f'WS_PROTOCOL_VERSION: Final[str] = "{version}"',
        "",
        "",
        "# Client -> Server Message Types",
        "class ClientMessageTypes:",
        '    """Message types sent from client to server."""',
        "",
    ]
    for message_type in client_types:
        lines.append(
            f'    {_constant_name(message_type)}: Final[str] = "{message_type}"'
        )
    lines.extend(
        [
            "",
            "",
            "# Server -> Client Message Types",
            "class ServerMessageTypes:",
            '    """Message types sent from server to client."""',
            "",
        ]
    )
    for message_type in server_types:
        lines.append(
            f'    {_constant_name(message_type)}: Final[str] = "{message_type}"'
        )
    lines.extend(
        [
            "",
            "",
            "# Connection States",
            "class ConnectionStates:",
            '    """WebSocket connection states."""',
            "",
        ]
    )
    for state in connection_states:
        lines.append(f'    {_constant_name(state)}: Final[str] = "{state}"')
    lines.extend(
        [
            "",
            "",
            "# Error Codes",
            "class ErrorCodes:",
            '    """WebSocket error codes matching backend implementation."""',
            "",
        ]
    )
    for code in error_codes:
        lines.append(f'    {_constant_name(code)}: Final[str] = "{code}"')
    lines.append("")
    return "\n".join(lines)


def _render_typescript(
    version: str,
    client_types: list[str],
    server_types: list[str],
    connection_states: list[str],
    error_codes: list[str],
) -> str:
    lines = [
        "// Auto-generated from schemas/ws_protocol.json. Do not edit by hand.",
        "",
        f"export const WS_PROTOCOL_VERSION = '{version}' as const;",
        "",
        "export const WS_MESSAGE_TYPES = {",
    ]
    for message_type in client_types + server_types:
        lines.append(f"  {_constant_name(message_type)}: '{message_type}',")
    lines.extend(
        [
            "} as const;",
            "",
            "export type WSMessageType = typeof WS_MESSAGE_TYPES[keyof typeof WS_MESSAGE_TYPES];",
            "",
            "export const WS_CONNECTION_STATES = {",
        ]
    )
    for state in connection_states:
        lines.append(f"  {_constant_name(state)}: '{state}',")
    lines.extend(
        [
            "} as const;",
            "",
            "export type WSConnectionState = typeof WS_CONNECTION_STATES[keyof typeof WS_CONNECTION_STATES];",
            "",
            "export const WS_ERROR_CODES = {",
        ]
    )
    for code in error_codes:
        lines.append(f"  {_constant_name(code)}: '{code}',")
    lines.extend(
        [
            "} as const;",
            "",
            "export type WSErrorCode = typeof WS_ERROR_CODES[keyof typeof WS_ERROR_CODES];",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    version, client_types, server_types, connection_states, error_codes = _load_spec()
    BACKEND_PATH.write_text(
        _render_python(version, client_types, server_types), encoding="utf-8"
    )
    CONSOLE_PATH.write_text(
        _render_console(
            version,
            client_types,
            server_types,
            connection_states,
            error_codes,
        ),
        encoding="utf-8",
    )
    FRONTEND_PATH.write_text(
        _render_typescript(
            version,
            client_types,
            server_types,
            connection_states,
            error_codes,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
