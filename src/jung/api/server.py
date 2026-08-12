"""Managed local Uvicorn server lifecycle for the foreground launcher."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from uvicorn.server import STARTUP_FAILURE

from jung._async_cleanup import drain_cancelled_task
from jung.api.app import ApplicationFactory, _uvicorn_log_config_with_jung, create_app
from jung.composition import application_context
from jung.config import JungSettings

_MANAGED_API_HOST = "127.0.0.1"


async def _wait_for_uvicorn_start(
    server: uvicorn.Server,
    serve_task: asyncio.Task[None],
) -> None:
    while not server.started:
        if serve_task.done():
            await serve_task
            raise RuntimeError(
                "Uvicorn exited without an exception before reporting startup"
            )
        await asyncio.sleep(0.01)


async def _shutdown_owned_serve_task(
    serve_task: asyncio.Task[None],
) -> BaseException | None:
    try:
        await asyncio.shield(serve_task)
    except asyncio.CancelledError:
        failure = await drain_cancelled_task(serve_task)
        if failure is not None and not isinstance(failure, asyncio.CancelledError):
            return failure
        raise
    except Exception as exc:
        return exc

    if serve_task.cancelled():
        return asyncio.CancelledError()

    try:
        serve_task.result()
    except Exception as exc:
        return exc

    return None


@asynccontextmanager
async def running_local_api(
    settings: JungSettings,
    *,
    application_factory: ApplicationFactory = application_context,
) -> AsyncIterator[str]:
    app = create_app(settings, application_factory=application_factory)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((_MANAGED_API_HOST, 0))
        sock.listen()
        port = sock.getsockname()[1]
        log_level = settings.api_log_level.value

        config = uvicorn.Config(
            app=app,
            host=_MANAGED_API_HOST,
            port=port,
            log_level=log_level,
            log_config=_uvicorn_log_config_with_jung(log_level),
            access_log=False,
        )
        server = uvicorn.Server(config)

        async def _serve() -> None:
            try:
                await server.serve(sockets=[sock])
            except SystemExit as exc:
                if exc.code == STARTUP_FAILURE:
                    raise RuntimeError(
                        "Uvicorn failed during managed API startup"
                    ) from exc
                raise

        serve_task = asyncio.create_task(_serve())
        body_error: BaseException | None = None

        try:
            await _wait_for_uvicorn_start(server, serve_task)
            try:
                yield f"http://{_MANAGED_API_HOST}:{port}"
            except BaseException as exc:
                body_error = exc
                raise
        finally:
            server.should_exit = True
            shutdown_failure = await _shutdown_owned_serve_task(serve_task)

            if body_error is None and shutdown_failure is not None:
                raise shutdown_failure
