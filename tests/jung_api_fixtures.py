"""Shared pytest fixtures for Jung API, client, and E2E tests."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import httpx
import pytest
import pytest_asyncio
import uvicorn
from fastapi import FastAPI
from httpx import ASGITransport

from jung.api.app import create_app
from jung.api.settings import ApiSettings
from jung.config import ApplicationSettings, build_settings
from jung.llm.fake import Expectation, FakeLLM
from jung.llm.gateway import ChatMessage, LLMTask, ModelPolicy
from jung.persistence.sqlite_store import SQLiteStore
from tests.integration.jung.application_fixtures import (
    TestApplicationRuntime,
    build_test_application,
)

T = TypeVar("T", bound=object)


class RecordingFakeLLM:
    """Test-only wrapper; records LLMTask at outermost client-facing entry only."""

    def __init__(self, delegate: FakeLLM) -> None:
        self._delegate = delegate
        self._recorded_tasks: list[LLMTask] = []

    @property
    def recorded_tasks(self) -> tuple[LLMTask, ...]:
        return tuple(self._recorded_tasks)

    async def generate_structured(
        self,
        messages: Sequence[ChatMessage],
        output_type: type[T],
        policy: ModelPolicy,
        validate_result: Callable[[T], T] | None = None,
    ) -> T:
        self._recorded_tasks.append(policy.task)
        return await self._delegate.generate_structured(
            messages=messages,
            output_type=output_type,
            policy=policy,
            validate_result=validate_result,
        )

    async def stream_text(
        self,
        messages: Sequence[ChatMessage],
        policy: ModelPolicy,
    ) -> AsyncIterator[str]:
        self._recorded_tasks.append(policy.task)
        async for chunk in self._delegate.stream_text(messages, policy):
            yield chunk

    def assert_exhausted(self) -> None:
        self._delegate.assert_exhausted()

    async def aclose(self) -> None:
        close = getattr(self._delegate, "aclose", None)
        if close is not None:
            await close()


class HoldingFakeLLM(FakeLLM):
    """FakeLLM delegate that holds after the first streamed chunk."""

    def __init__(
        self,
        expectations: Sequence[Expectation],
        *,
        release_event: asyncio.Event | None = None,
    ) -> None:
        super().__init__(expectations)
        self._release_event = release_event or asyncio.Event()
        self.first_chunk_emitted = asyncio.Event()

    def release(self) -> None:
        self._release_event.set()

    async def stream_text(
        self,
        messages: Sequence[ChatMessage],
        policy: ModelPolicy,
    ) -> AsyncIterator[str]:
        held = False
        async for chunk in super().stream_text(messages, policy):
            yield chunk
            if not held:
                held = True
                self.first_chunk_emitted.set()
                await self._release_event.wait()


@dataclass(frozen=True)
class TestApiApp:
    app: FastAPI
    fake_llm: RecordingFakeLLM
    store_path: Path


def create_test_api_app(
    *,
    store: SQLiteStore,
    fake_llm: RecordingFakeLLM,
    api_settings: ApiSettings | None = None,
) -> TestApiApp:
    settings = api_settings or ApiSettings(
        application=build_settings(
            database_path=store.database_path,
            llm_base_url="http://fake.test/v1",
            llm_api_key="fake",
            default_model="fake",
        ),
        allowed_origins=("http://frontend.test",),
    )
    app = create_app(
        settings,
        runtime_factory=runtime_factory(store, fake_llm),
    )
    return TestApiApp(
        app=app,
        fake_llm=fake_llm,
        store_path=store.database_path,
    )


@dataclass
class RuntimeProbe:
    runtime: TestApplicationRuntime | None = None


@pytest.fixture
def runtime_probe() -> RuntimeProbe:
    return RuntimeProbe()


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "jung-test.db"


@pytest.fixture
def store(store_path: Path) -> Iterator[SQLiteStore]:
    instance = SQLiteStore(store_path)
    instance.initialize()
    yield instance


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


def runtime_factory(
    store: SQLiteStore,
    fake_llm: FakeLLM | RecordingFakeLLM,
    runtime_probe: RuntimeProbe | None = None,
) -> Callable[[ApplicationSettings], Any]:
    @asynccontextmanager
    async def factory(
        _settings: ApplicationSettings,
    ) -> AsyncIterator[object]:
        async with build_test_application(store, fake_llm) as runtime:
            if runtime_probe is not None:
                runtime_probe.runtime = runtime
            try:
                yield runtime
            finally:
                if runtime_probe is not None:
                    runtime_probe.runtime = None

    return factory


@pytest.fixture
def api_app(
    store: SQLiteStore,
    fake_llm: FakeLLM,
    api_settings: ApiSettings,
    runtime_probe: RuntimeProbe,
):
    return create_app(
        api_settings,
        runtime_factory=runtime_factory(store, fake_llm, runtime_probe),
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
def fake_llm_expectations(request: pytest.FixtureRequest) -> tuple[Expectation, ...]:
    return getattr(request, "param", ())


@pytest.fixture
def fake_llm(fake_llm_expectations: tuple[Expectation, ...]) -> FakeLLM:
    return FakeLLM(fake_llm_expectations)


async def _wait_for_uvicorn_start(
    server: uvicorn.Server,
    serve_task: asyncio.Task[None],
    *,
    timeout: float,
) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while not server.started:
        if serve_task.done():
            await serve_task
            raise RuntimeError(
                "Uvicorn exited without an exception before reporting startup"
            )
        if asyncio.get_event_loop().time() >= deadline:
            raise TimeoutError("Uvicorn did not start within timeout")
        await asyncio.sleep(0.01)


@asynccontextmanager
async def run_uvicorn_api(api_app) -> AsyncIterator[tuple[str, str]]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]

    config = uvicorn.Config(
        app=api_app,
        host="127.0.0.1",
        port=port,
        log_level="error",
    )
    server = uvicorn.Server(config)
    serve_task = asyncio.create_task(server.serve(sockets=[sock]))

    http_base = f"http://127.0.0.1:{port}"
    ws_url = f"ws://127.0.0.1:{port}/api/v1/chat"

    try:
        await _wait_for_uvicorn_start(server, serve_task, timeout=5.0)
        yield http_base, ws_url
    finally:
        server.should_exit = True
        try:
            if serve_task.done():
                await asyncio.gather(serve_task, return_exceptions=True)
            else:
                try:
                    await asyncio.wait_for(serve_task, timeout=5.0)
                except TimeoutError:
                    await asyncio.gather(serve_task, return_exceptions=True)
        finally:
            sock.close()


@pytest_asyncio.fixture
async def uvicorn_api_urls(api_app) -> AsyncIterator[tuple[str, str]]:
    async with run_uvicorn_api(api_app) as urls:
        yield urls
