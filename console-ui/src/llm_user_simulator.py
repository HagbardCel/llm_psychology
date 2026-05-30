"""Local OpenAI-compatible model client for simulated console users."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

# Minimum output budget for local-model workflow probes and smoke tests.
LOCAL_USER_SIM_MAX_TOKENS = 8192


class LocalLLMUserSimulatorError(RuntimeError):
    """Raised when the local user simulator cannot produce a valid reply."""

    def __init__(self, reason: str, message: str, metadata: dict[str, Any] | None = None):
        super().__init__(message)
        self.reason = reason
        self.metadata = metadata or {}


@dataclass
class ChatCompletionResult:
    content: str
    http_status: int | None
    raw_preview: str
    response_shape: str
    failure_reason: str | None = None
    finish_reason: str | None = None
    reasoning_content_chars: int = 0


class LocalLLMUserSimulator:
    """Generate plausible patient replies from a local chat-completions API."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = LOCAL_USER_SIM_MAX_TOKENS,
        recorder: Any | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.recorder = recorder

    @classmethod
    def from_env(cls, recorder: Any | None = None) -> "LocalLLMUserSimulator":
        base_url = (
            os.getenv("USER_SIM_LLM_BASE_URL")
            or os.getenv("LLM_BASE_URL")
            or "http://host.docker.internal:1234/v1"
        )
        model = os.getenv("USER_SIM_LLM_MODEL") or os.getenv("MODEL_NAME", "local-model")
        api_key = os.getenv("USER_SIM_LLM_API_KEY", "not-needed")
        temperature = float(os.getenv("USER_SIM_LLM_TEMPERATURE", "0"))
        max_tokens = resolve_user_sim_max_tokens()
        return cls(
            base_url=base_url,
            model=model,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            recorder=recorder,
        )

    async def generate_user_reply(
        self,
        scenario: dict[str, Any],
        context: Any,
    ) -> dict[str, str | None]:
        prompt = self._build_prompt(scenario, context)
        result = await self._chat_completion(prompt)
        sanitized = sanitize_user_reply(result.content)
        failure_reason = self._reply_failure_reason(result, sanitized)

        if failure_reason == "invalid_reply":
            retry_prompt = (
                prompt
                + "\n\nYour previous reply was invalid. "
                "Return one concise patient reply only."
            )
            result = await self._chat_completion(retry_prompt)
            sanitized = sanitize_user_reply(result.content)
            failure_reason = self._reply_failure_reason(result, sanitized)

        if failure_reason:
            raise LocalLLMUserSimulatorError(
                failure_reason,
                f"Local user simulator failed: {failure_reason}",
                {
                    "model": self.model,
                    "base_url": self.base_url,
                    "http_status": result.http_status,
                    "response_shape": result.response_shape,
                    "raw_content_preview": result.raw_preview,
                    "parsed_content_preview": _preview(sanitized),
                },
            )

        if self.recorder:
            await self.recorder.record_model_call(
                prompt=prompt,
                raw_response=result.content,
                sanitized_response=sanitized,
                fallback_used=False,
                fallback_reason=None,
            )
        return {
            "text": sanitized,
            "input_origin": "local_llm",
            "fallback_reason": None,
        }

    async def _chat_completion(self, prompt: str) -> ChatCompletionResult:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a simulated user testing a console-based therapy "
                        "application. You are the patient, not the therapist. "
                        "Reply only with the next user message. Keep it concise, "
                        "plausible, and human. Do not mention being an AI or that "
                        "this is a test. Do not use markdown."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        payload["chat_template_kwargs"] = {"enable_thinking": False}

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
        except httpx.TimeoutException as exc:
            return await self._record_raw_result(
                ChatCompletionResult(
                    content=str(exc),
                    http_status=None,
                    raw_preview=str(exc),
                    response_shape="request_timeout",
                    failure_reason="local_llm_timeout",
                )
            )
        except httpx.HTTPError as exc:
            return await self._record_raw_result(
                ChatCompletionResult(
                    content=str(exc),
                    http_status=None,
                    raw_preview=str(exc),
                    response_shape="request_error",
                    failure_reason="local_llm_http_error",
                )
            )

        raw_text = response.text
        if response.is_error:
            return await self._record_raw_result(
                ChatCompletionResult(
                    content=raw_text,
                    http_status=response.status_code,
                    raw_preview=_preview(raw_text),
                    response_shape="http_error",
                    failure_reason="local_llm_http_error",
                )
            )
        if not raw_text.strip():
            return await self._record_raw_result(
                ChatCompletionResult(
                    content="",
                    http_status=response.status_code,
                    raw_preview="",
                    response_shape="empty_body",
                    failure_reason="empty_raw_response",
                )
            )

        try:
            data = response.json()
        except ValueError:
            return await self._record_raw_result(
                ChatCompletionResult(
                    content=raw_text,
                    http_status=response.status_code,
                    raw_preview=_preview(raw_text),
                    response_shape="invalid_json",
                    failure_reason="invalid_json",
                )
            )

        result = self._extract_content(data, response.status_code, raw_text)
        return await self._record_raw_result(result)

    def _extract_content(
        self, data: dict[str, Any], http_status: int, raw_text: str
    ) -> ChatCompletionResult:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return ChatCompletionResult(
                content="",
                http_status=http_status,
                raw_preview=_preview(raw_text),
                response_shape="missing_choices",
                failure_reason="missing_choices",
            )
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            return ChatCompletionResult(
                content="",
                http_status=http_status,
                raw_preview=_preview(raw_text),
                response_shape="invalid_choice",
                failure_reason="invalid_response_shape",
            )

        finish_reason = first_choice.get("finish_reason")
        finish_reason_str = str(finish_reason) if finish_reason is not None else None

        message = first_choice.get("message")
        if isinstance(message, dict) and "content" in message:
            content = message.get("content")
            reasoning = message.get("reasoning_content")
            reasoning_chars = (
                len(str(reasoning)) if isinstance(reasoning, str) and reasoning else 0
            )
            return ChatCompletionResult(
                content="" if content is None else str(content),
                http_status=http_status,
                raw_preview=_preview(raw_text),
                response_shape="choices[0].message.content",
                finish_reason=finish_reason_str,
                reasoning_content_chars=reasoning_chars,
            )

        delta = first_choice.get("delta")
        if isinstance(delta, dict) and "content" in delta:
            content = delta.get("content")
            return ChatCompletionResult(
                content="" if content is None else str(content),
                http_status=http_status,
                raw_preview=_preview(raw_text),
                response_shape="choices[0].delta.content",
            )

        return ChatCompletionResult(
            content="",
            http_status=http_status,
            raw_preview=_preview(raw_text),
            response_shape="missing_message_field",
            failure_reason="missing_message_field",
        )

    async def _record_raw_result(
        self, result: ChatCompletionResult
    ) -> ChatCompletionResult:
        if self.recorder:
            await self.recorder.record_user_simulator_raw_response(
                model=self.model,
                base_url=self.base_url,
                http_status=result.http_status,
                response_shape=result.response_shape,
                raw_content_preview=result.raw_preview,
                parsed_content_preview=_preview(result.content),
                fallback_reason=result.failure_reason,
                finish_reason=result.finish_reason,
                reasoning_content_chars=result.reasoning_content_chars,
            )
        return result

    def _reply_failure_reason(
        self, result: ChatCompletionResult, sanitized: str
    ) -> str | None:
        if result.failure_reason:
            return result.failure_reason
        if not result.content.strip():
            if (
                result.reasoning_content_chars > 0
                and result.finish_reason == "length"
            ):
                return "content_blank_after_reasoning_budget_exhausted"
            return "content_blank_after_strip"
        if not sanitized:
            if (
                result.reasoning_content_chars > 0
                and result.finish_reason == "length"
            ):
                return "content_blank_after_reasoning_budget_exhausted"
            return "content_blank_after_strip"
        if not is_valid_user_reply(sanitized):
            return "invalid_reply"
        return None

    def _build_prompt(self, scenario: dict[str, Any], context: Any) -> str:
        user = scenario.get("user", {})
        persona = scenario.get("persona", {})
        workflow_preferences = scenario.get("workflow_preferences", {})
        transcript = "\n".join(
            f"{item.get('role', 'unknown')}: {item.get('content', '')}"
            for item in context.transcript_tail
        )

        return "\n".join(
            [
                "Scenario:",
                f"- Name: {user.get('name', 'Console Probe User')}",
                f"- Primary language: {user.get('primary_language', 'English')}",
                "- Presenting problem: "
                f"{persona.get('presenting_problem', 'work-related anxiety')}",
                "- Patient style: "
                f"{persona.get('style', 'cooperative, reflective, concise')}",
                "- Preferred therapy style: "
                f"{workflow_preferences.get('therapy_style', 'cbt')}",
                "",
                f"Current phase: {context.simulator_phase}",
                "",
                "Recent transcript:",
                transcript or "(none yet)",
                "",
                f"Console prompt: {context.prompt or 'Your response:'}",
                "",
                "Rules:",
                "- Stay in the patient role.",
                "- Do not ask for recommendations, plans, support, systems, records, backend state, or waiting.",
                "- If therapy has started, respond about symptoms, thoughts, feelings, or the therapist's last message.",
                "",
                "Return exactly one patient reply, under 40 words.",
            ]
        )


def sanitize_user_reply(text: str) -> str:
    cleaned = text.strip()
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return ""

    candidate = ""
    for line in lines:
        normalized = line.lower()
        if normalized.startswith(("therapist:", "assistant:")):
            continue
        if any(
            phrase in normalized
            for phrase in ("here is my response", "this is a test", "as an ai")
        ):
            continue
        candidate = line
        break

    candidate = candidate or lines[0]
    candidate = re.sub(r"^\s*[-*]\s*", "", candidate)
    candidate = re.sub(r"^\s*(patient|user)\s*:\s*", "", candidate, flags=re.I)
    candidate = candidate.strip("\"'")
    candidate = re.sub(r"[ \t]+", " ", candidate).strip()
    words = candidate.split()
    if len(words) > 45:
        candidate = " ".join(words[:45])
    return candidate


def is_valid_user_reply(text: str, max_words: int = 45) -> bool:
    if not text:
        return False
    if "\n" in text:
        return False
    lowered = text.lower()
    rejected = [
        "as an ai",
        "i cannot",
        "i can't roleplay",
        "here is my response",
        "this is a test",
    ]
    if any(phrase in lowered for phrase in rejected):
        return False
    return len(text.split()) <= max_words


def resolve_user_sim_max_tokens() -> int | None:
    """Resolve simulator output cap from env.

    - Explicit positive integer: use that cap.
    - 0 or negative: no cap (omit max_tokens from the API request).
    - Unset: 8192 for APP_ENV=testing; no cap otherwise (production default).
    """
    raw = os.getenv("USER_SIM_LLM_MAX_TOKENS")
    if raw is not None and raw.strip() != "":
        value = int(raw)
        if value <= 0:
            return None
        return value
    if os.getenv("APP_ENV", "production").strip().lower() == "testing":
        return LOCAL_USER_SIM_MAX_TOKENS
    return None


def _preview(text: str | None, limit: int = 500) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()[:limit]
