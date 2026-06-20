"""TrioIntakeAgent: Trio-native agent for conducting initial user assessment."""

from __future__ import annotations

import logging

from psychoanalyst_app.agents.intake.prompts import GUEST_WELCOME_PROMPT
from psychoanalyst_app.agents.intake.runtime import (
    IntakeContinuationPlan,
    build_initial_intake_prompt,
    intake_record_metadata,
    intake_response_metadata,
    is_guest_intake_context,
    prepare_intake_record_state,
    resolve_intake_continuation_turn,
    should_use_structured_completion_gate,
)
from psychoanalyst_app.agents.intake.slots import (
    identify_covered_topics,
    identify_required_slots,
    intake_completion_diagnostics,
    is_intake_complete,
)
from psychoanalyst_app.config import Settings
from psychoanalyst_app.context.user_context import UserContext
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
        self.intake_note_tracking_enabled = config.INTAKE_NOTE_TRACKING_ENABLED
        self.intake_record_completion_gate_enabled = (
            config.INTAKE_RECORD_COMPLETION_GATE_ENABLED
        )
        self.intake_record_direct_ask_enabled = config.INTAKE_RECORD_DIRECT_ASK_ENABLED
        self.strict_quote_validation = (
            config.INTAKE_NOTE_TRACKING_STRICT_QUOTE_VALIDATION
        )
        self.note_tracking_timeout_seconds = (
            config.INTAKE_NOTE_TRACKING_TIMEOUT_SECONDS
        )

    async def process_message(
        self, message: str, context: ConversationContext
    ) -> AgentResponse:
        """Process user message during intake (orchestrator interface)."""
        try:
            logger.info(
                "Processing intake message for user %s",
                context.user_profile.user_id,
            )

            covered_topics = identify_covered_topics(message, context.message_history)
            intake_slot_coverage = identify_required_slots(
                message, context.message_history
            )
            completion_diagnostics = intake_completion_diagnostics(
                context, intake_slot_coverage
            )
            is_guest = is_guest_intake_context(context)
            use_structured_gate = should_use_structured_completion_gate(
                note_tracking_enabled=self.intake_note_tracking_enabled,
                completion_gate_enabled=self.intake_record_completion_gate_enabled,
            )
            record_state = await prepare_intake_record_state(
                message=message,
                context=context,
                llm_service=self.llm_service,
                note_tracking_enabled=self.intake_note_tracking_enabled,
                strict_quote_validation=self.strict_quote_validation,
                is_guest=is_guest,
                structured_gate_enabled=use_structured_gate,
                note_tracking_timeout_seconds=self.note_tracking_timeout_seconds,
            )
            record_metadata = intake_record_metadata(
                record_state,
                legacy_diagnostics=completion_diagnostics,
            )

            for topic in covered_topics:
                if topic not in context.topics_covered:
                    context.topics_covered.append(topic)

            logger.info("Topics covered so far: %s", context.topics_covered)

            is_complete = (
                record_state.gate_complete
                if use_structured_gate
                else is_intake_complete(context, intake_slot_coverage)
            )

            if is_guest:
                return self._handle_guest_turn(
                    message=message,
                    context=context,
                    intake_slot_coverage=intake_slot_coverage,
                    completion_diagnostics=completion_diagnostics,
                    record_metadata=record_metadata,
                )

            if len(context.message_history) == 0:
                return self._initial_prompt_response(
                    context=context,
                    intake_slot_coverage=intake_slot_coverage,
                    completion_diagnostics=completion_diagnostics,
                    record_metadata=record_metadata,
                    intake_complete=is_complete,
                )

            continuation = await resolve_intake_continuation_turn(
                message=message,
                context=context,
                record_state=record_state,
                is_complete=is_complete,
                use_structured_gate=use_structured_gate,
                intake_slot_coverage=intake_slot_coverage,
                intake_topics=self.intake_topics,
                direct_ask_enabled=self.intake_record_direct_ask_enabled,
                llm_service=self.llm_service,
                completion_diagnostics=completion_diagnostics,
                record_metadata=record_metadata,
            )
            if isinstance(continuation, AgentResponse):
                return continuation

            logger.info("Intake Agent returning: action=continue, event=None")
            return self._continuation_response(
                plan=continuation,
                context=context,
                intake_slot_coverage=intake_slot_coverage,
                completion_diagnostics=completion_diagnostics,
                record_metadata=record_metadata,
                intake_complete=is_complete,
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

    def _handle_guest_turn(
        self,
        *,
        message: str,
        context: ConversationContext,
        intake_slot_coverage: set[str],
        completion_diagnostics: dict[str, object],
        record_metadata: dict[str, object],
    ) -> AgentResponse:
        if not message.strip():
            return direct_agent_response(
                content=GUEST_WELCOME_PROMPT,
                metadata=intake_response_metadata(
                    context=context,
                    intake_slot_coverage=intake_slot_coverage,
                    completion_diagnostics=completion_diagnostics,
                    record_metadata=record_metadata,
                ),
            )

        context.user_profile.name = message.strip()
        structured_profile = build_user_profile_output({"name": message.strip()})
        return AgentResponse(
            content=build_initial_intake_prompt(context),
            next_action="transition",
            workflow_event=WorkflowEvent.START_INTAKE,
            metadata=intake_response_metadata(
                context=context,
                intake_slot_coverage=intake_slot_coverage,
                completion_diagnostics=completion_diagnostics,
                record_metadata=record_metadata,
                user_profile=structured_profile,
            ),
        )

    def _initial_prompt_response(
        self,
        *,
        context: ConversationContext,
        intake_slot_coverage: set[str],
        completion_diagnostics: dict[str, object],
        record_metadata: dict[str, object],
        intake_complete: bool,
    ) -> AgentResponse:
        return AgentResponse(
            content=build_initial_intake_prompt(context),
            next_action="continue",
            workflow_event=None,
            metadata=intake_response_metadata(
                context=context,
                intake_slot_coverage=intake_slot_coverage,
                completion_diagnostics=completion_diagnostics,
                record_metadata=record_metadata,
                intake_complete=intake_complete,
                intake_next_action_source="initial_prompt",
                selected_direct_ask_item=None,
            ),
        )

    def _continuation_response(
        self,
        *,
        plan: IntakeContinuationPlan,
        context: ConversationContext,
        intake_slot_coverage: set[str],
        completion_diagnostics: dict[str, object],
        record_metadata: dict[str, object],
        intake_complete: bool,
    ) -> AgentResponse:
        return AgentResponse(
            content=plan.prompt,
            next_action="continue",
            workflow_event=None,
            metadata=intake_response_metadata(
                context=context,
                intake_slot_coverage=intake_slot_coverage,
                completion_diagnostics=completion_diagnostics,
                record_metadata=record_metadata,
                intake_complete=intake_complete,
                intake_next_action_source=plan.intake_next_action_source,
                selected_direct_ask_item=plan.selected_direct_ask_item,
            ),
        )
