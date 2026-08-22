"""Unit tests for Phase 8D patient benchmark mechanics."""

from __future__ import annotations

import json

import pytest

from evals.phase8d import patient_benchmark as benchmark
from evals.simulation.patient import PatientTurnContext


@pytest.mark.asyncio
async def test_balanced_p0_p1_order(tmp_path) -> None:
    seen: list[tuple[str, str]] = []

    async def fake_generate(arm, context_id, _context: PatientTurnContext):
        seen.append((arm, context_id))
        return benchmark.ContextCallResult(
            arm=arm,
            context_id=context_id,
            latency_seconds=0.1,
            finish_reason="stop",
            prompt_tokens=1,
            completion_tokens=1,
            output_chars=2,
            output_text="ok",
        )

    run_dir, _ = await benchmark.run_p0_p1_benchmark(
        output_dir=tmp_path,
        generate=fake_generate,
    )
    assert seen == list(benchmark.BALANCED_P0_P1_SEQUENCE)
    payload = json.loads((run_dir / "benchmark.json").read_text(encoding="utf-8"))
    assert payload["invocation"] == "p0-p1"
    assert len(payload["calls"]) == 8


def test_build_p1_patient_extra_body_non_mutation() -> None:
    session_extra_body = {
        "chat_template_kwargs": {"enable_thinking": True, "mode": "default"},
        "top_p": 0.95,
        "reasoning_effort": "medium",
    }
    original = json.dumps(session_extra_body, sort_keys=True)
    p1_body = benchmark.build_p1_patient_extra_body(session_extra_body)
    assert json.dumps(session_extra_body, sort_keys=True) == original
    assert p1_body["chat_template_kwargs"]["enable_thinking"] is False
    assert p1_body["chat_template_kwargs"]["mode"] == "default"
    assert p1_body["top_p"] == 0.95
    assert p1_body["reasoning_effort"] == "low"


def test_social_anxiety_contexts_cover_abcd() -> None:
    contexts = benchmark.social_anxiety_contexts()
    assert set(contexts) == {"A", "B", "C", "D"}
    assert contexts["A"].turn_number == 1
    assert contexts["D"].session_number == 2
