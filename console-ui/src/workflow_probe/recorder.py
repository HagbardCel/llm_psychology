"""Run-scoped artifact recorder for workflow probes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class ProbeRecorder:
    def __init__(self, output_dir: str | Path, scenario_id: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.scenario_id = scenario_id
        self.started_at = datetime.now(UTC)
        self.events: list[dict[str, Any]] = []
        self.assertions: list[dict[str, Any]] = []
        self.trace_path = self.output_dir / "trace.jsonl"

    async def emit(self, event: str, **fields: Any) -> None:
        if event == "ws_message":
            await self.record("ws_event", **_compact_ws_message(fields["message"]))
        elif event == "workflow_action":
            action = fields["action"]
            await self.record(
                "workflow_action",
                action=action.get("required_action"),
                workflow_state=action.get("workflow_state"),
                session_id=action.get("session_id"),
                state_signature=action.get("state_signature"),
                delivery_source=fields.get("delivery_source"),
            )
        elif event == "prompt":
            context = fields["context"]
            await self.record("prompt", prompt=context.prompt, prompt_kind=context.prompt_kind)
        elif event == "user_input":
            context = fields["context"]
            await self.record(
                "user_input",
                text=fields.get("text"),
                source=fields.get("source"),
                prompt_kind=context.prompt_kind,
                input_origin=fields.get("input_origin"),
                used_default=fields.get("used_default", False),
            )
        else:
            await self.record(event, **fields)

    async def record(self, kind: str, **fields: Any) -> None:
        event = {"ts": datetime.now(UTC).isoformat(), "kind": kind, **fields}
        self.events.append(event)
        with self.trace_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=True, default=str) + "\n")

    async def record_assertion(self, name: str, passed: bool, detail: str = "") -> None:
        assertion = {"name": name, "passed": passed, "detail": detail}
        self.assertions.append(assertion)
        await self.record("assertion", **assertion)

    async def record_model_call(self, **fields: Any) -> None:
        fields.pop("prompt", None)
        fields.pop("raw_response", None)
        await self.record("user_sim_model_call", **fields)

    async def record_user_simulator_raw_response(self, **fields: Any) -> None:
        await self.record("user_simulator_raw_response", **fields)

    def observed_session_ids(self) -> list[str]:
        ids: list[str] = []
        for event in self.events:
            for value in _walk_session_ids(event):
                if value not in ids:
                    ids.append(value)
        return ids

    async def write_artifacts(self, status: str, scenario: dict[str, Any]) -> None:
        metadata = {
            "status": status,
            "scenario_id": self.scenario_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
        }
        (self.output_dir / "metadata.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
        transcript = [
            f"- **{('patient' if e['kind'] == 'user_input' else 'therapist')}**: {e.get('text', '')}"
            for e in self.events
            if (e["kind"] == "assistant_response" or (e["kind"] == "user_input" and e.get("prompt_kind") == "chat"))
        ]
        (self.output_dir / "transcript.md").write_text(
            "# Transcript\n\n" + "\n".join(transcript) + "\n", encoding="utf-8"
        )
        checks = [
            f"- {'PASS' if item['passed'] else 'FAIL'}: {item['name']} {item['detail']}"
            for item in self.assertions
        ]
        (self.output_dir / "summary.md").write_text(
            f"# Workflow Probe: {status}\n\nScenario: `{self.scenario_id}`\n\n"
            + "\n".join(checks)
            + "\n",
            encoding="utf-8",
        )


def _compact_ws_message(message: dict[str, Any]) -> dict[str, Any]:
    data = message.get("data") or {}
    result: dict[str, Any] = {"type": message.get("type")}
    if message.get("type") == "chat_response_chunk":
        result.update(is_complete=bool(data.get("is_complete")), chunk_chars=len(data.get("chunk") or ""))
    else:
        result["data"] = data
    return result


def _walk_session_ids(value: Any):
    if isinstance(value, dict):
        if value.get("session_id"):
            yield str(value["session_id"])
        for nested in value.values():
            yield from _walk_session_ids(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_session_ids(nested)
