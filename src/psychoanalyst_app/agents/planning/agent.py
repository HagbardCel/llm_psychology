"""TrioPlanningAgent: Trio-native specialized agent for therapy plan creation and adjustment."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import trio

from psychoanalyst_app.agents.memory.agent import TrioMemoryAgent
from psychoanalyst_app.agents.planning.analysis import (
    assess_update_necessity,
    calculate_effectiveness_score,
    create_planning_strategy,
    generate_effectiveness_assessment,
    generate_update_rationale,
    identify_plan_changes,
    prioritize_recommendations,
    recommend_goal_adjustments,
    recommend_technique_adjustments,
    recommend_theme_adjustments,
    recommend_therapy_style,
)
from psychoanalyst_app.agents.planning.extraction import (
    generate_initial_plan_details,
    generate_updated_plan_details,
    get_relevant_knowledge,
)
from psychoanalyst_app.agents.planning.formatting import extract_session_text
from psychoanalyst_app.agents.planning.models import PlanEvolution, PlanningStrategy
from psychoanalyst_app.context.user_context import UserContext
from psychoanalyst_app.exceptions import PlanningError
from psychoanalyst_app.models.domain import Session, TherapyPlan
from psychoanalyst_app.models.llm_outputs import StructuredTherapyPlanOutput
from psychoanalyst_app.orchestration.agent_output_validators import (
    build_therapy_plan_output,
)
from psychoanalyst_app.services.llm_service import LLMService
from psychoanalyst_app.services.rag import RAGServiceProtocol
from psychoanalyst_app.services.style_service import StyleService
from psychoanalyst_app.services.trio_db_service import TrioDatabaseService

logger = logging.getLogger(__name__)


class TrioPlanningAgent:
    """Trio-native agent specialized in therapy plan creation and strategic adjustments."""

    def __init__(
        self,
        llm_service: LLMService,
        db_service: TrioDatabaseService,
        rag_service: RAGServiceProtocol,
        user_context: UserContext,
        memory_agent: TrioMemoryAgent,
        style_service: StyleService | None = None,
    ):
        self.llm_service = llm_service
        self.db_service = db_service
        self.rag_service = rag_service
        self.user_context = user_context
        self.memory_agent = memory_agent
        if style_service is None:
            raise ValueError("style_service is required")
        self.style_service = style_service

        self.current_strategy: PlanningStrategy | None = None
        self.plan_evolution: list[PlanEvolution] = []

        logger.info(f"TrioPlanningAgent initialized for user {user_context.user_id}")

    async def create_initial_plan(
        self, intake_session: Session, selected_style: str | None = None
    ) -> StructuredTherapyPlanOutput:
        """Create comprehensive initial therapy plan, shielded from cancellation."""
        logger.info(f"Creating initial therapy plan for {self.user_context.user_id}")

        try:
            with trio.CancelScope(shield=True):
                logger.debug(
                    "TrioPlanningAgent.create_initial_plan started (shielded)"
                )
                structured_plan = await self.build_structured_plan_output(
                    intake_session, selected_style
                )
                logger.info(
                    "Initial therapy plan output created for user %s",
                    self.user_context.user_id,
                )
                return structured_plan

        except Exception as exc:
            logger.error(f"Failed to create initial therapy plan: {exc}", exc_info=True)
            raise PlanningError(f"Initial plan creation failed: {exc}")

    async def build_structured_plan_output(
        self,
        intake_session: Session,
        selected_style: str | None = None,
    ) -> StructuredTherapyPlanOutput:
        """Generate a structured therapy plan payload without persistence."""
        session_context = await self.memory_agent.analyze_session_context(
            intake_session
        )
        logger.debug("TrioPlanningAgent analyzed session context")

        session_text = extract_session_text(intake_session)
        relevant_knowledge = await get_relevant_knowledge(
            self.rag_service,
            self.style_service,
            session_text,
            selected_style,
        )
        logger.debug("TrioPlanningAgent got relevant knowledge")

        if not selected_style:
            selected_style = recommend_therapy_style(
                session_context, relevant_knowledge
            )

        strategy = create_planning_strategy(
            self.style_service, selected_style, session_context
        )
        self.current_strategy = strategy

        logger.debug("TrioPlanningAgent generating plan details via LLM")
        plan_update, plan_details = await generate_initial_plan_details(
            self.llm_service,
            self.style_service,
            intake_session,
            session_context,
            strategy,
            relevant_knowledge,
        )
        logger.debug("TrioPlanningAgent generated plan details")

        return build_therapy_plan_output(
            {
                "selected_therapy_style": selected_style,
                "plan_details": plan_details,
                "initial_goals": plan_update.goals,
                "current_progress": "Baseline established",
                "planned_interventions": plan_update.techniques,
                "revision_recommendations": [],
                "status": "active",
            }
        )

    async def update_plan(
        self, session: Session, current_plan: TherapyPlan, force_update: bool = False
    ) -> StructuredTherapyPlanOutput:
        """Update therapy plan based on session progress and memory insights."""
        logger.info(f"Updating therapy plan {current_plan.plan_id}")

        try:
            session_context = await self.memory_agent.analyze_session_context(session)
            memory = await self.memory_agent.get_therapeutic_memory()

            update_needed = force_update or assess_update_necessity(
                session_context, memory, current_plan
            )

            if not update_needed:
                logger.info("No plan update needed based on current assessment")
                return build_therapy_plan_output(
                    {
                        "selected_therapy_style": current_plan.selected_therapy_style,
                        "plan_details": current_plan.plan_details,
                        "initial_goals": current_plan.initial_goals,
                        "current_progress": current_plan.current_progress,
                        "planned_interventions": current_plan.planned_interventions,
                        "revision_recommendations": current_plan.revision_recommendations,
                        "status": current_plan.status,
                    }
                )

            session_text = extract_session_text(session)
            relevant_knowledge = await get_relevant_knowledge(
                self.rag_service,
                self.style_service,
                session_text,
                current_plan.selected_therapy_style,
            )

            plan_update, updated_details = await generate_updated_plan_details(
                self.llm_service,
                self.style_service,
                self.memory_agent,
                session,
                session_context,
                memory,
                current_plan,
                relevant_knowledge,
            )

            changes = identify_plan_changes(
                current_plan.plan_details, updated_details
            )
            updated_plan_output = build_therapy_plan_output(
                {
                    "selected_therapy_style": current_plan.selected_therapy_style,
                    "plan_details": updated_details,
                    "initial_goals": plan_update.goals,
                    "current_progress": current_plan.current_progress,
                    "planned_interventions": plan_update.techniques,
                    "revision_recommendations": current_plan.revision_recommendations,
                    "status": current_plan.status,
                }
            )

            evolution = PlanEvolution(
                plan_id=current_plan.plan_id,
                version=current_plan.version + 1,
                changes=changes,
                rationale=generate_update_rationale(session_context, memory, changes),
            )
            self.plan_evolution.append(evolution)

            logger.info(
                "Therapy plan update prepared for %s (next version=%s)",
                current_plan.plan_id,
                current_plan.version + 1,
            )
            return updated_plan_output

        except Exception as exc:
            logger.error(f"Failed to update therapy plan: {exc}", exc_info=True)
            raise PlanningError(f"Plan update failed: {exc}")

    async def assess_plan_effectiveness(self, plan: TherapyPlan) -> dict[str, Any]:
        """Assess the effectiveness of a therapy plan based on progress indicators."""
        logger.debug(f"Assessing effectiveness of plan {plan.plan_id}")

        try:
            memory = await self.memory_agent.get_therapeutic_memory()
            recent_context = await self.memory_agent.get_recent_context(num_sessions=3)
            patterns = await self.memory_agent.identify_patterns()

            effectiveness_score = calculate_effectiveness_score(
                plan, memory, recent_context, patterns
            )

            assessment = generate_effectiveness_assessment(
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

        except Exception as exc:
            logger.error(f"Failed to assess plan effectiveness: {exc}", exc_info=True)
            return {
                "plan_id": plan.plan_id,
                "version": plan.version,
                "effectiveness_score": 0.5,
                "error": str(exc),
                "assessment_timestamp": datetime.now().isoformat(),
            }

    async def recommend_plan_adjustments(
        self, plan: TherapyPlan
    ) -> list[dict[str, Any]]:
        """Recommend specific adjustments to improve therapy plan effectiveness."""
        logger.debug(f"Generating recommendations for plan {plan.plan_id}")

        try:
            effectiveness = await self.assess_plan_effectiveness(plan)
            memory = await self.memory_agent.get_therapeutic_memory()
            patterns = await self.memory_agent.identify_patterns()

            recommendations: list[dict[str, Any]] = []

            theme_recommendations = recommend_theme_adjustments(plan, patterns)
            recommendations.extend(theme_recommendations)

            technique_recommendations = recommend_technique_adjustments(plan, memory)
            recommendations.extend(technique_recommendations)

            goal_recommendations = recommend_goal_adjustments(plan, effectiveness)
            recommendations.extend(goal_recommendations)

            prioritized_recommendations = prioritize_recommendations(recommendations)

            logger.info(f"Generated {len(prioritized_recommendations)} recommendations")
            return prioritized_recommendations

        except Exception as exc:
            logger.error(f"Failed to generate recommendations: {exc}", exc_info=True)
            return []

    def get_plan_evolution_summary(self) -> dict[str, Any]:
        """Get summary of therapy plan evolution over time."""
        if not self.plan_evolution:
            return {
                "total_versions": 0,
                "evolution_timeline": [],
                "common_changes": [],
                "effectiveness_trend": "unknown",
            }

        all_changes: list[str] = []
        effectiveness_scores: list[float] = []

        for evolution in self.plan_evolution:
            all_changes.extend(evolution.changes)
            if evolution.effectiveness_score > 0:
                effectiveness_scores.append(evolution.effectiveness_score)

        effectiveness_trend = "stable"
        if len(effectiveness_scores) >= 2:
            if effectiveness_scores[-1] > effectiveness_scores[0]:
                effectiveness_trend = "improving"
            elif effectiveness_scores[-1] < effectiveness_scores[0]:
                effectiveness_trend = "declining"

        change_counts: dict[str, int] = {}
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
                "therapy_style": (
                    self.current_strategy.therapy_style
                    if self.current_strategy
                    else None
                ),
                "focus_areas": (
                    self.current_strategy.focus_areas if self.current_strategy else []
                ),
            },
        }

    async def health_check(self) -> bool:
        """Perform health check on the planning agent."""
        try:
            if not await self.memory_agent.health_check():
                return False

            await self.db_service.get_current_therapy_plan(
                self.user_context.user_id
            )

            test_prompt = "Respond with 'OK' if you can process this request."
            response = await trio.to_thread.run_sync(
                self.llm_service.generate_response, test_prompt
            )
            return "OK" in response or "ok" in response.lower()

        except Exception as exc:
            logger.error(f"TrioPlanningAgent health check failed: {exc}")
            return False

    def __str__(self) -> str:
        return (
            f"TrioPlanningAgent(user={self.user_context.user_id}, "
            f"style={self.current_strategy.therapy_style if self.current_strategy else 'none'})"
        )

    def __repr__(self) -> str:
        evolution_count = len(self.plan_evolution)
        return (
            f"TrioPlanningAgent(user='{self.user_context.user_id}', "
            f"evolutions={evolution_count})"
        )
