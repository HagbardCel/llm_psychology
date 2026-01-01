"""
TrioIntakeAgent: Trio-native agent for conducting initial user assessment.

This agent handles the initial intake session, gathering information about
the user's background, current concerns, and therapy goals.

Pure Trio implementation using structured concurrency.
"""

import logging
from datetime import datetime

from psychoanalyst_app.config import Settings
from psychoanalyst_app.context.user_context import UserContext
from psychoanalyst_app.models.data_models import (
    Message,
    UserStatus,
)
from psychoanalyst_app.models.structured_output_models import PatientProfileExtract
from psychoanalyst_app.orchestration.agent_output_validators import (
    build_user_profile_output,
)
from psychoanalyst_app.orchestration.models import (
    AgentResponse,
    ConversationContext,
    WorkflowEvent,
    direct_agent_response,
)
from psychoanalyst_app.prompts.intake_prompts import (
    CONTINUE_CONVERSATION_PROMPT,
    GUEST_WELCOME_PROMPT,
    INITIAL_GREETING_PROMPT,
    TIER1_EXTRACTION_PROMPT,
)
from psychoanalyst_app.services.llm_service import LLMService

logger = logging.getLogger(__name__)


class TrioIntakeAgent:
    """
    Trio-native agent responsible for conducting intake assessments.

    Uses Trio's structured concurrency for all async operations.
    """

    def __init__(
        self,
        llm_service: LLMService,
        user_context: UserContext,
        config: Settings,
    ):
        """
        Initialize the Trio Intake Agent.

        Args:
            llm_service: The LLM service for generating responses (synchronous)
            user_context: User context
            config: Application settings
        """
        self.llm_service = llm_service
        self.user_context = user_context
        self.session_duration = config.SESSION_DURATION_MINUTES
        self.intake_topics = config.INTAKE_TOPICS

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
            workflow_event = None
            prompt = ""
            structured_profile = None

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
                    workflow_event = None
                    # Mark as direct response so orchestrator doesn't send to LLM
                    return direct_agent_response(
                        content=prompt,
                        next_action=next_action,
                        workflow_event=workflow_event,
                        metadata={
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
                    structured_profile = build_user_profile_output({"name": new_name})

                    # Build standard initial prompt with new name
                    prompt = self._build_initial_prompt(context)
                    next_action = "transition"
                    workflow_event = WorkflowEvent.START_INTAKE
                    return AgentResponse(
                        content=prompt,
                        next_action=next_action,
                        workflow_event=workflow_event,
                        metadata={
                            "topics_covered": context.topics_covered,
                            "time_remaining_minutes": context.time_remaining_minutes,
                            "can_extend": context.can_extend,
                            "is_time_up": context.is_time_up,
                            "user_profile": structured_profile,
                        },
                    )

            # Standard intake flow
            elif len(context.message_history) == 0:
                # Initial greeting (should not happen if name collection worked, but good fallback)
                prompt = self._build_initial_prompt(context)
                next_action = "continue"
                workflow_event = None
            else:
                # Continue conversation
                prompt = self._build_continuation_prompt(message, context)

                # Determine next action and state
                if is_complete:
                    # Extract and save Tier 1 patient profile data
                    logger.info("Intake complete - extracting Tier 1 data...")
                    tier1_updates = await self._extract_tier1_data(
                        context.message_history
                    )

                    if tier1_updates:
                        structured_profile = build_user_profile_output(tier1_updates)
                        logger.info(
                            "Extracted Tier 1 user profile details for %s",
                            context.user_profile.user_id,
                        )
                    else:
                        structured_profile = None
                        logger.warning(
                            "Failed to extract Tier 1 data from intake conversation"
                        )

                    next_action = "transition"
                    workflow_event = WorkflowEvent.COMPLETE_INTAKE
                elif context.is_time_up:
                    # Time is up but intake is not complete.
                    # We should NOT transition to INTAKE_COMPLETE.
                    # Instead, we end the session but keep the state as INTAKE_IN_PROGRESS
                    # so the next session continues intake.
                    next_action = "continue"
                    workflow_event = None
                    prompt = (
                        "Our time is up for today. We will continue this intake "
                        "in our next session."
                    )
                else:
                    next_action = "continue"
                    workflow_event = None

            logger.info(
                f"Intake Agent returning: action={next_action}, event={workflow_event}"
            )

            return AgentResponse(
                content=prompt,
                next_action=next_action,
                workflow_event=workflow_event,
                metadata={
                    "topics_covered": context.topics_covered,
                    "time_remaining_minutes": context.time_remaining_minutes,
                    "can_extend": context.can_extend,
                    "is_time_up": context.is_time_up,
                    "user_profile": structured_profile,
                    "intake_complete": is_complete,
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
                workflow_event=None,
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
    ) -> dict[str, object] | None:
        """
        Extract Tier 1 patient profile data from intake conversation using LLM.

        Uses structured output to extract patient background information
        from the intake conversation transcript.

        Args:
            conversation_history: Complete intake conversation history

        Returns:
            Flattened Tier 1 data for user profile updates, or None if extraction fails
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

            # Map structured extract into flattened user profile fields
            tier1_updates = {
                "alias": extracted.basic_info.alias,
                "data_of_birth": extracted.basic_info.data_of_birth,
                "gender": extracted.basic_info.gender,
                "cultural_background": extracted.basic_info.cultural_background,
                "primary_language": extracted.basic_info.primary_language,
                "parents": extracted.family.parents,
                "siblings": extracted.family.siblings,
                "family_atmosphere": extracted.family.family_atmosphere,
                "significant_events": extracted.family.significant_events,
                "education": extracted.history.education,
                "work_history": extracted.history.work_history,
                "relationship_to_work": extracted.history.relationship_to_work,
                "relationships": extracted.context.relationships,
                "social_context": extracted.context.social_context,
                "current_situation": extracted.context.current_situation,
                "preferred_school": extracted.frame.preferred_school,
                "boundary_notes": extracted.frame.boundary_notes,
                "frame_notes": extracted.frame.frame_notes,
            }

            logger.info(
                f"Successfully extracted Tier 1 data for patient: {extracted.basic_info.alias}"
            )

            return tier1_updates

        except Exception as e:
            logger.error(f"Error extracting Tier 1 data: {e}", exc_info=True)
            return None
