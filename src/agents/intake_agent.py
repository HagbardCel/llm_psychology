"""
Intake Agent for conducting initial user assessment.

This agent handles the initial intake session, gathering information about
the user's background, current concerns, and therapy goals.
"""

from datetime import datetime, timedelta
import logging
import uuid
from typing import List, Optional

from config import Config
from context.user_context import UserContext
from models.data_models import Message, Session, Topic, UserProfile
from prompts.intake_prompts import (
    CLOSING_PROMPT,
    CONTINUE_CONVERSATION_PROMPT,
    INITIAL_GREETING_PROMPT,
)
from services.db_service import DatabaseService
from services.llm_service import LLMService
from src.orchestration.models import AgentResponse, ConversationContext, WorkflowState
from ui.base_ui import BaseUI

logger = logging.getLogger(__name__)


class IntakeAgent:
    """
    Agent responsible for conducting intake assessments.

    This agent has two modes:
    1. Legacy mode: Direct UI interaction (for backward compatibility)
    2. Orchestrator mode: Pure business logic, returns prompts
    """

    def __init__(
        self,
        llm_service: LLMService,
        db_service: DatabaseService,
        user_context: Optional[UserContext] = None,
    ):
        """
        Initialize the Intake Agent.

        Args:
            llm_service: The LLM service for generating responses
            db_service: The database service for storing sessions
            user_context: User context (optional, for legacy mode)
        """
        self.llm_service = llm_service
        self.db_service = db_service
        self.user_context = user_context
        self.session_duration = Config.SESSION_DURATION_MINUTES
        self.intake_topics = Config.INTAKE_TOPICS

    # ===== NEW ORCHESTRATOR INTERFACE =====

    async def process_message(
        self, message: str, context: ConversationContext
    ) -> AgentResponse:
        """
        Process user message during intake (orchestrator interface).

        This is the new interface for use with the orchestration layer.
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

            # Build prompt for LLM
            if len(context.message_history) == 0:
                # Initial greeting
                prompt = self._build_initial_prompt(context)
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
                content="I apologize, but I encountered an error. Could you please repeat that?",
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
                f"Intake complete: {len(context.topics_covered)}/{len(self.intake_topics)} topics covered"
            )
            return True

        # Minimum duration (at least 50% of time should pass)
        min_duration = context.duration_minutes * 0.5
        if context.time_elapsed_minutes < min_duration:
            return False  # Too early to end

        return False

    def _identify_covered_topics(
        self, message: str, message_history: List[Message]
    ) -> List[str]:
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
        combined_text = " ".join(
            [msg.content.lower() for msg in recent_messages]
        )

        covered = []

        # Topic keyword mapping
        topic_keywords = {
            "Presenting Problem": ["problem", "issue", "concern", "struggling", "difficulty"],
            "Current Symptoms": ["symptom", "feeling", "experience", "happening"],
            "Personal History": ["history", "past", "childhood", "grew up", "background"],
            "Family Background": ["family", "parents", "siblings", "mother", "father"],
            "Relationships": ["relationship", "partner", "spouse", "friend", "dating"],
            "Work/School": ["work", "job", "school", "career", "colleague", "boss"],
            "Physical Health": ["health", "medical", "physical", "doctor", "illness"],
            "Mental Health History": ["depression", "anxiety", "therapy", "counseling", "medication"],
            "Substance Use": ["alcohol", "drug", "substance", "drinking", "smoking"],
            "Coping Mechanisms": ["cope", "deal with", "handle", "manage", "stress"],
            "Support System": ["support", "help", "friend", "family support"],
            "Goals for Therapy": ["goal", "hope", "want", "expect", "looking for"],
        }

        for topic, keywords in topic_keywords.items():
            if any(keyword in combined_text for keyword in keywords):
                covered.append(topic)

        return covered

    # ===== LEGACY UI INTERFACE (for backward compatibility) =====

    async def _collect_user_profile(self, ui: BaseUI) -> UserProfile:
        """
        Collect user profile information at the beginning of the session.

        Args:
            ui: The UI interface to use for interaction

        Returns:
            UserProfile: The collected user profile information
        """
        await ui.display_user_message(
            "Before we begin, I'd like to get to know you better."
        )
        await ui.display_user_message(
            "This information will help me provide you with a more personalized experience.\n"
        )

        # Collect user information
        name = await ui.get_user_input("What is your name? ")
        name = name.strip()
        if not name:
            name = "Anonymous User"

        birthdate_str = await ui.get_user_input(
            "What is your birthdate? (YYYY-MM-DD, optional): "
        )
        birthdate_str = birthdate_str.strip()
        birthdate = None
        if birthdate_str:
            try:
                birthdate = datetime.strptime(birthdate_str, "%Y-%m-%d")
            except ValueError:
                await ui.display_system_status(
                    "Invalid date format. Birthdate will not be recorded."
                )

        profession = await ui.get_user_input("What is your profession? (optional): ")
        profession = profession.strip()
        if not profession:
            profession = None

        # Create user profile
        profile = UserProfile(
            user_id=self.user_context.user_id,
            name=name,
            birthdate=birthdate,
            profession=profession,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        # Save to database
        self.db_service.save_user_profile(profile)
        await ui.display_system_status(
            f"Thank you, {name}. Your information has been recorded.\n"
        )

        return profile

    def _get_pending_topics(self, session: Session) -> List[str]:
        """Get list of pending topics."""
        return [topic.name for topic in session.topics if topic.status == "pending"]

    def _get_covered_topics(self, session: Session) -> List[str]:
        """Get list of covered topics."""
        return [
            topic.name
            for topic in session.topics
            if topic.status in ["covered", "partially_covered"]
        ]

    def _update_topic_status(self, session: Session, topic_name: str, status: str):
        """Update the status of a topic."""
        for topic in session.topics:
            if topic.name == topic_name:
                topic.status = status
                break

    async def conduct_intake(self, ui: BaseUI) -> Session:
        """
        Conduct the initial intake conversation with the user (legacy interface).

        This method is kept for backward compatibility with the local UI.

        Args:
            ui: The UI interface to use for interaction

        Returns:
            Session: The completed intake session
        """
        await ui.display_user_message("Welcome to your virtual psychoanalysis session.")
        await ui.display_user_message(
            "I'm here to help you explore your thoughts and feelings."
        )
        await ui.display_user_message(
            "Please feel free to share whatever is on your mind.\n"
        )

        # Collect user profile information
        user_profile = await self._collect_user_profile(ui)

        # Initialize session with topics
        session_id = str(uuid.uuid4())
        topics = [Topic(name=topic_name) for topic_name in Config.INTAKE_TOPICS]
        session = Session(
            session_id=session_id,
            user_id=self.user_context.user_id,
            timestamp=datetime.now(),
            transcript=[],
            topics=topics,
        )

        # Start session timer
        session_start_time = datetime.now()
        session_end_time = session_start_time + timedelta(minutes=self.session_duration)

        # Initial greeting with personalized touch
        initial_prompt = INITIAL_GREETING_PROMPT.format(
            user_name=user_profile.name, session_duration=self.session_duration
        )

        initial_response = self.llm_service.generate_response(initial_prompt)
        await ui.display_message("therapist", initial_response)

        # Add to transcript
        session.transcript.append(
            Message(role="assistant", content=initial_response, timestamp=datetime.now())
        )

        # Conversation loop with time and topic awareness
        while True:
            # Check remaining time with higher precision
            current_time = datetime.now()
            remaining_time = session_end_time - current_time
            remaining_seconds = max(0, int(remaining_time.total_seconds()))

            # Check if session should end
            if remaining_seconds <= 0:
                await ui.display_system_status(
                    "Session time has expired. Wrapping up the assessment."
                )
                break

            # Check if all topics are covered
            pending_topics = self._get_pending_topics(session)
            if not pending_topics:
                await ui.display_system_status(
                    "All assessment topics have been covered."
                )
                break

            user_input = await ui.get_user_input()

            if user_input.lower() in ["quit", "exit", "bye", "goodbye"]:
                break

            if not user_input.strip():
                logger.warning("User provided empty response during intake session")

            if user_input:
                # Add user message to transcript
                session.transcript.append(
                    Message(role="user", content=user_input, timestamp=datetime.now())
                )

                # Calculate remaining minutes for the prompt
                remaining_minutes = max(0, int(remaining_time.total_seconds() / 60))

                # Generate response using context with time and topic awareness
                covered_topics = self._get_covered_topics(session)
                pending_topics = self._get_pending_topics(session)

                # Format the continuation prompt with time and topic information
                formatted_prompt = CONTINUE_CONVERSATION_PROMPT.format(
                    remaining_minutes=remaining_minutes,
                    session_duration=self.session_duration,
                    covered_topics=", ".join(covered_topics) if covered_topics else "None",
                    pending_topics=", ".join(pending_topics),
                )

                context = [
                    {"role": msg.role, "content": msg.content}
                    for msg in session.transcript
                ]
                response = self.llm_service.generate_response(formatted_prompt, context)

                await ui.display_message("therapist", response)

                # Add assistant response to transcript
                session.transcript.append(
                    Message(role="assistant", content=response, timestamp=datetime.now())
                )

        # End session
        closing_prompt = CLOSING_PROMPT

        closing_response = self.llm_service.generate_response(closing_prompt)
        await ui.display_message("therapist", closing_response)

        # Add closing to transcript
        session.transcript.append(
            Message(role="assistant", content=closing_response, timestamp=datetime.now())
        )

        # Save session to database
        self.db_service.save_session(session)
        await ui.display_system_status("Intake session completed and saved.\n")

        return session
