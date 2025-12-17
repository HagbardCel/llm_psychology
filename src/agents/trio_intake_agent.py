"""
TrioIntakeAgent: Trio-native agent for conducting initial user assessment.

This agent handles the initial intake session, gathering information about
the user's background, current concerns, and therapy goals.

Pure Trio implementation using structured concurrency.
"""

import json
import logging
from datetime import datetime

import trio

from config import settings
from context.user_context import UserContext
from models.data_models import (
    AnalyticFrame,
    BasicPatientBackground,
    EducationalWorkHistory,
    FamilyConstellation,
    Message,
    PatientProfile,
    RelationalLifeContext,
    UserStatus,
)
from models.structured_output_models import PatientProfileExtract
from orchestration.models import AgentResponse, ConversationContext, WorkflowState
from prompts.intake_prompts import (
    CONTINUE_CONVERSATION_PROMPT,
    GUEST_WELCOME_PROMPT,
    INITIAL_GREETING_PROMPT,
    TIER1_EXTRACTION_PROMPT,
)
from services.llm_service import LLMService
from services.trio_db_service import TrioDatabaseService

logger = logging.getLogger(__name__)


class TrioIntakeAgent:
    """
    Trio-native agent responsible for conducting intake assessments.

    Uses Trio's structured concurrency for all async operations.
    """

    def __init__(
        self,
        llm_service: LLMService,
        db_service: TrioDatabaseService,
        user_context: UserContext,
    ):
        """
        Initialize the Trio Intake Agent.

        Args:
            llm_service: The LLM service for generating responses (synchronous)
            db_service: The Trio database service for storing sessions
            user_context: User context
        """
        self.llm_service = llm_service
        self.db_service = db_service
        self.user_context = user_context
        self.session_duration = settings.SESSION_DURATION_MINUTES
        self.intake_topics = settings.INTAKE_TOPICS

    # ===== NEW ORCHESTRATOR INTERFACE =====

    async def process_message(
        self, message: str, context: ConversationContext
    ) -> AgentResponse:
        """
        Process user message during intake (orchestrator interface) using Trio.

        This is the interface for use with the orchestration layer.
        It returns prompts and decisions without any UI interaction.

        Args:
            message: User's message
            context: Conversation context

        Returns:
            AgentResponse with prompt and next action
        """
        try:
            logger.info(
                f"Processing message for user {context.user_profile.user_id}. Name: '{context.user_profile.name}'"
            )

            # Analyze message to identify covered topics
            covered_topics = self._identify_covered_topics(
                message, context.message_history
            )

            # Update topics covered in context
            for topic in covered_topics:
                if topic not in context.topics_covered:
                    context.topics_covered.append(topic)

            logger.info(
                f"Topics covered so far: {context.topics_covered} ({len(context.topics_covered)}/{len(self.intake_topics)})"
            )

            # Check if intake is complete
            is_complete = self._is_intake_complete(context)

            # Determine next action and state
            next_action = "continue"
            next_state = None
            prompt = ""

            # Handle Guest user (initial name collection)
            # Check if name is Guest OR status is PROFILE_ONLY (new user)
            is_guest = (
                context.user_profile.name == "Guest"
                or context.user_profile.status == UserStatus.PROFILE_ONLY
                or context.user_profile.name == context.user_profile.user_id
            )

            if is_guest:
                if not message.strip():
                    # Initial greeting for guest - send directly to user, not to LLM
                    prompt = GUEST_WELCOME_PROMPT
                    next_action = "continue"
                    next_state = None
                    # Mark as direct response so orchestrator doesn't send to LLM
                    return AgentResponse(
                        content=prompt,
                        next_action=next_action,
                        next_state=next_state,
                        metadata={
                            "is_direct_response": True,
                            "topics_covered": context.topics_covered,
                            "time_remaining_minutes": context.time_remaining_minutes,
                            "can_extend": context.can_extend,
                            "is_time_up": context.is_time_up,
                        },
                    )
                else:
                    # User provided name - update profile and start intake
                    new_name = message.strip()
                    context.user_profile.name = new_name
                    # Also update status to INTAKE_IN_PROGRESS in the profile object
                    # so that subsequent logic (if any) sees the new status
                    context.user_profile.status = UserStatus.INTAKE_IN_PROGRESS

                    await self.db_service.save_user_profile(context.user_profile)

                    # Build standard initial prompt with new name
                    prompt = self._build_initial_prompt(context)
                    next_action = "transition"
                    next_state = WorkflowState.INTAKE_IN_PROGRESS

            # Standard intake flow
            elif len(context.message_history) == 0:
                # Initial greeting (should not happen if name collection worked, but good fallback)
                prompt = self._build_initial_prompt(context)
                next_action = "continue"
                next_state = None
            else:
                # Continue conversation
                prompt = self._build_continuation_prompt(message, context)

                # Determine next action and state
                if is_complete:
                    # Extract and save Tier 1 patient profile data
                    logger.info("Intake complete - extracting Tier 1 data...")
                    patient_profile = await self._extract_tier1_data(
                        context.message_history
                    )

                    if patient_profile:
                        # Save patient profile to database
                        await self.db_service.save_patient_profile(patient_profile)
                        logger.info(
                            f"Saved Tier 1 patient profile for "
                            f"{patient_profile.basic_info.alias}"
                        )
                    else:
                        logger.warning(
                            "Failed to extract Tier 1 data from intake conversation"
                        )

                    next_action = "transition"
                    next_state = WorkflowState.INTAKE_COMPLETE
                elif context.is_time_up:
                    # Time is up but intake is not complete.
                    # We should NOT transition to INTAKE_COMPLETE.
                    # Instead, we end the session but keep the state as INTAKE_IN_PROGRESS
                    # so the next session continues intake.
                    next_action = "continue"
                    next_state = None
                    prompt = (
                        "Our time is up for today. We will continue this intake "
                        "in our next session."
                    )
                else:
                    next_action = "continue"
                    next_state = None

            logger.info(
                f"Intake Agent returning: action={next_action}, state={next_state}"
            )

            return AgentResponse(
                content=prompt,
                next_action=next_action,
                next_state=next_state,
                metadata={
                    "topics_covered": context.topics_covered,
                    "time_remaining_minutes": context.time_remaining_minutes,
                    "can_extend": context.can_extend,
                    "is_time_up": context.is_time_up,
                },
            )

        except Exception as e:
            logger.error(f"Error processing intake message: {e}", exc_info=True)
            # Return error response
            return AgentResponse(
                content=(
                    "I apologize, but I encountered an error. "
                    "Could you please repeat that?"
                ),
                next_action="continue",
                next_state=None,
                metadata={"error": str(e)},
            )

    def _build_initial_prompt(self, context: ConversationContext) -> str:
        """
        Build initial greeting prompt.

        Args:
            context: Conversation context

        Returns:
            Initial prompt for LLM
        """
        return INITIAL_GREETING_PROMPT.format(
            user_name=context.user_profile.name,
            session_duration=context.duration_minutes,
        )

    def _build_continuation_prompt(
        self, message: str, context: ConversationContext
    ) -> str:
        """
        Build continuation prompt with time and topic awareness.

        Args:
            message: User's current message
            context: Conversation context

        Returns:
            Continuation prompt for LLM
        """
        # Calculate remaining time
        remaining_minutes = max(0, int(context.time_remaining_minutes))

        # Get covered and pending topics
        covered = context.topics_covered
        pending = [t for t in self.intake_topics if t not in covered]

        # Format prompt
        prompt = CONTINUE_CONVERSATION_PROMPT.format(
            remaining_minutes=remaining_minutes,
            session_duration=context.duration_minutes,
            covered_topics=", ".join(covered) if covered else "None",
            pending_topics=", ".join(pending),
        )

        return prompt

    def _is_intake_complete(self, context: ConversationContext) -> bool:
        """
        Check if intake session should end.

        Args:
            context: Conversation context

        Returns:
            True if intake is complete, False otherwise
        """
        # Time-based completion is handled in process_message to ensure
        # we don't transition to COMPLETE just because time is up.
        # We only return True here if the intake objectives (topics) are met.

        # Topic-based completion (covered at least 80% of topics)
        topics_threshold = int(len(self.intake_topics) * 0.8)
        topics_covered = len(context.topics_covered) >= topics_threshold

        if topics_covered:
            logger.info(
                f"Intake complete: {len(context.topics_covered)}/"
                f"{len(self.intake_topics)} topics covered"
            )
            return True

        # Minimum duration (at least 50% of time should pass)
        min_duration = context.duration_minutes * 0.5
        if context.time_elapsed_minutes < min_duration:
            return False  # Too early to end

        return False

    def _identify_covered_topics(
        self, message: str, message_history: list[Message]
    ) -> list[str]:
        """
        Analyze conversation to identify which topics were covered.

        This uses keyword matching to identify topics. In a production
        system, you might use more sophisticated NLP.

        Args:
            message: Current user message
            message_history: Previous messages

        Returns:
            List of topic names that were covered
        """
        # Combine recent messages for analysis
        recent_messages = message_history[-3:] + [
            Message(role="user", content=message, timestamp=datetime.now())
        ]
        combined_text = " ".join([msg.content.lower() for msg in recent_messages])
        logger.info(f"Combined text for topic analysis: {combined_text}")

        covered = []

        # Topic keyword mapping
        topic_keywords = {
            "Presenting Problem": [
                "problem",
                "issue",
                "concern",
                "struggling",
                "difficulty",
            ],
            "Current Symptoms": ["symptom", "feeling", "experience", "happening"],
            "Personal History": [
                "history",
                "past",
                "childhood",
                "grew up",
                "background",
            ],
            "Family Background": ["family", "parents", "siblings", "mother", "father"],
            "Relationships": ["relationship", "partner", "spouse", "friend", "dating"],
            "Work/School": ["work", "job", "school", "career", "colleague", "boss"],
            "Physical Health": ["health", "medical", "physical", "doctor", "illness"],
            "Mental Health History": [
                "depression",
                "anxiety",
                "therapy",
                "counseling",
                "medication",
            ],
            "Substance Use": ["alcohol", "drug", "substance", "drinking", "smoking"],
            "Coping Mechanisms": ["cope", "deal with", "handle", "manage", "stress"],
            "Support System": ["support", "help", "friend", "family support"],
            "Goals for Therapy": ["goal", "hope", "want", "expect", "looking for"],
        }

        for topic, keywords in topic_keywords.items():
            if any(keyword in combined_text for keyword in keywords):
                covered.append(topic)
                logger.info(f"Matched topic: {topic}")

        return covered

    async def _extract_tier1_data(
        self, conversation_history: list[Message]
    ) -> PatientProfile | None:
        """
        Extract Tier 1 patient profile data from intake conversation using LLM.

        Uses structured output to extract patient background information
        from the intake conversation transcript.

        Args:
            conversation_history: Complete intake conversation history

        Returns:
            PatientProfile instance with extracted data, or None if extraction fails
        """
        try:
            # Format conversation into transcript
            transcript_lines = []
            for msg in conversation_history:
                role = "Therapist" if msg.role == "assistant" else "Patient"
                transcript_lines.append(f"{role}: {msg.content}")

            transcript = "\n".join(transcript_lines)

            # Format the extraction prompt
            extraction_prompt = TIER1_EXTRACTION_PROMPT.format(
                conversation_transcript=transcript
            )

            logger.info("Extracting Tier 1 patient data from intake conversation...")

            extracted = await self.llm_service.generate_structured_output_async(
                extraction_prompt,
                PatientProfileExtract,
                method="json_schema",
            )
            if not isinstance(extracted, PatientProfileExtract):
                logger.error("Tier 1 extraction returned unexpected type")
                return None

            # Construct PatientProfile
            patient_profile = PatientProfile(
                user_id=self.user_context.user_id,
                basic_info=extracted.basic_info,
                family=extracted.family,
                history=extracted.history,
                context=extracted.context,
                frame=extracted.frame,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )

            logger.info(
                f"Successfully extracted Tier 1 data for patient: {extracted.basic_info.alias}"
            )

            return patient_profile

        except Exception as e:
            logger.error(f"Error extracting Tier 1 data: {e}", exc_info=True)
            return None
