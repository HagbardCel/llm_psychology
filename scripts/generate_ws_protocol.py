"""Generate WebSocket protocol constants from schemas/ws_protocol.json."""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "schemas" / "ws_protocol.json"
BACKEND_PATH = ROOT / "src" / "psychoanalyst_app" / "utils" / "ws_protocol.py"
CONSOLE_PATH = ROOT / "console-ui" / "src" / "websocket_protocol.py"

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
        raise ValueError(
            "ws_protocol.json must include version and message_types arrays"
        )
    return (
        version,
        list(client_types),
        list(server_types),
        list(connection_states),
        list(error_codes),
    )


def _render_python(
    version: str, client_types: list[str], server_types: list[str]
) -> str:
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


def _render_all() -> dict[Path, str]:
    version, client_types, server_types, connection_states, error_codes = _load_spec()
    return {
        BACKEND_PATH: _render_python(version, client_types, server_types),
        CONSOLE_PATH: _render_console(
            version,
            client_types,
            server_types,
            connection_states,
            error_codes,
        ),
    }


def _check_generated_files(rendered: dict[Path, str]) -> int:
    drifted = False
    for path, expected in rendered.items():
        if not path.exists():
            print(f"✗ Missing generated WebSocket protocol file: {path}")
            drifted = True
            continue

        actual = path.read_text(encoding="utf-8")
        if actual == expected:
            continue

        drifted = True
        print(f"✗ WebSocket protocol file is out of date: {path}")
        diff = difflib.unified_diff(
            actual.splitlines(),
            expected.splitlines(),
            fromfile=f"{path} (committed)",
            tofile=f"{path} (generated)",
            lineterm="",
        )
        print("\n".join(diff))

    if drifted:
        print(
            "\nRun `docker compose run --rm api "
            "python scripts/generate_ws_protocol.py`."
        )
        return 1

    print("✓ Generated WebSocket protocol files are up to date")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate WebSocket protocol constants from schemas/ws_protocol.json."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate generated files without rewriting them.",
    )
    args = parser.parse_args(argv)

    rendered = _render_all()
    if args.check:
        return _check_generated_files(rendered)

    for path, content in rendered.items():
        path.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
