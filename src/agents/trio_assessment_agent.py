"""
TrioAssessmentAgent: Trio-native agent for evaluating user needs and recommending therapy styles.

This agent analyzes the intake session and recommends appropriate therapy
approaches based on the user's needs and presenting concerns.

Pure Trio implementation using structured concurrency.
"""

from datetime import datetime

import trio

from context.user_context import UserContext
from models.data_models import Session, TherapyPlan
from orchestration.models import (
    AgentResponse,
    ConversationContext,
    TherapyStyleRecommendation,
    WorkflowState,
)
from services.llm_service import LLMService
from services.rag_service import RAGService
from services.style_service import style_service
from services.trio_db_service import TrioDatabaseService


class TrioAssessmentAgent:
    """
    Trio-native agent responsible for assessing user needs and recommending therapy styles.

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
            reflection_agent: Optional TrioReflectionAgent for dependency injection
        """
        self.llm_service = llm_service
        self.db_service = db_service
        self.rag_service = rag_service
        self.user_context = user_context
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
            # Check if we are waiting for a selection
            # We look at the last message from the assistant to see if it was the recommendations
            last_assistant_msg = None
            for msg in reversed(context.message_history):
                if msg.role == "assistant":
                    last_assistant_msg = msg.content
                    break

            if (
                last_assistant_msg
                and "Which approach resonates most with you?" in last_assistant_msg
            ):
                # User is responding to recommendations
                return await self.process_selection(message, context)
            else:
                # We need to perform the assessment
                return await self.process_assessment(context)

        except Exception as e:
            return AgentResponse(
                content=f"I encountered an error: {str(e)}",
                next_action="continue",
                next_state=None,
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
                next_state=None,  # Don't transition yet
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
        Process user's style selection and create therapy plan using Trio (orchestrator interface).

        Args:
            selected_style: User's selected therapy style
            intake_session: Completed intake session
            context: Conversation context

        Returns:
            AgentResponse with confirmation
        """
        try:
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

            # Format confirmation message
            content = f"""
Excellent choice! I'll be using {selected_style.upper()} therapy approach for our sessions.

Your personalized therapy plan has been created and we're ready to begin our therapeutic work together.
"""

            return AgentResponse(
                content=content,
                next_action="transition",
                next_state=WorkflowState.ASSESSMENT_COMPLETE,
                metadata={
                    "selected_style": selected_style,
                    "plan_id": therapy_plan.plan_id,
                    "plan_version": therapy_plan.version,
                },
            )

        except Exception as e:
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
            "Based on our intake session, I'd like to recommend the following therapy approaches:\n"
        ]

        for i, rec in enumerate(recommendations, 1):
            parts.append(f"\n{i}. {rec.style_name.upper()} Therapy")
            parts.append(f"   {rec.explanation}\n")

        parts.append("\nWhich approach resonates most with you?")

        return "\n".join(parts)

    # ===== LEGACY INTERFACE (for backward compatibility) =====

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

        for style_id in available_styles:
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

            # Generate assessment (run in thread)
            assessment = await trio.to_thread.run_sync(
                self.llm_service.generate_response, evaluation_prompt
            )
            style_assessments[style_id] = assessment

        # Create recommendations with descriptions
        recommendations = []
        for style_id in available_styles:
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
        # Use the injected TrioReflectionAgent dependency
        if self.reflection_agent is None:
            raise ValueError("Reflection agent is required but not injected")

        reflection_agent = self.reflection_agent

        # FIXED: Added await to async method call
        return await reflection_agent.create_initial_plan_with_style(
            intake_session, selected_style
        )
