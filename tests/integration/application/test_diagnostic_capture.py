"""Composition exit-criterion tests for lean diagnostic capture."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from openai import AsyncOpenAI

from jung import composition as composition_module
from jung.composition import application_context
from jung.config import ApplicationSettings
from jung.diagnostics import DiagnosticRecorder
from jung.domain.commands import SendMessage, UpdateProfile
from jung.domain.models import MessageRole, Profile
from jung.domain.results import ChatFailed
from jung.llm.gateway import AdapterConfig, LLMSettings
from jung.llm.openai_compatible import OpenAICompatibleLLM
from jung.persistence.sqlite_store import SCHEMA_VERSION as SQLITE_SCHEMA_VERSION

from .application_fixtures import collect_stream

pytestmark = pytest.mark.asyncio


def _load_trace(run_dir: Path) -> list[dict[str, object]]:
    lines = (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _kinds(events: list[dict[str, object]]) -> list[str]:
    return [str(event["kind"]) for event in events]


def _completion_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "1",
            "object": "chat.completion",
            "choices": [
                {
                    "message": {"role": "assistant", "content": content},
                    "index": 0,
                }
            ],
        },
    )


def _llm_factory(
    handler: Callable[[httpx.Request], httpx.Response],
) -> Callable[[AdapterConfig, DiagnosticRecorder | None], OpenAICompatibleLLM]:
    def factory(
        config: AdapterConfig,
        recorder: DiagnosticRecorder | None,
    ) -> OpenAICompatibleLLM:
        return OpenAICompatibleLLM(
            config,
            client=AsyncOpenAI(
                base_url=config.base_url,
                api_key=config.api_key,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                max_retries=0,
            ),
            recorder=recorder,
        )

    return factory


def _settings(tmp_path: Path, *, run_dir: Path) -> ApplicationSettings:
    return ApplicationSettings(
        database_path=tmp_path / "composition.db",
        llm=LLMSettings(
            default_model="test-model",
            base_url="http://testserver/v1",
            api_key="test-key",
        ),
        shutdown_timeout_seconds=5.0,
        debug_run_dir=run_dir,
    )


def _assert_diagnostic_artifacts(run_dir: Path) -> None:
    assert {path.name for path in run_dir.iterdir()} == {
        "trace.jsonl",
        "db_snapshot.sqlite",
    }


async def test_diagnostic_capture_success_snapshot(tmp_path: Path) -> None:
    run_dir = tmp_path / "debug-run"

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("LLM should not be called")

    settings = _settings(tmp_path, run_dir=run_dir)
    async with application_context(
        settings, llm_factory=_llm_factory(handler)
    ) as runtime:
        await runtime.application.update_profile(
            UpdateProfile(
                profile=Profile(name="Alex", primary_language="English"),
            )
        )
        session = (await runtime.application.get_snapshot()).active_session
        assert session is not None
        session_id = session.id

    assert (run_dir / "trace.jsonl").exists()
    snapshot = run_dir / "db_snapshot.sqlite"
    assert snapshot.exists()
    assert (snapshot.stat().st_mode & 0o777) == 0o600
    _assert_diagnostic_artifacts(run_dir)

    conn = sqlite3.connect(snapshot)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert (
            conn.execute("PRAGMA user_version").fetchone()[0] == SQLITE_SCHEMA_VERSION
        )
        profile_name = conn.execute("SELECT name FROM profile LIMIT 1").fetchone()
        assert profile_name is not None
        assert profile_name[0] == "Alex"
        session_row = conn.execute(
            "SELECT id FROM sessions WHERE id = ?",
            (str(session_id),),
        ).fetchone()
        assert session_row is not None
    finally:
        conn.close()


async def test_diagnostic_capture_double_structured_failure(tmp_path: Path) -> None:
    run_dir = tmp_path / "debug-run"
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        requests.append(body)
        assert body.get("stream") is not True
        return _completion_response("not-json")

    settings = _settings(tmp_path, run_dir=run_dir)
    client_message_id = uuid4()
    async with application_context(
        settings, llm_factory=_llm_factory(handler)
    ) as runtime:
        await runtime.application.update_profile(
            UpdateProfile(
                profile=Profile(name="Alex", primary_language="English"),
            )
        )
        session = (await runtime.application.get_snapshot()).active_session
        assert session is not None
        items = await collect_stream(
            runtime.application,
            SendMessage(
                session_id=session.id,
                client_message_id=client_message_id,
                content="I feel anxious.",
            ),
        )
        assert isinstance(items[-1], ChatFailed)
        assert items[-1].code == "invalid_llm_output"

    assert len(requests) == 2
    events = _load_trace(run_dir)
    kinds = _kinds(events)
    assert kinds[0] == "diagnostics.start"
    assert kinds[-1] == "diagnostics.end"
    assert kinds.count("llm.provider.request") == 2
    assert kinds.count("llm.provider.response") == 2
    assert kinds.count("llm.validation.failed") == 2
    assert kinds.count("llm.correction.started") == 1
    assert kinds.count("llm.call.failed") == 1
    assert kinds.count("chat.turn.failed") == 1

    snapshot = run_dir / "db_snapshot.sqlite"
    assert snapshot.exists()
    conn = sqlite3.connect(snapshot)
    try:
        row = conn.execute(
            """
            SELECT role, client_message_id, content
            FROM messages
            WHERE client_message_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (str(client_message_id),),
        ).fetchone()
        assert row is not None
        assert row[0] == MessageRole.USER.value
        assert row[1] == str(client_message_id)
        assert row[2] == "I feel anxious."
    finally:
        conn.close()


@pytest.mark.parametrize("raise_primary", [False, True])
async def test_diagnostic_snapshot_failure_preserves_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raise_primary: bool,
) -> None:
    run_dir = tmp_path / "debug-run"
    sentinel = RuntimeError("sentinel-primary")

    def boom_snapshot(*_args, **_kwargs) -> None:
        raise OSError("forced snapshot failure")

    monkeypatch.setattr(composition_module, "snapshot_database", boom_snapshot)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("LLM should not be called")

    settings = _settings(tmp_path, run_dir=run_dir)
    if raise_primary:
        with pytest.raises(RuntimeError, match="sentinel-primary") as exc_info:
            async with application_context(
                settings, llm_factory=_llm_factory(handler)
            ) as runtime:
                await runtime.application.update_profile(
                    UpdateProfile(
                        profile=Profile(name="Alex", primary_language="English"),
                    )
                )
                raise sentinel
        assert exc_info.value is sentinel
    else:
        async with application_context(
            settings, llm_factory=_llm_factory(handler)
        ) as runtime:
            await runtime.application.update_profile(
                UpdateProfile(
                    profile=Profile(name="Alex", primary_language="English"),
                )
            )

    assert not (run_dir / "db_snapshot.sqlite").exists()
    events = _load_trace(run_dir)
    snapshot_errors = [
        e
        for e in events
        if e["kind"] == "runtime.error"
        and e["data"].get("phase") == "diagnostic_snapshot"
    ]
    assert len(snapshot_errors) == 1
    assert snapshot_errors[0]["data"]["error_type"] == "OSError"

    end = next(e for e in events if e["kind"] == "diagnostics.end")
    if raise_primary:
        assert end["data"]["status"] == "failed"
        assert end["data"]["error_type"] == "RuntimeError"
        assert end["data"]["error_message"] == "sentinel-primary"
    else:
        assert end["data"]["status"] == "success"
        assert "error_type" not in end["data"]
