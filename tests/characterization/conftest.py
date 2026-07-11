"""Ephemeral black-box harness for the current deterministic legacy server."""

from __future__ import annotations

import pytest

from .legacy_client import LegacyApiClient, start_legacy_server


@pytest.fixture
def legacy_server(tmp_path):
    server = start_legacy_server(tmp_path)
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def legacy_client(legacy_server) -> LegacyApiClient:
    import uuid

    return LegacyApiClient(legacy_server, user_id=f"char-{uuid.uuid4().hex[:10]}")
