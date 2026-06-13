"""Run-scoped artifact recorder for workflow probes."""

from __future__ import annotations

import json
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from psychoanalyst_app.shared.intake_slot_evidence import (
    HARD_REQUIRED_INTAKE_SLOTS,
    REQUIRED_INTAKE_SLOTS,
    SOFT_REQUIRED_INTAKE_SLOTS,
    covered_slots_from_evidence,
    intake_slot_evidence_from_transcript,
    next_required_follow_up_slot,
)


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
        self._logical_workflow_keys: set[str] = set()

    async def emit(self, event: str, **fields: Any) -> None:
        if event == "ws_message":
            await self.record("ws_event", **_compact_ws_message(fields["message"]))
        elif event == "workflow_action":
            action = fields["action"]
            delivery_source = fields.get("delivery_source")
            logical_key = _workflow_action_key(action)
            payload_hash = _payload_hash(action)
            await self.record(
                "raw_workflow_action",
                action=action.get("required_action"),
                workflow_state=action.get("workflow_state"),
                session_id=action.get("session_id"),
                state_signature=action.get("state_signature"),
                delivery_source=delivery_source,
                logical_key=logical_key,
                payload_hash=payload_hash,
            )
            if logical_key in self._logical_workflow_keys:
                return
            self._logical_workflow_keys.add(logical_key)
            kind = (
                "workflow_wait"
                if action.get("required_action") == "wait"
                else "workflow_action"
            )
            await self.record(
                kind,
                action=action.get("required_action"),
                workflow_state=action.get("workflow_state"),
                session_id=action.get("session_id"),
                state_signature=action.get("state_signature"),
                delivery_source=delivery_source,
                logical_key=logical_key,
            )
        elif event == "job_status":
            status = fields["status"]
            await self.record(
                "job_status",
                job_id=status.get("job_id"),
                job_type=status.get("job_type"),
                status=status.get("status"),
                current_step=status.get("current_step"),
                workflow_state=status.get("workflow_state"),
                session_id=status.get("session_id"),
                delivery_source=fields.get("delivery_source"),
                data=status,
            )
        elif event == "prompt":
            context = fields["context"]
            await self.record(
                "prompt",
                prompt=context.prompt,
                prompt_kind=context.prompt_kind,
            )
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
        if (
            kind
            in {
                "workflow_wait",
                "post_session_state",
                "post_session_enrichment",
                "post_session_job_status",
            }
            and not self.debug_raw_polls
        ):
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
        if (
            self._pending_poll
            and self._pending_poll["signature"] == signature
            and self._pending_poll["kind"] == kind
        ):
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
                    (pending["last_seen"] - pending["first_seen"]).total_seconds()
                    * 1000,
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
        finished_at = datetime.now(UTC)
        timing = self._load_llm_timing_summary()
        phase_timings = timing["phase_timings_ms"]
        timing["wall_clock_runtime_ms"] = round(
            (finished_at - self.started_at).total_seconds() * 1000,
            3,
        )
        timing.update(self._post_session_poll_timing())
        timing.update(self._job_status_timing())
        timing["response_latency_summary"] = self._response_latency_summary()
        timing["latency_undercoverage"] = self._latency_undercoverage_summary(
            timing["response_latency_summary"],
            timing,
            scenario,
        )
        thresholds = scenario.get("timing_warning_thresholds_ms", {})
        overruns = {
            phase: {"actual_ms": value, "threshold_ms": thresholds[phase]}
            for phase, value in phase_timings.items()
            if phase in thresholds and value > thresholds[phase]
        }
        structured_sessions = self._manifest_sessions()
        structured_plans = self._manifest_plans(structured_sessions)
        style_selection = self._manifest_style_selection()
        intake_diagnostics = self._intake_completion_diagnostics()
        failure_summary = self._failure_summary(status, intake_diagnostics)
        metadata = {
            "status": status,
            "scenario_id": self.scenario_id,
            "run_id": self.output_dir.name,
            "started_at": self.started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "user_id": self.user_id,
            "session_ids": self.observed_session_ids(),
            "sessions": structured_sessions,
            "plan_ids": [
                row.get("plan_id")
                for row in self.created_rows.get("therapy_plans", [])
                if row.get("plan_id")
            ],
            "plans": structured_plans,
            "style_selection": style_selection,
            "phase_timings_ms": phase_timings,
            "timing": timing,
            "timing_warning_overruns": overruns,
            "intake_completion_diagnostics": intake_diagnostics,
            "failure_summary": failure_summary,
            "workflow_actions": self._workflow_action_summary(),
            "job_status": self._job_status_summary(),
        }
        (self.output_dir / "metadata.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
        (self.output_dir / "run_manifest.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
        (self.output_dir / "transcript.md").write_text(
            self._render_transcript(), encoding="utf-8"
        )
        (self.output_dir / "timeline.md").write_text(
            self._render_timeline(), encoding="utf-8"
        )
        if intake_diagnostics:
            (self.output_dir / "intake_completion_diagnostics.json").write_text(
                json.dumps(intake_diagnostics, indent=2) + "\n",
                encoding="utf-8",
            )
        if failure_summary:
            (self.output_dir / "failure_summary.md").write_text(
                self._render_failure_summary(failure_summary),
                encoding="utf-8",
            )
        checks = [
            f"- {'PASS' if item['passed'] else 'FAIL'}: {item['name']} {item['detail']}"
            for item in self.assertions
        ]
        root_cause_section = ""
        if failure_summary:
            root_cause_section = (
                "\n\n## Root Cause Summary\n\n"
                + self._render_failure_summary(failure_summary).split("\n\n", 1)[1].rstrip()
                + "\n"
            )
        (self.output_dir / "summary.md").write_text(
            f"# Workflow Probe: {status}\n\nScenario: `{self.scenario_id}`\n\n"
            + "\n".join(checks)
            + root_cause_section
            + "\n\n## Phase Timings\n\n"
            + "\n".join(
                f"- `{phase}`: {value:.3f} ms"
                for phase, value in phase_timings.items()
            )
            + "\n\n## User-Visible Response Timings\n\n"
            + self._render_response_latency_summary(
                timing["response_latency_summary"]
            )
            + "\n\n## Latency Undercoverage\n\n"
            + self._render_latency_undercoverage_summary(
                timing["latency_undercoverage"]
            )
            + "\n\n## Workflow Action Deliveries\n\n"
            + self._render_workflow_action_summary()
            + "\n\n## Job Status\n\n"
            + self._render_job_status_summary()
            + "\n\n## Timing Warnings\n\n"
            + (
                "\n".join(
                    f"- `{phase}` exceeded {detail['threshold_ms']} ms "
                    f"({detail['actual_ms']:.3f} ms)"
                    for phase, detail in overruns.items()
                )
                or "- None"
            )
            + "\n",
            encoding="utf-8",
        )

    def _load_phase_timings(self) -> dict[str, float]:
        return self._load_llm_timing_summary()["phase_timings_ms"]

    def _load_llm_timing_summary(self) -> dict[str, Any]:
        metrics_path = self.output_dir / "backend_llm_calls.jsonl"
        totals: dict[str, float] = {}
        provider_totals: dict[str, float] = {}
        provider_boundary_totals: dict[str, float] = {}
        prompt_eval_totals: dict[str, float] = {}
        generation_totals: dict[str, float] = {}
        phase_chunk_counts: dict[str, int] = {}
        phase_completion_chars: dict[str, int] = {}
        token_status_counts: dict[str, int] = {}
        total_latency = 0.0
        provider_total_latency = 0.0
        provider_boundary_total = 0.0
        prompt_eval_total = 0.0
        generation_total = 0.0
        stream_chunk_count = 0
        completion_chars = 0
        unphased_latency = 0.0
        unphased_count = 0
        finished_count = 0
        if not metrics_path.exists():
            return {
                "phase_timings_ms": totals,
                "llm_total_latency_ms": total_latency,
                "llm_provider_latency_ms": provider_total_latency,
                "phase_provider_timings_ms": provider_totals,
                "llm_provider_boundary_ms": provider_boundary_total,
                "phase_provider_boundary_timings_ms": provider_boundary_totals,
                "llm_prompt_eval_ms": prompt_eval_total,
                "phase_prompt_eval_timings_ms": prompt_eval_totals,
                "llm_generation_ms": generation_total,
                "phase_generation_timings_ms": generation_totals,
                "llm_stream_chunk_count": stream_chunk_count,
                "phase_stream_chunk_counts": phase_chunk_counts,
                "llm_completion_chars": completion_chars,
                "phase_completion_chars": phase_completion_chars,
                "token_count_status_counts": token_status_counts,
                "llm_finished_count": finished_count,
                "llm_unphased_latency_ms": unphased_latency,
                "llm_unphased_finish_count": unphased_count,
            }
        for line in metrics_path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record.get("status") != "finish":
                continue
            finished_count += 1
            token_status = str(record.get("token_count_status") or "unknown")
            token_status_counts[token_status] = (
                token_status_counts.get(token_status, 0) + 1
            )
            provider_latency = _float_value(
                record.get("provider_latency_ms"),
                record.get("latency_ms"),
            )
            latency = float(record.get("total_wall_ms") or provider_latency)
            provider_boundary = _float_value(record.get("request_boundary_ms"))
            prompt_eval = _float_value(record.get("prompt_eval_ms"))
            generation = _float_value(record.get("generation_ms"))
            chunks = int(record.get("chunk_count") or 0)
            chars = int(record.get("completion_chars") or 0)
            total_latency += latency
            provider_total_latency += provider_latency
            provider_boundary_total += provider_boundary
            prompt_eval_total += prompt_eval
            generation_total += generation
            stream_chunk_count += chunks
            completion_chars += chars
            if not record.get("phase"):
                unphased_latency += latency
                unphased_count += 1
                continue
            phase = f"{record['phase']}_ms"
            totals[phase] = totals.get(phase, 0.0) + latency
            provider_totals[phase] = provider_totals.get(phase, 0.0) + provider_latency
            provider_boundary_totals[phase] = (
                provider_boundary_totals.get(phase, 0.0) + provider_boundary
            )
            prompt_eval_totals[phase] = prompt_eval_totals.get(phase, 0.0) + prompt_eval
            generation_totals[phase] = generation_totals.get(phase, 0.0) + generation
            phase_chunk_counts[phase] = phase_chunk_counts.get(phase, 0) + chunks
            phase_completion_chars[phase] = (
                phase_completion_chars.get(phase, 0) + chars
            )
        return {
            "phase_timings_ms": totals,
            "llm_total_latency_ms": round(total_latency, 3),
            "llm_provider_latency_ms": round(provider_total_latency, 3),
            "phase_provider_timings_ms": provider_totals,
            "llm_provider_boundary_ms": round(provider_boundary_total, 3),
            "phase_provider_boundary_timings_ms": provider_boundary_totals,
            "llm_prompt_eval_ms": round(prompt_eval_total, 3),
            "phase_prompt_eval_timings_ms": prompt_eval_totals,
            "llm_generation_ms": round(generation_total, 3),
            "phase_generation_timings_ms": generation_totals,
            "llm_stream_chunk_count": stream_chunk_count,
            "phase_stream_chunk_counts": phase_chunk_counts,
            "llm_completion_chars": completion_chars,
            "phase_completion_chars": phase_completion_chars,
            "token_count_status_counts": token_status_counts,
            "llm_finished_count": finished_count,
            "llm_unphased_latency_ms": round(unphased_latency, 3),
            "llm_unphased_finish_count": unphased_count,
        }

    def _post_session_poll_timing(self) -> dict[str, Any]:
        count = 0
        duration = 0.0
        for event in self.events:
            if event["kind"] == "post_session_state_summary":
                count += int(event.get("count") or 0)
                duration += float(event.get("duration_ms") or 0.0)
        return {
            "post_session_poll_count": count,
            "post_session_poll_duration_ms": round(duration, 3),
        }

    def _job_status_timing(self) -> dict[str, Any]:
        ws_count = sum(
            1
            for event in self.events
            if event.get("kind") == "job_status"
            and event.get("delivery_source") == "websocket"
        )
        fallback_count = 0
        fallback_duration = 0.0
        for event in self.events:
            if event["kind"] == "post_session_job_status_summary":
                fallback_count += int(event.get("count") or 0)
                fallback_duration += float(event.get("duration_ms") or 0.0)
        return {
            "job_status_ws_event_count": ws_count,
            "job_status_http_fallback_poll_count": fallback_count,
            "job_status_http_fallback_poll_duration_ms": round(fallback_duration, 3),
        }

    def _response_latency_summary(self) -> dict[str, Any]:
        samples: list[dict[str, Any]] = []
        current_session_type = "unknown"
        pending_user: dict[str, Any] | None = None
        chunks: list[dict[str, Any]] = []

        for event in self.events:
            if event.get("kind") == "session_started":
                data = _event_data_dict(event)
                current_session_type = str(data.get("session_type") or "unknown")
            if (
                event.get("kind") == "ws_event"
                and event.get("type") == "session_started"
            ):
                data = _event_data_dict(event)
                current_session_type = str(data.get("session_type") or "unknown")

            if (
                event.get("kind") == "user_input"
                and event.get("prompt_kind") == "chat"
                and not str(event.get("text") or "").startswith("/")
            ):
                pending_user = {
                    "event": event,
                    "session_type": current_session_type,
                }
                chunks = []
                continue

            if not pending_user:
                continue

            if (
                event.get("kind") == "ws_event"
                and event.get("type") == "chat_response_chunk"
            ):
                chunks.append(event)
                continue

            if event.get("kind") != "assistant_response":
                continue

            user_ts = _parse_event_ts(pending_user["event"])
            assistant_ts = _parse_event_ts(event)
            first_chunk = next(
                (chunk for chunk in chunks if not chunk.get("is_complete")), None
            )
            complete_chunk = next(
                (chunk for chunk in chunks if chunk.get("is_complete")), None
            )
            first_chunk_ts = _parse_event_ts(first_chunk) if first_chunk else None
            complete_ts = _parse_event_ts(complete_chunk) if complete_chunk else None
            samples.append(
                {
                    "session_type": pending_user["session_type"],
                    "user_visible_ms": _elapsed_ms(user_ts, assistant_ts),
                    "ttft_ms": _elapsed_ms(user_ts, first_chunk_ts),
                    "stream_ms": _elapsed_ms(first_chunk_ts, complete_ts),
                    "chars": len(str(event.get("text") or "")),
                }
            )
            pending_user = None
            chunks = []

        by_session_type: dict[str, list[dict[str, Any]]] = {}
        for sample in samples:
            by_session_type.setdefault(str(sample["session_type"]), []).append(sample)

        return {
            "overall": _latency_stats(samples),
            "by_session_type": {
                session_type: _latency_stats(items)
                for session_type, items in sorted(by_session_type.items())
            },
            "samples": samples,
        }

    def _render_response_latency_summary(self, summary: dict[str, Any]) -> str:
        rows = ["| Scope | Count | P50 | P95 | Max | TTFT P95 | Stream P95 |", "|---|---:|---:|---:|---:|---:|---:|"]
        scopes = [("overall", summary.get("overall") or {})]
        scopes.extend(
            (
                f"session:{name}",
                stats,
            )
            for name, stats in (summary.get("by_session_type") or {}).items()
        )
        for name, stats in scopes:
            rows.append(
                f"| {name} | {int(stats.get('count') or 0)} | "
                f"{float(stats.get('user_visible_p50_ms') or 0):.3f} | "
                f"{float(stats.get('user_visible_p95_ms') or 0):.3f} | "
                f"{float(stats.get('user_visible_max_ms') or 0):.3f} | "
                f"{float(stats.get('ttft_p95_ms') or 0):.3f} | "
                f"{float(stats.get('stream_p95_ms') or 0):.3f} |"
            )
        return "\n".join(rows)

    def _latency_undercoverage_summary(
        self,
        response_summary: dict[str, Any],
        timing: dict[str, Any],
        scenario: dict[str, Any],
    ) -> dict[str, Any]:
        warning_min_coverage = float(
            scenario.get("timing_undercoverage_warning_min_coverage_ratio", 0.8)
        )
        thresholds = scenario.get("timing_undercoverage_thresholds", {})
        scopes = {
            "overall": self._latency_undercoverage_scope(
                response_summary.get("samples") or [],
                timing,
                [
                    "intake_response_ms",
                    "therapy_opening_ms",
                    "therapy_response_ms",
                ],
            ),
            "intake": self._latency_undercoverage_scope(
                [
                    sample
                    for sample in response_summary.get("samples") or []
                    if sample.get("session_type") == "intake"
                ],
                timing,
                ["intake_response_ms"],
            ),
            "therapy": self._latency_undercoverage_scope(
                [
                    sample
                    for sample in response_summary.get("samples") or []
                    if sample.get("session_type") == "therapy"
                ],
                timing,
                ["therapy_opening_ms", "therapy_response_ms"],
            ),
        }
        warnings = []
        failures = []
        for name, detail in scopes.items():
            coverage_ratio = detail.get("coverage_ratio")
            if coverage_ratio is None:
                if detail.get("user_visible_total_ms"):
                    warnings.append(
                        {
                            "scope": name,
                            "reason": "No matching backend user-visible LLM timing",
                        }
                    )
                continue
            if coverage_ratio < warning_min_coverage:
                warnings.append(
                    {
                        "scope": name,
                        "coverage_ratio": coverage_ratio,
                        "threshold": warning_min_coverage,
                    }
                )
            threshold_key = f"{name}_min_coverage_ratio"
            if threshold_key in thresholds and coverage_ratio < float(
                thresholds[threshold_key]
            ):
                failures.append(
                    {
                        "scope": name,
                        "coverage_ratio": coverage_ratio,
                        "threshold": float(thresholds[threshold_key]),
                    }
                )
        return {
            "approximate": True,
            "warning_min_coverage_ratio": warning_min_coverage,
            "scopes": scopes,
            "warnings": warnings,
            "failures": failures,
        }

    def _latency_undercoverage_scope(
        self,
        samples: list[dict[str, Any]],
        timing: dict[str, Any],
        phase_keys: list[str],
    ) -> dict[str, Any]:
        phase_timings = timing.get("phase_timings_ms") or {}
        user_visible_total = round(
            sum(
                float(sample.get("user_visible_ms") or 0.0)
                for sample in samples
                if sample.get("user_visible_ms") is not None
            ),
            3,
        )
        backend_total = round(
            sum(float(phase_timings.get(phase) or 0.0) for phase in phase_keys),
            3,
        )
        if user_visible_total <= 0:
            coverage_ratio = None
            undercoverage_ratio = None
        elif backend_total <= 0:
            coverage_ratio = None
            undercoverage_ratio = None
        else:
            coverage_ratio = round(min(backend_total / user_visible_total, 1.0), 3)
            undercoverage_ratio = round(user_visible_total / backend_total, 3)
        return {
            "sample_count": len(samples),
            "phase_keys": phase_keys,
            "user_visible_total_ms": user_visible_total,
            "backend_phase_total_ms": backend_total,
            "coverage_ratio": coverage_ratio,
            "undercoverage_ratio": undercoverage_ratio,
        }

    def _render_latency_undercoverage_summary(self, summary: dict[str, Any]) -> str:
        rows = [
            "| Scope | Samples | User Visible | Backend Timed | Coverage | User/Backend |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for name, detail in (summary.get("scopes") or {}).items():
            rows.append(
                f"| {name} | {int(detail.get('sample_count') or 0)} | "
                f"{float(detail.get('user_visible_total_ms') or 0):.3f} | "
                f"{float(detail.get('backend_phase_total_ms') or 0):.3f} | "
                f"{_format_optional_float(detail.get('coverage_ratio'))} | "
                f"{_format_optional_float(detail.get('undercoverage_ratio'))} |"
            )
        warnings = summary.get("warnings") or []
        if warnings:
            rows.extend(["", "Warnings:"])
            for warning in warnings:
                if "reason" in warning:
                    rows.append(f"- `{warning['scope']}`: {warning['reason']}")
                else:
                    rows.append(
                        f"- `{warning['scope']}` coverage "
                        f"{float(warning['coverage_ratio']):.3f} below "
                        f"{float(warning['threshold']):.3f}"
                    )
        else:
            rows.extend(["", "Warnings: None"])
        return "\n".join(rows)

    def _manifest_sessions(self) -> list[dict[str, Any]]:
        sessions = []
        for row in self._session_rows():
            sessions.append(
                {
                    "session_id": row.get("session_id"),
                    "session_type": row.get("session_type"),
                    "started_at": row.get("timestamp"),
                    "ended_at": row.get("ended_at"),
                    "plan_id_used_at_start": row.get("plan_id"),
                    "has_session_briefing": bool(row.get("session_briefing")),
                    "enriched": bool(row.get("enriched")),
                }
            )
        return sessions

    def _manifest_plans(self, sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        plan_sessions: dict[str, list[str]] = {}
        for session in sessions:
            plan_id = session.get("plan_id_used_at_start")
            if plan_id:
                plan_sessions.setdefault(plan_id, []).append(
                    str(session.get("session_id"))
                )
        plans = []
        for row in sorted(
            self.created_rows.get("therapy_plans", []),
            key=lambda item: int(item.get("version") or 0),
        ):
            plan_id = row.get("plan_id")
            plans.append(
                {
                    "plan_id": plan_id,
                    "version": int(row.get("version") or 0),
                    "status": row.get("status"),
                    "created_at": row.get("created_at"),
                    "updated_at": row.get("updated_at"),
                    "supersedes_plan_id": row.get("supersedes_plan_id"),
                    "superseded_by_plan_id": row.get("superseded_by_plan_id"),
                    "used_by_sessions": plan_sessions.get(plan_id, []),
                    "has_session_briefing": bool(row.get("session_briefing")),
                }
            )
        return plans

    def _manifest_style_selection(self) -> dict[str, Any] | None:
        selection = next(
            (
                event
                for event in self.events
                if event["kind"] == "therapy_style_selected"
            ),
            None,
        )
        if not selection:
            return None
        return {
            "selected_style": selection.get("selected_therapy_style"),
            "selected_by": selection.get("input_origin") or "probe_or_user",
            "session_id": selection.get("session_id"),
            "recommendation_scores": self._recommendation_scores(),
        }

    def _recommendation_scores(self) -> dict[str, float]:
        scores: dict[str, float] = {}
        for row in self.created_rows.get("assessment_recommendations", []):
            recommendations = _loads_json(row.get("recommendations"), default=[])
            if not isinstance(recommendations, list):
                continue
            for rec in recommendations:
                if (
                    isinstance(rec, dict)
                    and rec.get("style_id")
                    and rec.get("score") is not None
                ):
                    scores[str(rec["style_id"])] = float(rec["score"])
        return scores

    def _intake_completion_diagnostics(self) -> dict[str, Any] | None:
        intake_session = next(
            (
                row
                for row in self._session_rows()
                if row.get("session_type") == "intake"
            ),
            None,
        )
        if not intake_session:
            return None

        transcript = _loads_json(intake_session.get("transcript"), default=[])
        if not isinstance(transcript, list):
            return None
        patient_messages = [
            str(item.get("content") or "")
            for item in transcript
            if isinstance(item, dict) and item.get("role") == "user"
        ]
        slot_evidence = intake_slot_evidence_from_transcript(transcript)
        covered = covered_slots_from_evidence(slot_evidence)
        missing_required = REQUIRED_INTAKE_SLOTS - covered
        missing_hard = HARD_REQUIRED_INTAKE_SLOTS - covered
        missing_soft = SOFT_REQUIRED_INTAKE_SLOTS - covered
        next_follow_up = next_required_follow_up_slot(covered)
        final_state = self._final_workflow_state()
        completion_decision = (
            "complete_intake"
            if final_state and final_state != "intake_in_progress"
            else "continue_intake"
        )
        return {
            "session_id": intake_session.get("session_id"),
            "workflow_state": final_state,
            "patient_turn_count": len(patient_messages),
            "covered_slots": sorted(covered),
            "slot_evidence": slot_evidence,
            "missing_required_slots": sorted(missing_required),
            "missing_hard_slots": sorted(missing_hard),
            "missing_soft_slots": sorted(missing_soft),
            "next_required_follow_up": next_follow_up,
            "completion_decision": completion_decision,
        }

    def _final_workflow_state(self) -> str | None:
        for event in reversed(self.events):
            state = event.get("workflow_state")
            if state:
                return str(state)
            data = _event_data_dict(event)
            if data.get("workflow_state"):
                return str(data["workflow_state"])
        profiles = self.created_rows.get("user_profiles", [])
        if profiles and profiles[0].get("status"):
            return str(profiles[0]["status"]).lower()
        return None

    def _failure_summary(
        self, status: str, intake_diagnostics: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if status == "PASS":
            return None
        failed = [item["name"] for item in self.assertions if not item["passed"]]
        final_state = self._final_workflow_state()
        error_events = [event for event in self.events if event.get("kind") == "error"]
        primary: list[str] = []
        if final_state == "intake_in_progress":
            primary.append("Intake did not complete before the scripted session ended.")
        if final_state == "plan_update_failed":
            primary.append("Post-session plan update failed.")
        for event in error_events[-2:]:
            detail = event.get("exception") or event.get("message")
            if detail:
                primary.append(str(detail))
        if intake_diagnostics and intake_diagnostics.get("missing_required_slots"):
            primary.append(
                "Missing intake slots: "
                + ", ".join(intake_diagnostics["missing_required_slots"])
            )
        if not primary and failed:
            primary.append(f"First failed assertion: {failed[0]}")

        cascade = [
            name
            for name in failed
            if name
            not in {
                "workflow_action_select_therapy_style",
                "session_end_state",
                "intake_minimum_patient_turns",
            }
        ]
        return {
            "final_workflow_state": final_state,
            "primary_failures": primary,
            "cascade_failures": cascade,
        }

    def _render_failure_summary(self, failure_summary: dict[str, Any]) -> str:
        lines = [
            "# Workflow Probe Failure Summary",
            "",
            f"- Final workflow state: `{failure_summary.get('final_workflow_state')}`",
        ]
        primary = failure_summary.get("primary_failures") or []
        if primary:
            lines.append("- Primary failure candidates:")
            lines.extend(f"  - {item}" for item in primary)
        cascade = failure_summary.get("cascade_failures") or []
        if cascade:
            lines.append("- Cascade failures:")
            lines.extend(f"  - {item}" for item in cascade)
        return "\n".join(lines) + "\n"

    def _render_transcript(self) -> str:
        lines = ["# Transcript", ""]
        sessions = self._session_rows()
        if not sessions:
            chat_lines = [
                "- **"
                + ("patient" if e["kind"] == "user_input" else "therapist")
                + f"**: {e.get('text', '')}"
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
            return "# Transcript\n\n" + "\n".join(chat_lines) + "\n"
        for index, session in enumerate(sessions, start=1):
            session_type = str(session.get("session_type") or "session").title()
            lines.extend([f"## Session {index} - {session_type}", ""])
            transcript = _loads_json(session.get("transcript"), default=[])
            if isinstance(transcript, list):
                for item in transcript:
                    if not isinstance(item, dict):
                        continue
                    role = "patient" if item.get("role") == "user" else "therapist"
                    lines.append(f"- **{role}**: {item.get('content', '')}")
            if index == 1 and len(sessions) > 1:
                inter_session = self._inter_session_lines()
                if inter_session:
                    lines.extend(["", "## Inter-session Workflow", "", *inter_session])
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _inter_session_lines(self) -> list[str]:
        lines = []
        if any(
            event["kind"] == "ws_event"
            and event.get("type") == "assessment_recommendations"
            for event in self.events
        ):
            lines.append("- Assessment recommendations generated and displayed.")
        style_selection = self._manifest_style_selection()
        if style_selection:
            lines.append(
                f"- Therapy style selected: `{style_selection.get('selected_style')}`."
            )
        first_plan = min(
            self.created_rows.get("therapy_plans", []),
            key=lambda row: int(row.get("version") or 0),
            default=None,
        )
        if first_plan:
            lines.append(
                f"- Initial plan v{first_plan.get('version')} created: "
                f"`{first_plan.get('plan_id')}`."
            )
        return lines

    def _session_rows(self) -> list[dict[str, Any]]:
        return sorted(
            self.created_rows.get("sessions", []),
            key=lambda row: str(row.get("timestamp") or ""),
        )

    def _workflow_action_summary(self) -> dict[str, Any]:
        raw = [event for event in self.events if event["kind"] == "raw_workflow_action"]
        logical = [event for event in self.events if event["kind"] == "workflow_action"]
        raw_by_action: dict[str, int] = {}
        logical_by_action: dict[str, int] = {}
        for event in raw:
            action = str(event.get("action") or "unknown")
            raw_by_action[action] = raw_by_action.get(action, 0) + 1
        for event in logical:
            action = str(event.get("action") or "unknown")
            logical_by_action[action] = logical_by_action.get(action, 0) + 1
        return {
            "raw_count": len(raw),
            "logical_count": len(logical),
            "duplicate_delivery_count": max(0, len(raw) - len(logical)),
            "raw_by_action": raw_by_action,
            "logical_by_action": logical_by_action,
        }

    def _job_status_summary(self) -> dict[str, Any]:
        statuses = [event for event in self.events if event["kind"] == "job_status"]
        by_job: dict[str, dict[str, Any]] = {}
        for event in statuses:
            job_id = str(event.get("job_id") or "unknown")
            current = by_job.setdefault(
                job_id,
                {
                    "event_count": 0,
                    "latest_status": None,
                    "latest_step": None,
                    "sources": [],
                },
            )
            current["event_count"] += 1
            current["latest_status"] = event.get("status")
            current["latest_step"] = event.get("current_step")
            source = event.get("delivery_source")
            if source and source not in current["sources"]:
                current["sources"].append(source)
        return {
            "event_count": len(statuses),
            "by_job": by_job,
        }

    def _render_workflow_action_summary(self) -> str:
        summary = self._workflow_action_summary()
        return "\n".join(
            [
                f"- Raw deliveries: {summary['raw_count']}",
                f"- Logical actions: {summary['logical_count']}",
                f"- Duplicate deliveries: {summary['duplicate_delivery_count']}",
            ]
        )

    def _render_job_status_summary(self) -> str:
        summary = self._job_status_summary()
        if not summary["by_job"]:
            return "- No job status events recorded"
        rows = ["| Job | Events | Latest | Step | Sources |", "|---|---:|---|---|---|"]
        for job_id, detail in sorted(summary["by_job"].items()):
            rows.append(
                f"| {_escape_table(job_id)} | {detail['event_count']} | "
                f"{_escape_table(str(detail.get('latest_status') or ''))} | "
                f"{_escape_table(str(detail.get('latest_step') or ''))} | "
                f"{_escape_table(','.join(detail.get('sources') or []))} |"
            )
        return "\n".join(rows)

    def _render_timeline(self) -> str:
        rows = [
            "# Workflow Timeline",
            "",
            "| Timestamp | Category | State | Session | Details |",
            "|---|---|---|---|---|",
        ]
        for event in self.events:
            category, state, session_id, details = self._timeline_row(event)
            rows.append(
                f"| {_escape_table(str(event.get('ts', '')))} | "
                f"{_escape_table(category)} | {_escape_table(state)} | "
                f"{_escape_table(session_id)} | {_escape_table(details)} |"
            )
        return "\n".join(rows) + "\n"

    def _timeline_row(self, event: dict[str, Any]) -> tuple[str, str, str, str]:
        kind = event["kind"]
        data = _event_data_dict(event)
        state = str(
            event.get("workflow_state")
            or data.get("workflow_state")
            or ""
        )
        session_id = str(event.get("session_id") or data.get("session_id") or "")
        if kind == "workflow_action":
            return (
                "workflow_logical",
                state,
                session_id,
                f"action={event.get('action')} source={event.get('delivery_source')}",
            )
        if kind == "raw_workflow_action":
            return (
                "workflow_raw",
                state,
                session_id,
                f"action={event.get('action')} source={event.get('delivery_source')} "
                f"logical_key={event.get('logical_key')}",
            )
        if kind == "job_status":
            return (
                "job_status",
                state,
                session_id,
                f"job_id={event.get('job_id')} status={event.get('status')} "
                f"step={event.get('current_step')} source={event.get('delivery_source')}",
            )
        if kind.endswith("_summary"):
            return (
                "polling_summary",
                state,
                session_id,
                f"{kind} count={event.get('count')} "
                f"duration_ms={event.get('duration_ms')}",
            )
        if kind == "ws_event":
            return "websocket", state, session_id, f"type={event.get('type')}"
        if kind == "therapy_style_selected":
            return (
                "probe_action",
                state,
                session_id,
                f"selected_style={event.get('selected_therapy_style')}",
            )
        if kind == "assistant_response":
            return (
                "assistant",
                state,
                session_id,
                f"chars={len(str(event.get('text') or ''))}",
            )
        if kind == "user_input":
            return "user", state, session_id, f"prompt_kind={event.get('prompt_kind')}"
        details = json.dumps(
            {k: v for k, v in event.items() if k not in {"ts", "kind"}},
            default=str,
        )[:240]
        return kind, state, session_id, details


def _event_data_dict(event: dict[str, Any]) -> dict[str, Any]:
    data = event.get("data")
    return data if isinstance(data, dict) else {}


def _compact_ws_message(message: dict[str, Any]) -> dict[str, Any]:
    data = message.get("data") or {}
    result: dict[str, Any] = {"type": message.get("type")}
    if message.get("type") == "chat_response_chunk":
        result.update(
            is_complete=bool(data.get("is_complete")),
            chunk_chars=len(data.get("chunk") or ""),
        )
    else:
        result["data"] = data
    return result


def _workflow_action_key(action: dict[str, Any]) -> str:
    payload = {
        "user_id": action.get("user_id"),
        "session_id": action.get("session_id"),
        "workflow_state": action.get("workflow_state"),
        "required_action": action.get("required_action"),
        "required_fields": action.get("required_fields") or [],
        "defaults": action.get("defaults"),
        "state_signature": action.get("state_signature"),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _loads_json(value: Any, *, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _parse_event_ts(event: dict[str, Any] | None) -> datetime | None:
    if not event:
        return None
    value = event.get("ts")
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _elapsed_ms(
    started_at: datetime | None,
    finished_at: datetime | None,
) -> float | None:
    if started_at is None or finished_at is None:
        return None
    return round((finished_at - started_at).total_seconds() * 1000, 3)


def _float_value(*values: Any) -> float:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _format_optional_float(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "n/a"


def _latency_stats(samples: list[dict[str, Any]]) -> dict[str, Any]:
    user_visible = _numeric_values(samples, "user_visible_ms")
    ttft = _numeric_values(samples, "ttft_ms")
    stream = _numeric_values(samples, "stream_ms")
    return {
        "count": len(samples),
        "user_visible_p50_ms": _percentile(user_visible, 0.50),
        "user_visible_p95_ms": _percentile(user_visible, 0.95),
        "user_visible_max_ms": max(user_visible) if user_visible else 0.0,
        "ttft_p95_ms": _percentile(ttft, 0.95),
        "stream_p95_ms": _percentile(stream, 0.95),
    }


def _numeric_values(samples: list[dict[str, Any]], key: str) -> list[float]:
    values = []
    for sample in samples:
        value = sample.get(key)
        if value is not None:
            values.append(float(value))
    return sorted(values)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    index = round((len(values) - 1) * percentile)
    return round(values[index], 3)


def _walk_session_ids(value: Any):
    if isinstance(value, dict):
        if value.get("session_id"):
            yield str(value["session_id"])
        for nested in value.values():
            yield from _walk_session_ids(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_session_ids(nested)
