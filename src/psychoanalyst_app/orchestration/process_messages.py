"""Helpers for TrioAgentOrchestrator.process_message."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from psychoanalyst_app.models.data_models import TherapyPlan
from psychoanalyst_app.models.structured_output_models import (
    StructuredTherapyPlanOutput,
    StructuredUserProfileOutput,
)
from psychoanalyst_app.orchestration.agent_output_validators import is_profile_complete
from psychoanalyst_app.orchestration.models import AgentResponse, WorkflowState
from psychoanalyst_app.orchestration.profile_helpers import (
    ensure_user_profile,
    merge_user_profile,
)

logger = logging.getLogger(__name__)


async def ensure_session(session_lifecycle, user_id: str, session_id: str | None) -> str:
    """Ensure a session exists and return its ID."""
    if session_id:
        return session_id
    return await session_lifecycle.create_session(user_id)


async def record_user_message(conversation_manager, session_id: str, message: str) -> None:
    """Persist user messages when non-empty."""
    if message.strip():
        await conversation_manager.add_message(session_id, "user", message)


async def ensure_profile_for_new_state(service_container, user_id: str, state: WorkflowState) -> None:
    """Create placeholder profiles for NEW users without workflow transitions."""
    if state != WorkflowState.NEW:
        return

    trio_db_service = service_container.get("trio_db_service")
    existing = await trio_db_service.get_user_profile(user_id)
    if existing:
        return

    await ensure_user_profile(trio_db_service, user_id, {"name": "Guest"})


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

    updated_profile = None
    user_profile_output = metadata.get("user_profile")
    if isinstance(user_profile_output, StructuredUserProfileOutput):
        updates = user_profile_output.model_dump(
            exclude_none=True, exclude_unset=True
        )
        existing = await trio_db_service.get_user_profile(user_id)
        merged = merge_user_profile(
            existing_profile=existing,
            user_id=user_id,
            updates=updates,
        )
        success = await trio_db_service.update_user_profile(
            merged,
            change_summary="Agent profile update",
            created_by_session=session_id,
        )
        if not success:
            raise ValueError("Failed to save user profile to database")
        updated_profile = merged
    elif user_profile_output is not None:
        logger.warning(
            "Ignoring unexpected user_profile payload type: %s",
            type(user_profile_output),
        )

    therapy_plan_output = metadata.get("therapy_plan")
    if isinstance(therapy_plan_output, StructuredTherapyPlanOutput):
        latest_plan = await trio_db_service.get_latest_therapy_plan(user_id)
        plan = TherapyPlan(
            plan_id=str(uuid.uuid4()),
            user_id=user_id,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            version=(latest_plan.version + 1) if latest_plan else 1,
            selected_therapy_style=therapy_plan_output.selected_therapy_style,
            plan_details=therapy_plan_output.plan_details,
            initial_goals=therapy_plan_output.initial_goals,
            current_progress=therapy_plan_output.current_progress,
            planned_interventions=therapy_plan_output.planned_interventions,
            status=therapy_plan_output.status,
        )
        success = await trio_db_service.save_therapy_plan(plan)
        if not success:
            raise ValueError("Failed to save therapy plan to database")
    elif therapy_plan_output is not None:
        logger.warning(
            "Ignoring unexpected therapy_plan payload type: %s",
            type(therapy_plan_output),
        )

    if agent_response.next_state == WorkflowState.INTAKE_IN_PROGRESS:
        profile = updated_profile or await trio_db_service.get_user_profile(user_id)
        if not profile or not is_profile_complete(profile):
            logger.info(
                "Profile incomplete for user %s; skipping transition to intake",
                user_id,
            )
            agent_response.next_state = None
            if agent_response.next_action == "transition":
                agent_response.next_action = "continue"

    await response_handler.handle(user_id, session_id, agent_response)
