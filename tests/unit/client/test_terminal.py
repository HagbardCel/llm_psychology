"""Unit tests for the Jung console terminal adapter."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from jung.api.contracts import ErrorResponse
from jung.client.api_client import JungApiError
from jung.client.console import (
    ConsoleExitRequested,
    ConsoleOperationFailed,
    PromptSpec,
)
from jung.client.terminal import (
    HumanInputProvider,
    TerminalConsoleOutput,
    _async_cli,
    _build_parser,
    cli,
    run_console,
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
    with patch(
        "jung.client.terminal._read_stdin_line_cancellable",
        AsyncMock(return_value="hello"),
    ):
        result = await provider.read(PromptSpec(text="> "))
    assert result == "hello"


@pytest.mark.asyncio
async def test_human_input_provider_eof_raises() -> None:
    provider = HumanInputProvider()
    with patch(
        "jung.client.terminal._read_stdin_line_cancellable",
        AsyncMock(side_effect=EOFError()),
    ):
        with pytest.raises(EOFError):
            await provider.read(PromptSpec(text="> "))


@pytest.mark.asyncio
async def test_human_input_provider_cancel_pending_read_completes_promptly() -> None:
    provider = HumanInputProvider()

    async def hang() -> str:
        await asyncio.Event().wait()
        return "never"

    with patch(
        "jung.client.terminal._read_stdin_line_cancellable",
        side_effect=hang,
    ):
        read_task = asyncio.create_task(provider.read(PromptSpec(text="> ")))
        await asyncio.sleep(0)
        read_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(read_task, timeout=0.5)


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


def test_cli_runs_async_entrypoint_and_returns_exit_code() -> None:
    with patch(
        "jung.client.terminal._async_cli",
        AsyncMock(return_value=7),
    ) as async_cli:
        assert cli() == 7

    async_cli.assert_awaited_once_with()


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


@pytest.mark.asyncio
async def test_run_console_maps_exit_codes() -> None:
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    settings = MagicMock()

    with patch("jung.client.terminal.JungApiClient", return_value=mock_client):
        with patch(
            "jung.client.terminal.ConsoleApp.run",
            AsyncMock(side_effect=ConsoleExitRequested),
        ):
            assert await run_console(settings) == 0

        with patch(
            "jung.client.terminal.ConsoleApp.run",
            AsyncMock(side_effect=ConsoleOperationFailed()),
        ):
            assert await run_console(settings) == 1

        with patch(
            "jung.client.terminal.ConsoleApp.run",
            AsyncMock(
                side_effect=JungApiError(
                    status=503,
                    error=ErrorResponse(
                        code="not_ready",
                        message="x",
                        request_id=uuid4(),
                        retryable=True,
                    ),
                )
            ),
        ):
            output = TerminalConsoleOutput()
            assert await run_console(settings, output=output) == 3


@pytest.mark.asyncio
async def test_async_cli_delegates_to_run_console() -> None:
    with (
        patch("sys.argv", ["jung-console", "--api-url", "http://localhost:8000"]),
        patch(
            "jung.client.terminal.run_console",
            AsyncMock(return_value=0),
        ) as run_console_mock,
    ):
        assert await _async_cli() == 0

    run_console_mock.assert_awaited_once()
    settings = run_console_mock.await_args.args[0]
    assert settings.base_url == "http://localhost:8000"
