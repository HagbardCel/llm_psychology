"""Shared fixtures for jung HTTP API integration tests."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
import uvicorn
from httpx import ASGITransport

from jung.api.app import create_app
from jung.api.settings import ApiSettings
from jung.composition import Settings as CompositionSettings
from jung.composition import build_settings
from jung.llm.fake import FakeLLM
from jung.persistence.sqlite_store import SQLiteStore
from tests.integration.jung.application_fixtures import build_test_application


@pytest.fixture
def api_settings(store_path: Path) -> ApiSettings:
    return ApiSettings(
        application=build_settings(
            database_path=store_path,
            llm_base_url="http://fake.test/v1",
            llm_api_key="fake",
            default_model="fake",
        ),
        allowed_origins=("http://frontend.test",),
    )


def _runtime_factory(
    store: SQLiteStore,
    fake_llm: FakeLLM,
) -> Callable[[CompositionSettings], Any]:
    @asynccontextmanager
    async def factory(
        _settings: CompositionSettings,
    ) -> AsyncIterator[object]:
        async with build_test_application(store, fake_llm) as runtime:
            yield runtime

    return factory


@pytest.fixture
def api_app(store: SQLiteStore, fake_llm: FakeLLM, api_settings: ApiSettings):
    return create_app(
        api_settings,
        runtime_factory=_runtime_factory(store, fake_llm),
    )


@pytest_asyncio.fixture
async def api_client(api_app) -> AsyncIterator[httpx.AsyncClient]:
    transport = ASGITransport(app=api_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def started_api_client(api_app) -> AsyncIterator[httpx.AsyncClient]:
    transport = ASGITransport(app=api_app, raise_app_exceptions=False)
    async with api_app.router.lifespan_context(api_app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            yield client


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM([])


@pytest_asyncio.fixture
async def uvicorn_api_urls(
    api_app,
) -> AsyncIterator[tuple[str, str]]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    config = uvicorn.Config(
        app=api_app,
        host="127.0.0.1",
        port=port,
        log_level="error",
    )
    server = uvicorn.Server(config)
    serve_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)

    http_base = f"http://127.0.0.1:{port}"
    ws_url = f"ws://127.0.0.1:{port}/api/v1/chat"
    try:
        yield http_base, ws_url
    finally:
        server.should_exit = True
        await serve_task
