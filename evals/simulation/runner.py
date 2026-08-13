"""Whole-product journey orchestration over public HTTP."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

from evals.simulation.audit import (
    AuditResult,
    JourneyLog,
    SimulationStatus,
    allocate_run_directory,
    artifact_relative_paths,
    create_checkpoint,
    diagnostics_end_status,
    git_provenance,
    load_jsonl,
    render_audit_markdown,
    render_transcript_from_snapshot,
    run_mechanical_audit,
    sanitized_endpoint,
    scenario_snapshot,
    write_private_text,
    write_run_json,
)
from evals.simulation.patient import (
    PATIENT_HISTORY_MAX_CHARS,
    PATIENT_TIMEOUT_SECONDS,
    WORKFLOW_TIMEOUT_SECONDS,
    PatientEvidence,
    PatientExchange,
    PatientGenerationError,
    PatientSimulator,
    PatientTurnContext,
    pack_visible_history,
    resolve_patient_endpoint,
    serialize_visible_history,
)
from evals.simulation.scenarios import SimulationScenario
from jung.api.contracts import (
    MessageCompletedEvent,
    ProfileUpdateRequest,
    ProfileWire,
    SelectStyleRequest,
    TokenEvent,
)
from jung.api.server import running_local_api
from jung.client.api_client import ClientSettings, JungApiClient
from jung.composition import application_context
from jung.config import JungSettings, load_settings
from jung.llm.gateway import LLMTask
from jung.llm.policies import build_model_policies

POLL_INTERVAL_SECONDS = 0.15


class PatientActor(Protocol):
    async def generate(self, context: PatientTurnContext) -> PatientEvidence: ...

    async def aclose(self) -> None: ...


class SimulationError(RuntimeError):
    """Fail-fast live-journey error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class SubmittedTurn:
    client_message_id: UUID
    request_id: UUID
    patient_text: str
    assistant_text: str


@dataclass
class TherapySessionRecord:
    session_id: UUID
    turns: list[SubmittedTurn] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SimulationResult:
    status: SimulationStatus
    run_dir: Path
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    scenario: SimulationScenario
    sessions: int
    turns_per_session: int
    max_intake_turns: int = 12
    output_dir: Path | None = None
    patient_base_url: str | None = None
    patient_model: str | None = None
    patient_timeout: float = PATIENT_TIMEOUT_SECONDS
    workflow_timeout: float = WORKFLOW_TIMEOUT_SECONDS
    overall_timeout: float | None = None
    patient_history_chars: int = PATIENT_HISTORY_MAX_CHARS
    require_provider_trace: bool = True
    profile_name: str = "Simulated Patient"
    profile_language: str = "English"


ApplicationFactory = Callable[[JungSettings], AbstractAsyncContextManager[Any]]


async def wait_for_stage(
    client: JungApiClient,
    *,
    desired: set[str],
    workflow_timeout: float,
    fail_if_operation_failed: bool = True,
) -> Any:
    deadline = time.monotonic() + workflow_timeout
    while True:
        snapshot = await client.get_state()
        if (
            fail_if_operation_failed
            and snapshot.operation is not None
            and snapshot.operation.status == "failed"
        ):
            error = snapshot.operation.error
            detail = error.message if error is not None else "operation failed"
            raise SimulationError("operation_failed", detail)
        if snapshot.stage in desired:
            return snapshot
        if time.monotonic() >= deadline:
            raise SimulationError(
                "workflow_timeout",
                f"timed out waiting for stages {sorted(desired)}; "
                f"last stage={snapshot.stage!r}",
            )
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def collect_chat_completion(
    client: JungApiClient,
    *,
    session_id: UUID,
    content: str,
    client_message_id: UUID,
    request_id: UUID,
) -> SubmittedTurn:
    token_text: list[str] = []
    terminal: MessageCompletedEvent | None = None
    async with client.stream_message(
        session_id,
        content,
        client_message_id=client_message_id,
        request_id=request_id,
    ) as events:
        async for event in events:
            if isinstance(event, TokenEvent):
                token_text.append(event.text)
                continue
            if isinstance(event, MessageCompletedEvent):
                terminal = event
                break
            raise SimulationError(
                "chat_terminal_failure",
                f"unexpected terminal event type={type(event).__name__}",
            )
    if terminal is None:
        raise SimulationError(
            "chat_terminal_failure", "stream ended without completion"
        )
    streamed = "".join(token_text)
    if streamed != terminal.assistant_message.content:
        raise SimulationError(
            "stream_persistence_mismatch",
            "concatenated token text != completed assistant content",
        )
    if content != terminal.user_message.content:
        raise SimulationError(
            "stream_persistence_mismatch",
            "submitted patient text != completed user content",
        )
    return SubmittedTurn(
        client_message_id=client_message_id,
        request_id=request_id,
        patient_text=content,
        assistant_text=terminal.assistant_message.content,
    )


def _select_style(recommendations: Sequence[Any]) -> Any:
    if not recommendations:
        raise SimulationError("style_selection", "no style recommendations available")
    return sorted(
        recommendations,
        key=lambda item: (-float(item.score), str(item.style_id)),
    )[0]


def _structured_output_modes(settings: JungSettings) -> dict[str, str]:
    supervisor_model = settings.supervisor_model_name or settings.model_name
    policies = build_model_policies(
        session_model=settings.model_name,
        supervisor_model=supervisor_model,
        task_overrides=settings.llm_task_config,
    )
    return {task.value: policies[task].structured_output_mode.value for task in LLMTask}


def _record_journey_exception(
    exc: BaseException,
) -> tuple[str, str]:
    if isinstance(exc, SimulationError):
        return exc.code, exc.message
    if isinstance(exc, PatientGenerationError):
        return "patient_generation_failed", str(exc)
    return "journey_error", f"{type(exc).__name__}: {exc}"


async def run_simulation(
    config: SimulationConfig,
    *,
    settings: JungSettings | None = None,
    application_factory: ApplicationFactory = application_context,
    patient_actor: PatientActor | None = None,
    require_provider_trace: bool | None = None,
) -> SimulationResult:
    provider_trace_required = (
        config.require_provider_trace
        if require_provider_trace is None
        else require_provider_trace
    )
    run_dir = allocate_run_directory(config.output_dir)
    journey = JourneyLog(run_dir / "journey.jsonl")
    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    git_commit, git_dirty = git_provenance()

    base_settings = settings or load_settings()
    isolated = base_settings.model_copy(
        update={
            "data_dir": run_dir / "data",
            "debug_run_dir": run_dir / "runtime",
        }
    )

    endpoint = resolve_patient_endpoint(
        session_base_url=isolated.llm_base_url,
        session_model=isolated.model_name,
        session_api_key=isolated.llm_api_key,
        session_default_headers=isolated.llm_default_headers,
        patient_base_url=config.patient_base_url,
        patient_model=config.patient_model,
        timeout_seconds=config.patient_timeout,
        session_extra_body=isolated.llm_extra_body,
    )
    owns_patient = patient_actor is None
    patient = patient_actor or PatientSimulator(endpoint)

    journey.append(
        "simulation.started",
        data={
            "scenario_id": config.scenario.id,
            "sessions": config.sessions,
            "turns_per_session": config.turns_per_session,
            "provider_trace_required": provider_trace_required,
            "run_dir": str(run_dir),
        },
    )

    journey_error: Exception | None = None
    error_code: str | None = None
    error_message: str | None = None
    therapy_records: list[TherapySessionRecord] = []
    prior_patient_sessions: list[tuple[PatientExchange, ...]] = []
    run_config: dict[str, Any] = {
        "artifact_schema_version": 1,
        "scenario": scenario_snapshot(config.scenario),
        "sessions": config.sessions,
        "turns_per_session": config.turns_per_session,
        "max_intake_turns": config.max_intake_turns,
        "provider_trace_required": provider_trace_required,
        "patient_timeout": config.patient_timeout,
        "workflow_timeout": config.workflow_timeout,
        "overall_timeout": config.overall_timeout,
        "patient_history_chars": config.patient_history_chars,
        "session_model": isolated.model_name,
        "session_endpoint": sanitized_endpoint(isolated.llm_base_url),
        "supervisor_model": isolated.supervisor_model_name or isolated.model_name,
        "supervisor_endpoint": sanitized_endpoint(
            isolated.supervisor_llm_base_url or isolated.llm_base_url
        ),
        "patient_model": endpoint.model,
        "patient_endpoint": sanitized_endpoint(endpoint.base_url),
        "patient_max_completion_tokens": endpoint.max_completion_tokens,
        "structured_output_modes": _structured_output_modes(isolated),
        "git_commit": git_commit,
        "git_worktree_dirty": git_dirty,
    }

    try:
        try:
            async with running_local_api(
                isolated,
                application_factory=application_factory,
            ) as base_url:
                async with JungApiClient(ClientSettings(base_url=base_url)) as client:
                    if config.overall_timeout is None:
                        await _run_live_journey(
                            client=client,
                            config=config,
                            patient=patient,
                            journey=journey,
                            isolated=isolated,
                            therapy_records=therapy_records,
                            prior_patient_sessions=prior_patient_sessions,
                            style_selection_out=run_config,
                        )
                    else:
                        try:
                            async with asyncio.timeout(config.overall_timeout):
                                await _run_live_journey(
                                    client=client,
                                    config=config,
                                    patient=patient,
                                    journey=journey,
                                    isolated=isolated,
                                    therapy_records=therapy_records,
                                    prior_patient_sessions=prior_patient_sessions,
                                    style_selection_out=run_config,
                                )
                        except TimeoutError as exc:
                            raise SimulationError(
                                "overall_timeout",
                                "live journey overall timeout",
                            ) from exc
        except Exception as exc:
            journey_error = exc
            error_code, error_message = _record_journey_exception(exc)
            journey.append(
                "workflow.observed",
                data={
                    "error_code": error_code,
                    "error_message": error_message,
                },
            )

        return _finalize_run(
            config=config,
            run_dir=run_dir,
            journey=journey,
            run_config=run_config,
            therapy_records=therapy_records,
            provider_trace_required=provider_trace_required,
            started_at=started_at,
            journey_error=journey_error,
            error_code=error_code,
            error_message=error_message,
        )
    finally:
        if owns_patient:
            try:
                await patient.aclose()
            except Exception:
                pass


def _finalize_run(
    *,
    config: SimulationConfig,
    run_dir: Path,
    journey: JourneyLog,
    run_config: dict[str, Any],
    therapy_records: list[TherapySessionRecord],
    provider_trace_required: bool,
    started_at: str,
    journey_error: Exception | None,
    error_code: str | None,
    error_message: str | None,
) -> SimulationResult:
    try:
        audit = run_mechanical_audit(
            run_dir=run_dir,
            provider_trace_required=provider_trace_required,
            configured_sessions=config.sessions,
            therapy_sessions=[
                {
                    "session_id": record.session_id,
                    "turns": [
                        {
                            "client_message_id": turn.client_message_id,
                            "patient_text": turn.patient_text,
                            "assistant_text": turn.assistant_text,
                        }
                        for turn in record.turns
                    ],
                }
                for record in therapy_records
            ],
        )
    except Exception as exc:
        audit = AuditResult()
        audit.fail(
            "audit_internal_error",
            f"{type(exc).__name__}: {exc}",
        )

    snapshot_path = run_dir / "runtime" / "db_snapshot.sqlite"
    if snapshot_path.is_file():
        try:
            write_private_text(
                run_dir / "transcript.md",
                render_transcript_from_snapshot(snapshot_path),
            )
        except Exception as exc:
            audit.fail(
                "transcript_write_failed",
                f"{type(exc).__name__}: {exc}",
            )

    runtime_status: str | None = None
    try:
        trace = load_jsonl(run_dir / "runtime" / "trace.jsonl")
        runtime_status = diagnostics_end_status(trace)
    except Exception as exc:
        audit.fail(
            "runtime_trace_read_failed",
            f"{type(exc).__name__}: {exc}",
        )

    if journey_error is not None and error_code is None:
        error_code = "journey_error"
        error_message = str(journey_error)
    if journey_error is None and not audit.ok:
        codes = sorted({finding.code for finding in audit.findings})
        error_code = "mechanical_audit_failed"
        error_message = f"mechanical audit failed: {', '.join(codes)}"

    final_status: SimulationStatus = (
        "failed" if journey_error is not None or not audit.ok else "complete"
    )

    try:
        write_private_text(
            run_dir / "audit.md",
            render_audit_markdown(
                status=final_status,
                runtime_diagnostics_status=runtime_status,
                findings=audit.findings,
                warnings=audit.warnings,
                run_config=run_config,
                artifact_index=artifact_relative_paths(run_dir),
                journey_error_code=error_code,
                journey_error_message=error_message,
            ),
        )
    except Exception:
        final_status = "failed"

    terminal_kind = (
        "simulation.completed" if final_status == "complete" else "simulation.failed"
    )
    try:
        journey.append(
            terminal_kind,
            data={
                "status": final_status,
                "error_code": error_code,
                "error_message": error_message,
                "finding_codes": [item.code for item in audit.findings],
            },
        )
    except Exception:
        final_status = "failed"

    completed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    run_payload = {
        **run_config,
        "run_id": run_dir.name,
        "started_at": started_at,
        "completed_at": completed_at,
        "status": final_status,
        "error_code": error_code,
        "error_message": error_message,
        "provider_trace_required": provider_trace_required,
    }
    try:
        write_run_json(run_dir / "run.json", run_payload)
    except Exception:
        final_status = "failed"

    return SimulationResult(
        status=final_status,
        run_dir=run_dir,
        error_code=error_code,
        error_message=error_message,
    )


async def _run_live_journey(
    *,
    client: JungApiClient,
    config: SimulationConfig,
    patient: PatientActor,
    journey: JourneyLog,
    isolated: JungSettings,
    therapy_records: list[TherapySessionRecord],
    prior_patient_sessions: list[tuple[PatientExchange, ...]],
    style_selection_out: dict[str, Any],
) -> None:
    health = await client.get_health()
    if health.status != "healthy":
        raise SimulationError("health_failed", f"health status={health.status!r}")
    journey.append(
        "api.command", data={"command": "get_health", "status": health.status}
    )

    snapshot = await client.update_profile(
        ProfileUpdateRequest(
            profile=ProfileWire(
                name=config.profile_name,
                primary_language=config.profile_language,
            )
        )
    )
    journey.append(
        "api.command",
        data={"command": "update_profile", "stage": snapshot.stage},
    )
    if snapshot.stage != "intake":
        raise SimulationError(
            "impossible_stage",
            f"expected intake after profile update, got {snapshot.stage!r}",
        )

    intake_exchanges = await _run_intake(
        client=client,
        config=config,
        patient=patient,
        journey=journey,
        intake_session_id=(
            snapshot.active_session.id if snapshot.active_session is not None else None
        ),
    )
    prior_patient_sessions.append(tuple(intake_exchanges))

    await _await_style_selection(
        client=client,
        workflow_timeout=config.workflow_timeout,
        journey=journey,
    )
    await _select_initial_style(
        client=client,
        config=config,
        journey=journey,
        isolated=isolated,
        style_selection_out=style_selection_out,
    )

    for session_number in range(1, config.sessions + 1):
        await _run_therapy_session(
            client=client,
            config=config,
            patient=patient,
            journey=journey,
            isolated=isolated,
            therapy_records=therapy_records,
            prior_patient_sessions=prior_patient_sessions,
            session_number=session_number,
        )


async def _run_intake(
    *,
    client: JungApiClient,
    config: SimulationConfig,
    patient: PatientActor,
    journey: JourneyLog,
    intake_session_id: UUID | None,
) -> list[PatientExchange]:
    intake_exchanges: list[PatientExchange] = []
    session_id = intake_session_id
    for turn_number in range(1, config.max_intake_turns + 1):
        state = await client.get_state()
        if state.stage != "intake":
            break
        if state.active_session is not None:
            session_id = state.active_session.id
        if session_id is None:
            raise SimulationError("impossible_stage", "intake has no active session")
        history = pack_visible_history(
            current_session=intake_exchanges,
            prior_sessions=(),
            max_chars=config.patient_history_chars,
        )
        context = PatientTurnContext(
            scenario=config.scenario,
            phase="intake",
            session_number=0,
            turn_number=turn_number,
            visible_history=history,
        )
        journey.append(
            "patient.request",
            data={
                "phase": "intake",
                "turn_number": turn_number,
                "history_chars": len(serialize_visible_history(history)),
            },
        )
        evidence = await patient.generate(context)
        journey.append(
            "patient.response",
            data={
                "submitted_text": evidence.submitted_text,
                "finish_reason": evidence.finish_reason,
                "prompt_tokens": evidence.prompt_tokens,
                "completion_tokens": evidence.completion_tokens,
                "latency_seconds": evidence.latency_seconds,
                "model": evidence.model,
                "resolved_prompt": evidence.resolved_prompt,
                "raw_provider_text": evidence.raw_provider_text,
                "visible_history": [
                    {"role": turn.role, "content": turn.content}
                    for turn in evidence.visible_history
                ],
            },
        )
        client_message_id = uuid4()
        request_id = uuid4()
        journey.append(
            "chat.submitted",
            context={
                "session_id": str(session_id),
                "client_message_id": str(client_message_id),
                "request_id": str(request_id),
            },
            data={"content": evidence.submitted_text, "phase": "intake"},
        )
        completed = await collect_chat_completion(
            client,
            session_id=session_id,
            content=evidence.submitted_text,
            client_message_id=client_message_id,
            request_id=request_id,
        )
        journey.append(
            "chat.completed",
            context={
                "session_id": str(session_id),
                "client_message_id": str(client_message_id),
                "request_id": str(request_id),
            },
            data={"assistant_text": completed.assistant_text},
        )
        intake_exchanges.append(
            PatientExchange(
                patient=completed.patient_text,
                therapist=completed.assistant_text,
            )
        )
    else:
        state = await client.get_state()
        if state.stage == "intake":
            raise SimulationError(
                "intake_turn_limit_exceeded",
                f"still in intake after {config.max_intake_turns} turns",
            )
    return intake_exchanges


async def _await_style_selection(
    client: JungApiClient,
    *,
    workflow_timeout: float,
    journey: JourneyLog,
) -> Any:
    """Accept either assessment or style_selection after intake completes."""
    state = await client.get_state()
    journey.append(
        "workflow.observed", data={"stage": state.stage, "phase": "post_intake"}
    )
    if state.stage == "assessment":
        return await wait_for_stage(
            client,
            desired={"style_selection"},
            workflow_timeout=workflow_timeout,
        )
    if state.stage == "style_selection":
        return state
    raise SimulationError(
        "impossible_stage",
        f"after intake expected assessment or style_selection, got {state.stage!r}",
    )


async def _select_initial_style(
    *,
    client: JungApiClient,
    config: SimulationConfig,
    journey: JourneyLog,
    isolated: JungSettings,
    style_selection_out: dict[str, Any],
) -> None:
    styles = await client.get_styles()
    selected = _select_style(styles.recommendations)
    style_selection_out["style_selection"] = {
        "recommendations": [
            {
                "style_id": item.style_id,
                "score": item.score,
                "rationale": item.rationale,
                "key_topics": list(item.key_topics),
            }
            for item in styles.recommendations
        ],
        "selected_style_id": selected.style_id,
    }
    journey.append(
        "style.selected",
        data={
            "selected_style_id": selected.style_id,
            "score": selected.score,
            "recommendations": style_selection_out["style_selection"][
                "recommendations"
            ],
        },
    )
    snapshot = await client.select_style(SelectStyleRequest(style_id=selected.style_id))
    if snapshot.stage != "ready":
        await wait_for_stage(
            client,
            desired={"ready"},
            workflow_timeout=config.workflow_timeout,
        )
    create_checkpoint(
        isolated.database_path,
        Path(isolated.data_dir).parent / "checkpoints" / "initial-ready.sqlite",
    )
    journey.append(
        "checkpoint.created",
        data={"name": "initial-ready.sqlite"},
    )


async def _run_therapy_session(
    *,
    client: JungApiClient,
    config: SimulationConfig,
    patient: PatientActor,
    journey: JourneyLog,
    isolated: JungSettings,
    therapy_records: list[TherapySessionRecord],
    prior_patient_sessions: list[tuple[PatientExchange, ...]],
    session_number: int,
) -> None:
    started = await client.start_session()
    if started.snapshot.stage != "therapy":
        raise SimulationError(
            "impossible_stage",
            f"start_session returned stage={started.snapshot.stage!r}",
        )
    session_id = started.session.id
    record = TherapySessionRecord(session_id=session_id)
    therapy_records.append(record)
    journey.append(
        "api.command",
        context={"session_id": str(session_id)},
        data={"command": "start_session", "session_number": session_number},
    )
    current_exchanges: list[PatientExchange] = []
    for turn_number in range(1, config.turns_per_session + 1):
        history = pack_visible_history(
            current_session=current_exchanges,
            prior_sessions=prior_patient_sessions,
            max_chars=config.patient_history_chars,
        )
        context = PatientTurnContext(
            scenario=config.scenario,
            phase="therapy",
            session_number=session_number,
            turn_number=turn_number,
            visible_history=history,
        )
        journey.append(
            "patient.request",
            context={"session_id": str(session_id)},
            data={"phase": "therapy", "turn_number": turn_number},
        )
        evidence = await patient.generate(context)
        journey.append(
            "patient.response",
            context={"session_id": str(session_id)},
            data={
                "submitted_text": evidence.submitted_text,
                "finish_reason": evidence.finish_reason,
                "prompt_tokens": evidence.prompt_tokens,
                "completion_tokens": evidence.completion_tokens,
                "latency_seconds": evidence.latency_seconds,
                "model": evidence.model,
                "resolved_prompt": evidence.resolved_prompt,
                "raw_provider_text": evidence.raw_provider_text,
                "visible_history": [
                    {"role": turn.role, "content": turn.content}
                    for turn in evidence.visible_history
                ],
            },
        )
        client_message_id = uuid4()
        request_id = uuid4()
        journey.append(
            "chat.submitted",
            context={
                "session_id": str(session_id),
                "client_message_id": str(client_message_id),
                "request_id": str(request_id),
            },
            data={"content": evidence.submitted_text, "phase": "therapy"},
        )
        completed = await collect_chat_completion(
            client,
            session_id=session_id,
            content=evidence.submitted_text,
            client_message_id=client_message_id,
            request_id=request_id,
        )
        journey.append(
            "chat.completed",
            context={
                "session_id": str(session_id),
                "client_message_id": str(client_message_id),
                "request_id": str(request_id),
            },
            data={"assistant_text": completed.assistant_text},
        )
        record.turns.append(completed)
        current_exchanges.append(
            PatientExchange(
                patient=completed.patient_text,
                therapist=completed.assistant_text,
            )
        )

    ended = await client.end_session(session_id)
    if ended.stage != "post_session":
        raise SimulationError(
            "impossible_stage",
            f"end_session returned stage={ended.stage!r}",
        )
    journey.append(
        "api.command",
        context={"session_id": str(session_id)},
        data={"command": "end_session", "stage": ended.stage},
    )
    await wait_for_stage(
        client,
        desired={"ready"},
        workflow_timeout=config.workflow_timeout,
    )
    create_checkpoint(
        isolated.database_path,
        Path(isolated.data_dir).parent
        / "checkpoints"
        / f"after-session-{session_number:03d}.sqlite",
    )
    journey.append(
        "checkpoint.created",
        context={"session_id": str(session_id)},
        data={"name": f"after-session-{session_number:03d}.sqlite"},
    )
    prior_patient_sessions.append(tuple(current_exchanges))
