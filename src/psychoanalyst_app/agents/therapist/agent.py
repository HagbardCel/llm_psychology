"""TrioTherapistAgent: Trio-native agent for conducting therapy sessions."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import trio

from psychoanalyst_app.agents.therapist.deep_topic import detect_deep_topic_via_llm
from psychoanalyst_app.agents.therapist.prompt_context import (
    build_continuation_prompt_with_context,
    build_plan_context,
    default_style_instructions,
    load_patient_context,
)
from psychoanalyst_app.agents.therapist.prompts import (
    CLOSING_SESSION_PROMPT,
    build_initial_prompt,
    build_resumption_prompt,
)
from psychoanalyst_app.agents.therapist.session_policy import (
    resolve_response_mode,
    should_offer_extension,
)
from psychoanalyst_app.config import Settings
from psychoanalyst_app.models.domain import BriefingStatus, TherapyPlan, UserProfile
from psychoanalyst_app.orchestration.models import (
    AgentResponse,
    ConversationContext,
)
from psychoanalyst_app.services.llm_service import LLMService
from psychoanalyst_app.services.rag import RAGServiceProtocol
from psychoanalyst_app.services.style_service import StyleService
from psychoanalyst_app.services.trio_db_service import TrioDatabaseService

logger = logging.getLogger(__name__)


class TrioTherapistAgent:
    """Trio-native agent responsible for conducting therapy sessions."""

    def __init__(
        self,
        llm_service: LLMService,
        db_service: TrioDatabaseService,
        rag_service: RAGServiceProtocol,
        reflection_agent: Any | None = None,
        style_service: StyleService | None = None,
        config: Settings | None = None,
    ):
        self.llm_service = llm_service
        self.db_service = db_service
        self.rag_service = rag_service
        self.reflection_agent = reflection_agent
        if config is None:
            raise ValueError("config is required")
        self.config = config
        if style_service is None:
            raise ValueError("style_service is required")
        self.style_service = style_service

    def get_briefing_status(self, briefing: dict[str, Any]) -> BriefingStatus:
        """Determine the status of a briefing based on its age."""
        try:
            generated_at_str = briefing.get("generated_at")
            if not generated_at_str:
                return BriefingStatus.INVALID

            generated_at = datetime.fromisoformat(generated_at_str)
            age_days = (datetime.now() - generated_at).days

            if age_days <= self.config.BRIEFING_VALIDITY_DAYS:
                return BriefingStatus.FRESH
            elif age_days <= self.config.STALE_BRIEFING_DAYS:
                return BriefingStatus.STALE
            else:
                return BriefingStatus.VERY_STALE

        except (ValueError, TypeError) as exc:
            logger.warning(f"Error parsing briefing timestamp: {exc}")
            return BriefingStatus.INVALID

    async def process_message(
        self, message: str, context: ConversationContext
    ) -> AgentResponse:
        """Process user message during therapy session (orchestrator interface)."""
        try:
            therapy_plan = context.therapy_plan
            if not therapy_plan:
                therapy_plan = await self.db_service.get_current_therapy_plan(
                    context.user_profile.user_id
                )
                context.therapy_plan = therapy_plan

            if not therapy_plan:
                logger.error(
                    "Therapy context recovery found no plan for user %s "
                    "(session=%s)",
                    context.user_profile.user_id,
                    context.session_id,
                )
                return AgentResponse(
                    content=(
                        "Let's stay with what feels most urgent right now. "
                        "Tell me one recent moment when the worry became strongest, "
                        "and we can work from there."
                    ),
                    next_action="continue",
                    workflow_event=None,
                    metadata={"error": "No therapy plan"},
                )

            selected_style = therapy_plan.selected_therapy_style

            has_patient_history = any(
                item.role == "user" for item in context.message_history
            )
            if not message.strip() and not has_patient_history:
                prompt = await self._build_initial_session_prompt(
                    context.user_profile,
                    therapy_plan,
                    active_session_id=context.session_id,
                )
            else:
                prompt = await self._build_continuation_prompt(
                    message, context, therapy_plan, selected_style
                )

            next_action, workflow_event = resolve_response_mode(
                context,
                should_offer_extension=await self._should_offer_extension(context),
            )

            return AgentResponse(
                content=prompt,
                next_action=next_action,
                workflow_event=workflow_event,
                metadata={
                    "therapy_style": selected_style,
                    "time_remaining": context.time_remaining_minutes,
                    "can_extend": context.can_extend,
                    "extensions_used": context.extensions_used,
                },
            )

        except Exception as exc:
            return AgentResponse(
                content=(
                    "I apologize, but I encountered an error. "
                    "Could you please repeat that?"
                ),
                next_action="continue",
                workflow_event=None,
                metadata={"error": str(exc)},
            )

    async def _build_initial_session_prompt(
        self,
        user_profile: UserProfile,
        therapy_plan: TherapyPlan,
        *,
        active_session_id: str | None = None,
    ) -> str:
        """Build initial greeting prompt for therapy session."""
        if therapy_plan.session_briefing:
            briefing = therapy_plan.session_briefing
            status = self.get_briefing_status(briefing)

            if status in [BriefingStatus.FRESH, BriefingStatus.STALE]:
                logger.info(
                    "Using session briefing (status: %s) for user %s",
                    status.value,
                    user_profile.user_id,
                )
                return build_resumption_prompt(
                    user_profile, therapy_plan, briefing, status
                )
            else:
                logger.warning(
                    f"Briefing is {status.value} for user {user_profile.user_id}; "
                    "falling back to standard initial prompt"
                )

        selected_style = therapy_plan.selected_therapy_style
        user_name = user_profile.name
        plan_context = await build_plan_context(
            therapy_plan,
            self.rag_service,
            self.style_service,
        )
        exclude = {active_session_id} if active_session_id else None
        patient_context = await load_patient_context(
            self.db_service,
            user_profile.user_id,
            exclude_session_ids=exclude,
        )
        if patient_context:
            plan_context = f"{patient_context}\n\n{plan_context}"

        style_instructions = default_style_instructions(
            selected_style, self.style_service
        )

        return build_initial_prompt(
            user_name=user_name,
            plan_context=plan_context,
            style_instructions=style_instructions,
        )

    async def _build_continuation_prompt(
        self,
        message: str,
        context: ConversationContext,
        therapy_plan: TherapyPlan,
        selected_style: str,
    ) -> str:
        """Build continuation prompt with RAG context."""
        return await build_continuation_prompt_with_context(
            message=message,
            context=context,
            therapy_plan=therapy_plan,
            selected_style=selected_style,
            rag_service=self.rag_service,
            style_service=self.style_service,
            db_service=self.db_service,
        )

    async def _should_offer_extension(self, context: ConversationContext) -> bool:
        """Check if session extension should be offered."""
        if not should_offer_extension(context, in_deep_topic=False):
            return False
        return should_offer_extension(
            context,
            in_deep_topic=await detect_deep_topic_via_llm(self.llm_service, context),
        )

    async def get_closing_response(self, therapy_plan: TherapyPlan) -> str:
        """Generate a closing response for the therapy session."""
        selected_style = therapy_plan.selected_therapy_style if therapy_plan else None
        plan_context = await build_plan_context(
            therapy_plan,
            self.rag_service,
            self.style_service,
        )

        style_instructions = default_style_instructions(
            selected_style, self.style_service
        )

        closing_prompt = CLOSING_SESSION_PROMPT.format(
            plan_context=plan_context, style_instructions=style_instructions
        )

        return await trio.to_thread.run_sync(
            self.llm_service.generate_response, closing_prompt
        )

    def _get_agent_display_name(self) -> str:
        """Get the display name for the agent in UI."""
        return "therapist"
