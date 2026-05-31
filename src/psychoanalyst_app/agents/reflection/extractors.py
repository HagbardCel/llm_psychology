"""Structured-output helpers for reflection workflows."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from psychoanalyst_app.models.briefing_models import SessionBriefing
from psychoanalyst_app.models.data_models import PatientAnalysis
from psychoanalyst_app.models.structured_output_models import (
    ChangeDetectionDecision,
    Tier2Enrichment,
)
from psychoanalyst_app.services.llm_service import LLMService

logger = logging.getLogger(__name__)


async def extract_tier2_enrichment(
    llm_service: LLMService, prompt: str
) -> dict[str, Any] | None:
    """Run the Tier 2 enrichment structured output flow."""
    try:
        tier2 = await llm_service.generate_structured_output_async(
            prompt,
            Tier2Enrichment,
            method="json_schema",
            phase="post_session_update",
        )
        if not isinstance(tier2, Tier2Enrichment):
            logger.error("Tier 2 enrichment returned unexpected type %s", type(tier2))
            return None
        return tier2.model_dump()
    except ValidationError as exc:
        logger.error("Tier 2 enrichment failed validation: %s", exc)
        return None


async def extract_session_briefing(
    llm_service: LLMService, prompt: str, *, session_count: int, session_id: str
) -> dict[str, Any]:
    """Generate a validated SessionBriefing payload."""
    briefing = await llm_service.generate_structured_output_async(
        prompt,
        SessionBriefing,
        method="json_schema",
            phase="post_session_update",
    )
    if not isinstance(briefing, SessionBriefing):
        raise TypeError("Unexpected SessionBriefing type")

    now = datetime.now().isoformat()
    payload = briefing.model_dump()
    payload.update(
        {
            "generated_at": now,
            "session_count": session_count,
            "last_session_id": session_id,
        }
    )
    return payload


async def extract_tier3_change_decision(
    llm_service: LLMService, prompt: str
) -> ChangeDetectionDecision | None:
    """Call the Tier 3 change detection schema."""
    decision = await llm_service.generate_structured_output_async(
        prompt,
        ChangeDetectionDecision,
        method="json_schema",
            phase="post_session_update",
    )
    if not isinstance(decision, ChangeDetectionDecision):
        logger.error("Tier 3 change detection returned unexpected type %s", type(decision))
        return None
    return decision


async def extract_updated_tier3_analysis(
    llm_service: LLMService, prompt: str
) -> PatientAnalysis | None:
    """Call the Tier 3 update schema."""
    analysis = await llm_service.generate_structured_output_async(
        prompt,
        PatientAnalysis,
        method="json_schema",
            phase="post_session_update",
    )
    if not isinstance(analysis, PatientAnalysis):
        logger.error("Tier 3 update returned unexpected type %s", type(analysis))
        return None
    return analysis

