"""LLM + RAG helper functions for the planning agent."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import trio

from psychoanalyst_app.agents.planning.formatting import (
    extract_session_text,
    format_plan_details,
)
from psychoanalyst_app.agents.planning.models import PlanningStrategy
from psychoanalyst_app.agents.planning.prompts import (
    build_initial_plan_prompt,
    build_update_plan_prompt,
)
from psychoanalyst_app.exceptions import PlanningError
from psychoanalyst_app.models.domain import Session, TherapyPlan
from psychoanalyst_app.models.llm_outputs import PlanUpdate
from psychoanalyst_app.services.llm_service import LLMService
from psychoanalyst_app.services.rag import RAGServiceProtocol
from psychoanalyst_app.services.style_service import StyleService

logger = logging.getLogger(__name__)


def _plan_update_details(plan_update: PlanUpdate) -> dict[str, Any]:
    """Keep legacy display strings while exposing structured plan lists."""
    details = plan_update.model_dump()
    details["goals"] = "\n".join(
        f"{index}. {goal}" for index, goal in enumerate(plan_update.goals, start=1)
    )
    details["techniques"] = "\n".join(
        f"{index}. {technique}"
        for index, technique in enumerate(plan_update.techniques, start=1)
    )
    return details


async def get_relevant_knowledge(
    rag_service: RAGServiceProtocol,
    style_service: StyleService,
    session_text: str,
    therapy_style: str | None,
) -> list[dict[str, Any]]:
    """Get relevant domain knowledge filtered by therapy style using Trio."""
    logger.debug("get_relevant_knowledge style=%s", therapy_style)

    try:
        with trio.move_on_after(30) as cancel_scope:
            if therapy_style and style_service.get_style_pack(therapy_style):
                knowledge_source = f"{therapy_style.lower()}.md"
                return await trio.to_thread.run_sync(
                    rag_service.retrieve_relevant_knowledge,
                    session_text,
                    3,
                    knowledge_source,
                )

            return await trio.to_thread.run_sync(
                rag_service.retrieve_relevant_knowledge,
                session_text,
                3,
            )
    except trio.Cancelled:  # pragma: no cover
        raise
    except Exception as exc:  # pragma: no cover
        logger.error("Failed to get relevant knowledge: %s", exc, exc_info=True)
        if cancel_scope.cancelled_caught:
            logger.warning("RAG retrieval timed out")
        return []


async def generate_initial_plan_details(
    llm_service: LLMService,
    style_service: StyleService,
    intake_session: Session,
    session_context,
    strategy: PlanningStrategy,
    relevant_knowledge: list[dict[str, Any]],
) -> tuple[PlanUpdate, dict[str, Any]]:
    """Generate detailed plan using LLM."""
    session_text = extract_session_text(intake_session)

    context = f"""
    Intake Session Analysis:
    Key Themes: {", ".join(session_context.key_themes)}
    Emotional State: {session_context.emotional_state}
    Insights: {", ".join(session_context.insights)}
    Progress Indicators: {", ".join(session_context.progress_indicators)}

    Session Transcript:
    {session_text}

    Therapy Strategy:
    Style: {strategy.therapy_style.upper()}
    Focus Areas: {", ".join(strategy.focus_areas)}
    Techniques: {", ".join(strategy.techniques)}

    Relevant Knowledge:
    """

    for i, knowledge in enumerate(relevant_knowledge, 1):
        context += f"{i}. From {knowledge['source']}: {knowledge['content']}\n"

    reflection_prompt = None
    if style_service.get_style_pack(strategy.therapy_style):
        reflection_prompt = style_service.get_reflection_prompt(
            strategy.therapy_style
        )

    plan_prompt = build_initial_plan_prompt(
        context=context,
        therapy_style=strategy.therapy_style,
        reflection_prompt=reflection_prompt,
    )

    plan_update = await llm_service.generate_structured_output_async(
        plan_prompt,
        PlanUpdate,
        method="json_schema",
        phase="initial_plan_generation",
    )
    if not isinstance(plan_update, PlanUpdate):
        raise PlanningError("Initial plan generation returned unexpected type")

    plan_details = _plan_update_details(plan_update)
    plan_details.update(
        {
            "created_from_session": intake_session.session_id,
            "therapy_style": strategy.therapy_style,
            "focus_areas": strategy.focus_areas,
            "initial_themes": session_context.key_themes,
            "initial_emotional_state": session_context.emotional_state,
        }
    )
    return plan_update, plan_details


async def generate_updated_plan_details(
    llm_service: LLMService,
    style_service: StyleService,
    memory_agent,
    session: Session,
    session_context,
    memory,
    current_plan: TherapyPlan,
    relevant_knowledge: list[dict[str, Any]],
) -> tuple[PlanUpdate, dict[str, Any]]:
    """Generate updated plan details using LLM."""
    session_text = extract_session_text(session)
    recent_context = await memory_agent.get_recent_context(num_sessions=3)

    context = f"""
    Current Therapy Plan (Version {current_plan.version}):
    {format_plan_details(current_plan.plan_details)}

    Latest Session Analysis:
    Key Themes: {", ".join(session_context.key_themes)}
    Emotional State: {session_context.emotional_state}
    Insights: {", ".join(session_context.insights)}
    Progress Indicators: {", ".join(session_context.progress_indicators)}

    Recent Context Summary:
    {recent_context.get("context_summary", "No recent context")}

    Therapeutic Memory Patterns:
    Dominant Themes: {", ".join(list(memory.recurring_themes.keys())[:3]) if memory.recurring_themes else "None"}
    Emotional Progression: {" → ".join(memory.emotional_patterns[-3:]) if memory.emotional_patterns else "None"}
    Relationship Quality: {memory.relationship_quality}

    Latest Session Transcript:
    {session_text}

    Relevant Knowledge:
    """

    for i, knowledge in enumerate(relevant_knowledge, 1):
        context += f"{i}. From {knowledge['source']}: {knowledge['content']}\n"

    therapy_style = current_plan.selected_therapy_style
    reflection_prompt = None
    if therapy_style and style_service.get_style_pack(therapy_style):
        reflection_prompt = style_service.get_reflection_prompt(therapy_style)

    update_prompt = build_update_plan_prompt(
        context=context,
        therapy_style=therapy_style,
        reflection_prompt=reflection_prompt,
    )

    plan_update = await llm_service.generate_structured_output_async(
        update_prompt,
        PlanUpdate,
        method="json_schema",
        phase="post_session_update",
    )
    if not isinstance(plan_update, PlanUpdate):
        raise PlanningError("Plan update generation returned unexpected type")

    updated_details = current_plan.plan_details.copy()
    for key, value in _plan_update_details(plan_update).items():
        if isinstance(value, str) and value.strip():
            updated_details[key] = value

    updated_details.update(
        {
            "updated_from_session": session.session_id,
            "update_timestamp": datetime.now().isoformat(),
            "memory_insights": recent_context.get("insights", [])[-2:],
            "progress_indicators": session_context.progress_indicators,
        }
    )

    return plan_update, updated_details
