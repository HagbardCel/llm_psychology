"""Eval-only synthetic patient LLM boundary.

The patient is test machinery, not a Jung ``LLMRole``. It must never receive
treatment plans, session reviews, supervisor briefings, therapist prompts,
SQLite rows, or diagnostic traces.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from openai import AsyncOpenAI

from evals.simulation.scenarios import SimulationScenario

PATIENT_TIMEOUT_SECONDS = 120.0
PATIENT_HISTORY_MAX_CHARS = 40_000
WORKFLOW_TIMEOUT_SECONDS = 600.0

PATIENT_API_KEY_ENV = "JUNG_SIM_PATIENT_API_KEY"
PATIENT_THINKING_PREFILL_ENV = "JUNG_SIM_PATIENT_THINKING_PREFILL"
_LOCAL_PLACEHOLDER_API_KEY = "not-needed"

PatientPhase = Literal["intake", "therapy"]


@dataclass(frozen=True, slots=True)
class VisibleTurn:
    """One patient-visible utterance (patient or therapist side)."""

    role: Literal["patient", "therapist"]
    content: str


@dataclass(frozen=True, slots=True)
class PatientExchange:
    """One completed patient→therapist exchange."""

    patient: str
    therapist: str


@dataclass(frozen=True, slots=True)
class PatientTurnContext:
    """Narrow input the patient simulator is allowed to see."""

    scenario: SimulationScenario
    phase: PatientPhase
    session_number: int
    turn_number: int
    visible_history: tuple[VisibleTurn, ...]


@dataclass(frozen=True, slots=True)
class PatientEvidence:
    """Forensic record of one patient-simulator generation."""

    model: str
    resolved_prompt: str
    visible_history: tuple[VisibleTurn, ...]
    raw_provider_text: str
    submitted_text: str
    finish_reason: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_seconds: float


@dataclass(frozen=True, slots=True)
class PatientEndpointConfig:
    """Resolved transport settings for the patient simulator."""

    base_url: str
    model: str
    api_key: str
    default_headers: Mapping[str, str] | None
    timeout_seconds: float
    extra_body: Mapping[str, Any] | None = None


class PatientGenerationError(RuntimeError):
    """Raised when the patient simulator cannot produce a usable utterance."""


def serialize_visible_history(history: Sequence[VisibleTurn]) -> str:
    """Canonical model-facing serialization used for packing and prompting."""
    payload = [{"role": turn.role, "content": turn.content} for turn in history]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _exchange_turns(exchange: PatientExchange) -> tuple[VisibleTurn, VisibleTurn]:
    return (
        VisibleTurn(role="patient", content=exchange.patient),
        VisibleTurn(role="therapist", content=exchange.therapist),
    )


def pack_visible_history(
    *,
    current_session: Sequence[PatientExchange],
    prior_sessions: Sequence[Sequence[PatientExchange]],
    max_chars: int = PATIENT_HISTORY_MAX_CHARS,
) -> tuple[VisibleTurn, ...]:
    """Pack newest complete exchanges under the model-facing char budget.

    Prefer current-session exchanges when they fit, then newest prior-session
    exchanges. Never split an exchange. Omit an exchange that alone exceeds
    the entire budget.
    """
    if max_chars <= 0:
        return ()

    selected: list[VisibleTurn] = []

    def try_prepend(exchange: PatientExchange) -> bool:
        candidate = [*_exchange_turns(exchange), *selected]
        if len(serialize_visible_history(candidate)) <= max_chars:
            selected[:] = candidate
            return True
        return False

    for exchange in reversed(tuple(current_session)):
        if not try_prepend(exchange):
            # Oversized newest exchange must not block a smaller older one.
            continue

    for session in reversed(tuple(prior_sessions)):
        for exchange in reversed(tuple(session)):
            if not try_prepend(exchange):
                continue

    return tuple(selected)


def _same_origin_url(left: str, right: str) -> bool:
    return left.rstrip("/") == right.rstrip("/")


def resolve_patient_endpoint(
    *,
    session_base_url: str,
    session_model: str,
    session_api_key: str,
    session_default_headers: Mapping[str, str] | None,
    patient_base_url: str | None = None,
    patient_model: str | None = None,
    patient_api_key_env: str | None = None,
    timeout_seconds: float = PATIENT_TIMEOUT_SECONDS,
    session_extra_body: Mapping[str, Any] | None = None,
    patient_extra_body: Mapping[str, Any] | None = None,
) -> PatientEndpointConfig:
    """Resolve patient transport without leaking credentials across origins."""
    model = patient_model or session_model
    implicit_endpoint = patient_base_url is None

    if implicit_endpoint:
        if patient_extra_body is None:
            extra_body = (
                dict(session_extra_body) if session_extra_body is not None else None
            )
        else:
            extra_body = dict(patient_extra_body)
        return PatientEndpointConfig(
            base_url=session_base_url,
            model=model,
            api_key=session_api_key or _LOCAL_PLACEHOLDER_API_KEY,
            default_headers=(
                dict(session_default_headers)
                if session_default_headers is not None
                else None
            ),
            timeout_seconds=timeout_seconds,
            extra_body=extra_body,
        )

    if patient_extra_body is None:
        extra_body = None
    else:
        extra_body = dict(patient_extra_body)

    if patient_api_key_env is None:
        patient_api_key_env = os.environ.get(PATIENT_API_KEY_ENV, "").strip() or None

    same_origin = _same_origin_url(patient_base_url, session_base_url)
    if same_origin:
        api_key = session_api_key or _LOCAL_PLACEHOLDER_API_KEY
        default_headers = (
            dict(session_default_headers)
            if session_default_headers is not None
            else None
        )
        if patient_api_key_env is not None:
            api_key = patient_api_key_env
    else:
        api_key = patient_api_key_env or _LOCAL_PLACEHOLDER_API_KEY
        default_headers = None

    return PatientEndpointConfig(
        base_url=patient_base_url,
        model=model,
        api_key=api_key,
        default_headers=default_headers,
        timeout_seconds=timeout_seconds,
        extra_body=extra_body,
    )


def build_patient_prompt(context: PatientTurnContext) -> str:
    """Build the patient-simulator prompt from allowed inputs only."""
    scenario = context.scenario
    history_json = serialize_visible_history(context.visible_history)
    facts = "\n".join(f"- {item}" for item in scenario.stable_facts)
    gradual = "\n".join(f"- {item}" for item in scenario.gradual_disclosure_facts)
    reactions = "\n".join(f"- {item}" for item in scenario.likely_emotional_reactions)
    goals = "\n".join(f"- {item}" for item in scenario.cross_session_goals)
    return (
        "You are simulating a therapy patient for a software evaluation.\n"
        "Stay consistent with the scenario. Do not invent contradictory "
        "background facts. Disclose gradual facts only when rapport and "
        "context make that natural. Speak in first person as the patient.\n"
        "Return only the patient's next utterance — no stage directions, "
        "no meta commentary, no therapist advice.\n\n"
        f"Scenario id: {scenario.id} version={scenario.version}\n"
        f"Persona: {scenario.persona}\n"
        f"Background: {scenario.background}\n"
        f"Presenting concern: {scenario.presenting_concern}\n"
        f"Safety baseline: {scenario.safety_baseline}\n"
        f"Conversation style: {scenario.conversation_style}\n"
        f"Stable facts:\n{facts}\n"
        f"Facts to disclose gradually:\n{gradual}\n"
        f"Likely emotional reactions:\n{reactions}\n"
        f"Cross-session goals:\n{goals}\n\n"
        f"Phase: {context.phase}\n"
        f"Session number: {context.session_number}\n"
        f"Turn number: {context.turn_number}\n\n"
        "Patient-visible conversation history (JSON):\n"
        f"{history_json}\n"
    )


def normalize_patient_text(raw: str) -> str:
    """Whitespace-normalize patient text; do not rewrite substance."""
    return " ".join(raw.split()).strip()


def _usage_int(usage: Any, name: str) -> int | None:
    if usage is None:
        return None
    value = getattr(usage, name, None)
    return int(value) if isinstance(value, int) else None


def _patient_thinking_prefill_enabled() -> bool:
    return os.environ.get(PATIENT_THINKING_PREFILL_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


class PatientSimulator:
    """Direct AsyncOpenAI patient actor with zero SDK retries."""

    def __init__(
        self,
        config: PatientEndpointConfig,
        *,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self._config = config
        if client is not None:
            self._client = client
            self._owns_client = False
        else:
            kwargs: dict[str, Any] = {
                "base_url": config.base_url,
                "api_key": config.api_key,
                "max_retries": 0,
                "timeout": config.timeout_seconds,
            }
            if config.default_headers:
                kwargs["default_headers"] = dict(config.default_headers)
            self._client = AsyncOpenAI(**kwargs)
            self._owns_client = True
            if self._client.max_retries != 0:
                raise RuntimeError("patient AsyncOpenAI must use max_retries=0")

    @property
    def config(self) -> PatientEndpointConfig:
        return self._config

    @property
    def client(self) -> AsyncOpenAI:
        return self._client

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.close()

    async def generate(self, context: PatientTurnContext) -> PatientEvidence:
        prompt = build_patient_prompt(context)
        started = time.perf_counter()
        try:
            messages: list[dict[str, str]] = [{"role": "user", "content": prompt}]
            if _patient_thinking_prefill_enabled():
                messages.append({"role": "assistant", "content": " \n"})
            create_kwargs: dict[str, Any] = {
                "model": self._config.model,
                "messages": messages,
                "temperature": 0.7,
            }
            if self._config.extra_body is not None:
                create_kwargs["extra_body"] = dict(self._config.extra_body)
            response = await self._client.chat.completions.create(**create_kwargs)
        except Exception as exc:
            raise PatientGenerationError(
                f"patient provider unavailable: {type(exc).__name__}: {exc}"
            ) from exc

        latency = time.perf_counter() - started
        choice = response.choices[0] if response.choices else None
        if choice is None:
            raise PatientGenerationError("patient provider returned no choices")
        raw = (choice.message.content or "") if choice.message is not None else ""
        finish_reason = choice.finish_reason
        submitted = normalize_patient_text(raw)
        if not submitted:
            raise PatientGenerationError("patient emitted blank text")

        usage = getattr(response, "usage", None)
        return PatientEvidence(
            model=self._config.model,
            resolved_prompt=prompt,
            visible_history=context.visible_history,
            raw_provider_text=raw,
            submitted_text=submitted,
            finish_reason=finish_reason,
            prompt_tokens=_usage_int(usage, "prompt_tokens"),
            completion_tokens=_usage_int(usage, "completion_tokens"),
            latency_seconds=latency,
        )
