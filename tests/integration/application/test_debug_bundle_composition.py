"""Composition exit-criterion tests for the AI-agent debug bundle."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from openai import AsyncOpenAI

from jung.composition import application_context
from jung.config import ApplicationSettings
from jung.diagnostics import DiagnosticRecorder
from jung.domain.commands import SendMessage, UpdateProfile
from jung.domain.models import ChatTurnStatus, MessageRole, Profile
from jung.llm.gateway import AdapterConfig, LLMSettings
from jung.llm.openai_compatible import OpenAICompatibleLLM
from jung.phases.intake.models import IntakeRecordPatch

from .application_fixtures import wait_for_chat_turn

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


def _stream_response(text: str) -> httpx.Response:
    chunk = json.dumps(
        {
            "id": "1",
            "object": "chat.completion.chunk",
            "choices": [{"delta": {"content": text}, "index": 0}],
        }
    )
    return httpx.Response(
        200,
        content=f"data: {chunk}\n\ndata: [DONE]\n\n",
        headers={"content-type": "text/event-stream"},
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


async def test_debug_bundle_double_structured_failure(tmp_path: Path) -> None:
    run_dir = tmp_path / "debug-run"
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        requests.append(body)
        assert body.get("stream") is not True
        return _completion_response("not-json")

    settings = _settings(tmp_path, run_dir=run_dir)
    async with application_context(
        settings, llm_factory=_llm_factory(handler)
    ) as runtime:
        await runtime.application.update_profile(
            UpdateProfile(
                expected_revision=0,
                profile=Profile(name="Alex", primary_language="English"),
            )
        )
        session = (await runtime.application.get_snapshot()).active_session
        assert session is not None
        turn = await runtime.application.submit_message(
            SendMessage(
                expected_revision=(await runtime.application.get_snapshot()).revision,
                session_id=session.id,
                client_message_id=uuid4(),
                content="I feel anxious.",
            )
        )
        terminal = await wait_for_chat_turn(
            runtime.application,
            turn.id,
            ChatTurnStatus.FAILED,
        )
        assert terminal.status is ChatTurnStatus.FAILED
        assert terminal.error_code == "invalid_llm_output"
        assert terminal.retryable is False

    assert len(requests) == 2
    assert all(body.get("stream") is not True for body in requests)

    events = _load_trace(run_dir)
    kinds = _kinds(events)
    assert kinds[0] == "diagnostics.start"
    assert kinds[-1] == "diagnostics.end"

    started = [
        e
        for e in events
        if e["kind"] == "workflow.command.started"
        and e["data"].get("command") == "send_message"
    ]
    completed = [
        e
        for e in events
        if e["kind"] == "workflow.command.completed"
        and e["data"].get("command") == "send_message"
        and e["data"].get("outcome") == "committed"
    ]
    assert len(started) == 1
    assert len(completed) == 1
    assert "chat.turn.accepted" in kinds
    assert "chat.turn.started" in kinds
    assert "chat.turn.failed" in kinds

    structured_started = [
        e
        for e in events
        if e["kind"] == "llm.call.started"
        and e["data"].get("call_type") == "generate_structured"
        and e["data"].get("task") == "intake_patch"
    ]
    assert len(structured_started) == 1
    assert kinds.count("llm.provider.request") == 2
    assert kinds.count("llm.provider.response") == 2
    assert kinds.count("llm.validation.failed") == 2
    assert kinds.count("llm.correction.started") == 1
    assert kinds.count("llm.call.failed") == 1
    assert not any(
        e["kind"] == "llm.call.started" and e["data"].get("call_type") == "stream_text"
        for e in events
    )
    assert not any(e.get("data", {}).get("task") == "intake_response" for e in events)

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert any(s["id"] == str(session.id) for s in state["sessions"])
    turn_rows = [t for t in state["chat_turns"] if t["id"] == str(turn.id)]
    assert len(turn_rows) == 1
    assert turn_rows[0]["status"] == ChatTurnStatus.FAILED.value
    assert turn_rows[0]["error_code"] == "invalid_llm_output"
    assert turn_rows[0]["retryable"] is False

    transcript = (run_dir / "transcript.md").read_text(encoding="utf-8")
    assert "I feel anxious." in transcript
    assert f"] {MessageRole.ASSISTANT.value}" not in transcript

    summary = (run_dir / "failure_summary.md").read_text(encoding="utf-8")
    assert str(turn.id) in summary


async def test_debug_bundle_correction_success(tmp_path: Path) -> None:
    run_dir = tmp_path / "debug-run"
    requests: list[dict[str, object]] = []
    valid_patch = IntakeRecordPatch(
        no_new_information=True,
        rationale="Patient restated anxiety without new details.",
    ).model_dump_json()
    assistant_text = "Tell me more about what anxiety feels like for you."

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        requests.append(body)
        if body.get("stream") is True:
            return _stream_response(assistant_text)
        if sum(1 for item in requests if item.get("stream") is not True) == 1:
            return _completion_response("not-json")
        return _completion_response(valid_patch)

    settings = _settings(tmp_path, run_dir=run_dir)
    async with application_context(
        settings, llm_factory=_llm_factory(handler)
    ) as runtime:
        await runtime.application.update_profile(
            UpdateProfile(
                expected_revision=0,
                profile=Profile(name="Alex", primary_language="English"),
            )
        )
        session = (await runtime.application.get_snapshot()).active_session
        assert session is not None
        turn = await runtime.application.submit_message(
            SendMessage(
                expected_revision=(await runtime.application.get_snapshot()).revision,
                session_id=session.id,
                client_message_id=uuid4(),
                content="I feel anxious.",
            )
        )
        terminal = await wait_for_chat_turn(
            runtime.application,
            turn.id,
            ChatTurnStatus.COMPLETE,
        )
        assert terminal.status is ChatTurnStatus.COMPLETE

    non_stream = [body for body in requests if body.get("stream") is not True]
    stream = [body for body in requests if body.get("stream") is True]
    assert len(non_stream) == 2
    assert len(stream) == 1

    events = _load_trace(run_dir)
    kinds = _kinds(events)
    assert kinds.count("llm.validation.failed") == 1
    assert kinds.count("llm.correction.started") == 1
    assert kinds.count("llm.output.accepted") == 1

    structured = [
        e
        for e in events
        if e["kind"] == "llm.call.started"
        and e["data"].get("call_type") == "generate_structured"
        and e["data"].get("task") == "intake_patch"
    ]
    assert len(structured) == 1
    assert any(
        e["kind"] == "llm.call.completed" and e["data"].get("task") == "intake_patch"
        for e in events
    ) or any(
        e["kind"] == "llm.call.completed"
        and e["context"].get("llm_call_id")
        == structured[0]["context"].get("llm_call_id")
        for e in events
    )

    streaming = [
        e
        for e in events
        if e["kind"] == "llm.call.started"
        and e["data"].get("call_type") == "stream_text"
        and e["data"].get("task") == "intake_response"
    ]
    assert len(streaming) == 1
    assert any(
        e["kind"] == "llm.call.completed"
        and e["context"].get("llm_call_id")
        == streaming[0]["context"].get("llm_call_id")
        for e in events
    )
    assert "chat.turn.completed" in kinds

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    turn_rows = [t for t in state["chat_turns"] if t["id"] == str(turn.id)]
    assert len(turn_rows) == 1
    assert turn_rows[0]["status"] == ChatTurnStatus.COMPLETE.value

    transcript = (run_dir / "transcript.md").read_text(encoding="utf-8")
    assert "I feel anxious." in transcript
    assert assistant_text in transcript
    assert not (run_dir / "failure_summary.md").exists()
