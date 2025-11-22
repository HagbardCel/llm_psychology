"""
TrioPlanningAgent: Trio-native specialized agent for therapy plan creation and adjustment.

This agent is responsible for:
- Creating initial therapy plans based on intake sessions
- Updating therapy plans based on session progress
- Integrating memory insights into planning decisions
- Managing therapy style-specific planning approaches
- Tracking plan evolution and effectiveness

Pure Trio implementation using structured concurrency.
"""

import logging
import uuid
from datetime import datetime
from typing import Any

import trio

from agents.trio_memory_agent import TrioMemoryAgent
from context.user_context import UserContext
from exceptions import PlanningError
from models.data_models import Session, TherapyPlan
from prompts.reflection_prompts import CREATE_INITIAL_PLAN_PROMPT, UPDATE_PLAN_PROMPT
from services.llm_service import LLMService
from services.rag_service import RAGService
from services.style_service import style_service
from services.trio_db_service import TrioDatabaseService

logger = logging.getLogger(__name__)


class PlanEvolution:
    """Tracks the evolution of a therapy plan over time."""

    def __init__(
        self,
        plan_id: str,
        version: int,
        changes: list[str],
        rationale: str,
        effectiveness_score: float = 0.0,
    ):
        self.plan_id = plan_id
        self.version = version
        self.changes = changes
        self.rationale = rationale
        self.effectiveness_score = effectiveness_score
        self.timestamp = datetime.now()


class PlanningStrategy:
    """Defines a strategy for therapy planning based on style and context."""

    def __init__(
        self,
        therapy_style: str,
        focus_areas: list[str],
        techniques: list[str],
        assessment_criteria: list[str],
    ):
        self.therapy_style = therapy_style
        self.focus_areas = focus_areas
        self.techniques = techniques
        self.assessment_criteria = assessment_criteria
        self.created_at = datetime.now()


class TrioPlanningAgent:
    """
    Trio-native agent specialized in therapy plan creation and strategic adjustments.

    This agent creates comprehensive therapy plans by:
    - Analyzing intake sessions and user context
    - Integrating memory insights and patterns
    - Applying therapy style-specific approaches
    - Tracking plan effectiveness and evolution
    - Making data-driven plan adjustments

    Uses Trio's structured concurrency for all async operations.
    """

    def __init__(
        self,
        llm_service: LLMService,
        db_service: TrioDatabaseService,
        rag_service: RAGService,
        user_context: UserContext,
        memory_agent: TrioMemoryAgent,
    ):
        """
        Initialize the Trio Planning Agent.

        Args:
            llm_service: LLM service for plan generation (synchronous)
            db_service: Trio database service for plan storage
            rag_service: RAG service for domain knowledge (synchronous)
            user_context: User context for this planning session
            memory_agent: Trio memory agent for therapeutic context
        """
        self.llm_service = llm_service
        self.db_service = db_service
        self.rag_service = rag_service
        self.user_context = user_context
        self.memory_agent = memory_agent

        # Planning state
        self.current_strategy: PlanningStrategy | None = None
        self.plan_evolution: list[PlanEvolution] = []

        logger.info(f"TrioPlanningAgent initialized for user {user_context.user_id}")

    async def create_initial_plan(
        self, intake_session: Session, selected_style: str | None = None
    ) -> TherapyPlan:
        """
        Create comprehensive initial therapy plan using Trio.

        Args:
            intake_session: The completed intake session
            selected_style: Optional therapy style preference

        Returns:
            TherapyPlan: The created initial therapy plan

        Raises:
            PlanningError: If plan creation fails
        """
        logger.info(f"Creating initial therapy plan for {self.user_context.user_id}")

        try:
            # Analyze intake session with memory agent
            session_context = await self.memory_agent.analyze_session_context(
                intake_session
            )

            # Get relevant domain knowledge (run in thread)
            session_text = self._extract_session_text(intake_session)
            relevant_knowledge = await self._get_relevant_knowledge(
                session_text, selected_style
            )

            # Determine therapy style if not specified
            if not selected_style:
                selected_style = self._recommend_therapy_style(
                    session_context, relevant_knowledge
                )

            # Create planning strategy
            strategy = self._create_planning_strategy(selected_style, session_context)
            self.current_strategy = strategy

            # Generate plan using LLM (run in thread)
            plan_details = await self._generate_initial_plan_details(
                intake_session, session_context, strategy, relevant_knowledge
            )

            # Create therapy plan object
            plan_id = str(uuid.uuid4())
            therapy_plan = TherapyPlan(
                plan_id=plan_id,
                user_id=self.user_context.user_id,
                created_at=datetime.now(),
                updated_at=datetime.now(),
                plan_details=plan_details,
                version=1,
                selected_therapy_style=selected_style,
            )

            # Save plan to database
            success = await self.db_service.save_therapy_plan(therapy_plan)
            if not success:
                raise PlanningError("Failed to save therapy plan to database")

            # Record plan creation
            evolution = PlanEvolution(
                plan_id=plan_id,
                version=1,
                changes=["initial_plan_created"],
                rationale="Initial therapy plan based on intake session analysis",
            )
            self.plan_evolution.append(evolution)

            logger.info(f"Initial therapy plan created: {plan_id}")
            return therapy_plan

        except Exception as e:
            logger.error(f"Failed to create initial therapy plan: {e}", exc_info=True)
            raise PlanningError(f"Initial plan creation failed: {e}")

    async def update_plan(
        self, session: Session, current_plan: TherapyPlan, force_update: bool = False
    ) -> TherapyPlan:
        """
        Update therapy plan based on session progress and memory insights using Trio.

        Args:
            session: The completed therapy session
            current_plan: The current therapy plan
            force_update: Whether to force an update regardless of assessment

        Returns:
            TherapyPlan: The updated therapy plan

        Raises:
            PlanningError: If plan update fails
        """
        logger.info(f"Updating therapy plan {current_plan.plan_id}")

        try:
            # Analyze current session
            session_context = await self.memory_agent.analyze_session_context(session)

            # Get therapeutic memory for pattern analysis
            memory = await self.memory_agent.get_therapeutic_memory()

            # Assess if plan update is needed
            update_needed = force_update or self._assess_update_necessity(
                session_context, memory, current_plan
            )

            if not update_needed:
                logger.info("No plan update needed based on current assessment")
                return current_plan

            # Get relevant knowledge for update (run in thread)
            session_text = self._extract_session_text(session)
            relevant_knowledge = await self._get_relevant_knowledge(
                session_text, current_plan.selected_therapy_style
            )

            # Generate updated plan details (run in thread)
            updated_details = await self._generate_updated_plan_details(
                session, session_context, memory, current_plan, relevant_knowledge
            )

            # Identify specific changes made
            changes = self._identify_plan_changes(
                current_plan.plan_details, updated_details
            )

            # Create updated therapy plan
            new_plan_id = str(uuid.uuid4())
            updated_plan = TherapyPlan(
                plan_id=new_plan_id,
                user_id=self.user_context.user_id,
                created_at=current_plan.created_at,
                updated_at=datetime.now(),
                plan_details=updated_details,
                version=current_plan.version + 1,
                selected_therapy_style=current_plan.selected_therapy_style,
            )

            # Save updated plan
            success = await self.db_service.save_therapy_plan(updated_plan)
            if not success:
                raise PlanningError("Failed to save updated therapy plan to database")

            # Record plan evolution
            evolution = PlanEvolution(
                plan_id=new_plan_id,
                version=updated_plan.version,
                changes=changes,
                rationale=self._generate_update_rationale(
                    session_context, memory, changes
                ),
            )
            self.plan_evolution.append(evolution)

            logger.info(f"Therapy plan updated to version {updated_plan.version}")
            return updated_plan

        except Exception as e:
            logger.error(f"Failed to update therapy plan: {e}", exc_info=True)
            raise PlanningError(f"Plan update failed: {e}")

    async def assess_plan_effectiveness(self, plan: TherapyPlan) -> dict[str, Any]:
        """
        Assess the effectiveness of a therapy plan based on progress indicators using Trio.

        Args:
            plan: The therapy plan to assess

        Returns:
            Dict containing effectiveness assessment
        """
        logger.debug(f"Assessing effectiveness of plan {plan.plan_id}")

        try:
            # Get therapeutic memory
            memory = await self.memory_agent.get_therapeutic_memory()

            # Get recent context for progress assessment
            recent_context = await self.memory_agent.get_recent_context(num_sessions=3)

            # Analyze patterns since plan creation
            patterns = await self.memory_agent.identify_patterns()

            # Calculate effectiveness metrics
            effectiveness_score = self._calculate_effectiveness_score(
                plan, memory, recent_context, patterns
            )

            # Identify strengths and areas for improvement
            assessment = self._generate_effectiveness_assessment(
                plan, memory, recent_context, effectiveness_score
            )

            return {
                "plan_id": plan.plan_id,
                "version": plan.version,
                "effectiveness_score": effectiveness_score,
                "strengths": assessment.get("strengths", []),
                "improvement_areas": assessment.get("improvement_areas", []),
                "recommendations": assessment.get("recommendations", []),
                "progress_indicators": recent_context.get("insights", []),
                "assessment_timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Failed to assess plan effectiveness: {e}", exc_info=True)
            return {
                "plan_id": plan.plan_id,
                "version": plan.version,
                "effectiveness_score": 0.5,  # Neutral score
                "error": str(e),
                "assessment_timestamp": datetime.now().isoformat(),
            }

    async def recommend_plan_adjustments(
        self, plan: TherapyPlan
    ) -> list[dict[str, Any]]:
        """
        Recommend specific adjustments to improve therapy plan effectiveness using Trio.

        Args:
            plan: The therapy plan to analyze

        Returns:
            List of recommended adjustments
        """
        logger.debug(f"Generating recommendations for plan {plan.plan_id}")

        try:
            # Assess current effectiveness
            effectiveness = await self.assess_plan_effectiveness(plan)

            # Get therapeutic memory and patterns
            memory = await self.memory_agent.get_therapeutic_memory()
            patterns = await self.memory_agent.identify_patterns()

            # Generate specific recommendations
            recommendations = []

            # Analyze theme focus alignment
            theme_recommendations = self._recommend_theme_adjustments(plan, patterns)
            recommendations.extend(theme_recommendations)

            # Analyze technique effectiveness
            technique_recommendations = self._recommend_technique_adjustments(
                plan, memory
            )
            recommendations.extend(technique_recommendations)

            # Analyze goal progression
            goal_recommendations = self._recommend_goal_adjustments(plan, effectiveness)
            recommendations.extend(goal_recommendations)

            # Prioritize recommendations
            prioritized_recommendations = self._prioritize_recommendations(
                recommendations
            )

            logger.info(f"Generated {len(prioritized_recommendations)} recommendations")
            return prioritized_recommendations

        except Exception as e:
            logger.error(f"Failed to generate recommendations: {e}", exc_info=True)
            return []

    def get_plan_evolution_summary(self) -> dict[str, Any]:
        """
        Get summary of therapy plan evolution over time.

        Returns:
            Dict containing evolution summary
        """
        if not self.plan_evolution:
            return {
                "total_versions": 0,
                "evolution_timeline": [],
                "common_changes": [],
                "effectiveness_trend": "unknown",
            }

        # Analyze evolution patterns
        all_changes = []
        effectiveness_scores = []

        for evolution in self.plan_evolution:
            all_changes.extend(evolution.changes)
            if evolution.effectiveness_score > 0:
                effectiveness_scores.append(evolution.effectiveness_score)

        # Calculate trend
        effectiveness_trend = "stable"
        if len(effectiveness_scores) >= 2:
            if effectiveness_scores[-1] > effectiveness_scores[0]:
                effectiveness_trend = "improving"
            elif effectiveness_scores[-1] < effectiveness_scores[0]:
                effectiveness_trend = "declining"

        # Count common changes
        change_counts = {}
        for change in all_changes:
            change_counts[change] = change_counts.get(change, 0) + 1

        common_changes = sorted(
            change_counts.items(), key=lambda x: x[1], reverse=True
        )[:5]

        return {
            "total_versions": len(self.plan_evolution),
            "evolution_timeline": [
                {
                    "version": evo.version,
                    "changes": evo.changes,
                    "rationale": evo.rationale,
                    "timestamp": evo.timestamp.isoformat(),
                }
                for evo in self.plan_evolution
            ],
            "common_changes": [change for change, count in common_changes],
            "effectiveness_trend": effectiveness_trend,
            "current_strategy": {
                "therapy_style": self.current_strategy.therapy_style
                if self.current_strategy
                else None,
                "focus_areas": self.current_strategy.focus_areas
                if self.current_strategy
                else [],
            },
        }

    # Private helper methods

    def _extract_session_text(self, session: Session) -> str:
        """Extract text content from session transcript."""
        return "\n".join([f"{msg.role}: {msg.content}" for msg in session.transcript])

    async def _get_relevant_knowledge(
        self, session_text: str, therapy_style: str | None
    ) -> list[dict[str, Any]]:
        """Get relevant domain knowledge filtered by therapy style using Trio."""
        if therapy_style and style_service.get_style_pack(therapy_style):
            knowledge_source = style_service.get_knowledge_source(therapy_style)
            if knowledge_source:
                return await trio.to_thread.run_sync(
                    self.rag_service.retrieve_relevant_knowledge,
                    session_text,
                    3,  # n_results
                    knowledge_source,  # filter_source
                )

        return await trio.to_thread.run_sync(
            self.rag_service.retrieve_relevant_knowledge,
            session_text,
            3,  # n_results
        )

    def _recommend_therapy_style(self, session_context, relevant_knowledge) -> str:
        """Recommend appropriate therapy style based on session analysis."""
        # Simple heuristic - can be enhanced with ML model
        themes = session_context.key_themes

        if any(theme in ["anxiety", "thoughts", "behavior"] for theme in themes):
            return "cbt"
        elif any(theme in ["dreams", "unconscious", "childhood"] for theme in themes):
            return "freud"
        elif any(theme in ["archetypes", "symbols", "meaning"] for theme in themes):
            return "jung"
        else:
            return "cbt"  # Default

    def _create_planning_strategy(
        self, therapy_style: str, session_context
    ) -> PlanningStrategy:
        """Create therapy planning strategy based on style and context."""
        style_config = style_service.get_style_pack(therapy_style)

        if style_config:
            focus_areas = session_context.key_themes[:3]  # Top 3 themes
            techniques = ["active_listening", "reflection"]  # Base techniques
            assessment_criteria = [
                "emotional_progress",
                "behavioral_changes",
                "insight_development",
            ]
        else:
            focus_areas = ["general_wellbeing"]
            techniques = ["supportive_therapy"]
            assessment_criteria = ["general_progress"]

        return PlanningStrategy(
            therapy_style=therapy_style,
            focus_areas=focus_areas,
            techniques=techniques,
            assessment_criteria=assessment_criteria,
        )

    async def _generate_initial_plan_details(
        self,
        intake_session: Session,
        session_context,
        strategy: PlanningStrategy,
        relevant_knowledge: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Generate detailed plan using LLM with Trio."""
        session_text = self._extract_session_text(intake_session)

        # Create comprehensive context
        context = f"""
        Intake Session Analysis:
        Key Themes: {", ".join(session_context.key_themes)}
        Emotional State: {session_context.emotional_state}
        Insights: {", ".join(session_context.insights)}
        Progress Indicators: {", ".join(session_context.progress_indicators)}

        Session Transcript:
        {session_text}

        Therapy Strategy:
        Style: {strategy.therapy_style.upper()}
        Focus Areas: {", ".join(strategy.focus_areas)}
        Techniques: {", ".join(strategy.techniques)}

        Relevant Knowledge:
        """

        for i, knowledge in enumerate(relevant_knowledge, 1):
            context += f"{i}. From {knowledge['source']}: {knowledge['content']}\n"

        # Get style-specific prompt if available
        if style_service.get_style_pack(strategy.therapy_style):
            reflection_prompt = style_service.get_reflection_prompt(
                strategy.therapy_style
            )
            if reflection_prompt:
                plan_prompt = f"""
{reflection_prompt}

Context for analysis:
{context}

Please create a comprehensive initial therapy plan based on this {strategy.therapy_style.upper()} approach.
Focus on the identified themes and provide specific, actionable elements.
"""
            else:
                plan_prompt = CREATE_INITIAL_PLAN_PROMPT.format(context=context)
        else:
            plan_prompt = CREATE_INITIAL_PLAN_PROMPT.format(context=context)

        # Generate structured response (run in thread)
        response = await trio.to_thread.run_sync(
            self.llm_service.generate_structured_response,
            plan_prompt,
            '{"focus": "string", "goals": "string", "techniques": "string", "themes": "string", "timeline": "string"}',
        )

        # Parse and enhance response
        plan_details = self._parse_plan_response(response, strategy)

        # Add metadata
        plan_details.update(
            {
                "created_from_session": intake_session.session_id,
                "therapy_style": strategy.therapy_style,
                "focus_areas": strategy.focus_areas,
                "initial_themes": session_context.key_themes,
                "initial_emotional_state": session_context.emotional_state,
            }
        )

        return plan_details

    async def _generate_updated_plan_details(
        self,
        session: Session,
        session_context,
        memory,
        current_plan: TherapyPlan,
        relevant_knowledge: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Generate updated plan details using LLM with Trio."""
        session_text = self._extract_session_text(session)
        recent_context = await self.memory_agent.get_recent_context(num_sessions=3)

        # Create update context
        context = f"""
        Current Therapy Plan (Version {current_plan.version}):
        {self._format_plan_details(current_plan.plan_details)}

        Latest Session Analysis:
        Key Themes: {", ".join(session_context.key_themes)}
        Emotional State: {session_context.emotional_state}
        Insights: {", ".join(session_context.insights)}
        Progress Indicators: {", ".join(session_context.progress_indicators)}

        Recent Context Summary:
        {recent_context.get("context_summary", "No recent context")}

        Therapeutic Memory Patterns:
        Dominant Themes: {", ".join(list(memory.recurring_themes.keys())[:3]) if memory.recurring_themes else "None"}
        Emotional Progression: {" → ".join(memory.emotional_patterns[-3:]) if memory.emotional_patterns else "None"}
        Relationship Quality: {memory.relationship_quality}

        Latest Session Transcript:
        {session_text}

        Relevant Knowledge:
        """

        for i, knowledge in enumerate(relevant_knowledge, 1):
            context += f"{i}. From {knowledge['source']}: {knowledge['content']}\n"

        # Use style-specific prompt if available
        therapy_style = current_plan.selected_therapy_style
        if therapy_style and style_service.get_style_pack(therapy_style):
            reflection_prompt = style_service.get_reflection_prompt(therapy_style)
            if reflection_prompt:
                update_prompt = f"""
{reflection_prompt}

Context for plan update:
{context}

Please update the therapy plan based on this {therapy_style.upper()} approach.
Consider the therapeutic progress, emerging patterns, and current session insights.
"""
            else:
                update_prompt = UPDATE_PLAN_PROMPT.format(context=context)
        else:
            update_prompt = UPDATE_PLAN_PROMPT.format(context=context)

        # Generate structured response (run in thread)
        response = await trio.to_thread.run_sync(
            self.llm_service.generate_structured_response,
            update_prompt,
            '{"focus": "string", "goals": "string", "techniques": "string", "themes": "string", "timeline": "string"}',
        )

        # Parse response and merge with current plan
        updated_details = current_plan.plan_details.copy()
        parsed_updates = self._parse_plan_response(response, self.current_strategy)

        # Update specific fields
        for key, value in parsed_updates.items():
            if value and value.strip():  # Only update non-empty values
                updated_details[key] = value

        # Add update metadata
        updated_details.update(
            {
                "updated_from_session": session.session_id,
                "update_timestamp": datetime.now().isoformat(),
                "memory_insights": recent_context.get("insights", [])[
                    -2:
                ],  # Last 2 insights
                "progress_indicators": session_context.progress_indicators,
            }
        )

        return updated_details

    def _parse_plan_response(
        self, response: dict[str, Any], strategy: PlanningStrategy | None
    ) -> dict[str, Any]:
        """Parse LLM response into plan details."""
        default_details = {
            "focus": f"Therapeutic work using {strategy.therapy_style.upper() if strategy else 'general'} approach",
            "goals": "Build therapeutic relationship and address key concerns",
            "techniques": ", ".join(
                strategy.techniques if strategy else ["supportive_therapy"]
            ),
            "themes": ", ".join(
                strategy.focus_areas if strategy else ["general_wellbeing"]
            ),
            "timeline": "Ongoing assessment with regular reviews",
        }

        if "raw_response" in response:
            try:
                import json

                raw_response = response["raw_response"].strip()

                # Clean markdown formatting
                if raw_response.startswith("```json"):
                    raw_response = raw_response[7:]
                if raw_response.startswith("```"):
                    raw_response = raw_response[3:]
                if raw_response.endswith("```"):
                    raw_response = raw_response[:-3]

                parsed = json.loads(raw_response.strip())

                # Update defaults with parsed values
                for key in default_details.keys():
                    if key in parsed and parsed[key]:
                        default_details[key] = parsed[key]

            except Exception as e:
                logger.warning(f"Failed to parse plan response: {e}")

        return default_details

    def _format_plan_details(self, plan_details: dict[str, Any]) -> str:
        """Format plan details for LLM context."""
        formatted = []
        for key, value in plan_details.items():
            if isinstance(value, (str, int, float)):
                formatted.append(f"{key.title()}: {value}")
        return "\n".join(formatted)

    def _assess_update_necessity(
        self, session_context, memory, current_plan: TherapyPlan
    ) -> bool:
        """Assess if plan update is necessary based on recent progress."""
        # Update if significant new insights
        if len(session_context.insights) >= 2:
            return True

        # Update if new themes emerge
        current_themes = set(current_plan.plan_details.get("themes", "").split(", "))
        new_themes = set(session_context.key_themes)
        if len(new_themes - current_themes) >= 2:
            return True

        # Update if strong progress indicators
        if len(session_context.progress_indicators) >= 2:
            return True

        # Update if plan is old (version 1 and multiple sessions)
        if current_plan.version == 1 and len(memory.session_contexts) >= 3:
            return True

        return False

    def _identify_plan_changes(
        self, old_details: dict[str, Any], new_details: dict[str, Any]
    ) -> list[str]:
        """Identify specific changes between plan versions."""
        changes = []

        for key in ["focus", "goals", "techniques", "themes"]:
            old_value = old_details.get(key, "")
            new_value = new_details.get(key, "")

            if old_value != new_value:
                changes.append(f"{key}_updated")

        # Check for new metadata
        if "memory_insights" in new_details:
            changes.append("memory_insights_integrated")

        if "progress_indicators" in new_details:
            changes.append("progress_tracking_updated")

        return changes

    def _generate_update_rationale(
        self, session_context, memory, changes: list[str]
    ) -> str:
        """Generate rationale for plan updates."""
        rationale_parts = []

        if "memory_insights_integrated" in changes:
            rationale_parts.append("Integrated insights from therapeutic memory")

        if "progress_tracking_updated" in changes:
            rationale_parts.append("Updated based on recent progress indicators")

        if session_context.insights:
            rationale_parts.append("Incorporated new session insights")

        if memory.relationship_quality in ["established", "strong"]:
            rationale_parts.append("Adjusted for deepening therapeutic relationship")

        return (
            "; ".join(rationale_parts)
            if rationale_parts
            else "Routine plan update based on session progress"
        )

    def _calculate_effectiveness_score(
        self,
        plan: TherapyPlan,
        memory,
        recent_context: dict[str, Any],
        patterns: dict[str, Any],
    ) -> float:
        """Calculate plan effectiveness score (0.0 to 1.0)."""
        score = 0.5  # Base score

        # Progress indicators boost
        progress_indicators = recent_context.get("insights", [])
        if progress_indicators:
            score += min(0.3, len(progress_indicators) * 0.1)

        # Emotional progression
        emotional_trend = patterns.get("emotional_patterns", {}).get(
            "recent_trend", "stable"
        )
        if emotional_trend == "improving":
            score += 0.2
        elif emotional_trend == "declining":
            score -= 0.2

        # Relationship quality
        relationship_quality = memory.relationship_quality
        quality_scores = {
            "new": 0.0,
            "building": 0.1,
            "developing": 0.2,
            "established": 0.3,
            "strong": 0.4,
        }
        score += quality_scores.get(relationship_quality, 0.0)

        # Clamp score between 0.0 and 1.0
        return max(0.0, min(1.0, score))

    def _generate_effectiveness_assessment(
        self,
        plan: TherapyPlan,
        memory,
        recent_context: dict[str, Any],
        effectiveness_score: float,
    ) -> dict[str, Any]:
        """Generate detailed effectiveness assessment."""
        strengths = []
        improvement_areas = []
        recommendations = []

        # Assess based on score
        if effectiveness_score >= 0.7:
            strengths.append("Strong therapeutic progress evident")
            strengths.append("Good alignment between plan and outcomes")
        elif effectiveness_score >= 0.5:
            strengths.append("Moderate progress observed")
            improvement_areas.append("Consider plan refinements")
        else:
            improvement_areas.append("Limited progress indicators")
            improvement_areas.append("Plan may need significant adjustment")
            recommendations.append("Review and update therapy approach")

        # Assess relationship quality
        if memory.relationship_quality in ["established", "strong"]:
            strengths.append("Strong therapeutic relationship")
        else:
            improvement_areas.append("Continue building therapeutic rapport")

        # Assess insights
        insights = recent_context.get("insights", [])
        if len(insights) >= 2:
            strengths.append("Client demonstrating good insight development")
        else:
            recommendations.append("Focus on insight-building activities")

        return {
            "strengths": strengths,
            "improvement_areas": improvement_areas,
            "recommendations": recommendations,
        }

    def _recommend_theme_adjustments(
        self, plan: TherapyPlan, patterns: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Recommend theme-related adjustments."""
        recommendations = []

        theme_patterns = patterns.get("theme_patterns", {})
        dominant_themes = theme_patterns.get("dominant_themes", [])

        current_themes = set(plan.plan_details.get("themes", "").split(", "))

        for theme in dominant_themes[:2]:  # Top 2 themes
            if theme not in current_themes:
                recommendations.append(
                    {
                        "type": "theme_addition",
                        "description": f"Consider adding '{theme}' as a focus theme",
                        "rationale": "Theme appears frequently in recent sessions",
                        "priority": "medium",
                    }
                )

        return recommendations

    def _recommend_technique_adjustments(
        self, plan: TherapyPlan, memory
    ) -> list[dict[str, Any]]:
        """Recommend technique-related adjustments."""
        recommendations = []

        # Base recommendation on relationship quality
        if memory.relationship_quality in ["established", "strong"]:
            recommendations.append(
                {
                    "type": "technique_advancement",
                    "description": "Consider introducing more advanced therapeutic techniques",
                    "rationale": "Strong therapeutic relationship allows for deeper work",
                    "priority": "medium",
                }
            )

        return recommendations

    def _recommend_goal_adjustments(
        self, plan: TherapyPlan, effectiveness: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Recommend goal-related adjustments."""
        recommendations = []

        if effectiveness["effectiveness_score"] >= 0.7:
            recommendations.append(
                {
                    "type": "goal_progression",
                    "description": "Consider setting more advanced therapeutic goals",
                    "rationale": "High effectiveness suggests readiness for next level",
                    "priority": "high",
                }
            )
        elif effectiveness["effectiveness_score"] < 0.4:
            recommendations.append(
                {
                    "type": "goal_simplification",
                    "description": "Consider simplifying current therapeutic goals",
                    "rationale": "Lower effectiveness may indicate goals are too ambitious",
                    "priority": "high",
                }
            )

        return recommendations

    def _prioritize_recommendations(
        self, recommendations: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Prioritize recommendations by importance."""
        priority_order = {"high": 0, "medium": 1, "low": 2}

        return sorted(
            recommendations,
            key=lambda x: priority_order.get(x.get("priority", "low"), 2),
        )

    async def health_check(self) -> bool:
        """
        Perform health check on the planning agent using Trio.

        Returns:
            bool: True if healthy, False otherwise
        """
        try:
            # Test memory agent connectivity
            if not await self.memory_agent.health_check():
                return False

            # Test database connectivity
            plans = await self.db_service.get_latest_therapy_plan(
                self.user_context.user_id
            )

            # Test LLM service (run in thread)
            test_prompt = "Respond with 'OK' if you can process this request."
            response = await trio.to_thread.run_sync(
                self.llm_service.generate_response, test_prompt
            )
            return "OK" in response or "ok" in response.lower()

        except Exception as e:
            logger.error(f"TrioPlanningAgent health check failed: {e}")
            return False

    def __str__(self) -> str:
        """String representation of planning agent."""
        return f"TrioPlanningAgent(user={self.user_context.user_id}, style={self.current_strategy.therapy_style if self.current_strategy else 'none'})"

    def __repr__(self) -> str:
        """Detailed representation of planning agent."""
        evolution_count = len(self.plan_evolution)
        return f"TrioPlanningAgent(user='{self.user_context.user_id}', evolutions={evolution_count})"
