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
        self.created_rows: dict[str, list[dict[str, Any]]] = {}
        self.user_id: str | None = None
        self.trace_path = self.output_dir / "trace.jsonl"
        self.debug_raw_polls = False
        self._pending_poll: dict[str, Any] | None = None

    async def emit(self, event: str, **fields: Any) -> None:
        if event == "ws_message":
            await self.record("ws_event", **_compact_ws_message(fields["message"]))
        elif event == "workflow_action":
            action = fields["action"]
            kind = "workflow_wait" if action.get("required_action") == "wait" else "workflow_action"
            await self.record(
                kind,
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
        if kind in {"workflow_wait", "post_session_state", "post_session_enrichment"} and not self.debug_raw_polls:
            await self._record_collapsed_poll(kind, fields)
            return
        await self._flush_pending_poll()
        event = {"ts": datetime.now(UTC).isoformat(), "kind": kind, **fields}
        self._append_event(event)

    def _append_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        with self.trace_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=True, default=str) + "\n")

    async def _record_collapsed_poll(self, kind: str, fields: dict[str, Any]) -> None:
        now = datetime.now(UTC)
        signature = json.dumps(fields, sort_keys=True, default=str)
        if self._pending_poll and self._pending_poll["signature"] == signature and self._pending_poll["kind"] == kind:
            self._pending_poll["count"] += 1
            self._pending_poll["last_seen"] = now
            return
        await self._flush_pending_poll()
        self._pending_poll = {
            "kind": kind,
            "fields": fields,
            "signature": signature,
            "count": 1,
            "first_seen": now,
            "last_seen": now,
        }

    async def _flush_pending_poll(self) -> None:
        if not self._pending_poll:
            return
        pending = self._pending_poll
        self._pending_poll = None
        self._append_event(
            {
                "ts": pending["first_seen"].isoformat(),
                "kind": f"{pending['kind']}_summary",
                **pending["fields"],
                "count": pending["count"],
                "duration_ms": round(
                    (pending["last_seen"] - pending["first_seen"]).total_seconds() * 1000,
                    3,
                ),
            }
        )

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
        await self._flush_pending_poll()
        phase_timings = self._load_phase_timings()
        thresholds = scenario.get("timing_warning_thresholds_ms", {})
        overruns = {
            phase: {"actual_ms": value, "threshold_ms": thresholds[phase]}
            for phase, value in phase_timings.items()
            if phase in thresholds and value > thresholds[phase]
        }
        metadata = {
            "status": status,
            "scenario_id": self.scenario_id,
            "run_id": self.output_dir.name,
            "started_at": self.started_at.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "user_id": self.user_id,
            "session_ids": self.observed_session_ids(),
            "plan_ids": [
                row.get("plan_id")
                for row in self.created_rows.get("therapy_plans", [])
                if row.get("plan_id")
            ],
            "phase_timings_ms": phase_timings,
            "timing_warning_overruns": overruns,
        }
        (self.output_dir / "metadata.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
        (self.output_dir / "run_manifest.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
        transcript = [
            f"- **{('patient' if e['kind'] == 'user_input' else 'therapist')}**: {e.get('text', '')}"
            for e in self.events
            if (
                e["kind"] == "assistant_response"
                or (
                    e["kind"] == "user_input"
                    and e.get("prompt_kind") == "chat"
                    and not str(e.get("text") or "").startswith("/")
                )
            )
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
            + "\n\n## Phase Timings\n\n"
            + "\n".join(f"- `{phase}`: {value:.3f} ms" for phase, value in phase_timings.items())
            + "\n\n## Timing Warnings\n\n"
            + ("\n".join(f"- `{phase}` exceeded {detail['threshold_ms']} ms ({detail['actual_ms']:.3f} ms)" for phase, detail in overruns.items()) or "- None")
            + "\n",
            encoding="utf-8",
        )

    def _load_phase_timings(self) -> dict[str, float]:
        metrics_path = self.output_dir / "backend_llm_calls.jsonl"
        totals: dict[str, float] = {}
        if not metrics_path.exists():
            return totals
        for line in metrics_path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record.get("status") != "finish" or not record.get("phase"):
                continue
            phase = f"{record['phase']}_ms"
            totals[phase] = totals.get(phase, 0.0) + float(record.get("latency_ms") or 0.0)
        return totals


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
