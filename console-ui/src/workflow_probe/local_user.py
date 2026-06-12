"""Strict local-LLM simulated patient for the workflow probe."""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any

from ..input_providers import InputContext, InputResult
from ..llm_user_simulator import LocalLLMUserSimulator


class LocalUser:
    """Provide deterministic structural answers and model-generated chat replies."""

    def __init__(self, scenario: dict[str, Any], recorder: Any):
        self.deterministic = os.getenv("PROBE_DETERMINISTIC_USER", "").lower() == "true"
        self.scenario = scenario
        self.transcript: list[dict[str, str]] = []
        self.turn_index = 0
        self.therapy_started = False
        self.therapy_turns = 0
        self.max_total_turns = int(scenario.get("limits", {}).get("max_total_turns", 14))
        self.simulator = (
            None
            if self.deterministic
            else LocalLLMUserSimulator.from_env(recorder=recorder)
        )

    async def get_input(self, context: InputContext) -> str | InputResult:
        structural = self._structural_answer(context)
        if structural is not None:
            return structural
        if self.therapy_started and self.therapy_turns >= 1:
            return "/quit"
        if self.turn_index >= self.max_total_turns:
            return "/quit"
        if self.deterministic:
            replies = self.scenario.get("deterministic_chat_replies", [])
            if not replies:
                raise ValueError("deterministic_chat_replies are required for deterministic probe mode")
            return str(replies[min(self.turn_index, len(replies) - 1)])
        probe_context = replace(
            context,
            transcript_tail=self.transcript[-8:],
            turn_index=self.turn_index,
        )
        assert self.simulator is not None
        result = await self.simulator.generate_user_reply(
            scenario=self.scenario,
            context=probe_context,
        )
        return InputResult(
            text=str(result["text"]),
            input_origin="local_llm",
            fallback_reason=None,
        )

    async def emit(self, event: str, **fields: Any) -> None:
        if event == "assistant_response":
            self._append("assistant", str(fields.get("text") or ""))
        elif event == "user_input":
            context = fields.get("context")
            if getattr(context, "prompt_kind", None) == "chat":
                text = str(fields.get("text") or "")
                if not text.startswith("/"):
                    self._append("user", text)
                    self.turn_index += 1
                    if self.therapy_started:
                        self.therapy_turns += 1
        elif event == "session_started" and fields.get("data", {}).get("session_type") == "therapy":
            self.therapy_started = True
            self._append("system", "Therapy has started.")

    def _structural_answer(self, context: InputContext) -> str | None:
        structural = self.scenario.get("structural_answers", {})
        defaults = {
            "profile_selection": "1",
            "profile_name": "Console Probe User",
            "primary_language": context.default or "English",
            "therapy_style": "cbt",
            "start_therapy": "y",
            "retry_plan_update": "y",
        }
        if context.prompt_kind in defaults:
            return str(structural.get(context.prompt_kind, defaults[context.prompt_kind]))
        return None

    def _append(self, role: str, content: str) -> None:
        if content:
            self.transcript.append({"role": role, "content": content})
            self.transcript = self.transcript[-12:]
