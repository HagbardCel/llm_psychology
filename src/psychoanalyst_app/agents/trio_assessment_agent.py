"""
TrioAssessmentAgent: Agent for evaluating needs and recommending styles.

This agent analyzes the intake session and recommends appropriate therapy
approaches based on the user's needs and presenting concerns.

Pure Trio implementation using structured concurrency.
"""

import logging
from typing import Any

import trio

from psychoanalyst_app.agents.assessment.intake_artifacts import (
    extract_tier3_initial_formulation,
    extract_tier4_initial_plan,
    load_user_profile_context,
)
from psychoanalyst_app.agents.assessment.recommendation_payloads import (
    build_recommendation_metadata,
    build_structured_recommendations,
    format_recommendations,
)
from psychoanalyst_app.agents.assessment.scoring import resolve_recommendation_score
from psychoanalyst_app.agents.assessment.selection_handling import (
    build_continuation_choice_response,
    build_selection_pending_response,
)
from psychoanalyst_app.agents.assessment.topic_extraction import extract_key_topics
from psychoanalyst_app.agents.parsing import (
    parse_continuation_choice,
    parse_style_selection,
)
from psychoanalyst_app.context.user_context import UserContext
from psychoanalyst_app.models.data_models import (
    PatientAnalysisVersion,
    Session,
)
from psychoanalyst_app.models.structured_output_models import (
    StructuredTherapyPlanOutput,
    StyleAssessmentOutput,
)
from psychoanalyst_app.orchestration.models import (
    AgentResponse,
    ConversationContext,
    TherapyStyleRecommendation,
    build_agent_response,
    continue_agent_response,
)
from psychoanalyst_app.prompts.assessment_prompt_builder import (
    build_style_assessment_prompt,
)
from psychoanalyst_app.services.llm_service import LLMService
from psychoanalyst_app.services.rag_service import RAGService
from psychoanalyst_app.services.style_service import StyleService
from psychoanalyst_app.services.trio_db_service import TrioDatabaseService

logger = logging.getLogger(__name__)


class TrioAssessmentAgent:
    """
    Agent for assessing user needs and recommending therapy styles.

    Uses Trio's structured concurrency for all async operations.
    """

    def __init__(
        self,
        llm_service: LLMService,
        db_service: TrioDatabaseService,
        rag_service: RAGService,
        user_context: UserContext,
        reflection_agent=None,
        style_service: StyleService | None = None,
    ):
        """
        Initialize the Trio Assessment Agent.

        Args:
            llm_service: The LLM service for generating responses (synchronous)
            db_service: The Trio database service for storing therapy plans
            rag_service: The RAG service for retrieving domain knowledge (synchronous)
            user_context: User context
            reflection_agent: TrioReflectionAgent for dependency injection
        """
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

    # ===== NEW ORCHESTRATOR INTERFACE =====

    async def process_message(
        self, message: str, context: ConversationContext
    ) -> AgentResponse:
        """
        Process user message during assessment (orchestrator interface).

        Args:
            message: User's message
            context: Conversation context

        Returns:
            AgentResponse with recommendations or confirmation
        """
        try:
            # Check if we're waiting for a continuation choice
            continuation_signature = "Would you like to:"
            awaiting_continuation = False
            for msg in reversed(context.message_history[-3:]):
                if msg.role == "assistant" and continuation_signature in msg.content:
                    awaiting_continuation = True
                    break

            if awaiting_continuation:
                # Parse continuation choice
                choice = parse_continuation_choice(message)
                return build_continuation_choice_response(choice)

            # Check if recommendations have been made recently
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
                # We have made recommendations, so any user message now is
                # a selection attempt
                selected_style = parse_style_selection(
                    message, self.style_service.get_available_styles()
                )

                if selected_style:
                    return await self.process_selection(selected_style, context)
                else:
                    # Could not identify style, ask for clarification
                    # This keeps us in the selection loop
                    return build_agent_response(
                        content="I understood you want to proceed, but I'm not sure \
which therapy style you'd like to start with. Could you please specify one of the \
recommended approaches (e.g., Psychoanalysis, CBT)?",
                        next_action="await_selection",
                        next_state=None,
                        workflow_event=None,
                    )
            else:
                # Recommendations not yet made, generate them
                return await self.process_assessment(context)

        except Exception as e:
            return continue_agent_response(
                content=f"I encountered an error: {str(e)}",
                metadata={"error": str(e)},
            )

    async def process_assessment(self, context: ConversationContext) -> AgentResponse:
        """
        Process assessment and generate recommendations using Trio.

        Args:
            context: Conversation context

        Returns:
            AgentResponse with recommendations
        """
        try:
            # Generate recommendations
            recommendations = await self._generate_recommendations(
                context.message_history
            )

            # Convert to structured format
            structured_recs = build_structured_recommendations(recommendations, limit=3)

            # Format response content
            content = self._format_recommendations(structured_recs)

            return AgentResponse(
                content=content,
                next_action="await_selection",  # Wait for user to select
                next_state=None,
                workflow_event=None,
                metadata={
                    "recommendations": build_recommendation_metadata(structured_recs),
                    "awaiting_selection": True,
                    "is_direct_response": True,
                },
            )

        except Exception as e:
            return AgentResponse(
                content=f"I encountered an error during assessment: {str(e)}",
                next_action="continue",
                workflow_event=None,
                metadata={"error": str(e)},
            )

    def _resolve_recommendation_score(self, recommendation: dict[str, Any]) -> float:
        """Resolve recommendation score from recommendation payload."""
        return resolve_recommendation_score(recommendation)

    def _extract_key_topics(self, recommendation: dict[str, Any]) -> list[str]:
        """Extract key topics from recommendation payload with safe fallbacks."""
        return extract_key_topics(recommendation)

    async def process_selection(
        self,
        selected_style: str,
        context: ConversationContext,
    ) -> AgentResponse:
        """
        Process style selection without persisting backend plan data.

        Args:
            selected_style: User's selected therapy style
            intake_session: Completed intake session
            context: Conversation context

        Returns:
            AgentResponse with confirmation
        """
        logger.info("Received assessment style selection: %s", selected_style)
        return build_selection_pending_response(selected_style)

    def _format_recommendations(
        self, recommendations: list[TherapyStyleRecommendation]
    ) -> str:
        """
        Format recommendations for display.

        Args:
            recommendations: List of therapy style recommendations

        Returns:
            Formatted string
        """
        return format_recommendations(recommendations)

    async def _generate_recommendations(
        self, message_history: list
    ) -> list[dict[str, Any]]:
        """
        Generate therapy style recommendations based on the intake session using Trio.

        Args:
            message_history: The conversation history

        Returns:
            List of recommended therapy styles with descriptions
        """
        # Get all available therapy styles
        available_styles = self.style_service.get_available_styles()

        # Create a comprehensive session summary for assessment
        session_context = []
        for msg in message_history:
            session_context.append(f"{msg.role}: {msg.content}")

        session_summary = "\n".join(session_context)

        # For each style, use the assessment prompt to evaluate suitability
        style_assessments: dict[str, dict[str, Any]] = {}

        # Use a nursery to run assessments concurrently
        async with trio.open_nursery() as nursery:
            for style_id in available_styles:
                nursery.start_soon(
                    self._assess_style,
                    style_id,
                    session_summary,
                    style_assessments,
                )

        # Create recommendations with descriptions
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
            key=lambda recommendation: self._resolve_recommendation_score(
                recommendation
            ),
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

        # Create a prompt to evaluate the session against this style's criteria
        evaluation_prompt = build_style_assessment_prompt(
            assessment_prompt=assessment_prompt,
            style_id=style_id,
            session_summary=session_summary,
        )

        try:
            # Generate structured assessment payload with LLM-provided score/topics.
            assessment_output = await self.llm_service.generate_structured_output_async(
                evaluation_prompt,
                StyleAssessmentOutput,
                method="json_schema",
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
        """
        Create an initial therapy plan with the selected therapy style using Trio.

        Args:
            intake_session: The completed intake session
            selected_style: The user-selected therapy style

        Returns:
            StructuredTherapyPlanOutput: Structured plan payload (no persistence)
        """
        # Use the injected TrioReflectionAgent dependency
        reflection_agent = self.reflection_agent

        # FIXED: Added await to async method call
        return await reflection_agent.create_initial_plan_with_style(
            intake_session, selected_style
        )

    async def _load_user_profile(self, user_id: str) -> str | None:
        """
        Load user profile and format as Tier 1 context string.

        Args:
            user_id: User ID

        Returns:
            Formatted patient background string, or None if not found
        """
        return await load_user_profile_context(self.db_service, user_id)

    async def _extract_tier3_initial_formulation(
        self,
        intake_session: Session,
        therapy_style: str,
        patient_background: str | None,
    ) -> PatientAnalysisVersion | None:
        """
        Extract initial clinical formulation (Tier 3) from intake assessment.

        Creates version 1 of PatientAnalysis.

        Args:
            intake_session: Completed intake session
            therapy_style: Selected therapy style
            patient_background: Formatted patient background (Tier 1)

        Returns:
            PatientAnalysisVersion v1, or None if extraction fails
        """
        return await extract_tier3_initial_formulation(
            llm_service=self.llm_service,
            intake_session=intake_session,
            therapy_style=therapy_style,
            patient_background=patient_background,
        )

    async def _extract_tier4_initial_plan(
        self,
        intake_session: Session,
        therapy_style: str,
        patient_background: str | None,
        tier3_formulation: PatientAnalysisVersion | None,
    ) -> dict[str, Any] | None:
        """
        Extract initial treatment plan (Tier 4) from intake assessment.

        Args:
            intake_session: Completed intake session
            therapy_style: Selected therapy style
            patient_background: Formatted patient background (Tier 1)
            tier3_formulation: Clinical formulation (Tier 3)

        Returns:
            Dict containing Tier 4 data, or None if extraction fails
        """
        return await extract_tier4_initial_plan(
            llm_service=self.llm_service,
            intake_session=intake_session,
            therapy_style=therapy_style,
            patient_background=patient_background,
            tier3_formulation=tier3_formulation,
        )
