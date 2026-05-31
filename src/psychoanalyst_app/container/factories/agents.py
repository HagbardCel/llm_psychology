"""Agent factory functions for ServiceContainer."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from psychoanalyst_app.context.user_context import UserContext

if TYPE_CHECKING:
    from psychoanalyst_app.container.service_container import ServiceContainer

logger = logging.getLogger(__name__)


def create_agent(
    container: ServiceContainer, agent_type: str, user_context: UserContext
):
    """Create agent instance using centralized mapping."""
    normalized = agent_type.upper()
    builders = {
        "INTAKE": build_intake_agent,
        "ASSESSMENT": build_assessment_agent,
        "THERAPIST": build_therapist_agent,
        "REFLECTION": build_reflection_agent,
        "MEMORY": build_memory_agent,
        "PLANNING": build_planning_agent,
    }
    builder = builders.get(normalized)
    if not builder:
        raise ValueError(f"Unknown agent type: {agent_type}")
    return builder(container, user_context)


def build_intake_agent(container: ServiceContainer, user_context: UserContext):
    """Build intake agent."""
    from psychoanalyst_app.agents.intake import TrioIntakeAgent

    logger.debug("Creating TrioIntakeAgent for user %s", user_context.user_id)
    agent = TrioIntakeAgent(
        llm_service=container._get_llm_service_for_agent("INTAKE"),
        user_context=user_context,
        config=container.config,
    )
    logger.info("Created TrioIntakeAgent for user %s", user_context.user_id)
    return agent


def build_assessment_agent(container: ServiceContainer, user_context: UserContext):
    """Build assessment agent."""
    from psychoanalyst_app.agents.assessment import TrioAssessmentAgent

    logger.debug("Creating TrioAssessmentAgent for user %s", user_context.user_id)
    reflection_agent = container.create_reflection_agent(user_context)
    agent = TrioAssessmentAgent(
        llm_service=container._get_llm_service_for_agent("ASSESSMENT"),
        db_service=container.get("trio_db_service"),
        rag_service=container.get("rag_service"),
        user_context=user_context,
        reflection_agent=reflection_agent,
        style_service=container.get("style_service"),
    )
    logger.info("Created TrioAssessmentAgent for user %s", user_context.user_id)
    return agent


def build_therapist_agent(container: ServiceContainer, user_context: UserContext):
    """Build psychoanalyst agent."""
    from psychoanalyst_app.agents.therapist import TrioTherapistAgent

    logger.debug("Creating TrioTherapistAgent for user %s", user_context.user_id)
    reflection_agent = container.create_reflection_agent(user_context)
    agent = TrioTherapistAgent(
        llm_service=container._get_llm_service_for_agent("THERAPIST"),
        db_service=container.get("trio_db_service"),
        rag_service=container.get("rag_service"),
        reflection_agent=reflection_agent,
        style_service=container.get("style_service"),
        config=container.config,
    )
    logger.info("Created TrioTherapistAgent for user %s", user_context.user_id)
    return agent


def build_reflection_agent(container: ServiceContainer, user_context: UserContext):
    """Build reflection agent."""
    from psychoanalyst_app.agents.reflection import TrioReflectionAgent

    logger.debug("Creating TrioReflectionAgent for user %s", user_context.user_id)
    memory_agent = container.create_memory_agent(user_context)
    planning_agent = container.create_planning_agent(user_context)
    agent = TrioReflectionAgent(
        llm_service=container._get_llm_service_for_agent("REFLECTION"),
        db_service=container.get("trio_db_service"),
        rag_service=container.get("rag_service"),
        user_context=user_context,
        memory_agent=memory_agent,
        planning_agent=planning_agent,
        config=container.config,
    )
    logger.info("Created TrioReflectionAgent for user %s", user_context.user_id)
    return agent


def build_memory_agent(container: ServiceContainer, user_context: UserContext):
    """Build memory agent."""
    from psychoanalyst_app.agents.memory import TrioMemoryAgent

    logger.debug("Creating TrioMemoryAgent for user %s", user_context.user_id)
    agent = TrioMemoryAgent(
        llm_service=container._get_llm_service_for_agent("MEMORY"),
        db_service=container.get("trio_db_service"),
        rag_service=container.get("rag_service"),
        user_context=user_context,
    )
    logger.info("Created TrioMemoryAgent for user %s", user_context.user_id)
    return agent


def build_planning_agent(container: ServiceContainer, user_context: UserContext):
    """Build planning agent."""
    from psychoanalyst_app.agents.planning import TrioPlanningAgent

    logger.debug("Creating TrioPlanningAgent for user %s", user_context.user_id)
    memory_agent = container.create_memory_agent(user_context)
    agent = TrioPlanningAgent(
        llm_service=container._get_llm_service_for_agent("PLANNING"),
        db_service=container.get("trio_db_service"),
        rag_service=container.get("rag_service"),
        user_context=user_context,
        memory_agent=memory_agent,
        style_service=container.get("style_service"),
    )
    logger.info("Created TrioPlanningAgent for user %s", user_context.user_id)
    return agent
