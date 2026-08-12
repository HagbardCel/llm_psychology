"""Unit tests for the local foreground launcher orchestration."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jung.client.api_client import ClientSettings
from jung.config import JungSettings
from jung.local import cli, run_local
from tests.support.settings import make_test_settings


@pytest.mark.asyncio
async def test_run_local_starts_server_before_health_and_console() -> None:
    settings = make_test_settings()
    call_order: list[str] = []

    @asynccontextmanager
    async def fake_running_local_api(_settings):
        call_order.append("server_enter")
        yield "http://127.0.0.1:54321"
        call_order.append("server_exit")

    mock_client = MagicMock()
    mock_client.get_health = AsyncMock(side_effect=lambda: call_order.append("health"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("jung.local.running_local_api", fake_running_local_api),
        patch("jung.local.JungApiClient", return_value=mock_client),
        patch(
            "jung.local.run_console",
            AsyncMock(
                side_effect=lambda *_args, **_kwargs: call_order.append("console") or 0
            ),
        ),
    ):
        assert await run_local(settings) == 0

    assert call_order == [
        "server_enter",
        "health",
        "console",
        "server_exit",
    ]


@pytest.mark.asyncio
async def test_run_local_propagates_yielded_url_to_client_and_console() -> None:
    settings = make_test_settings()
    captured: dict[str, object] = {}

    @asynccontextmanager
    async def fake_running_local_api(_settings):
        yield "http://127.0.0.1:9999"

    mock_client = MagicMock()
    mock_client.get_health = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    def capture_client_settings(*args, **kwargs):
        captured["client_settings"] = kwargs
        return ClientSettings(**kwargs)

    async def capture_run_console(client_settings):
        captured["console_settings"] = client_settings
        return 0

    with (
        patch("jung.local.running_local_api", fake_running_local_api),
        patch("jung.local.ClientSettings", side_effect=capture_client_settings),
        patch("jung.local.JungApiClient", return_value=mock_client),
        patch("jung.local.run_console", AsyncMock(side_effect=capture_run_console)),
    ):
        await run_local(settings)

    assert captured["client_settings"] == {"base_url": "http://127.0.0.1:9999"}
    assert captured["console_settings"].base_url == "http://127.0.0.1:9999"


@pytest.mark.asyncio
async def test_run_local_health_failure_prevents_console_start() -> None:
    settings = make_test_settings()

    @asynccontextmanager
    async def fake_running_local_api(_settings):
        yield "http://127.0.0.1:54321"

    mock_client = MagicMock()
    mock_client.get_health = AsyncMock(side_effect=RuntimeError("health failed"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("jung.local.running_local_api", fake_running_local_api),
        patch("jung.local.JungApiClient", return_value=mock_client),
        patch("jung.local.run_console", AsyncMock()) as run_console,
    ):
        with pytest.raises(RuntimeError, match="health failed"):
            await run_local(settings)

    run_console.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_local_returns_console_exit_code() -> None:
    settings = make_test_settings()

    @asynccontextmanager
    async def fake_running_local_api(_settings):
        yield "http://127.0.0.1:54321"

    mock_client = MagicMock()
    mock_client.get_health = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("jung.local.running_local_api", fake_running_local_api),
        patch("jung.local.JungApiClient", return_value=mock_client),
        patch("jung.local.run_console", AsyncMock(return_value=1)),
    ):
        assert await run_local(settings) == 1


@pytest.mark.asyncio
async def test_run_local_exits_server_context_on_console_failure() -> None:
    settings = make_test_settings()
    exited = False

    @asynccontextmanager
    async def fake_running_local_api(_settings):
        try:
            yield "http://127.0.0.1:54321"
        finally:
            nonlocal exited
            exited = True

    mock_client = MagicMock()
    mock_client.get_health = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("jung.local.running_local_api", fake_running_local_api),
        patch("jung.local.JungApiClient", return_value=mock_client),
        patch("jung.local.run_console", AsyncMock(side_effect=RuntimeError("console"))),
    ):
        with pytest.raises(RuntimeError, match="console"):
            await run_local(settings)

    assert exited is True


def test_cli_maps_keyboard_interrupt_to_exit_130() -> None:
    with (
        patch("jung.local.load_settings", return_value=MagicMock(spec=JungSettings)),
        patch("jung.local.asyncio.run", side_effect=KeyboardInterrupt),
    ):
        assert cli() == 130
