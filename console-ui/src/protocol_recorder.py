"""Structured recorder for console workflow probes."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ProtocolRecorder:
    """Write JSONL traces and a compact Markdown summary for probe runs."""

    def __init__(
        self,
        output_dir: str | Path,
        scenario_id: str,
        redact_model_context: bool = True,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.scenario_id = scenario_id
        self.redact_model_context = redact_model_context
        self.started_at = datetime.now(timezone.utc)
        timestamp = self.started_at.strftime("%Y%m%dT%H%M%SZ")
        safe_scenario = "".join(
            c if c.isalnum() or c in {"-", "_"} else "_" for c in scenario_id
        )
        self.jsonl_path = self.output_dir / f"{timestamp}_{safe_scenario}.jsonl"
        self.md_path = self.output_dir / f"{timestamp}_{safe_scenario}.md"
        self.db_export_path = (
            self.output_dir / f"{timestamp}_{safe_scenario}_db_export.json"
        )
        self.latest_jsonl_path = self.output_dir / "latest.jsonl"
        self.latest_md_path = self.output_dir / "latest.md"
        self.latest_db_export_path = self.output_dir / "latest_db_export.json"
        self.events: list[dict[str, Any]] = []
        self.assertions: list[dict[str, Any]] = []
        self.status = "RUNNING"

    async def record(self, kind: str, **fields: Any) -> None:
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            **fields,
        }
        self.events.append(event)
        with self.jsonl_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=True, default=str) + "\n")
        shutil.copyfile(self.jsonl_path, self.latest_jsonl_path)

    async def record_prompt(self, context: Any) -> None:
        await self.record(
            "prompt",
            prompt=context.prompt,
            prompt_kind=context.prompt_kind,
            turn_index=context.turn_index,
            workflow_action=_action_name(context.workflow_action),
        )

    async def record_user_input(
        self,
        text: str,
        source: str,
        context: Any,
        used_default: bool = False,
        input_origin: str | None = None,
        fallback_reason: str | None = None,
    ) -> None:
        await self.record(
            "user_input",
            source=source,
            text=text,
            prompt_kind=context.prompt_kind,
            turn_index=context.turn_index,
            used_default=used_default,
            input_origin=input_origin or _default_input_origin(source),
            fallback_reason=fallback_reason,
        )

    async def record_assistant_response(self, text: str) -> None:
        await self.record("assistant_response", text=text)

    async def record_ws_event(self, message: dict[str, Any]) -> None:
        msg_type = message.get("type")
        data = message.get("data") or {}
        event: dict[str, Any] = {"type": msg_type}
        if msg_type == "chat_response_chunk":
            event["is_complete"] = bool(data.get("is_complete"))
            event["chunk_chars"] = len(data.get("chunk") or "")
        elif msg_type == "error":
            event["data"] = data
        elif msg_type in {"session_started", "session_ended", "workflow_next_action"}:
            event["data"] = data
        await self.record("ws_event", **event)

    async def record_workflow_action(self, action: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        previous_action = next(
            (
                event
                for event in reversed(self.events)
                if event.get("kind") == "workflow_action"
            ),
            None,
        )
        elapsed_since_previous = None
        if previous_action:
            try:
                previous_ts = datetime.fromisoformat(str(previous_action["ts"]))
                elapsed_since_previous = (now - previous_ts).total_seconds()
            except (KeyError, TypeError, ValueError):
                elapsed_since_previous = None

        wait_sequence_index = None
        total_wait_seconds = None
        if action.get("required_action") == "wait":
            previous_wait = next(
                (
                    event
                    for event in reversed(self.events)
                    if event.get("kind") == "workflow_action"
                    and event.get("action") == "wait"
                ),
                None,
            )
            if previous_wait:
                wait_sequence_index = (
                    int(previous_wait.get("wait_sequence_index") or 0) + 1
                )
            else:
                wait_sequence_index = 1
            total_wait_seconds = (
                float(previous_wait.get("total_wait_seconds") or 0)
                + float(elapsed_since_previous or 0)
                if previous_wait
                else 0.0
            )
        await self.record(
            "workflow_action",
            action=action.get("required_action"),
            workflow_state=action.get("workflow_state"),
            prompt=action.get("prompt"),
            session_id=action.get("session_id"),
            elapsed_since_previous_action=elapsed_since_previous,
            total_wait_seconds=total_wait_seconds,
            wait_sequence_index=wait_sequence_index,
        )

    async def record_error(self, message: str, data: Any | None = None) -> None:
        await self.record("error", message=message, data=data)

    async def record_assertion(
        self, name: str, passed: bool, detail: str | None = None
    ) -> None:
        assertion = {"name": name, "passed": passed, "detail": detail}
        self.assertions.append(assertion)
        await self.record("assertion", **assertion)

    async def record_model_call(
        self,
        prompt: str,
        raw_response: str,
        sanitized_response: str,
        fallback_used: bool,
        fallback_reason: str | None = None,
    ) -> None:
        if self.redact_model_context:
            prompt = "[redacted]"
            raw_response = "[redacted]"
        await self.record(
            "user_sim_model_call",
            prompt=prompt,
            raw_response=raw_response,
            sanitized_response=sanitized_response,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
        )

    async def record_user_simulator_raw_response(
        self,
        model: str,
        base_url: str,
        http_status: int | None,
        response_shape: str,
        raw_content_preview: str,
        parsed_content_preview: str,
        fallback_reason: str | None = None,
        finish_reason: str | None = None,
        reasoning_content_chars: int = 0,
    ) -> None:
        await self.record(
            "user_simulator_raw_response",
            model=model,
            base_url=base_url,
            http_status=http_status,
            response_shape=response_shape,
            raw_content_preview=raw_content_preview,
            parsed_content_preview=parsed_content_preview,
            fallback_reason=fallback_reason,
            finish_reason=finish_reason,
            reasoning_content_chars=reasoning_content_chars,
        )

    def count_events(self, kind: str, **filters: Any) -> int:
        count = 0
        for event in self.events:
            if event.get("kind") != kind:
                continue
            if all(event.get(key) == value for key, value in filters.items()):
                count += 1
        return count

    def has_ws_error(self) -> bool:
        return any(
            event.get("kind") == "ws_event" and event.get("type") == "error"
            for event in self.events
        )

    def workflow_actions(self) -> list[str]:
        return [
            str(event.get("action"))
            for event in self.events
            if event.get("kind") == "workflow_action" and event.get("action")
        ]

    def latest_workflow_state(self) -> str | None:
        for event in reversed(self.events):
            if event.get("kind") == "workflow_action" and event.get("workflow_state"):
                return str(event["workflow_state"])
            data = event.get("data")
            if isinstance(data, dict) and data.get("workflow_state"):
                return str(data["workflow_state"])
        return None

    def latest_session_id(self) -> str | None:
        for event in reversed(self.events):
            if event.get("session_id"):
                return str(event["session_id"])
            data = event.get("data")
            if isinstance(data, dict) and data.get("session_id"):
                return str(data["session_id"])
        return None

    def observed_session_ids(self) -> list[str]:
        """Return session IDs observed anywhere in recorded event payloads."""
        session_ids: list[str] = []
        seen: set[str] = set()

        def add(value: Any) -> None:
            if value is None:
                return
            session_id = str(value)
            if session_id and session_id not in seen:
                seen.add(session_id)
                session_ids.append(session_id)

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                if "session_id" in value:
                    add(value.get("session_id"))
                for nested in value.values():
                    walk(nested)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        for event in self.events:
            walk(event)
        return session_ids

    def latest_required_action(self) -> str | None:
        for event in reversed(self.events):
            if event.get("kind") == "workflow_action" and event.get("action"):
                return str(event["action"])
            data = event.get("data")
            if isinstance(data, dict) and data.get("required_action"):
                return str(data["required_action"])
        return None

    def session_end_seen(self) -> bool:
        return any(event.get("kind") == "session_ended" for event in self.events)

    def session_end_workflow_state(self) -> str | None:
        for event in reversed(self.events):
            if event.get("kind") != "session_ended":
                continue
            data = event.get("data")
            if isinstance(data, dict) and data.get("workflow_state"):
                return str(data["workflow_state"])
        return None

    def therapy_assistant_turns_after_style_selection(self) -> int:
        style_selected = False
        count = 0
        for event in self.events:
            if event.get("kind") == "therapy_style_selected":
                style_selected = True
            elif style_selected and event.get("kind") == "assistant_response":
                count += 1
        return count

    def fallback_reason_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for event in self.events:
            if event.get("kind") != "user_sim_model_call":
                continue
            if not event.get("fallback_used"):
                continue
            reason = str(event.get("fallback_reason") or "unknown")
            counts[reason] = counts.get(reason, 0) + 1
        return counts

    def total_wait_seconds_before(self, action_name: str) -> float:
        total = 0.0
        for event in self.events:
            if event.get("kind") != "workflow_action":
                continue
            if event.get("action") == action_name:
                return total
            if event.get("action") == "wait":
                total = max(total, float(event.get("total_wait_seconds") or 0))
        return total

    def assessment_wait_seconds(self) -> float | None:
        """Return wall-clock seconds from first wait action to style selection."""
        wait_started_at: datetime | None = None
        for event in self.events:
            if event.get("kind") != "workflow_action":
                continue
            action = event.get("action")
            if action == "wait" and wait_started_at is None:
                wait_started_at = _parse_event_ts(event)
            if action == "select_therapy_style" and wait_started_at is not None:
                selected_at = _parse_event_ts(event)
                if selected_at is None:
                    return None
                return max(0.0, (selected_at - wait_started_at).total_seconds())
        return None

    def style_submit_to_style_selected_seconds(self) -> float | None:
        """Return seconds from submitted therapy style input to saved selection."""
        latest_style_submit_at: datetime | None = None
        for event in self.events:
            if (
                event.get("kind") == "user_input"
                and event.get("prompt_kind") == "therapy_style"
            ):
                latest_style_submit_at = _parse_event_ts(event)
                continue
            if event.get("kind") == "therapy_style_selected":
                selected_at = _parse_event_ts(event)
                if latest_style_submit_at is None or selected_at is None:
                    return None
                return max(0.0, (selected_at - latest_style_submit_at).total_seconds())
        return None

    def style_selected_to_therapy_ready_seconds(self) -> float | None:
        """Return wall-clock seconds from saved style selection to continue_therapy."""
        style_selected_at: datetime | None = None
        for event in self.events:
            if event.get("kind") == "therapy_style_selected":
                style_selected_at = _parse_event_ts(event)
                continue
            if (
                style_selected_at is not None
                and event.get("kind") == "workflow_action"
                and event.get("action") == "continue_therapy"
            ):
                therapy_ready_at = _parse_event_ts(event)
                if therapy_ready_at is None:
                    return None
                return max(0.0, (therapy_ready_at - style_selected_at).total_seconds())
        return None

    def plan_update_complete_after_plan_update_seconds(self) -> float | None:
        """Return seconds from plan update start to observed plan_update_complete."""
        plan_update_started_at: datetime | None = None
        for event in self.events:
            workflow_state = _event_workflow_state(event)
            if (
                workflow_state == "plan_update_in_progress"
                and plan_update_started_at is None
            ):
                plan_update_started_at = _parse_event_ts(event)
            if (
                workflow_state == "plan_update_complete"
                and plan_update_started_at is not None
            ):
                completed_at = _parse_event_ts(event)
                if completed_at is None:
                    return None
                return max(0.0, (completed_at - plan_update_started_at).total_seconds())
        return None

    async def write_summary(
        self,
        status: str,
        scenario: dict[str, Any],
        extra_assertions: list[dict[str, Any]] | None = None,
    ) -> None:
        self.status = status
        assertions = [*self.assertions, *(extra_assertions or [])]
        duration = (datetime.now(timezone.utc) - self.started_at).total_seconds()
        user_turns = self.count_events("user_input", prompt_kind="chat")
        assistant_turns = self.count_events("assistant_response")
        actions = self.workflow_actions()
        transcript = self._transcript_excerpt()
        user_messages = [
            str(event.get("text") or "")
            for event in self.events
            if event.get("kind") == "user_input" and event.get("prompt_kind") == "chat"
        ]
        assistant_messages = [
            str(event.get("text") or "")
            for event in self.events
            if event.get("kind") == "assistant_response"
        ]
        errors = [event for event in self.events if event.get("kind") == "error"]
        fallback_count = sum(
            1
            for event in self.events
            if event.get("kind") == "user_sim_model_call" and event.get("fallback_used")
        )
        fallback_rate = fallback_count / user_turns if user_turns else 0
        fallback_reasons = self.fallback_reason_counts()
        criteria = scenario.get("success_criteria") or {}
        fallback_warn = float(criteria.get("warn_user_sim_fallback_rate", 0.2))
        fallback_health = _fallback_health(fallback_rate, fallback_warn)
        wait_before_style = self.total_wait_seconds_before("select_therapy_style")
        assessment_wait = self.assessment_wait_seconds()
        style_submit_to_selected = self.style_submit_to_style_selected_seconds()
        style_selected_to_therapy = self.style_selected_to_therapy_ready_seconds()
        wait_warn = float(criteria.get("warn_wait_seconds_before_style_selection", 0))
        wait_health = _wait_health(wait_before_style, wait_warn)
        session_end_state = self.session_end_workflow_state()

        lines = [
            "# Console LLM Workflow Probe Result",
            "",
            f"Status: {status}",
            f"Scenario: {scenario.get('id', self.scenario_id)}",
            f"Started: {self.started_at.isoformat()}",
            f"Duration: {duration:.1f}s",
            "",
            "## Milestones",
            "",
            "- Session started events: "
            f"{self.count_events('ws_event', type='session_started')}",
            f"- Profiles created: {self.count_events('profile_created')}",
            f"- Profiles selected: {self.count_events('profile_selected')}",
            f"- Therapy styles selected: {self.count_events('therapy_style_selected')}",
            f"- User chat turns: {user_turns}",
            f"- Unique user chat messages: {len(set(user_messages))}",
            f"- Assistant turns: {assistant_turns}",
            f"- Unique assistant responses: {len(set(assistant_messages))}",
            f"- User simulator fallbacks: {fallback_count}",
            f"- User simulator fallback rate: {fallback_rate:.2f} ({fallback_health})",
            "- Fallback reasons: "
            f"{_format_counts(fallback_reasons) if fallback_reasons else 'none'}",
            "- Wait before therapy style selection: "
            f"{wait_before_style:.1f}s"
            f"{f' ({wait_health})' if wait_warn else ''}",
            (
                "- assessment_wait_seconds: " f"{assessment_wait:.1f}s"
                if assessment_wait is not None
                else "- assessment_wait_seconds: unknown"
            ),
            (
                "- style_submit_to_style_selected_seconds: "
                f"{style_submit_to_selected:.1f}s"
                if style_submit_to_selected is not None
                else "- style_submit_to_style_selected_seconds: unknown"
            ),
            (
                "- style_selected_to_therapy_ready_seconds: "
                f"{style_selected_to_therapy:.1f}s"
                if style_selected_to_therapy is not None
                else "- style_selected_to_therapy_ready_seconds: unknown"
            ),
            f"- Last valid workflow state seen: {self.latest_workflow_state() or 'unknown'}",
            f"- Last required action seen: {self.latest_required_action() or 'unknown'}",
            f"- Session end seen: {self.session_end_seen()}",
            f"- Workflow state at session end: {session_end_state or 'unknown'}",
            "- Therapy assistant turns after style selection: "
            f"{self.therapy_assistant_turns_after_style_selection()}",
            f"- Workflow actions: {', '.join(actions) if actions else 'none recorded'}",
            f"- WebSocket errors: {self.count_events('ws_event', type='error')}",
            "",
            "## Errors",
            "",
        ]
        if errors:
            for error in errors:
                lines.append(
                    f"- {error.get('message')}: {_format_error_data(error.get('data'))}"
                )
        else:
            lines.append("- No errors recorded.")

        lines.extend(
            [
                "",
                "## Assertions",
                "",
            ]
        )
        if assertions:
            for assertion in assertions:
                result = "PASS" if assertion.get("passed") else "FAIL"
                detail = assertion.get("detail")
                suffix = f" - {detail}" if detail else ""
                lines.append(f"- {result}: {assertion.get('name')}{suffix}")
        else:
            lines.append("- No assertions recorded.")

        lines.extend(
            [
                "",
                "## Transcript Excerpt",
                "",
                transcript or "No transcript events recorded.",
                "",
                "## Files",
                "",
                f"- JSONL trace: {self.jsonl_path}",
                f"- Markdown summary: {self.md_path}",
                f"- DB export: {self.db_export_path}",
            ]
        )

        self.md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        shutil.copyfile(self.md_path, self.latest_md_path)

    def _transcript_excerpt(self) -> str:
        transcript_events = [
            event
            for event in self.events
            if event.get("kind") in {"user_input", "assistant_response"}
        ][-6:]
        parts: list[str] = []
        for event in transcript_events:
            if event.get("kind") == "user_input":
                role = "User"
                if event.get("input_origin") == "fallback":
                    reason = event.get("fallback_reason") or "unknown"
                    role = f"User [fallback: {reason}]"
                elif event.get("input_origin"):
                    role = f"User [{event.get('input_origin')}]"
            else:
                role = "Therapist"
            text = str(event.get("text") or "")
            parts.append(f"### {role}\n{text}")
        return "\n\n".join(parts)


def env_trace_prompts_enabled() -> bool:
    return os.getenv("USER_SIM_TRACE_PROMPTS", "").strip() == "1"


def _action_name(action: dict[str, Any] | None) -> str | None:
    if not action:
        return None
    return action.get("required_action")


def _default_input_origin(source: str) -> str:
    if source == "LLMSimulatedUserProvider":
        return "local_llm"
    if source == "ScriptedInputProvider":
        return "scripted"
    if source == "HumanInputProvider":
        return "human"
    return source


def _format_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{reason}: {count}" for reason, count in sorted(counts.items()))


def _format_error_data(data: Any) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        text = data
    else:
        text = json.dumps(data, ensure_ascii=True, default=str)
    return text if len(text) <= 800 else f"{text[:800]}..."


def _fallback_health(rate: float, warn_threshold: float) -> str:
    if rate == 0:
        return "PASS"
    if rate <= warn_threshold:
        return "WARN"
    return "FAIL"


def _wait_health(wait_seconds: float, warn_threshold: float) -> str:
    if wait_seconds <= warn_threshold:
        return "PASS"
    return "WARN"


def _parse_event_ts(event: dict[str, Any]) -> datetime | None:
    try:
        return datetime.fromisoformat(str(event["ts"]))
    except (KeyError, TypeError, ValueError):
        return None


def _event_workflow_state(event: dict[str, Any]) -> str | None:
    if event.get("workflow_state"):
        return str(event["workflow_state"])
    data = event.get("data")
    if isinstance(data, dict) and data.get("workflow_state"):
        return str(data["workflow_state"])
    return None
