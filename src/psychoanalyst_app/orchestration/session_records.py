"""Persisted session lookup and construction helpers."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from psychoanalyst_app.container.service_container import ServiceContainer
from psychoanalyst_app.models.domain import Message, Session
from psychoanalyst_app.orchestration.models import SessionInfo
from psychoanalyst_app.orchestration.trio_workflow_engine import TrioWorkflowEngine

logger = logging.getLogger(__name__)


async def find_intake_sessions(
    service_container: ServiceContainer,
    user_id: str,
    *,
    limit: int = 1000,
) -> list[Session]:
    """Return intake sessions for a user, logging invalid multiplicity."""
    db_service = service_container.get("trio_db_service")
    sessions = await db_service.get_user_sessions(user_id, limit=limit)
    intake_sessions = [
        session for session in sessions if session.session_type == "intake"
    ]
    if len(intake_sessions) > 1:
        logger.error(
            "Expected a single intake session for user %s; found %s",
            user_id,
            len(intake_sessions),
        )
    return intake_sessions


async def get_latest_therapy_session(
    service_container: ServiceContainer, user_id: str
) -> Session | None:
    """Return the most recent persisted therapy session."""
    db_service = service_container.get("trio_db_service")
    sessions = await db_service.get_user_sessions(user_id, limit=1000)
    return next(
        (session for session in sessions if session.session_type == "therapy"),
        None,
    )


async def create_persisted_session(
    service_container: ServiceContainer,
    *,
    user_id: str,
    session_type: str,
    plan_id: str | None,
) -> str:
    """Create a persisted session and return its generated identifier."""
    session_id = str(uuid.uuid4())
    session = Session(
        session_id=session_id,
        user_id=user_id,
        session_type=session_type,
        plan_id=plan_id,
        timestamp=datetime.now(),
        transcript=[
            Message(
                role="system",
                content="Session started",
                timestamp=datetime.now(),
            )
        ],
        topics=[],
    )
    db_service = service_container.get("trio_db_service")
    if not await db_service.save_session(session):
        raise ValueError("Failed to save session to database")
    return session_id


async def build_session_info(
    service_container: ServiceContainer,
    workflow_engine: TrioWorkflowEngine,
    *,
    user_id: str,
    session_id: str,
) -> SessionInfo:
    """Build client-visible information for a persisted session."""
    db_service = service_container.get("trio_db_service")
    session = await db_service.get_session(session_id)
    state = await workflow_engine.get_user_state(user_id)
    plan = (
        await db_service.get_therapy_plan(session.plan_id)
        if session and session.session_type == "therapy" and session.plan_id
        else None
    )
    return SessionInfo(
        session_id=session_id,
        user_id=user_id,
        agent_type=workflow_engine.get_current_agent(state),
        workflow_state=state,
        created_at=session.timestamp if session else datetime.now(),
        session_type=session.session_type if session else "intake",
        selected_therapy_style=plan.selected_therapy_style if plan else None,
    )
