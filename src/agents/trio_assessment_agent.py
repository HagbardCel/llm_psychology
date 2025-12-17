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

from context.user_context import UserContext
from models.data_models import (
    AnalyticOrientation,
    CurrentFocus,
    DefensiveOrganization,
    PatientAnalysis,
    PatientAnalysisVersion,
    RecurringNarrative,
    Session,
    TherapyPlan,
    TransferenceImpressions,
)
from models.structured_output_models import Tier4Extract
from orchestration.models import (
    AgentResponse,
    ConversationContext,
    TherapyStyleRecommendation,
    WorkflowState,
)
from prompts.assessment_prompts import (
    TIER3_INITIAL_FORMULATION_PROMPT,
    TIER4_INITIAL_PLAN_PROMPT,
)
from services.llm_service import LLMService
from services.rag_service import RAGService
from services.style_service import style_service
from services.trio_db_service import TrioDatabaseService

logger = logging.getLogger(__name__)


class TrioAssessmentAgent:
    """
    Agent for assessing user needs and recommending therapy styles.

    This agent has two modes:
    1. Legacy mode: Direct method calls (for backward compatibility)
    2. Orchestrator mode: Returns AgentResponse for orchestration layer

    Uses Trio's structured concurrency for all async operations.
    """

    def __init__(
        self,
        llm_service: LLMService,
        db_service: TrioDatabaseService,
        rag_service: RAGService,
        user_context: UserContext | None = None,
        reflection_agent=None,
    ):
        """
        Initialize the Trio Assessment Agent.

        Args:
            llm_service: The LLM service for generating responses (synchronous)
            db_service: The Trio database service for storing therapy plans
            rag_service: The RAG service for retrieving domain knowledge (synchronous)
            user_context: User context (optional, for legacy mode)
            reflection_agent: TrioReflectionAgent for dependency injection
        """
        self.llm_service = llm_service
        self.db_service = db_service
        self.rag_service = rag_service
        self.user_context = user_context
        if reflection_agent is None:
            raise ValueError("reflection_agent is required")
        self.reflection_agent = reflection_agent

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
                choice = await self._parse_continuation_choice(message)
                if choice == "finish":
                    return AgentResponse(
                        content="That sounds like a good plan. Take your time to \
reflect on what we've discussed today. I look forward to our first therapy session \
together. Take care!",
                        next_action="end_session",
                        next_state=None,
                        metadata={"is_direct_response": True, "session_ended": True},
                    )
                elif choice == "continue":
                    return AgentResponse(
                        content="Wonderful! Let's begin our first therapy session. \
I'm here to support you.",
                        next_action="start_therapy",
                        next_state=WorkflowState.THERAPY_IN_PROGRESS,
                        metadata={
                            "is_direct_response": True,
                            "new_session_required": True,
                        },
                    )
                else:
                    # Could not parse choice
                    return AgentResponse(
                        content="I'm not sure which option you'd prefer. Would you \
like to finish for today (option 1) or continue with our first therapy session now \
(option 2)?",
                        next_action="await_continuation_choice",
                        next_state=None,
                        metadata={"is_direct_response": True},
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
                selected_style = await self._parse_selection(message)

                if selected_style:
                    return await self.process_selection(selected_style, context)
                else:
                    # Could not identify style, ask for clarification
                    # This keeps us in the selection loop
                    return AgentResponse(
                        content="I understood you want to proceed, but I'm not sure \
which therapy style you'd like to start with. Could you please specify one of the \
recommended approaches (e.g., Psychoanalysis, CBT)?",
                        next_action="await_selection",
                        next_state=WorkflowState.ASSESSMENT_IN_PROGRESS,
                    )
            else:
                # Recommendations not yet made, generate them
                return await self.process_assessment(context)

        except Exception as e:
            return AgentResponse(
                content=f"I encountered an error: {str(e)}",
                next_action="continue",
                next_state=None,
                metadata={"error": str(e)},
            )

    async def _parse_continuation_choice(self, message: str) -> str | None:
        """
        Parse user message to identify continuation choice.

        Args:
            message: User's message

        Returns:
            "finish", "continue", or None if unclear
        """
        message = message.lower()

        # Check for finish indicators
        finish_keywords = [
            "finish", "stop", "end", "done", "later", "next time",
            "option 1", "1", "first", "reflect"
        ]
        for keyword in finish_keywords:
            if keyword in message:
                return "finish"

        # Check for continue indicators
        continue_keywords = [
            "continue", "start", "begin", "now", "yes", "go ahead",
            "option 2", "2", "second", "therapy"
        ]
        for keyword in continue_keywords:
            if keyword in message:
                return "continue"

        return None

    async def _parse_selection(self, message: str) -> str | None:
        """
        Parse user message to identify selected therapy style.

        Args:
            message: User's message

        Returns:
            Selected style ID or None
        """
        message = message.lower()
        available_styles = style_service.get_available_styles()
        logger.debug(
            "Assessment selection parse: message=%r styles=%s",
            message,
            available_styles,
        )

        # Simple keyword matching for now
        # In a real system, we might use LLM to interpret intent
        for style in available_styles:
            if style.lower() in message:
                logger.debug("Assessment selection matched style: %s", style)
                return style

        logger.debug("Assessment selection: no style found")
        return None

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
            structured_recs = [
                TherapyStyleRecommendation(
                    style_name=rec["style_id"],
                    score=0.8,  # TODO: Implement actual scoring
                    explanation=rec["assessment"],
                    key_topics=[],  # TODO: Extract from assessment
                )
                for rec in recommendations[:3]  # Top 3
            ]

            # Format response content
            content = self._format_recommendations(structured_recs)

            return AgentResponse(
                content=content,
                next_action="await_selection",  # Wait for user to select
                next_state=WorkflowState.ASSESSMENT_IN_PROGRESS,
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
                next_state=None,
                metadata={"error": str(e)},
            )

    async def process_selection(
        self,
        selected_style: str,
        context: ConversationContext,
    ) -> AgentResponse:
        """
        Process style selection and create therapy plan (orchestrator).

        Args:
            selected_style: User's selected therapy style
            intake_session: Completed intake session
            context: Conversation context

        Returns:
            AgentResponse with confirmation
        """
        try:
            logger.debug("Processing assessment selection style=%s", selected_style)
            # Create therapy plan with selected style (FIXED: added await)
            # Construct a temporary session object for the plan creation
            # (ReflectionAgent expects a Session object)
            temp_session = Session(
                session_id=context.session_id,
                user_id=context.user_profile.user_id,
                timestamp=datetime.now(),
                transcript=context.message_history,
                topics=[],
            )

            therapy_plan = await self.create_initial_plan_with_style(
                temp_session, selected_style
            )
            logger.debug("Therapy plan created: %s", therapy_plan.plan_id)

            # Phase 4: Create Tier 3 & 4 initial data
            logger.info(
                f"Creating initial Tier 3 & 4 data for user "
                f"{context.user_profile.user_id}"
            )

            # Load Tier 1 (PatientProfile) for context
            patient_background = await self._load_patient_profile(
                context.user_profile.user_id
            )

            # Extract Tier 3 (initial clinical formulation)
            tier3_analysis = await self._extract_tier3_initial_formulation(
                temp_session, selected_style, patient_background
            )

            if tier3_analysis:
                # Save to database
                success = await self.db_service.save_patient_analysis_version(
                    tier3_analysis
                )
                if success:
                    logger.info(
                        f"Saved Tier 3 v1 for user {context.user_profile.user_id}"
                    )
                else:
                    logger.warning(
                        f"Failed to save Tier 3 for user "
                        f"{context.user_profile.user_id}"
                    )
            else:
                logger.warning(
                    "Failed to extract Tier 3 initial formulation"
                )

            # Extract Tier 4 (initial treatment plan)
            tier4_data = await self._extract_tier4_initial_plan(
                temp_session, selected_style, patient_background, tier3_analysis
            )

            if tier4_data:
                therapy_plan.initial_goals = tier4_data["initial_goals"]
                therapy_plan.current_progress = tier4_data["current_progress"]
                therapy_plan.planned_interventions = tier4_data["planned_interventions"]
                therapy_plan.status = tier4_data["status"]
                therapy_plan.updated_at = datetime.now()

                # Persist unified therapy plan (now containing Tier 4 data)
                plan_saved = await self.db_service.save_therapy_plan(therapy_plan)
                if plan_saved:
                    logger.info(
                        "Updated TherapyPlan with Tier 4 data for user %s",
                        context.user_profile.user_id,
                    )
                else:
                    logger.warning(
                        "Failed to persist Tier 4 data for user %s",
                        context.user_profile.user_id,
                    )
            else:
                logger.warning("Failed to extract Tier 4 initial plan")

            # Format confirmation message with suggestion to finish for the day
            content = f"""
Excellent choice! I'll be using {selected_style.upper()} therapy approach for \
our sessions.

Your personalized therapy plan has been created. We've covered a lot of ground \
today through our intake and assessment process.

I'd suggest we finish here for today to give you time to reflect on what we've \
discussed. However, if you'd prefer, we could start our first therapy session \
right now.

Would you like to:
1. Finish for today and begin therapy in our next session
2. Continue with our first therapy session now

What would you prefer?
"""

            return AgentResponse(
                content=content,
                next_action="await_continuation_choice",
                next_state=WorkflowState.ASSESSMENT_COMPLETE,
                metadata={
                    "selected_style": selected_style,
                    "plan_id": therapy_plan.plan_id,
                    "plan_version": therapy_plan.version,
                    "tier3_created": tier3_analysis is not None,
                    "tier4_created": tier4_data is not None,
                    "is_direct_response": True,
                    "awaiting_continuation": True,
                },
            )

        except Exception as e:
            logger.error("Error in process_selection: %s", e, exc_info=True)
            return AgentResponse(
                content=f"I encountered an error creating your therapy plan: {str(e)}",
                next_action="continue",
                next_state=None,
                metadata={"error": str(e)},
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
        available_styles = style_service.get_available_styles()

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
                        "description": style_service.get_style_description(style_id),
                        "assessment": style_assessments[style_id],
                    }
                )

        # Sort recommendations by relevance
        # (for now, we'll keep all but limit to 3 in the UI)
        return recommendations

    async def _assess_style(self, style_id: str, session_summary: str, results: dict):
        """Helper to assess a single style asynchronously."""
        assessment_prompt = style_service.get_assessment_prompt(style_id)

        # Create a prompt to evaluate the session against this style's criteria
        evaluation_prompt = f"""
{assessment_prompt}

        Based on the following intake session transcript, assess whether this patient
        would be a good candidate for {style_id.upper()} therapy:

Session Transcript:
{session_summary}

        Please provide a brief assessment of why this patient might or might not be
        suitable for {style_id.upper()} therapy, focusing on the key indicators you
        see in the transcript.
"""

        # Generate assessment
        assessment = await self.llm_service.generate_response_async(evaluation_prompt)
        results[style_id] = assessment

    async def create_initial_plan_with_style(
        self, intake_session: Session, selected_style: str
    ) -> TherapyPlan:
        """
        Create an initial therapy plan with the selected therapy style using Trio.

        Args:
            intake_session: The completed intake session
            selected_style: The user-selected therapy style

        Returns:
            TherapyPlan: The initial therapy plan with selected style
        """
        # Use the injected TrioReflectionAgent dependency
        reflection_agent = self.reflection_agent

        # FIXED: Added await to async method call
        return await reflection_agent.create_initial_plan_with_style(
            intake_session, selected_style
        )

    async def _load_patient_profile(self, user_id: str) -> str | None:
        """
        Load Tier 1 patient profile and format as context string.

        Args:
            user_id: User ID

        Returns:
            Formatted patient background string, or None if not found
        """
        try:
            patient_profile = await self.db_service.get_patient_profile(user_id)

            if not patient_profile:
                logger.warning(f"No patient profile found for user {user_id}")
                return None

            # Format patient profile into readable context
            parts = [f"Patient: {patient_profile.basic_info.alias}"]

            if patient_profile.basic_info.date_of_birth:
                parts.append(f"DOB: {patient_profile.basic_info.date_of_birth}")
            if patient_profile.basic_info.gender:
                parts.append(f"Gender: {patient_profile.basic_info.gender}")
            if patient_profile.basic_info.cultural_background:
                parts.append(
                    f"Cultural Background: "
                    f"{patient_profile.basic_info.cultural_background}"
                )

            if patient_profile.family.parents:
                parts.append(f"Family - Parents: {patient_profile.family.parents}")
            if patient_profile.family.siblings:
                parts.append(
                    f"Family - Siblings: {patient_profile.family.siblings}"
                )
            if patient_profile.family.family_atmosphere:
                parts.append(
                    f"Family Atmosphere: "
                    f"{patient_profile.family.family_atmosphere}"
                )

            if patient_profile.history.education:
                parts.append(f"Education: {patient_profile.history.education}")
            if patient_profile.history.work_history:
                parts.append(
                    f"Work History: {patient_profile.history.work_history}"
                )
            if patient_profile.history.relationship_to_work:
                parts.append(
                    f"Relationship to Work: "
                    f"{patient_profile.history.relationship_to_work}"
                )

            if patient_profile.context.relationships:
                parts.append(
                    f"Relationships: {patient_profile.context.relationships}"
                )
            if patient_profile.context.social_context:
                parts.append(
                    f"Social Context: {patient_profile.context.social_context}"
                )
            if patient_profile.context.current_situation:
                parts.append(
                    f"Current Situation: "
                    f"{patient_profile.context.current_situation}"
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
