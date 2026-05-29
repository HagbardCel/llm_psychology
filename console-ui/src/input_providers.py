"""Replaceable input sources for the Trio console client."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

import trio


DEFAULT_FALLBACK_RESPONSE = (
    "I'm feeling anxious about work and would like to understand it better."
)


@dataclass
class InputContext:
    """Context passed to an input provider before the console needs text."""

    prompt: str | None
    default: str | None
    prompt_kind: str
    user_id: str | None
    session_id: str | None
    workflow_action: dict[str, Any] | None
    pending_recommendations: list[dict[str, Any]] | None
    transcript_tail: list[dict[str, str]]
    turn_index: int


@dataclass
class InputResult:
    """Provider response plus probe attribution metadata."""

    text: str
    input_origin: str
    fallback_reason: str | None = None


class InputProvider(Protocol):
    """Async input provider used by ConsoleClient."""

    async def get_input(self, context: InputContext) -> str | InputResult:
        """Return the next user input string."""


class HumanInputProvider:
    """Default provider that preserves the existing interactive behavior."""

    def __init__(self, output: Any):
        self.output = output

    async def get_input(self, context: InputContext) -> str:
        if context.prompt:
            self.output.prompt(context.prompt)
        self.output.prompt("\nYour response: ", end="")
        return await trio.to_thread.run_sync(lambda: input().strip())


class ScriptedInputProvider:
    """Deterministic input provider for workflow probe smoke tests."""

    def __init__(
        self,
        responses: list[str] | None = None,
        prompt_responses: dict[str, str | list[str]] | None = None,
        fallback_response: str = DEFAULT_FALLBACK_RESPONSE,
    ):
        self.responses = list(responses or [])
        self.prompt_responses = {
            key: list(value) if isinstance(value, list) else [value]
            for key, value in (prompt_responses or {}).items()
        }
        self.fallback_response = fallback_response

    async def get_input(self, context: InputContext) -> str:
        prompt_response = self._pop_prompt_response(context)
        if prompt_response is not None:
            return prompt_response
        if self.responses:
            return self.responses.pop(0)
        return self.fallback_response

    def _pop_prompt_response(self, context: InputContext) -> str | None:
        keys = [context.prompt_kind]
        if context.prompt:
            keys.append(_normalize_prompt(context.prompt))

        for key in keys:
            values = self.prompt_responses.get(key)
            if values:
                return values.pop(0)
        return None


class LLMSimulatedUserProvider:
    """Input provider that uses deterministic structural answers and LLM chat."""

    def __init__(
        self,
        simulator: Any,
        scenario: dict[str, Any],
        fallback_response: str = DEFAULT_FALLBACK_RESPONSE,
    ):
        self.simulator = simulator
        self.scenario = scenario
        self.fallback_response = fallback_response
        self.fallback_responses = [
            response
            for response in scenario.get("scripted_responses", [])
            if isinstance(response, str) and not response.startswith("/")
        ]

    async def get_input(self, context: InputContext) -> str | InputResult:
        structural = self._structural_response(context)
        if structural is not None:
            return structural
        reply = await self.simulator.generate_user_reply(
            scenario=self.scenario,
            context=context,
            fallback_response=self._next_fallback_response(),
        )
        if isinstance(reply, InputResult):
            return reply
        if isinstance(reply, dict):
            return InputResult(
                text=str(reply.get("text") or ""),
                input_origin=str(reply.get("input_origin") or "local_llm"),
                fallback_reason=reply.get("fallback_reason"),
            )
        return InputResult(text=str(reply), input_origin="local_llm")

    def _structural_response(self, context: InputContext) -> str | None:
        user = self.scenario.get("user", {})
        workflow_preferences = self.scenario.get("workflow_preferences", {})

        if context.prompt_kind == "profile_selection":
            return str(workflow_preferences.get("profile_selection_answer", "1"))
        if context.prompt_kind == "profile_name":
            return str(user.get("name", "Console Probe User"))
        if context.prompt_kind == "primary_language":
            return str(user.get("primary_language", context.default or "English"))
        if context.prompt_kind == "therapy_style":
            return str(workflow_preferences.get("therapy_style", "cbt"))
        return None

    def _next_fallback_response(self) -> str:
        if self.fallback_responses:
            return self.fallback_responses.pop(0)
        return self.fallback_response


def infer_prompt_kind(prompt: str | None) -> str:
    """Classify console prompts so providers can answer structural prompts."""

    if not prompt:
        return "chat"

    normalized = _normalize_prompt(prompt)
    if "enter your name" in normalized or "enter name" in normalized:
        return "profile_name"
    if "primary language" in normalized:
        return "primary_language"
    if "therapy style" in normalized or "style id" in normalized:
        return "therapy_style"
    if "number for your choice" in normalized:
        return "profile_selection"
    if normalized.startswith("enter ") and "language" not in normalized:
        return "profile_field"
    return "prompt"


def _normalize_prompt(prompt: str) -> str:
    return re.sub(r"\s+", " ", prompt.strip().lower())
