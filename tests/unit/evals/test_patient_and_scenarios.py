"""Unit tests for simulation scenarios and patient actor."""

from __future__ import annotations

from dataclasses import fields
from unittest.mock import AsyncMock, MagicMock

import pytest
from openai import AsyncOpenAI

from evals.simulation.patient import (
    PATIENT_API_KEY_ENV,
    PATIENT_HISTORY_MAX_CHARS,
    PATIENT_MAX_COMPLETION_TOKENS,
    PatientEndpointConfig,
    PatientExchange,
    PatientGenerationError,
    PatientSimulator,
    PatientTurnContext,
    VisibleTurn,
    build_patient_prompt,
    normalize_patient_text,
    pack_visible_history,
    resolve_patient_endpoint,
    serialize_visible_history,
)
from evals.simulation.scenarios import get_scenario, list_scenario_ids


def _exchange_as_turns(
    exchange: PatientExchange,
) -> tuple[VisibleTurn, VisibleTurn]:
    return (
        VisibleTurn("patient", exchange.patient),
        VisibleTurn("therapist", exchange.therapist),
    )


def test_scenario_lookup_and_inventory() -> None:
    assert set(list_scenario_ids()) == {
        "anxiety_sleep",
        "social_anxiety",
        "relationship_conflict",
    }
    scenario = get_scenario("anxiety_sleep")
    assert scenario.id == "anxiety_sleep"
    assert scenario.version == "1"
    assert "sleep" in scenario.presenting_concern.lower()


def test_unknown_scenario_lists_available_ids() -> None:
    with pytest.raises(KeyError, match="available"):
        get_scenario("not_a_scenario")


def test_patient_turn_context_fields_are_patient_visible_only() -> None:
    names = {field.name for field in fields(PatientTurnContext)}
    assert names == {
        "scenario",
        "phase",
        "session_number",
        "turn_number",
        "visible_history",
    }
    forbidden = {
        "plan",
        "review",
        "briefing",
        "system_prompt",
        "trace",
        "sqlite",
        "grounding",
    }
    assert names.isdisjoint(forbidden)


def test_normalize_rejects_blank_and_collapses_whitespace() -> None:
    assert normalize_patient_text("  hello   world \n") == "hello world"
    assert normalize_patient_text("   \n\t  ") == ""


def test_patient_max_completion_tokens_is_frozen() -> None:
    assert PATIENT_MAX_COMPLETION_TOKENS == 400


def test_resolve_patient_endpoint_inherits_session_when_same_origin() -> None:
    config = resolve_patient_endpoint(
        session_base_url="http://session.test/v1",
        session_model="session-model",
        session_api_key="SESSION_SECRET",
        session_default_headers={"Authorization": "Bearer SESSION_SECRET"},
        session_extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    assert config.base_url == "http://session.test/v1"
    assert config.model == "session-model"
    assert config.api_key == "SESSION_SECRET"
    assert config.default_headers == {"Authorization": "Bearer SESSION_SECRET"}
    assert config.max_completion_tokens == 400
    assert config.extra_body == {"chat_template_kwargs": {"enable_thinking": False}}


def test_resolve_patient_endpoint_uses_placeholder_for_empty_session_key() -> None:
    config = resolve_patient_endpoint(
        session_base_url="http://session.test/v1",
        session_model="session-model",
        session_api_key="",
        session_default_headers=None,
    )
    assert config.api_key == "not-needed"


def test_resolve_patient_endpoint_never_inherits_credentials_across_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PATIENT_API_KEY_ENV, raising=False)
    config = resolve_patient_endpoint(
        session_base_url="http://session.test/v1",
        session_model="session-model",
        session_api_key="SESSION_SECRET",
        session_default_headers={"X-Api-Key": "SESSION_SECRET"},
        patient_base_url="http://other.test/v1",
        patient_model="patient-model",
    )
    assert config.base_url == "http://other.test/v1"
    assert config.model == "patient-model"
    assert config.api_key == "not-needed"
    assert config.default_headers is None


def test_resolve_patient_endpoint_uses_sim_env_for_alternate_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PATIENT_API_KEY_ENV, "PATIENT_ONLY")
    config = resolve_patient_endpoint(
        session_base_url="http://session.test/v1",
        session_model="session-model",
        session_api_key="SESSION_SECRET",
        session_default_headers={"X-Api-Key": "SESSION_SECRET"},
        patient_base_url="http://other.test/v1",
    )
    assert config.api_key == "PATIENT_ONLY"
    assert config.default_headers is None
    assert config.model == "session-model"


def test_pack_visible_history_fits_everything() -> None:
    current = (PatientExchange(patient="hi", therapist="hello"),)
    prior = ((PatientExchange(patient="earlier", therapist="ok"),),)
    packed = pack_visible_history(
        current_session=current,
        prior_sessions=prior,
        max_chars=PATIENT_HISTORY_MAX_CHARS,
    )
    assert packed == (
        VisibleTurn("patient", "earlier"),
        VisibleTurn("therapist", "ok"),
        VisibleTurn("patient", "hi"),
        VisibleTurn("therapist", "hello"),
    )
    assert len(serialize_visible_history(packed)) <= PATIENT_HISTORY_MAX_CHARS


def test_pack_visible_history_drops_old_sessions_first() -> None:
    current = (PatientExchange(patient="now", therapist="reply"),)
    prior = (
        (PatientExchange(patient="old-a", therapist="ta"),),
        (PatientExchange(patient="old-b", therapist="tb"),),
    )
    one_prior = serialize_visible_history(
        (
            *_exchange_as_turns(prior[1][0]),
            *_exchange_as_turns(current[0]),
        )
    )
    budget = len(one_prior) + 1
    assert budget < len(
        serialize_visible_history(
            (
                *_exchange_as_turns(prior[0][0]),
                *_exchange_as_turns(prior[1][0]),
                *_exchange_as_turns(current[0]),
            )
        )
    )
    packed = pack_visible_history(
        current_session=current,
        prior_sessions=prior,
        max_chars=budget,
    )
    assert packed[0].content == "old-b"
    assert packed[-1].content == "reply"
    assert all(turn.content != "old-a" for turn in packed)
    assert len(serialize_visible_history(packed)) <= budget


def test_pack_visible_history_current_session_alone_can_exceed_cap() -> None:
    huge = "x" * 500
    current = (
        PatientExchange(patient=huge, therapist=huge),
        PatientExchange(patient="keep", therapist="me"),
    )
    newest = serialize_visible_history(_exchange_as_turns(current[1]))
    packed = pack_visible_history(
        current_session=current,
        prior_sessions=(),
        max_chars=len(newest),
    )
    assert packed == _exchange_as_turns(current[1])


def test_pack_visible_history_omits_oversized_exchange() -> None:
    huge = "y" * 200
    exchange = PatientExchange(patient=huge, therapist=huge)
    serialized = serialize_visible_history(_exchange_as_turns(exchange))
    packed = pack_visible_history(
        current_session=(exchange,),
        prior_sessions=(),
        max_chars=len(serialized) - 1,
    )
    assert packed == ()


def test_pack_visible_history_skips_oversized_current_keeps_smaller_older() -> None:
    huge = "x" * 200
    current = (
        PatientExchange(patient="small", therapist="ok"),
        PatientExchange(patient=huge, therapist=huge),
    )
    small = serialize_visible_history(_exchange_as_turns(current[0]))
    packed = pack_visible_history(
        current_session=current,
        prior_sessions=(),
        max_chars=len(small),
    )
    assert packed == _exchange_as_turns(current[0])


def test_build_patient_prompt_contains_only_allowed_inputs() -> None:
    scenario = get_scenario("anxiety_sleep")
    context = PatientTurnContext(
        scenario=scenario,
        phase="therapy",
        session_number=2,
        turn_number=3,
        visible_history=(
            VisibleTurn("patient", "I slept badly"),
            VisibleTurn("therapist", "Tell me more"),
        ),
    )
    prompt = build_patient_prompt(context)
    assert scenario.persona in prompt
    assert "I slept badly" in prompt
    assert "SessionReview" not in prompt
    assert "<context_data>" not in prompt
    assert "review_json" not in prompt


@pytest.mark.asyncio
async def test_patient_simulator_rejects_blank_and_truncation() -> None:
    client = MagicMock(spec=AsyncOpenAI)
    client.max_retries = 0

    blank = MagicMock()
    blank.choices = [MagicMock(message=MagicMock(content="   "), finish_reason="stop")]
    blank.usage = None
    client.chat.completions.create = AsyncMock(return_value=blank)

    simulator = PatientSimulator(
        PatientEndpointConfig(
            base_url="http://test/v1",
            model="m",
            api_key="k",
            default_headers=None,
            timeout_seconds=30.0,
            max_completion_tokens=400,
        ),
        client=client,
    )
    context = PatientTurnContext(
        scenario=get_scenario("anxiety_sleep"),
        phase="intake",
        session_number=0,
        turn_number=1,
        visible_history=(),
    )
    with pytest.raises(PatientGenerationError, match="blank"):
        await simulator.generate(context)

    truncated = MagicMock()
    truncated.choices = [
        MagicMock(message=MagicMock(content="partial"), finish_reason="length")
    ]
    truncated.usage = None
    client.chat.completions.create = AsyncMock(return_value=truncated)
    with pytest.raises(PatientGenerationError, match="truncated"):
        await simulator.generate(context)


@pytest.mark.asyncio
async def test_patient_simulator_requires_zero_retries_on_owned_client() -> None:
    client = MagicMock(spec=AsyncOpenAI)
    client.max_retries = 0
    sim = PatientSimulator(
        PatientEndpointConfig(
            base_url="http://test/v1",
            model="m",
            api_key="k",
            default_headers=None,
            timeout_seconds=30.0,
            max_completion_tokens=400,
        ),
        client=client,
    )
    assert sim.client.max_retries == 0
