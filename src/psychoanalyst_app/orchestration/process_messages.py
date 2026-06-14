"""Helpers for TrioAgentOrchestrator.process_message."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from psychoanalyst_app.models.llm_outputs import StructuredUserProfileOutput
from psychoanalyst_app.orchestration.intake_record_persistence import (
    update_intake_record,
)
from psychoanalyst_app.orchestration.models import AgentResponse, WorkflowState
from psychoanalyst_app.orchestration.profile_helpers import (
    persist_structured_user_profile_output,
)

logger = logging.getLogger(__name__)


async def ensure_session(
    session_lifecycle,
    user_id: str,
    session_id: str | None,
) -> str:
    """Ensure a session exists and return its ID."""
    return await session_lifecycle.ensure_session_id(user_id, session_id)


async def record_user_message(
    conversation_manager,
    session_id: str,
    message: str,
) -> None:
    """Persist user messages when non-empty."""
    if message.strip():
        await conversation_manager.add_message(session_id, "user", message)


async def ensure_profile_for_new_state(
    service_container,
    user_id: str,
    state: WorkflowState,
) -> None:
    """Require a profile for NEW users before entering message processing."""
    if state != WorkflowState.NEW:
        return

    trio_db_service = service_container.get("trio_db_service")
    existing = await trio_db_service.get_user_profile(user_id)
    if not existing:
        raise ValueError("User profile not found; register before starting a session")


async def resolve_agent_and_context(
    workflow_engine,
    conversation_manager,
    get_agent,
    user_id: str,
    session_id: str,
    state: WorkflowState,
) -> tuple[str, Any, Any]:
    """Resolve the agent type, agent instance, and conversation context."""
    agent_type = workflow_engine.get_current_agent(state)
    context = await conversation_manager.get_context(session_id)
    agent = await get_agent(agent_type, user_id)
    return agent_type, agent, context


async def stream_agent_response(
    conversation_manager,
    service_container,
    agent_type: str,
    agent,
    agent_response: AgentResponse,
    context,
) -> AsyncIterator[str]:
    """Stream content for an agent response."""
    metadata = agent_response.metadata or {}
    agent_llm_service = getattr(agent, "llm_service", None)
    if agent_llm_service is None:
        agent_llm_service = service_container.get("llm_service")

    if metadata.get("is_direct_response"):
        async for chunk in conversation_manager.stream_static_response(
            agent_response.content, context, agent=agent_type
        ):
            yield chunk
    else:
        async for chunk in conversation_manager.stream_response(
            agent_response.content,
            context,
            agent=agent_type,
            llm_service=agent_llm_service,
        ):
            yield chunk


async def finalize_agent_response(
    service_container,
    response_handler,
    user_id: str,
    session_id: str,
    agent_response: AgentResponse,
) -> None:
    """Persist structured outputs and handle workflow transitions."""
    metadata = agent_response.metadata or {}
    trio_db_service = service_container.get("trio_db_service")

    user_profile_output = metadata.get("user_profile")
    if isinstance(user_profile_output, StructuredUserProfileOutput):
        saved = await persist_structured_user_profile_output(
            trio_db_service=trio_db_service,
            user_id=user_id,
            session_id=session_id,
            user_profile_output=user_profile_output,
            change_summary="Agent profile update",
        )
        if not saved:
            raise ValueError("Failed to save user profile to database")
    elif user_profile_output is not None:
        logger.warning(
            "Ignoring unexpected user_profile payload type: %s",
            type(user_profile_output),
        )

    intake_record = metadata.get("intake_record")
    if isinstance(intake_record, dict):
        await update_intake_record(
            response_handler.conversation_manager,
            session_id,
            intake_record,
        )
    elif intake_record is not None:
        logger.warning(
            "Ignoring unexpected intake_record payload type: %s",
            type(intake_record),
        )

    await response_handler.handle(user_id, session_id, agent_response)
