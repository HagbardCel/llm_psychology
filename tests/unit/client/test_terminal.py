"""Unit tests for the Jung console terminal adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from jung.api.contracts import ErrorResponse
from jung.client.api_client import JungApiError
from jung.client.console import (
    ConsoleChatFailed,
    ConsoleExitRequested,
    ConsoleOperationFailed,
    ConsoleUncertainDelivery,
    PromptSpec,
)
from jung.client.terminal import (
    HumanInputProvider,
    TerminalConsoleOutput,
    _async_cli,
    _build_parser,
    cli,
)


def test_build_parser_requires_api_url() -> None:
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_build_parser_accepts_transport_timeout() -> None:
    parser = _build_parser()
    args = parser.parse_args(
        ["--api-url", "http://localhost:8000", "--transport-timeout", "30"]
    )
    assert args.api_url == "http://localhost:8000"
    assert args.transport_timeout == 30.0


@pytest.mark.asyncio
async def test_human_input_provider_reads_line() -> None:
    provider = HumanInputProvider()
    with patch("sys.stdin.readline", return_value="hello\n"):
        result = await provider.read(PromptSpec(text="> "))
    assert result == "hello"


@pytest.mark.asyncio
async def test_human_input_provider_eof_raises() -> None:
    provider = HumanInputProvider()
    with patch("sys.stdin.readline", return_value=""):
        with pytest.raises(EOFError):
            await provider.read(PromptSpec(text="> "))


def test_terminal_output_assistant_stream_lifecycle(
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = TerminalConsoleOutput()
    output.begin_assistant_message()
    output.append_assistant_token("hi")
    output.finish_assistant_stream()
    captured = capsys.readouterr()
    assert "Therapist: hi" in captured.out.replace("\n", "")


def test_terminal_output_discard_partial_assistant_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = TerminalConsoleOutput()
    output.begin_assistant_message()
    output.append_assistant_token("partial")
    output.discard_partial_assistant_message()
    captured = capsys.readouterr()
    assert "partial" in captured.out
    output.begin_assistant_message()
    output.discard_partial_assistant_message()
    captured = capsys.readouterr()
    assert captured.out.endswith("\n")


def test_cli_delegates_through_asyncio_run() -> None:
    def fake_run(coro: object) -> int:
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return 7

    with patch("jung.client.terminal.asyncio.run", fake_run):
        assert cli() == 7


@pytest.mark.asyncio
async def test_async_cli_passes_transport_timeout_to_settings() -> None:
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    with (
        patch(
            "sys.argv",
            [
                "jung-console",
                "--api-url",
                "http://localhost:8000",
                "--transport-timeout",
                "12.5",
            ],
        ),
        patch(
            "jung.client.terminal.ClientSettings",
        ) as mock_settings,
        patch(
            "jung.client.terminal.JungApiClient",
            return_value=mock_client,
        ),
        patch(
            "jung.client.terminal.ConsoleApp.run",
            AsyncMock(side_effect=ConsoleExitRequested),
        ),
    ):
        mock_settings.return_value = MagicMock()
        assert await _async_cli() == 0
    mock_settings.assert_called_once_with(
        base_url="http://localhost:8000",
        transport_timeout=12.5,
    )


@pytest.mark.asyncio
async def test_async_cli_maps_exit_zero_on_console_exit() -> None:
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    with (
        patch("sys.argv", ["jung-console", "--api-url", "http://localhost:8000"]),
        patch(
            "jung.client.terminal.JungApiClient",
            return_value=mock_client,
        ),
        patch(
            "jung.client.terminal.ConsoleApp.run",
            AsyncMock(side_effect=ConsoleExitRequested),
        ),
    ):
        assert await _async_cli() == 0


@pytest.mark.asyncio
async def test_async_cli_maps_operation_failure_to_exit_one() -> None:
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    with (
        patch("sys.argv", ["jung-console", "--api-url", "http://localhost:8000"]),
        patch(
            "jung.client.terminal.JungApiClient",
            return_value=mock_client,
        ),
        patch(
            "jung.client.terminal.ConsoleApp.run",
            AsyncMock(side_effect=ConsoleOperationFailed()),
        ),
    ):
        assert await _async_cli() == 1


@pytest.mark.asyncio
async def test_async_cli_maps_chat_failure_to_exit_one() -> None:
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    with (
        patch("sys.argv", ["jung-console", "--api-url", "http://localhost:8000"]),
        patch(
            "jung.client.terminal.JungApiClient",
            return_value=mock_client,
        ),
        patch(
            "jung.client.terminal.ConsoleApp.run",
            AsyncMock(side_effect=ConsoleChatFailed()),
        ),
    ):
        assert await _async_cli() == 1


@pytest.mark.asyncio
async def test_async_cli_maps_uncertain_delivery_to_exit_two() -> None:
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    with (
        patch("sys.argv", ["jung-console", "--api-url", "http://localhost:8000"]),
        patch(
            "jung.client.terminal.JungApiClient",
            return_value=mock_client,
        ),
        patch(
            "jung.client.terminal.ConsoleApp.run",
            AsyncMock(side_effect=ConsoleUncertainDelivery()),
        ),
    ):
        assert await _async_cli() == 2


@pytest.mark.asyncio
async def test_async_cli_maps_jung_client_errors_to_exit_three(
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_id = uuid4()
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    with (
        patch("sys.argv", ["jung-console", "--api-url", "http://localhost:8000"]),
        patch(
            "jung.client.terminal.JungApiClient",
            return_value=mock_client,
        ),
        patch(
            "jung.client.terminal.ConsoleApp.run",
            AsyncMock(
                side_effect=JungApiError(
                    status=503,
                    error=ErrorResponse(
                        code="not_ready",
                        message="x",
                        request_id=request_id,
                        retryable=True,
                    ),
                )
            ),
        ),
    ):
        assert await _async_cli() == 3
    assert "Client error:" in capsys.readouterr().out
