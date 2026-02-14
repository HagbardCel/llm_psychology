"""
TrioAssessmentAgent: Agent for evaluating needs and recommending styles.

This agent analyzes the intake session and recommends appropriate therapy
approaches based on the user's needs and presenting concerns.

Pure Trio implementation using structured concurrency.
"""

import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any

import trio

from psychoanalyst_app.agents.parsing import parse_continuation_choice, parse_style_selection
from psychoanalyst_app.context.user_context import UserContext
from psychoanalyst_app.models.data_models import (
    AnalyticOrientation,
    CurrentFocus,
    DefensiveOrganization,
    PatientAnalysis,
    PatientAnalysisVersion,
    RecurringNarrative,
    Session,
    TransferenceImpressions,
)
from psychoanalyst_app.models.structured_output_models import (
    StructuredTherapyPlanOutput,
    Tier4Extract,
)
from psychoanalyst_app.orchestration.models import (
    AgentResponse,
    ConversationContext,
    TherapyStyleRecommendation,
    build_agent_response,
    continue_agent_response,
    direct_agent_response,
)
from psychoanalyst_app.prompts.assessment_prompts import (
    TIER3_INITIAL_FORMULATION_PROMPT,
    TIER4_INITIAL_PLAN_PROMPT,
)
from psychoanalyst_app.prompts.assessment_prompt_builder import build_style_assessment_prompt
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
                if choice == "finish":
                    return direct_agent_response(
                        content="That sounds like a good plan. Take your time to \
reflect on what we've discussed today. I look forward to our first therapy session \
together. Take care!",
                        next_action="end_session",
                        metadata={"session_ended": True},
                    )
                elif choice == "continue":
                    return direct_agent_response(
                        content="Wonderful! Let's begin our first therapy session. \
I'm here to support you.",
                        next_action="start_therapy",
                        workflow_event=None,
                        metadata={"new_session_required": True},
                    )
                else:
                    return direct_agent_response(
                        content="I'm not sure which option you'd prefer. Would you \
like to finish for today (option 1) or continue with our first therapy session now \
(option 2)?",
                        next_action="await_continuation_choice",
                    )

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
            structured_recs = []
            for rank, rec in enumerate(recommendations[:3]):  # Top 3
                structured_recs.append(
                    TherapyStyleRecommendation(
                        style_name=rec["style_id"],
                        score=self._resolve_recommendation_score(rec, rank),
                        explanation=rec["assessment"],
                        key_topics=self._extract_key_topics(rec),
                    )
                )

            # Format response content
            content = self._format_recommendations(structured_recs)

            return AgentResponse(
                content=content,
                next_action="await_selection",  # Wait for user to select
                next_state=None,
                workflow_event=None,
                metadata={
                    "recommendations": [
                        {
                            "style_id": rec.style_name,
                            "explanation": rec.explanation,
                            "score": rec.score,
                        }
                        for rec in structured_recs
                    ],
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

    def _resolve_recommendation_score(self, recommendation: dict[str, Any], rank: int) -> float:
        """Resolve recommendation score with deterministic rank fallback."""
        raw_score = recommendation.get("score")
        if isinstance(raw_score, (int, float)):
            return max(0.0, min(1.0, float(raw_score)))
        return max(0.1, 0.9 - (rank * 0.1))

    def _extract_key_topics(self, recommendation: dict[str, Any]) -> list[str]:
        """Extract key topics from recommendation payload with safe fallbacks."""
        for key in ("key_topics", "topics"):
            value = recommendation.get(key)
            if isinstance(value, list):
                topics = [str(item).strip() for item in value if str(item).strip()]
                if topics:
                    return topics[:5]

        assessment = recommendation.get("assessment")
        if not isinstance(assessment, str):
            return []

        extracted: list[str] = []
        for line in assessment.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            topic = re.sub(r"^[-*0-9.)\s]+", "", stripped).strip()
            if not topic:
                continue
            if topic.endswith("."):
                topic = topic[:-1].strip()
            if not topic:
                continue
            extracted.append(topic)
            if len(extracted) == 3:
                break
        return extracted

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
        content = (
            "Thanks for sharing your preference. "
            "Therapy style selection is handled through the workflow UI. "
            "Please choose your style there so the backend can create your plan."
        )
        return direct_agent_response(
            content=content,
            next_action="await_selection",
            metadata={"selected_style": selected_style},
        )

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
        parts = [
            "Based on our intake session, I'd like to recommend the "
            "following therapy approaches:\n"
        ]

        for i, rec in enumerate(recommendations, 1):
            parts.append(f"\n{i}. {rec.style_name.upper()} Therapy")
            parts.append(f"   {rec.explanation}\n")

        parts.append("\nWhich approach resonates most with you?")

        return "\n".join(parts)

    async def _generate_recommendations(
        self, message_history: list
    ) -> list[dict[str, str]]:
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
        style_assessments = {}

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
                recommendations.append(
                    {
                        "style_id": style_id,
                        "name": style_id.upper(),
                        "description": self.style_service.get_style_description(style_id),
                        "assessment": style_assessments[style_id],
                    }
                )

        # Sort recommendations by relevance
        # (for now, we'll keep all but limit to 3 in the UI)
        return recommendations

    async def _assess_style(self, style_id: str, session_summary: str, results: dict):
        """Helper to assess a single style asynchronously."""
        assessment_prompt = self.style_service.get_assessment_prompt(style_id)

        # Create a prompt to evaluate the session against this style's criteria
        evaluation_prompt = build_style_assessment_prompt(
            assessment_prompt=assessment_prompt,
            style_id=style_id,
            session_summary=session_summary,
        )

        # Generate assessment
        assessment = await self.llm_service.generate_response_async(evaluation_prompt)
        results[style_id] = assessment

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
        try:
            user_profile = await self.db_service.get_user_profile(user_id)

            if not user_profile:
                logger.warning(f"No user profile found for user {user_id}")
                return None

            # Format patient profile into readable context
            display_name = user_profile.alias or user_profile.name
            parts = [f"Patient: {display_name}"]

            if user_profile.data_of_birth:
                parts.append(f"DOB: {user_profile.data_of_birth}")
            if user_profile.gender:
                parts.append(f"Gender: {user_profile.gender}")
            if user_profile.cultural_background:
                parts.append(
                    f"Cultural Background: "
                    f"{user_profile.cultural_background}"
                )

            if user_profile.parents:
                parts.append(f"Family - Parents: {user_profile.parents}")
            if user_profile.siblings:
                parts.append(
                    f"Family - Siblings: {user_profile.siblings}"
                )
            if user_profile.family_atmosphere:
                parts.append(
                    f"Family Atmosphere: "
                    f"{user_profile.family_atmosphere}"
                )

            if user_profile.education:
                parts.append(f"Education: {user_profile.education}")
            if user_profile.work_history:
                parts.append(
                    f"Work History: {user_profile.work_history}"
                )
            if user_profile.relationship_to_work:
                parts.append(
                    f"Relationship to Work: "
                    f"{user_profile.relationship_to_work}"
                )

            if user_profile.relationships:
                parts.append(
                    f"Relationships: {user_profile.relationships}"
                )
            if user_profile.social_context:
                parts.append(
                    f"Social Context: {user_profile.social_context}"
                )
            if user_profile.current_situation:
                parts.append(
                    f"Current Situation: "
                    f"{user_profile.current_situation}"
                )

            return "\n".join(parts)

        except Exception as e:
            logger.error(
                f"Error loading patient profile for {user_id}: {e}",
                exc_info=True,
            )
            return None

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
        try:
            # Format intake transcript
            transcript_lines = []
            for msg in intake_session.transcript:
                role = "Therapist" if msg.role == "assistant" else "Patient"
                transcript_lines.append(f"{role}: {msg.content}")

            transcript = "\n".join(transcript_lines)

            # Format extraction prompt
            extraction_prompt = TIER3_INITIAL_FORMULATION_PROMPT.format(
                patient_background=patient_background or "No background data",
                intake_transcript=transcript,
                therapy_style=therapy_style,
            )

            logger.info("Extracting Tier 3 initial formulation...")

            analysis = await self.llm_service.generate_structured_output_async(
                extraction_prompt,
                PatientAnalysis,
                method="json_schema",
            )
            if not isinstance(analysis, PatientAnalysis):
                logger.error("Tier 3 extraction returned unexpected type")
                return None

            # Create versioned wrapper (v1)
            analysis_version = PatientAnalysisVersion(
                user_id=intake_session.user_id,
                version=1,
                analysis_data=analysis,
                created_at=datetime.now(),
                created_by_session=intake_session.session_id,
                change_summary="Initial formulation created from intake assessment",
            )

            logger.info(
                f"Successfully created Tier 3 v1 for user "
                f"{intake_session.user_id}"
            )

            return analysis_version

        except Exception as e:
            logger.error(
                f"Error extracting Tier 3 formulation: {e}", exc_info=True
            )
            return None

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
        try:
            # Format intake transcript
            transcript_lines = []
            for msg in intake_session.transcript:
                role = "Therapist" if msg.role == "assistant" else "Patient"
                transcript_lines.append(f"{role}: {msg.content}")

            transcript = "\n".join(transcript_lines)

            # Format Tier 3 formulation for context
            if tier3_formulation:
                analysis_data = tier3_formulation.analysis_data
                formulation_summary = (
                    f"Central Theme: {analysis_data.current_focus.theme}\n"
                    f"Primary Defenses: "
                    f"{', '.join(analysis_data.defenses.primary_defenses)}\n"
                    f"Risk Areas: "
                    f"{', '.join(analysis_data.orientation.risk_areas)}"
                )
            else:
                formulation_summary = "No formulation available"

            # Format extraction prompt
            extraction_prompt = TIER4_INITIAL_PLAN_PROMPT.format(
                patient_background=patient_background or "No background data",
                intake_transcript=transcript,
                therapy_style=therapy_style,
                clinical_formulation=formulation_summary,
            )

            logger.info("Extracting Tier 4 initial treatment plan...")

            tier4 = await self.llm_service.generate_structured_output_async(
                extraction_prompt,
                Tier4Extract,
                method="json_schema",
            )
            if not isinstance(tier4, Tier4Extract):
                logger.error("Tier 4 extraction returned unexpected type")
                return None

            tier4_payload = {
                "initial_goals": tier4.initial_goals,
                "current_progress": tier4.current_progress,
                "planned_interventions": tier4.planned_interventions,
                "status": tier4.status,
            }

            logger.info(
                "Successfully extracted Tier 4 plan details for user %s",
                intake_session.user_id,
            )

            return tier4_payload

        except Exception as e:
            logger.error(
                f"Error extracting Tier 4 treatment plan: {e}", exc_info=True
            )
            return None
