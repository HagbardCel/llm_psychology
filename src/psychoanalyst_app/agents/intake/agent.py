"""TrioIntakeAgent: Trio-native agent for conducting initial user assessment."""

from __future__ import annotations

import logging

from psychoanalyst_app.agents.intake.extraction import extract_tier1_data
from psychoanalyst_app.agents.intake.prompts import (
    CLOSING_PROMPT,
    CONTINUE_CONVERSATION_PROMPT,
    GUEST_WELCOME_PROMPT,
    INITIAL_GREETING_PROMPT,
)
from psychoanalyst_app.agents.intake.slots import (
    identify_covered_topics,
    identify_required_slots,
    intake_completion_diagnostics,
    is_intake_complete,
    next_required_follow_up,
)
from psychoanalyst_app.config import Settings
from psychoanalyst_app.context.user_context import UserContext
from psychoanalyst_app.models.domain import UserStatus
from psychoanalyst_app.orchestration.agent_output_validators import (
    build_user_profile_output,
)
from psychoanalyst_app.orchestration.models import (
    AgentResponse,
    ConversationContext,
    WorkflowEvent,
    direct_agent_response,
)
from psychoanalyst_app.services.llm_service import LLMService

logger = logging.getLogger(__name__)


class TrioIntakeAgent:
    """Trio-native agent responsible for conducting intake assessments."""

    def __init__(
        self,
        llm_service: LLMService,
        user_context: UserContext,
        config: Settings,
    ):
        self.llm_service = llm_service
        self.user_context = user_context
        self.session_duration = config.SESSION_DURATION_MINUTES
        self.intake_topics = config.INTAKE_TOPICS

    async def process_message(
        self, message: str, context: ConversationContext
    ) -> AgentResponse:
        """Process user message during intake (orchestrator interface)."""
        try:
            logger.info(
                "Processing message for user %s. Name: '%s'",
                context.user_profile.user_id,
                context.user_profile.name,
            )

            covered_topics = identify_covered_topics(message, context.message_history)
            intake_slot_coverage = identify_required_slots(
                message, context.message_history
            )
            completion_diagnostics = intake_completion_diagnostics(
                context, intake_slot_coverage
            )

            for topic in covered_topics:
                if topic not in context.topics_covered:
                    context.topics_covered.append(topic)

            logger.info(
                "Topics covered so far: %s (%s/%s)",
                context.topics_covered,
                len(context.topics_covered),
                len(self.intake_topics),
            )

            is_complete = is_intake_complete(context, intake_slot_coverage)

            next_action = "continue"
            workflow_event = None
            prompt = ""
            structured_profile = None

            is_guest = (
                context.user_profile.name == "Guest"
                or context.user_profile.status == UserStatus.PROFILE_ONLY
                or context.user_profile.name == context.user_profile.user_id
            )

            if is_guest:
                if not message.strip():
                    prompt = GUEST_WELCOME_PROMPT
                    next_action = "continue"
                    workflow_event = None
                    return direct_agent_response(
                        content=prompt,
                        next_action=next_action,
                        workflow_event=workflow_event,
                        metadata={
                            "topics_covered": context.topics_covered,
                            "intake_slot_coverage": sorted(intake_slot_coverage),
                            "intake_completion_diagnostics": completion_diagnostics,
                            "time_remaining_minutes": context.time_remaining_minutes,
                            "can_extend": context.can_extend,
                            "is_time_up": context.is_time_up,
                        },
                    )
                else:
                    new_name = message.strip()
                    context.user_profile.name = new_name
                    structured_profile = build_user_profile_output({"name": new_name})

                    prompt = self._build_initial_prompt(context)
                    next_action = "transition"
                    workflow_event = WorkflowEvent.START_INTAKE
                    return AgentResponse(
                        content=prompt,
                        next_action=next_action,
                        workflow_event=workflow_event,
                        metadata={
                            "topics_covered": context.topics_covered,
                            "intake_slot_coverage": sorted(intake_slot_coverage),
                            "intake_completion_diagnostics": completion_diagnostics,
                            "time_remaining_minutes": context.time_remaining_minutes,
                            "can_extend": context.can_extend,
                            "is_time_up": context.is_time_up,
                            "user_profile": structured_profile,
                        },
                    )

            elif len(context.message_history) == 0:
                prompt = self._build_initial_prompt(context)
                next_action = "continue"
                workflow_event = None
            else:
                prompt = self._build_continuation_prompt(message, context)
                required_follow_up = next_required_follow_up(intake_slot_coverage)

                if is_complete:
                    prompt = CLOSING_PROMPT

                    logger.info("Intake complete - extracting Tier 1 data...")
                    tier1_updates = await extract_tier1_data(
                        self.llm_service, context.message_history
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
                    return direct_agent_response(
                        content=prompt,
                        next_action=next_action,
                        workflow_event=workflow_event,
                        metadata={
                            "topics_covered": context.topics_covered,
                            "intake_slot_coverage": sorted(intake_slot_coverage),
                            "intake_completion_diagnostics": completion_diagnostics,
                            "time_remaining_minutes": context.time_remaining_minutes,
                            "can_extend": context.can_extend,
                            "is_time_up": context.is_time_up,
                            "user_profile": structured_profile,
                            "intake_complete": is_complete,
                        },
                    )
                elif context.is_time_up:
                    next_action = "continue"
                    workflow_event = None
                    prompt = (
                        "Our time is up for today. We will continue this intake "
                        "in our next session."
                    )
                    return direct_agent_response(
                        content=prompt,
                        next_action=next_action,
                        workflow_event=workflow_event,
                        metadata={
                            "topics_covered": context.topics_covered,
                            "intake_slot_coverage": sorted(intake_slot_coverage),
                            "intake_completion_diagnostics": completion_diagnostics,
                            "time_remaining_minutes": context.time_remaining_minutes,
                            "can_extend": context.can_extend,
                            "is_time_up": context.is_time_up,
                            "user_profile": structured_profile,
                            "intake_complete": is_complete,
                        },
                    )
                elif required_follow_up:
                    return direct_agent_response(
                        content=required_follow_up,
                        metadata={
                            "topics_covered": context.topics_covered,
                            "intake_slot_coverage": sorted(intake_slot_coverage),
                            "intake_completion_diagnostics": completion_diagnostics,
                            "time_remaining_minutes": context.time_remaining_minutes,
                            "can_extend": context.can_extend,
                            "is_time_up": context.is_time_up,
                            "intake_complete": is_complete,
                        },
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
                    "intake_slot_coverage": sorted(intake_slot_coverage),
                    "intake_completion_diagnostics": completion_diagnostics,
                    "time_remaining_minutes": context.time_remaining_minutes,
                    "can_extend": context.can_extend,
                    "is_time_up": context.is_time_up,
                    "user_profile": structured_profile,
                    "intake_complete": is_complete,
                },
            )

        except Exception as exc:
            logger.error(f"Error processing intake message: {exc}", exc_info=True)
            return AgentResponse(
                content=(
                    "I apologize, but I encountered an error. "
                    "Could you please repeat that?"
                ),
                next_action="continue",
                workflow_event=None,
                metadata={"error": str(exc)},
            )

    def _build_initial_prompt(self, context: ConversationContext) -> str:
        """Build initial greeting prompt."""
        return INITIAL_GREETING_PROMPT.format(
            user_name=context.user_profile.name,
            session_duration=context.duration_minutes,
        )

    def _build_continuation_prompt(
        self, message: str, context: ConversationContext
    ) -> str:
        """Build continuation prompt with time and topic awareness."""
        remaining_minutes = max(0, int(context.time_remaining_minutes))

        covered = context.topics_covered
        pending = [t for t in self.intake_topics if t not in covered]

        prompt = CONTINUE_CONVERSATION_PROMPT.format(
            remaining_minutes=remaining_minutes,
            session_duration=context.duration_minutes,
            covered_topics=", ".join(covered) if covered else "None",
            pending_topics=", ".join(pending),
        )

        return prompt
