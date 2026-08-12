"""Local foreground operator shell: managed API + console over HTTP."""

from __future__ import annotations

import asyncio

from jung.api.server import running_local_api
from jung.client.api_client import ClientSettings, JungApiClient
from jung.client.terminal import run_console
from jung.config import JungSettings, load_settings


async def run_local(settings: JungSettings) -> int:
    async with running_local_api(settings) as base_url:
        client_settings = ClientSettings(base_url=base_url)
        async with JungApiClient(client_settings) as client:
            await client.get_health()
        return await run_console(client_settings)


def cli() -> int:
    settings = load_settings()
    try:
        return asyncio.run(run_local(settings))
    except KeyboardInterrupt:
        return 130
