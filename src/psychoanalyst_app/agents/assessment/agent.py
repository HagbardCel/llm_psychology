"""TrioAssessmentAgent: Agent for evaluating needs and recommending styles."""

from __future__ import annotations

import logging
from typing import Any

import trio

from psychoanalyst_app.agents.assessment.prompts import build_style_assessment_prompt
from psychoanalyst_app.agents.assessment.recommendations import (
    build_recommendation_metadata,
    build_structured_recommendations,
    format_recommendations,
    resolve_recommendation_score,
)
from psychoanalyst_app.agents.assessment.selection import (
    build_continuation_choice_response,
    build_selection_pending_response,
    parse_continuation_choice,
    parse_style_selection,
)
from psychoanalyst_app.context.user_context import UserContext
from psychoanalyst_app.models.domain import Session
from psychoanalyst_app.models.llm_outputs import (
    StructuredTherapyPlanOutput,
    StyleAssessmentOutput,
)
from psychoanalyst_app.orchestration.models import (
    AgentResponse,
    ConversationContext,
    build_agent_response,
    continue_agent_response,
)
from psychoanalyst_app.services.llm_phases import ASSESSMENT_STYLE_SCORING
from psychoanalyst_app.services.llm_service import LLMService
from psychoanalyst_app.services.rag import RAGServiceProtocol
from psychoanalyst_app.services.style_service import StyleService
from psychoanalyst_app.services.trio_db_service import TrioDatabaseService

logger = logging.getLogger(__name__)


class TrioAssessmentAgent:
    """Agent for assessing user needs and recommending therapy styles."""

    def __init__(
        self,
        llm_service: LLMService,
        db_service: TrioDatabaseService,
        rag_service: RAGServiceProtocol,
        user_context: UserContext,
        reflection_agent=None,
        style_service: StyleService | None = None,
    ):
        self.llm_service = llm_service
        self.db_service = db_service
        self.rag_service = rag_service
        self.user_context = user_context
        if reflection_agent is None:
            raise ValueError("reflection_agent is required")
        self.reflection_agent = reflection_agent
        if style_service is None:
            raise ValueError("style_service is required")
        self.style_service = style_service

    async def process_message(
        self, message: str, context: ConversationContext
    ) -> AgentResponse:
        """Process user message during assessment (orchestrator interface)."""
        try:
            continuation_signature = "Would you like to:"
            awaiting_continuation = False
            for msg in reversed(context.message_history[-3:]):
                if msg.role == "assistant" and continuation_signature in msg.content:
                    awaiting_continuation = True
                    break

            if awaiting_continuation:
                choice = parse_continuation_choice(message)
                return build_continuation_choice_response(choice)

            recommendation_signature = (
                "Based on our intake session, I'd like to recommend the following"
            )

            recommendations_made = False
            for msg in reversed(context.message_history[-5:]):
                if msg.role == "assistant" and recommendation_signature in msg.content:
                    recommendations_made = True
                    break

            logger.debug("Assessment history length: %s", len(context.message_history))
            logger.debug("Assessment recommendations made: %s", recommendations_made)

            if recommendations_made:
                selected_style = parse_style_selection(
                    message, self.style_service.get_available_styles()
                )

                if selected_style:
                    return await self.process_selection(selected_style, context)
                else:
                    return build_agent_response(
                        content="I understood you want to proceed, but I'm not sure \
which therapy style you'd like to start with. Could you please specify one of the \
recommended approaches (e.g., Psychoanalysis, CBT)?",
                        next_action="await_selection",
                        next_state=None,
                        workflow_event=None,
                    )
            else:
                return await self.process_assessment(context)

        except Exception as exc:
            return continue_agent_response(
                content=f"I encountered an error: {str(exc)}",
                metadata={"error": str(exc)},
            )

    async def process_assessment(self, context: ConversationContext) -> AgentResponse:
        """Process assessment and generate recommendations."""
        try:
            recommendations = await self._generate_recommendations(
                context.message_history
            )

            structured_recs = build_structured_recommendations(recommendations, limit=3)

            content = format_recommendations(structured_recs)

            return AgentResponse(
                content=content,
                next_action="await_selection",
                next_state=None,
                workflow_event=None,
                metadata={
                    "recommendations": build_recommendation_metadata(structured_recs),
                    "awaiting_selection": True,
                    "is_direct_response": True,
                },
            )

        except Exception as exc:
            return AgentResponse(
                content=f"I encountered an error during assessment: {str(exc)}",
                next_action="continue",
                workflow_event=None,
                metadata={"error": str(exc)},
            )

    async def process_selection(
        self,
        selected_style: str,
        context: ConversationContext,
    ) -> AgentResponse:
        """Process style selection without persisting backend plan data."""
        logger.info("Received assessment style selection: %s", selected_style)
        return build_selection_pending_response(selected_style)

    async def _generate_recommendations(
        self, message_history: list
    ) -> list[dict[str, Any]]:
        """Generate therapy style recommendations based on the intake session."""
        available_styles = self.style_service.get_available_styles()

        session_context = []
        for msg in message_history:
            session_context.append(f"{msg.role}: {msg.content}")

        session_summary = "\n".join(session_context)

        style_assessments: dict[str, dict[str, Any]] = {}

        async with trio.open_nursery() as nursery:
            for style_id in available_styles:
                nursery.start_soon(
                    self._assess_style,
                    style_id,
                    session_summary,
                    style_assessments,
                )

        recommendations = []
        for style_id in available_styles:
            if style_id in style_assessments:
                style_assessment = style_assessments[style_id]
                recommendations.append(
                    {
                        "style_id": style_id,
                        "name": style_id.upper(),
                        "description": self.style_service.get_style_description(
                            style_id
                        ),
                        "assessment": style_assessment["assessment"],
                        "score": style_assessment["score"],
                        "key_topics": style_assessment["key_topics"],
                    }
                )

        recommendations.sort(
            key=lambda recommendation: resolve_recommendation_score(recommendation),
            reverse=True,
        )
        return recommendations

    async def _assess_style(
        self,
        style_id: str,
        session_summary: str,
        results: dict[str, dict[str, Any]],
    ) -> None:
        """Helper to assess a single style asynchronously."""
        assessment_prompt = self.style_service.get_assessment_prompt(style_id)

        evaluation_prompt = build_style_assessment_prompt(
            assessment_prompt=assessment_prompt,
            style_id=style_id,
            session_summary=session_summary,
        )

        try:
            assessment_output = await self.llm_service.generate_structured_output_async(
                evaluation_prompt,
                StyleAssessmentOutput,
                method="json_schema",
                phase=ASSESSMENT_STYLE_SCORING,
            )
            if not isinstance(assessment_output, StyleAssessmentOutput):
                assessment_output = StyleAssessmentOutput.model_validate(
                    assessment_output
                )
            results[style_id] = assessment_output.model_dump(mode="python")
        except Exception:
            logger.warning(
                (
                    "Structured assessment failed for style %s; "
                    "using conservative fallback"
                ),
                style_id,
                exc_info=True,
            )
            results[style_id] = {
                "assessment": (
                    "I do not have enough reliable signal to score this style yet."
                ),
                "score": 0.5,
                "key_topics": [],
            }

    async def create_initial_plan_with_style(
        self, intake_session: Session, selected_style: str
    ) -> StructuredTherapyPlanOutput:
        """Create an initial therapy plan with the selected therapy style."""
        reflection_agent = self.reflection_agent
        return await reflection_agent.create_initial_plan_with_style(
            intake_session, selected_style
        )
