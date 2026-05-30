"""Replaceable input sources for the Trio console client."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

import trio


@dataclass
class InputContext:
    """Context passed to an input provider before the console needs text."""

    prompt: str | None
    default: str | None
    prompt_kind: str
    user_id: str | None
    session_id: str | None
    workflow_action: dict[str, Any] | None
    simulator_phase: str
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


def simulator_phase_for_action(workflow_action: dict[str, Any] | None) -> str:
    """Return only patient-visible phase context for simulated chat input."""
    if not isinstance(workflow_action, dict):
        return "You are in a therapy conversation."

    action = workflow_action.get("required_action")
    if action == "start_intake":
        return "You are answering intake questions."
    if action == "continue_therapy":
        return "You are in a therapy conversation."
    if action == "select_therapy_style":
        return "You are choosing a therapy style."
    if action == "wait":
        return "The conversation is paused."
    return "You are in a therapy conversation."


def _normalize_prompt(prompt: str) -> str:
    return re.sub(r"\s+", " ", prompt.strip().lower())
