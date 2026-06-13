"""Workflow job status resolution."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psychoanalyst_app.models.http import JobStatusDTO
from psychoanalyst_app.orchestration.models import WorkflowState

VALID_JOB_TYPES = {
    "assessment",
    "plan_update",
    "session_enrichment",
    "post_session_update",
}


class JobStatusNotFound(ValueError):
    """Raised when a semantic job id is invalid or not visible to the user."""


def parse_job_id(job_id: str) -> tuple[str, str]:
    job_type, separator, identifier = job_id.partition(":")
    if separator != ":" or not identifier or job_type not in VALID_JOB_TYPES:
        raise JobStatusNotFound("Invalid job id")
    return job_type, identifier


async def resolve_job_status(
    *,
    job_id: str,
    user_id: str,
    db_service: Any,
    workflow_engine: Any,
    response_handler: Any | None = None,
) -> JobStatusDTO:
    job_type, identifier = parse_job_id(job_id)
    if job_type == "assessment":
        if identifier != user_id:
            raise JobStatusNotFound("Job is not visible to this user")
        return await _assessment_status(
            job_id=job_id,
            user_id=user_id,
            db_service=db_service,
            workflow_engine=workflow_engine,
            response_handler=response_handler,
        )

    session = await db_service.get_session(identifier)
    if not session or session.user_id != user_id:
        raise JobStatusNotFound("Job is not visible to this user")

    if job_type == "plan_update":
        return await _plan_update_status(
            job_id=job_id,
            user_id=user_id,
            session_id=identifier,
            workflow_engine=workflow_engine,
            response_handler=response_handler,
        )
    if job_type == "session_enrichment":
        return await _session_enrichment_status(
            job_id=job_id,
            user_id=user_id,
            session_id=identifier,
            db_service=db_service,
        )
    return await _post_session_update_status(
        job_id=job_id,
        user_id=user_id,
        session_id=identifier,
        db_service=db_service,
        workflow_engine=workflow_engine,
        response_handler=response_handler,
    )


async def _assessment_status(
    *,
    job_id: str,
    user_id: str,
    db_service: Any,
    workflow_engine: Any,
    response_handler: Any | None,
) -> JobStatusDTO:
    state = await workflow_engine.get_user_state(user_id)
    if state in (
        WorkflowState.ASSESSMENT_COMPLETE,
        WorkflowState.INITIAL_PLAN_COMPLETE,
        WorkflowState.THERAPY_IN_PROGRESS,
        WorkflowState.PLAN_UPDATE_IN_PROGRESS,
        WorkflowState.REFLECTION_IN_PROGRESS,
        WorkflowState.PLAN_UPDATE_COMPLETE,
        WorkflowState.PLAN_UPDATE_FAILED,
    ):
        status = "complete"
        current_step = "assessment_complete"
    elif _assessment_running(response_handler, user_id) or state in (
        WorkflowState.INTAKE_COMPLETE,
        WorkflowState.ASSESSMENT_IN_PROGRESS,
    ):
        status = "running"
        current_step = "generating_assessment"
    else:
        status = "not_started"
        current_step = "waiting_for_intake_completion"

    return JobStatusDTO(
        job_id=job_id,
        job_type="assessment",
        user_id=user_id,
        status=status,
        current_step=current_step,
        workflow_state=state,
        correlation_id=job_id,
    )


async def _plan_update_status(
    *,
    job_id: str,
    user_id: str,
    session_id: str,
    workflow_engine: Any,
    response_handler: Any | None,
) -> JobStatusDTO:
    state = await workflow_engine.get_user_state(user_id)
    if state == WorkflowState.PLAN_UPDATE_COMPLETE:
        status = "complete"
        current_step = "plan_update_complete"
    elif state == WorkflowState.PLAN_UPDATE_FAILED:
        status = "failed"
        current_step = "plan_update_failed"
    elif state in (
        WorkflowState.PLAN_UPDATE_IN_PROGRESS,
        WorkflowState.REFLECTION_IN_PROGRESS,
    ) or _reflection_running(response_handler, session_id):
        status = "running"
        current_step = "running_reflection"
    else:
        status = "not_started"
        current_step = "waiting_for_session_end"

    return JobStatusDTO(
        job_id=job_id,
        job_type="plan_update",
        user_id=user_id,
        session_id=session_id,
        status=status,
        current_step=current_step,
        workflow_state=state,
        correlation_id=job_id,
    )


async def _session_enrichment_status(
    *,
    job_id: str,
    user_id: str,
    session_id: str,
    db_service: Any,
) -> JobStatusDTO:
    job = await db_service.get_session_enrichment_job(session_id)
    if not job:
        status = "not_started"
        current_step = "waiting_for_enqueue"
        attempt = None
        updated_at = datetime.utcnow()
        last_error = None
    else:
        raw_status = str(job.get("status") or "")
        status = {
            "processing": "running",
            "queued": "queued",
            "complete": "complete",
            "failed": "failed",
        }.get(raw_status, "not_started")
        current_step = {
            "queued": "queued_for_enrichment",
            "running": "running_enrichment",
            "complete": "enrichment_complete",
            "failed": "enrichment_failed",
            "not_started": "waiting_for_enqueue",
        }[status]
        attempt = int(job.get("attempts") or 0)
        updated_at = _parse_datetime(job.get("updated_at")) or datetime.utcnow()
        last_error = job.get("last_error")

    return JobStatusDTO(
        job_id=job_id,
        job_type="session_enrichment",
        user_id=user_id,
        session_id=session_id,
        status=status,
        current_step=current_step,
        attempt=attempt,
        correlation_id=f"{job_id}:attempt:{attempt or 0}",
        updated_at=updated_at,
        last_error=last_error,
    )


async def _post_session_update_status(
    *,
    job_id: str,
    user_id: str,
    session_id: str,
    db_service: Any,
    workflow_engine: Any,
    response_handler: Any | None,
) -> JobStatusDTO:
    plan = await _plan_update_status(
        job_id=f"plan_update:{session_id}",
        user_id=user_id,
        session_id=session_id,
        workflow_engine=workflow_engine,
        response_handler=response_handler,
    )
    enrichment = await _session_enrichment_status(
        job_id=f"session_enrichment:{session_id}",
        user_id=user_id,
        session_id=session_id,
        db_service=db_service,
    )
    children = [plan, enrichment]
    state = await workflow_engine.get_user_state(user_id)
    if any(child.status == "failed" for child in children):
        status = "failed"
        current_step = _first_blocking_step(children)
    elif all(child.status == "complete" for child in children) and (
        state == WorkflowState.PLAN_UPDATE_COMPLETE
    ):
        status = "complete"
        current_step = "post_session_update_complete"
    elif any(child.status in {"running", "queued"} for child in children):
        status = "running"
        current_step = _first_blocking_step(children)
    else:
        status = "not_started"
        current_step = "waiting_for_session_end"

    attempts = [child.attempt for child in children if child.attempt is not None]
    updated_values = [child.updated_at for child in children if child.updated_at]
    return JobStatusDTO(
        job_id=job_id,
        job_type="post_session_update",
        user_id=user_id,
        session_id=session_id,
        status=status,
        current_step=current_step,
        workflow_state=state,
        attempt=max(attempts) if attempts else None,
        correlation_id=job_id,
        updated_at=max(updated_values) if updated_values else datetime.utcnow(),
        last_error=next(
            (child.last_error for child in children if child.last_error),
            None,
        ),
        children=children,
    )


def _assessment_running(response_handler: Any | None, user_id: str) -> bool:
    jobs = (
        getattr(response_handler, "_assessment_jobs", set())
        if response_handler
        else set()
    )
    return user_id in jobs


def _reflection_running(response_handler: Any | None, session_id: str) -> bool:
    jobs = (
        getattr(response_handler, "_reflection_jobs", set())
        if response_handler
        else set()
    )
    return session_id in jobs


def _first_blocking_step(children: list[JobStatusDTO]) -> str | None:
    for child in children:
        if child.status != "complete":
            return child.current_step
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
