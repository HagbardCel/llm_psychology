"""Integration tests for managed local Uvicorn server lifecycle."""

from __future__ import annotations

import asyncio
import socket
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from uvicorn.server import STARTUP_FAILURE

from jung.api.server import running_local_api
from jung.client.api_client import ClientSettings, JungApiClient
from jung.config import JungSettings
from tests.support.api import application_factory


class _FactoryExitProbe:
    exited = False


def _probe_application_factory(store, fake_llm):
    base_factory = application_factory(store, fake_llm)

    @asynccontextmanager
    async def factory(settings: JungSettings):
        async with base_factory(settings) as application:
            try:
                yield application
            finally:
                _FactoryExitProbe.exited = True

    return factory


def _gated_application_factory(
    store,
    fake_llm,
    *,
    teardown_started: asyncio.Event,
    release_teardown: asyncio.Event,
    teardown_completed: asyncio.Event,
):
    base_factory = application_factory(store, fake_llm)

    @asynccontextmanager
    async def factory(settings: JungSettings):
        try:
            async with base_factory(settings) as application:
                try:
                    yield application
                finally:
                    teardown_started.set()
                    _FactoryExitProbe.exited = True
                    await release_teardown.wait()
        finally:
            teardown_completed.set()

    return factory


async def _connection_refused(base_url: str) -> bool:
    host, port_text = base_url.removeprefix("http://").split(":", 1)
    port = int(port_text)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.2)
    try:
        result = sock.connect_ex((host, port))
    finally:
        sock.close()
    return result != 0


@pytest.mark.asyncio
async def test_running_local_api_serves_health_over_tcp(
    store,
    fake_llm,
    api_settings: JungSettings,
) -> None:
    _FactoryExitProbe.exited = False

    async with running_local_api(
        api_settings,
        application_factory=_probe_application_factory(store, fake_llm),
    ) as base_url:
        async with JungApiClient(ClientSettings(base_url=base_url)) as client:
            health = await client.get_health()

    assert health.status == "healthy"
    assert _FactoryExitProbe.exited is True
    assert await _connection_refused(base_url) is True


@pytest.mark.asyncio
async def test_running_local_api_lifespan_startup_failure_does_not_yield(
    store,
    fake_llm,
    api_settings: JungSettings,
) -> None:
    @asynccontextmanager
    async def failing_startup_factory(_settings: JungSettings):
        raise RuntimeError("lifespan startup failed")
        yield  # pragma: no cover

    with pytest.raises(RuntimeError, match="managed API startup"):
        async with running_local_api(
            api_settings,
            application_factory=failing_startup_factory,
        ):
            pytest.fail("running_local_api should not yield after startup failure")


@pytest.mark.asyncio
async def test_running_local_api_normalizes_uvicorn_startup_systemexit(
    store,
    fake_llm,
    api_settings: JungSettings,
) -> None:
    async def fake_serve(self, sockets=None):
        raise SystemExit(STARTUP_FAILURE)

    with patch("uvicorn.Server.serve", new=fake_serve):
        with pytest.raises(RuntimeError, match="managed API startup"):
            async with running_local_api(
                api_settings,
                application_factory=_probe_application_factory(store, fake_llm),
            ):
                pytest.fail("running_local_api should not yield on startup failure")


@pytest.mark.asyncio
async def test_running_local_api_body_exception_survives_cleanup(
    store,
    fake_llm,
    api_settings: JungSettings,
) -> None:
    _FactoryExitProbe.exited = False

    with pytest.raises(ValueError, match="body failed"):
        async with running_local_api(
            api_settings,
            application_factory=_probe_application_factory(store, fake_llm),
        ) as base_url:
            assert base_url.startswith("http://127.0.0.1:")
            raise ValueError("body failed")

    assert _FactoryExitProbe.exited is True


@pytest.mark.asyncio
async def test_running_local_api_body_cancellation_survives_cleanup(
    store,
    fake_llm,
    api_settings: JungSettings,
) -> None:
    _FactoryExitProbe.exited = False

    with pytest.raises(asyncio.CancelledError):
        async with running_local_api(
            api_settings,
            application_factory=_probe_application_factory(store, fake_llm),
        ):
            raise asyncio.CancelledError()

    assert _FactoryExitProbe.exited is True


@pytest.mark.asyncio
async def test_running_local_api_body_exception_survives_cleanup_cancellation(
    store,
    fake_llm,
    api_settings: JungSettings,
) -> None:
    _FactoryExitProbe.exited = False
    teardown_started = asyncio.Event()
    release_teardown = asyncio.Event()
    teardown_completed = asyncio.Event()
    base_url_holder: list[str] = []

    async def runner() -> None:
        async with running_local_api(
            api_settings,
            application_factory=_gated_application_factory(
                store,
                fake_llm,
                teardown_started=teardown_started,
                release_teardown=release_teardown,
                teardown_completed=teardown_completed,
            ),
        ) as base_url:
            base_url_holder.append(base_url)
            raise ValueError("primary")

    runner_task = asyncio.create_task(runner())
    await teardown_started.wait()
    runner_task.cancel()
    release_teardown.set()

    with pytest.raises(ValueError, match="primary"):
        await runner_task

    assert teardown_completed.is_set()
    assert _FactoryExitProbe.exited is True
    assert base_url_holder
    assert await _connection_refused(base_url_holder[0]) is True


@pytest.mark.asyncio
async def test_running_local_api_repeated_cancellation_during_real_teardown(
    store,
    fake_llm,
    api_settings: JungSettings,
) -> None:
    _FactoryExitProbe.exited = False
    body_started = asyncio.Event()
    body_block = asyncio.Event()
    teardown_started = asyncio.Event()
    release_teardown = asyncio.Event()
    teardown_completed = asyncio.Event()
    base_url_holder: list[str] = []

    async def runner() -> None:
        async with running_local_api(
            api_settings,
            application_factory=_gated_application_factory(
                store,
                fake_llm,
                teardown_started=teardown_started,
                release_teardown=release_teardown,
                teardown_completed=teardown_completed,
            ),
        ) as base_url:
            base_url_holder.append(base_url)
            body_started.set()
            await body_block.wait()

    runner_task = asyncio.create_task(runner())
    await body_started.wait()
    runner_task.cancel()
    await teardown_started.wait()
    runner_task.cancel()
    release_teardown.set()

    with pytest.raises(asyncio.CancelledError):
        await runner_task

    assert teardown_completed.is_set()
    assert _FactoryExitProbe.exited is True
    assert base_url_holder
    assert await _connection_refused(base_url_holder[0]) is True


@pytest.mark.asyncio
async def test_running_local_api_shutdown_failure_surfaces_without_primary(
    store,
    fake_llm,
    api_settings: JungSettings,
) -> None:
    async def failing_shutdown(_task: asyncio.Task[None]) -> RuntimeError:
        return RuntimeError("serve failed during cleanup")

    with patch(
        "jung.api.server._shutdown_owned_serve_task",
        side_effect=failing_shutdown,
    ):
        with pytest.raises(RuntimeError, match="serve failed during cleanup"):
            async with running_local_api(
                api_settings,
                application_factory=_probe_application_factory(store, fake_llm),
            ):
                pass


@pytest.mark.asyncio
async def test_running_local_api_primary_failure_wins_over_cleanup_failure(
    store,
    fake_llm,
    api_settings: JungSettings,
) -> None:
    async def failing_shutdown(_task: asyncio.Task[None]) -> RuntimeError:
        return RuntimeError("cleanup failed")

    with patch(
        "jung.api.server._shutdown_owned_serve_task",
        side_effect=failing_shutdown,
    ):
        with pytest.raises(ValueError, match="primary body"):
            async with running_local_api(
                api_settings,
                application_factory=_probe_application_factory(store, fake_llm),
            ):
                raise ValueError("primary body")
