"""Prompt/context assembly helpers for therapist agent."""

from __future__ import annotations

import logging
from typing import Any

import trio

from psychoanalyst_app.agents.therapist.prompts import build_continuation_prompt
from psychoanalyst_app.models.domain import TherapyPlan
from psychoanalyst_app.orchestration.models import ConversationContext

logger = logging.getLogger(__name__)


def _default_style_instructions(
    selected_style: str | None,
    style_service,
) -> str:
    style_instructions = "Conduct a general psychoanalytic session."
    if selected_style and style_service.get_style_pack(selected_style):
        style_instructions = style_service.get_therapist_prompt(selected_style)
    return style_instructions


async def _retrieve_relevant_knowledge(
    rag_service,
    style_service,
    selected_style: str | None,
    query: str,
    *,
    n_results: int,
) -> list[dict[str, Any]]:
    if selected_style:
        knowledge_source = style_service.get_knowledge_source(selected_style)
        return await trio.to_thread.run_sync(
            rag_service.retrieve_relevant_knowledge,
            query,
            n_results,
            knowledge_source,
        )
    return await trio.to_thread.run_sync(
        rag_service.retrieve_relevant_knowledge,
        query,
        n_results,
    )


async def build_plan_context(
    therapy_plan: TherapyPlan,
    rag_service,
    style_service,
) -> str:
    """Build the therapy plan context string."""
    selected_style = therapy_plan.selected_therapy_style
    plan_focus = therapy_plan.focus

    relevant_knowledge = await _retrieve_relevant_knowledge(
        rag_service,
        style_service,
        selected_style,
        plan_focus,
        n_results=2,
    )

    context = f"""
        Therapy Plan (Version {therapy_plan.version}):
        Focus: {therapy_plan.focus}
        Goals: {", ".join(therapy_plan.initial_goals)}
        Techniques: {", ".join(therapy_plan.planned_interventions)}
        Themes: {", ".join(therapy_plan.themes) or "None"}
        Timeline: {therapy_plan.timeline or "Not specified"}

        Relevant Psychological Knowledge:
        """

    for index, knowledge in enumerate(relevant_knowledge, 1):
        context += f"{index}. From {knowledge['source']}: {knowledge['content']}\\n"

    return context


async def load_patient_context(
    db_service,
    user_id: str,
    *,
    exclude_session_ids: set[str] | None = None,
) -> str | None:
    """Load comprehensive patient context from all 4 tiers."""
    exclude_session_ids = exclude_session_ids or set()
    try:
        async with trio.open_nursery() as nursery:
            tier1_result = {"data": None}
            tier2_result = {"data": None}
            tier3_result = {"data": None}
            tier4_result = {"data": None}

            async def load_tier1() -> None:
                tier1_result["data"] = await db_service.get_user_profile(user_id)

            async def load_tier2() -> None:
                limit = 5
                enriched = await db_service.get_recent_sessions(
                    user_id,
                    limit=limit,
                    enriched_only=True,
                )
                tier2_result["data"] = enriched

                if len(enriched) < limit:
                    recent_any = await db_service.get_recent_sessions(
                        user_id,
                        limit=max(limit * 3, 10),
                        enriched_only=False,
                    )
                    for session in recent_any:
                        if session.session_id in exclude_session_ids:
                            continue
                        if getattr(session, "enriched", False):
                            continue
                        await db_service.enqueue_session_enrichment_job(
                            session.session_id,
                            user_id,
                        )

            async def load_tier3() -> None:
                tier3_result["data"] = await db_service.get_latest_patient_analysis(
                    user_id
                )

            async def load_tier4() -> None:
                tier4_result["data"] = await db_service.get_current_therapy_plan(
                    user_id
                )

            nursery.start_soon(load_tier1)
            nursery.start_soon(load_tier2)
            nursery.start_soon(load_tier3)
            nursery.start_soon(load_tier4)

        user_profile = tier1_result["data"]
        recent_sessions = tier2_result["data"]
        current_analysis = tier3_result["data"]
        treatment_plan = tier4_result["data"]

        has_data = any(
            [user_profile, recent_sessions, current_analysis, treatment_plan],
        )
        if not has_data:
            logger.info("No patient context data for user %s", user_id)
            return None

        context_parts: list[str] = []

        if user_profile:
            context_parts.append("=== PATIENT BACKGROUND ===")
            context_parts.append(f"Patient: {user_profile.alias or user_profile.name}")
            if user_profile.cultural_background:
                context_parts.append(
                    f"Cultural Background: {user_profile.cultural_background}"
                )
            if user_profile.family_atmosphere:
                context_parts.append(f"Family: {user_profile.family_atmosphere}")
            if user_profile.relationship_to_work:
                context_parts.append(f"Work: {user_profile.relationship_to_work}")
            if user_profile.current_situation:
                context_parts.append(
                    f"Current Situation: {user_profile.current_situation}"
                )
            context_parts.append("")

        if current_analysis:
            analysis = current_analysis.analysis_data
            context_parts.append("=== CLINICAL FORMULATION ===")
            context_parts.append(f"(Version {current_analysis.version})")
            context_parts.append(f"Current Focus: {analysis.current_focus.theme}")
            context_parts.append(f"  {analysis.current_focus.salience}")
            if analysis.transference.other_patterns:
                context_parts.append(
                    f"Transference: {analysis.transference.other_patterns}"
                )
            if analysis.narratives:
                context_parts.append("Recurring Narratives:")
                for narrative in analysis.narratives[:3]:
                    context_parts.append(
                        f"  - {narrative.title}: {narrative.description}"
                    )
            if analysis.defenses.primary_defenses:
                context_parts.append(
                    "Primary Defenses: "
                    + ", ".join(analysis.defenses.primary_defenses[:3])
                )
            if analysis.orientation.pacing:
                context_parts.append(
                    f"Therapeutic Pacing: {analysis.orientation.pacing}"
                )
            if analysis.orientation.risk_areas:
                context_parts.append(
                    "Risk Areas: " + ", ".join(analysis.orientation.risk_areas[:3])
                )
            context_parts.append("")

        if treatment_plan:
            context_parts.append("=== TREATMENT GOALS ===")
            for index, goal in enumerate(treatment_plan.initial_goals[:3], 1):
                context_parts.append(f"{index}. {goal}")
            if treatment_plan.current_progress:
                progress = treatment_plan.current_progress[:200]
                if len(treatment_plan.current_progress) > 200:
                    progress += "..."
                context_parts.append(f"Progress: {progress}")
            context_parts.append("")

        if recent_sessions and len(recent_sessions) > 0:
            context_parts.append(
                f"=== RECENT SESSIONS (Last {len(recent_sessions)}) ==="
            )
            for session in recent_sessions:
                date = session.timestamp.strftime("%Y-%m-%d")
                if session.enriched and session.psychological_summary:
                    summary = session.psychological_summary.split(".")[0]
                    if len(summary) > 100:
                        summary = summary[:100] + "..."
                    context_parts.append(f"[{date}] {summary}")
                    if session.key_themes:
                        themes = ", ".join(session.key_themes[:3])
                        context_parts.append(f"  Themes: {themes}")
                else:
                    context_parts.append(f"[{date}] Session recorded")

        return "\\n".join(context_parts)

    except Exception as exc:
        logger.error(
            "Error loading patient context for user %s: %s",
            user_id,
            exc,
            exc_info=True,
        )
        return None


async def build_continuation_prompt_with_context(
    message: str,
    context: ConversationContext,
    therapy_plan: TherapyPlan,
    selected_style: str,
    rag_service,
    style_service,
    db_service,
) -> str:
    """Build continuation prompt with RAG + patient context."""
    recent_messages = context.message_history[-3:]
    recent_context = " ".join([msg.content for msg in recent_messages] + [message])
    context_knowledge = await _retrieve_relevant_knowledge(
        rag_service,
        style_service,
        selected_style,
        recent_context,
        n_results=1,
    )

    plan_context = await build_plan_context(therapy_plan, rag_service, style_service)
    patient_context = await load_patient_context(
        db_service,
        context.user_profile.user_id,
        exclude_session_ids={context.session_id},
    )
    if patient_context:
        plan_context = f"{patient_context}\\n\\n{plan_context}"

    style_instructions = _default_style_instructions(selected_style, style_service)
    knowledge_text = context_knowledge[0]["content"] if context_knowledge else "None"

    return build_continuation_prompt(
        plan_context=plan_context,
        additional_knowledge=knowledge_text,
        latest_message=message,
        style_instructions=style_instructions,
    )


def default_style_instructions(
    selected_style: str | None,
    style_service,
) -> str:
    """Expose style instruction defaulting logic for agent wrappers."""
    return _default_style_instructions(selected_style, style_service)
