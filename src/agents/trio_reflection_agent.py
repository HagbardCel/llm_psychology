"""
TrioReflectionAgent: Trio-native agent for analyzing therapy sessions and updating plans.

This agent coordinates memory and planning functionality to provide
comprehensive therapy session analysis and plan management.

Pure Trio implementation using structured concurrency.
"""

import json
import logging
from datetime import datetime
from typing import Any

import trio
from pydantic import ValidationError

from agents.trio_memory_agent import TrioMemoryAgent
from agents.trio_planning_agent import TrioPlanningAgent
from config import settings
from context.user_context import UserContext
from exceptions import ReflectionError
from models.briefing_models import SessionBriefing
from models.data_models import Session, TherapyPlan
from orchestration.models import AgentResponse, ConversationContext, WorkflowState
from prompts.reflection_prompts import SESSION_SUMMARY_PROMPT
from services.llm_service import LLMService
from services.rag_service import RAGService
from services.trio_db_service import TrioDatabaseService

logger = logging.getLogger(__name__)


class TrioReflectionAgent:
    """
    Trio-native coordination agent for therapeutic reflection and planning.

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
        user_context: UserContext,
        memory_agent: TrioMemoryAgent,
        planning_agent: TrioPlanningAgent,
    ):
        """
        Initialize the Trio Reflection Agent.

        Args:
            llm_service: The LLM service for generating responses (synchronous)
            db_service: The Trio database service for storing plans
            rag_service: The RAG service for retrieving domain knowledge (synchronous)
            user_context: User context for this reflection session
            memory_agent: Trio memory agent for session context analysis
            planning_agent: Trio planning agent for therapy plan management
        """
        self.llm_service = llm_service
        self.db_service = db_service
        self.rag_service = rag_service
        self.user_context = user_context
        self.memory_agent = memory_agent
        self.planning_agent = planning_agent

        logger.info(f"TrioReflectionAgent initialized for user {user_context.user_id}")

    # ===== NEW ORCHESTRATOR INTERFACE =====

    async def process_reflection(
        self, session: Session, context: ConversationContext
    ) -> AgentResponse:
        """
        Process reflection on completed therapy session using Trio (orchestrator interface).

        This is the interface for use with the orchestration layer.
        It updates the therapy plan and returns summary information.

        Args:
            session: Completed therapy session
            context: Conversation context

        Returns:
            AgentResponse with reflection summary

        Raises:
            Exception: Any errors during reflection processing (fail-fast behavior)
        """
        logger.info(f"Processing reflection for session {session.session_id}")

        # Update therapy plan
        current_plan = context.therapy_plan
        updated_plan = await self.update_plan(session, current_plan)

        # Generate comprehensive reflection (includes memory and planning analysis)
        reflection = await self.generate_comprehensive_reflection(session, updated_plan)

        # Generate session briefing for next session resumption
        # This is critical for session resumption feature
        session_briefing = await self._generate_session_briefing(
            session_context=reflection["session_context"],
            therapeutic_memory=reflection["therapeutic_memory"],
            plan_assessment=reflection.get("plan_assessment"),
            session=session,
            therapy_plan=updated_plan,
        )

        if session_briefing:
            # Update therapy plan with the new briefing
            updated_plan.session_briefing = session_briefing

            # Save updated plan with briefing
            await self.db_service.save_therapy_plan(updated_plan)
            logger.info(
                f"Successfully generated and saved session briefing for session {session.session_id}"
            )
        else:
            logger.warning(
                f"Session briefing generation returned None for session {session.session_id}"
            )

        # Build response content
        content = self._format_reflection_summary(reflection)

        return AgentResponse(
            content=content,
            next_action="transition",
            next_state=WorkflowState.PLAN_COMPLETE,
            metadata={
                "plan_id": updated_plan.plan_id,
                "plan_version": updated_plan.version,
                "session_id": session.session_id,
                "reflection": reflection,
                "has_briefing": updated_plan.session_briefing is not None,
            },
        )

    def _format_reflection_summary(self, reflection: dict[str, Any]) -> str:
        """
        Format reflection data into a readable summary.

        Args:
            reflection: Reflection data dictionary

        Returns:
            Formatted summary string
        """
        summary_parts = []

        # Session context
        if "session_context" in reflection:
            ctx = reflection["session_context"]
            summary_parts.append("## Session Reflection\n")
            summary_parts.append(f"Key themes: {', '.join(ctx.get('key_themes', []))}")
            summary_parts.append(
                f"Emotional state: {ctx.get('emotional_state', 'N/A')}"
            )

        # Memory insights
        if "therapeutic_memory" in reflection:
            mem = reflection["therapeutic_memory"]
            summary_parts.append("\n## Progress Overview")
            summary_parts.append(f"Total sessions: {mem.get('total_sessions', 0)}")
            summary_parts.append(
                f"Relationship quality: {mem.get('relationship_quality', 'developing')}"
            )

        # Plan recommendations
        if "plan_recommendations" in reflection and reflection["plan_recommendations"]:
            summary_parts.append("\n## Recommendations")
            for rec in reflection["plan_recommendations"][:3]:
                summary_parts.append(f"- {rec.get('description', '')}")

        return "\n".join(summary_parts)

    # ===== LEGACY INTERFACE (for backward compatibility) =====

    async def create_initial_plan(
        self, intake_session: Session, selected_style: str | None = None
    ) -> TherapyPlan:
        """
        Coordinate initial therapy plan creation using specialized agents with Trio.

        Args:
            intake_session: The completed intake session
            selected_style: Optional therapy style preference

        Returns:
            TherapyPlan: The initial therapy plan

        Raises:
            ReflectionError: If plan creation fails
        """
        logger.info(
            f"TrioReflectionAgent: Coordinating initial plan creation for user {self.user_context.user_id}"
        )

        try:
            # Use planning agent to create comprehensive initial plan
            therapy_plan = await self.planning_agent.create_initial_plan(
                intake_session, selected_style
            )

            logger.info(f"Initial therapy plan created with ID: {therapy_plan.plan_id}")
            return therapy_plan

        except Exception as e:
            logger.error(
                f"Failed to coordinate initial plan creation: {e}", exc_info=True
            )
            raise ReflectionError(f"Initial plan creation failed: {e}")

    async def create_initial_plan_with_style(
        self, intake_session: Session, selected_style: str
    ) -> TherapyPlan:
        """
        Create initial therapy plan with specific style using Trio (delegates to create_initial_plan).

        Args:
            intake_session: The completed intake session
            selected_style: The selected therapy style

        Returns:
            TherapyPlan: The initial therapy plan with selected style
        """
        logger.info(
            f"TrioReflectionAgent: Creating initial {selected_style.upper()} therapy plan"
        )
        return await self.create_initial_plan(intake_session, selected_style)

    async def update_plan(
        self, session: Session, current_plan: TherapyPlan | None = None
    ) -> TherapyPlan:
        """
        Coordinate therapy plan updates using specialized agents with Trio.

        Args:
            session: The completed therapy session
            current_plan: The current therapy plan (if None, retrieves latest)

        Returns:
            TherapyPlan: The updated therapy plan

        Raises:
            ReflectionError: If plan update fails
        """
        logger.info(
            f"TrioReflectionAgent: Coordinating plan update for user {self.user_context.user_id}"
        )

        try:
            # Get current plan if not provided
            if current_plan is None:
                current_plan = await self.db_service.get_latest_therapy_plan(
                    self.user_context.user_id
                )

                if current_plan is None:
                    logger.warning(
                        "No existing plan found. Creating initial plan based on session."
                    )
                    return await self.planning_agent.create_initial_plan(session)

            # Use planning agent to update plan
            updated_plan = await self.planning_agent.update_plan(session, current_plan)

            logger.info(f"Therapy plan updated to version {updated_plan.version}")
            return updated_plan

        except Exception as e:
            logger.error(f"Failed to coordinate plan update: {e}", exc_info=True)
            raise ReflectionError(f"Plan update failed: {e}")

    async def generate_comprehensive_reflection(
        self, session: Session, current_plan: TherapyPlan | None = None
    ) -> dict[str, Any]:
        """
        Generate comprehensive reflection combining memory analysis and planning insights using Trio.

        Args:
            session: The session to reflect on
            current_plan: Optional current therapy plan

        Returns:
            Dict containing comprehensive reflection analysis

        Raises:
            ReflectionError: If reflection generation fails
        """
        logger.info(
            f"TrioReflectionAgent: Generating comprehensive reflection for session {session.session_id}"
        )

        try:
            # Analyze session context using memory agent (FIXED: added await)
            session_context = await self.memory_agent.analyze_session_context(session)

            # Get therapeutic memory and patterns (FIXED: added await)
            memory = await self.memory_agent.get_therapeutic_memory()
            patterns = await self.memory_agent.identify_patterns()

            # Get continuity context (FIXED: added await)
            continuity_context = await self.memory_agent.get_continuity_context(
                [topic.name for topic in session.topics]
            )

            # Assess plan effectiveness if plan exists (FIXED: added await)
            plan_assessment = None
            plan_recommendations = []

            if current_plan:
                plan_assessment = await self.planning_agent.assess_plan_effectiveness(
                    current_plan
                )
                plan_recommendations = (
                    await self.planning_agent.recommend_plan_adjustments(current_plan)
                )

            # Generate traditional session summary
            session_summary = await self._generate_session_summary(session)

            # Compile comprehensive reflection
            reflection = {
                "session_id": session.session_id,
                "timestamp": session.timestamp.isoformat(),
                "user_id": self.user_context.user_id,
                # Memory analysis
                "session_context": {
                    "key_themes": session_context.key_themes,
                    "emotional_state": session_context.emotional_state,
                    "insights": session_context.insights,
                    "progress_indicators": session_context.progress_indicators,
                },
                "therapeutic_memory": {
                    "total_sessions": len(memory.session_contexts),
                    "relationship_quality": memory.relationship_quality,
                    "dominant_themes": list(memory.recurring_themes.keys())[:5],
                    "emotional_progression": memory.emotional_patterns[-5:]
                    if memory.emotional_patterns
                    else [],
                },
                "patterns": patterns,
                "continuity_context": continuity_context,
                # Planning analysis
                "plan_assessment": plan_assessment,
                "plan_recommendations": plan_recommendations,
                # Traditional summary
                "session_summary": session_summary,
                # Metadata
                "reflection_generated_at": datetime.now().isoformat(),
                "agents_used": [
                    "TrioMemoryAgent",
                    "TrioPlanningAgent",
                    "TrioReflectionAgent",
                ],
            }

            logger.info(
                f"Comprehensive reflection generated for session {session.session_id}"
            )
            return reflection

        except Exception as e:
            logger.error(
                f"Failed to generate comprehensive reflection: {e}", exc_info=True
            )
            raise ReflectionError(f"Reflection generation failed: {e}")

    async def _generate_session_summary(self, session: Session) -> str:
        """
        Generate traditional session summary using LLM with Trio.

        Args:
            session: The session to summarize

        Returns:
            String summary of the session
        """
        session_text = "\n".join(
            [f"{msg.role}: {msg.content}" for msg in session.transcript]
        )
        summary_prompt = SESSION_SUMMARY_PROMPT.format(session_text=session_text)

        # Run synchronous LLM call in thread
        return await trio.to_thread.run_sync(
            self.llm_service.generate_response, summary_prompt
        )

    async def generate_session_summary(self, session: Session) -> dict[str, Any]:
        """
        Generate a simple session summary using Trio (backwards compatibility).

        Args:
            session: The session to summarize

        Returns:
            Dict containing session summary
        """
        summary = await self._generate_session_summary(session)

        return {
            "session_id": session.session_id,
            "summary": summary,
            "timestamp": session.timestamp.isoformat(),
        }

    async def _generate_session_briefing(
        self,
        session_context: dict[str, Any],
        therapeutic_memory: dict[str, Any],
        plan_assessment: dict[str, Any] | None,
        session: Session,
        therapy_plan: TherapyPlan | None,
    ) -> dict[str, Any] | None:
        """
        Generate a comprehensive session briefing for the next therapy session.

        This performs a deep analysis of the completed session and generates a rich
        briefing object that will be used by the Psychoanalyst Agent when starting
        the next session.

        Args:
            session_context: Key themes, emotional state, and insights from the session
            therapeutic_memory: Aggregated memory across all sessions
            plan_assessment: Assessment of therapy plan effectiveness
            session: The completed session
            therapy_plan: Current therapy plan

        Returns:
            Dict containing validated session briefing, or None if generation fails

        Raises:
            Exception: Propagates LLM and validation errors (fail-fast)
        """
        logger.info(f"Generating session briefing for session {session.session_id}")

        # Get session transcript as string
        session_transcript = "\n".join(
            [f"{msg.role}: {msg.content}" for msg in session.transcript]
        )

        # Construct comprehensive analysis prompt
        analysis_prompt = f"""You are a supervising psychoanalyst conducting a comprehensive review of a completed therapy session. Your role is to create a detailed "Session Briefing" that will be used by the therapist who conducts the next session with this patient.

PATIENT CONTEXT:
- Total Sessions Completed: {therapeutic_memory.get("total_sessions", 0)}
- Therapeutic Relationship Quality: {therapeutic_memory.get("relationship_quality", "building")}
- Therapy Style: {therapy_plan.selected_therapy_style if therapy_plan else "Not specified"}

PREVIOUS SESSION DATA:
Session Transcript:
{session_transcript}

Session Analysis (from Memory Agent):
- Key Themes: {json.dumps(session_context.get("key_themes", []), indent=2)}
- Emotional State: {session_context.get("emotional_state", "Not assessed")}
- Insights: {json.dumps(session_context.get("insights", []), indent=2)}
- Progress Indicators: {json.dumps(session_context.get("progress_indicators", []), indent=2)}

Therapeutic Memory (Aggregated Across All Sessions):
{json.dumps(therapeutic_memory, indent=2)}

Treatment Plan Assessment (from Planning Agent):
{json.dumps(plan_assessment if plan_assessment else {}, indent=2)}

YOUR TASK:
Generate a complete SessionBriefing JSON object with the following structure. Each field must be carefully synthesized from the above data:

{{
  "briefing_type": "resumption",
  "generated_at": "{datetime.now().isoformat()}",
  "session_count": {therapeutic_memory.get("total_sessions", 0)},
  "last_session_id": "{session.session_id}",
  "last_session_date": "{session.timestamp.date().isoformat()}",

  "narrative_handoff": "<REQUIRED: 3-4 sentence narrative that captures the essence of the last session. What was the emotional arc? What core themes emerged? What progress or challenges occurred? This should read like a supervisor briefing the next therapist.>",

  "patient_observations": "<REQUIRED: 2-3 sentences about HOW the patient communicated, not just WHAT they said. Note: communication style, openness level, defensiveness, engagement, any shifts in behavior or presentation compared to previous sessions.>",

  "plan_progression_notes": "<REQUIRED: 2-3 sentences assessing how this session advanced the overall treatment plan. Did it move forward as expected? Were there deviations? Is the plan still appropriate?>",

  "relationship_quality": "<One of: 'building', 'developing', 'established', 'strong'>",

  "continuity_points": [
    "<Most important topic/issue from last session that should be followed up on>",
    "<Second most important continuity point>",
    "<Additional points as needed - maximum {settings.MAX_CONTINUITY_POINTS} total>"
  ],

  "emotional_summary": {{
    "last_session": "<Emotional state during the last session>",
    "trend": "<One of: 'improving', 'stable', 'declining', 'fluctuating'>",
    "note": "<Brief note explaining the emotional progression or context>"
  }},

  "key_themes": [
    {{
      "theme": "<Theme name>",
      "status": "<One of: 'ongoing', 'newly introduced', 'underlying', 'emerging', 'resolved'>",
      "priority": "<One of: 'high', 'medium', 'low'>",
      "frequency": <number of sessions this theme has appeared>,
      "first_appearance": "<session ID>",
      "last_discussed": "<session ID>"
    }}
    // Include all relevant themes, maximum {settings.MAX_KEY_THEMES}
  ],

  "progress_highlights": [
    "<Specific achievement or breakthrough from this or recent sessions>",
    "<Additional progress point>",
    // Maximum {settings.MAX_PROGRESS_HIGHLIGHTS} highlights
  ],

  "unresolved_issues": [
    "<Issue or theme that remains unaddressed or needs further exploration>",
    "<Additional unresolved issue>",
    // Maximum {settings.MAX_UNRESOLVED_ISSUES} issues
  ],

  "recommended_approach": {{
    "opening_tone": "<Warm and welcoming | Gentle and supportive | Direct and focused | Curious and exploratory>",
    "opening_focus": "<1-2 sentences: What should the therapist focus on when opening the next session?>",
    "things_to_avoid": "<1-2 sentences: What topics or approaches might not be helpful right now?>",
    "suggested_questions": [
      "<Specific open-ended question that would be good to start with>",
      "<Second suggested question>",
      "<Third suggested question - maximum {settings.MAX_SUGGESTED_QUESTIONS} total>"
    ],
    "therapeutic_goals_for_session": [
      "<Concrete, achievable goal for the upcoming session>",
      "<Second goal>",
      "<Third goal - maximum {settings.MAX_SESSION_GOALS} total>"
    ]
  }}
}}

CRITICAL REQUIREMENTS:
1. Output ONLY valid JSON - no markdown code blocks, no explanations
2. All string fields must use double quotes
3. narrative_handoff must be at least {settings.MIN_NARRATIVE_LENGTH} characters and no more than {settings.MAX_NARRATIVE_LENGTH}
4. patient_observations must be no more than {settings.MAX_OBSERVATIONS_LENGTH} characters
5. plan_progression_notes must be no more than {settings.MAX_PLAN_NOTES_LENGTH} characters
6. At least one continuity_point and one key_theme are required
7. Use specific, concrete language - avoid vague therapeutic jargon
8. Base all analysis strictly on the provided session data
9. Ensure all enum values match exactly (case-sensitive)

Generate the complete JSON object now:"""

        # Call LLM to generate the structured JSON briefing using Trio
        briefing_json_str = await trio.to_thread.run_sync(
            self.llm_service.generate_response, analysis_prompt
        )

        # Parse and validate the response
        try:
            briefing_data = json.loads(briefing_json_str)

            # Add metadata not generated by LLM (these are auto-filled from context)
            briefing_data["generated_at"] = datetime.now().isoformat()
            briefing_data["session_count"] = therapeutic_memory.get("total_sessions", 0)
            briefing_data["last_session_id"] = session.session_id

            # Validate with Pydantic model
            validated_briefing = SessionBriefing(**briefing_data)
            logger.info(
                f"Successfully generated and validated session briefing for session {session.session_id}"
            )
            return validated_briefing.dict()

        except json.JSONDecodeError as e:
            logger.error(f"LLM returned invalid JSON for session briefing: {e}")
            logger.error(f"Raw LLM output: {briefing_json_str}")
            raise  # Fail fast - don't fall back

        except ValidationError as e:
            logger.error(f"Session briefing failed Pydantic validation: {e}")
            logger.error(
                f"Invalid briefing data: {json.dumps(briefing_data, indent=2)}"
            )
            raise  # Fail fast - don't fall back

    async def get_therapeutic_insights(self) -> dict[str, Any]:
        """
        Get comprehensive therapeutic insights across all sessions using Trio.

        Returns:
            Dict containing therapeutic insights
        """
        logger.info(
            f"TrioReflectionAgent: Gathering therapeutic insights for user {self.user_context.user_id}"
        )

        try:
            # Get memory insights (FIXED: added await)
            memory = await self.memory_agent.get_therapeutic_memory()
            patterns = await self.memory_agent.identify_patterns()
            recent_context = await self.memory_agent.get_recent_context(num_sessions=5)

            # Get planning insights
            current_plan = await self.db_service.get_latest_therapy_plan(
                self.user_context.user_id
            )
            plan_evolution = self.planning_agent.get_plan_evolution_summary()

            plan_assessment = None
            if current_plan:
                # FIXED: added await
                plan_assessment = await self.planning_agent.assess_plan_effectiveness(
                    current_plan
                )

            # FIXED: added await to _generate_combined_recommendations
            recommendations = await self._generate_combined_recommendations(
                memory, patterns, current_plan
            )

            return {
                "user_id": self.user_context.user_id,
                "insights_generated_at": datetime.now().isoformat(),
                # Memory insights
                "memory_insights": {
                    "total_sessions": len(memory.session_contexts),
                    "relationship_quality": memory.relationship_quality,
                    "recurring_themes": dict(memory.recurring_themes),
                    "emotional_patterns": memory.emotional_patterns,
                    "recent_progress": recent_context.get("insights", []),
                    "patterns": patterns,
                },
                # Planning insights
                "planning_insights": {
                    "current_plan_id": current_plan.plan_id if current_plan else None,
                    "current_plan_version": current_plan.version
                    if current_plan
                    else None,
                    "plan_effectiveness": plan_assessment,
                    "plan_evolution": plan_evolution,
                },
                # Combined recommendations
                "recommendations": recommendations,
            }

        except Exception as e:
            logger.error(f"Failed to gather therapeutic insights: {e}", exc_info=True)
            return {
                "user_id": self.user_context.user_id,
                "error": str(e),
                "insights_generated_at": datetime.now().isoformat(),
            }

    async def _generate_combined_recommendations(
        self, memory, patterns: dict[str, Any], current_plan: TherapyPlan | None
    ) -> list[dict[str, Any]]:
        """
        Generate combined recommendations based on memory and planning insights using Trio.

        Args:
            memory: Therapeutic memory object
            patterns: Identified patterns
            current_plan: Current therapy plan

        Returns:
            List of combined recommendations
        """
        recommendations = []

        # Memory-based recommendations
        if memory.relationship_quality in ["established", "strong"]:
            recommendations.append(
                {
                    "type": "relationship",
                    "description": "Strong therapeutic relationship established - consider deeper therapeutic work",
                    "source": "memory_analysis",
                    "priority": "medium",
                }
            )

        # Pattern-based recommendations
        emotional_trend = patterns.get("emotional_patterns", {}).get(
            "recent_trend", "stable"
        )
        if emotional_trend == "improving":
            recommendations.append(
                {
                    "type": "progress",
                    "description": "Positive emotional trend - maintain current approach and build on progress",
                    "source": "pattern_analysis",
                    "priority": "high",
                }
            )
        elif emotional_trend == "declining":
            recommendations.append(
                {
                    "type": "intervention",
                    "description": "Declining emotional trend - consider plan adjustment or additional support",
                    "source": "pattern_analysis",
                    "priority": "high",
                }
            )

        # Planning-based recommendations (FIXED: added await)
        if current_plan:
            plan_recommendations = await self.planning_agent.recommend_plan_adjustments(
                current_plan
            )
            for rec in plan_recommendations[:3]:  # Top 3 recommendations
                rec["source"] = "planning_analysis"
                recommendations.append(rec)

        return recommendations

    async def health_check(self) -> bool:
        """
        Perform health check on the reflection agent and its dependencies using Trio.

        Returns:
            bool: True if healthy, False otherwise
        """
        try:
            # Check memory agent health
            if not await self.memory_agent.health_check():
                logger.error("TrioMemoryAgent health check failed")
                return False

            # Check planning agent health
            if not await self.planning_agent.health_check():
                logger.error("TrioPlanningAgent health check failed")
                return False

            # Check LLM service (run in thread)
            test_prompt = "Respond with 'OK' if you can process this request."
            response = await trio.to_thread.run_sync(
                self.llm_service.generate_response, test_prompt
            )
            if "OK" not in response and "ok" not in response.lower():
                logger.error("LLM service health check failed")
                return False

            return True

        except Exception as e:
            logger.error(f"TrioReflectionAgent health check failed: {e}")
            return False

    def __str__(self) -> str:
        """String representation of reflection agent."""
        return f"TrioReflectionAgent(user={self.user_context.user_id}, coordinator)"

    def __repr__(self) -> str:
        """Detailed representation of reflection agent."""
        return f"TrioReflectionAgent(user='{self.user_context.user_id}', memory_agent={type(self.memory_agent).__name__}, planning_agent={type(self.planning_agent).__name__})"
