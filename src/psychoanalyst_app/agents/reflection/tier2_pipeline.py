"""Tier 2 enrichment pipeline helpers for reflection workflows."""

from __future__ import annotations

import logging
from typing import Any

from psychoanalyst_app.models.data_models import DetailedSession, Session
from psychoanalyst_app.prompts.reflection_prompt_builder import (
    build_tier2_enrichment_prompt,
)
from psychoanalyst_app.services.llm_service import LLMService
from psychoanalyst_app.services.trio_db_service import TrioDatabaseService

from .extractors import extract_tier2_enrichment

logger = logging.getLogger(__name__)


async def enrich_session_tier2(
    llm_service: LLMService,
    session: Session,
) -> dict[str, Any] | None:
    """Generate Tier 2 enrichment payload for a single session."""
    try:
        enrichment_prompt = build_tier2_enrichment_prompt(session)
        tier2_data = await extract_tier2_enrichment(llm_service, enrichment_prompt)
        if not tier2_data:
            return None
        return tier2_data
    except Exception as exc:
        logger.error(
            "Error enriching session %s: %s",
            session.session_id,
            exc,
            exc_info=True,
        )
        return None


def apply_tier2_enrichment(session: Session, tier2_data: dict[str, Any]) -> Session:
    """Apply Tier 2 enrichment to a session object without persistence."""
    updates = {
        "psychological_summary": tier2_data.get(
            "psychological_summary", session.psychological_summary
        ),
        "dominant_affects": tier2_data.get(
            "dominant_affects", session.dominant_affects
        ),
        "key_themes": tier2_data.get("key_themes", session.key_themes),
        "notable_interactions": tier2_data.get(
            "notable_interactions", session.notable_interactions
        ),
        "interpretations": tier2_data.get("interpretations", session.interpretations),
        "patient_reactions": tier2_data.get(
            "patient_reactions", session.patient_reactions
        ),
        "enriched": True,
    }
    return session.model_copy(update=updates)


async def load_or_enrich_session_record(
    db_service: TrioDatabaseService,
    llm_service: LLMService,
    session: Session,
) -> tuple[Session, dict[str, Any] | None]:
    """Load enriched record when available, otherwise enrich in-memory."""
    tier2_enrichment = None
    session_record = await db_service.get_session(session.session_id) or session

    if not getattr(session_record, "enriched", False):
        logger.info(
            "Session %s not yet enriched - extracting Tier 2 data...",
            session_record.session_id,
        )
        tier2_enrichment = await enrich_session_tier2(llm_service, session_record)
        if tier2_enrichment:
            session_record = apply_tier2_enrichment(session_record, tier2_enrichment)
            logger.info(
                "Successfully enriched session %s with Tier 2 data",
                session_record.session_id,
            )
        else:
            logger.warning(
                "Failed to enrich session %s - continuing without enrichment",
                session_record.session_id,
            )
        return session_record, tier2_enrichment

    logger.info("Session %s already enriched - skipping", session_record.session_id)
    return session_record, tier2_enrichment


async def ensure_recent_sessions_enriched(
    db_service: TrioDatabaseService,
    llm_service: LLMService,
    user_id: str,
    *,
    limit: int = 5,
    scan_limit: int | None = None,
) -> list[DetailedSession]:
    """Ensure recent sessions have Tier 2 enrichment, enriching on-demand."""
    scan_limit = scan_limit or max(limit * 3, 10)

    enriched = await db_service.get_recent_sessions(
        user_id, limit=limit, enriched_only=True
    )
    if len(enriched) >= limit:
        return enriched

    recent_any = await db_service.get_recent_sessions(
        user_id, limit=scan_limit, enriched_only=False
    )
    for session in recent_any:
        if getattr(session, "enriched", False):
            continue
        try:
            await enrich_session_tier2(llm_service, session)
        except Exception:
            logger.warning(
                "On-demand Tier 2 enrichment failed for session %s",
                session.session_id,
                exc_info=True,
            )

        enriched = await db_service.get_recent_sessions(
            user_id, limit=limit, enriched_only=True
        )
        if len(enriched) >= limit:
            break

    return enriched
