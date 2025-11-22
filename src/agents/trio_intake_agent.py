"""
TrioIntakeAgent: Trio-native agent for conducting initial user assessment.

This agent handles the initial intake session, gathering information about
the user's background, current concerns, and therapy goals.

Pure Trio implementation using structured concurrency.
"""

import logging
from datetime import datetime

from config import settings
from context.user_context import UserContext
from models.data_models import Message
from orchestration.models import AgentResponse, ConversationContext, WorkflowState
from prompts.intake_prompts import (
    CONTINUE_CONVERSATION_PROMPT,
    INITIAL_GREETING_PROMPT,
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
            # Analyze message to identify covered topics
            covered_topics = self._identify_covered_topics(
                message, context.message_history
            )

            # Update topics covered in context
            for topic in covered_topics:
                if topic not in context.topics_covered:
                    context.topics_covered.append(topic)

            # Check if intake is complete
            is_complete = self._is_intake_complete(context)

            # Handle Guest user (initial name collection)
            if context.user_profile.name == "Guest":
                if not message.strip():
                    # Initial trigger - ask for name
                    prompt = (
                        "You are a professional psychoanalyst conducting an intake assessment. "
                        "Your first task is to establish a connection with the user.\n\n"
                        "Start by warmly welcoming them and introducing yourself as their AI Psychoanalyst. "
                        "Since you do not know their name yet, politely ask them to introduce themselves "
                        "so you can address them properly.\n"
                        "Be professional, welcoming, and concise."
                    )
                    next_action = "continue"
                    next_state = None
                else:
                    # User provided name - update profile and start intake
                    new_name = message.strip()
                    context.user_profile.name = new_name
                    await self.db_service.save_user_profile(context.user_profile)

                    # Build standard initial prompt with new name
                    prompt = self._build_initial_prompt(context)
                    next_action = "continue"
                    next_state = None

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
                    next_action = "transition"
                    next_state = WorkflowState.INTAKE_COMPLETE
                else:
                    next_action = "continue"
                    next_state = None

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
        # Time-based completion
        if context.is_time_up:
            logger.info("Intake complete: time is up")
            return True

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

        return covered
