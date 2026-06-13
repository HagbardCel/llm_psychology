"""Deep-topic detection helpers used by the therapist agent."""

from __future__ import annotations

import logging

from psychoanalyst_app.agents.therapist.prompts import DEEP_TOPIC_DETECTION_PROMPT
from psychoanalyst_app.agents.therapist.session_policy import is_in_deep_topic
from psychoanalyst_app.models.llm_outputs import DeepTopicSignalOutput
from psychoanalyst_app.orchestration.models import ConversationContext
from psychoanalyst_app.services.llm_service import LLMService
from psychoanalyst_app.services.llm_phases import THERAPY_DEEP_TOPIC_DETECTION

logger = logging.getLogger(__name__)


async def detect_deep_topic_via_llm(
    llm_service: LLMService,
    context: ConversationContext,
) -> bool:
    """Use the LLM to determine whether the conversation is in a deep topic."""
    try:
        recent_messages = context.message_history[-6:]
        if not recent_messages:
            return is_in_deep_topic(context)

        transcript_lines: list[str] = []
        for message in recent_messages:
            role = "Therapist" if message.role == "assistant" else "Patient"
            transcript_lines.append(f"{role}: {message.content}")

        prompt = DEEP_TOPIC_DETECTION_PROMPT.format(
            transcript="\n".join(transcript_lines)
        )
        signal_output = await llm_service.generate_structured_output_async(
            prompt,
            DeepTopicSignalOutput,
            method="json_schema",
            phase=THERAPY_DEEP_TOPIC_DETECTION,
        )
        if not isinstance(signal_output, DeepTopicSignalOutput):
            signal_output = DeepTopicSignalOutput.model_validate(signal_output)
        return signal_output.in_deep_topic
    except Exception:
        logger.debug(
            "Deep topic signal detection failed; using conservative fallback",
            exc_info=True,
        )
        return is_in_deep_topic(context)
