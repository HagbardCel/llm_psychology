"""Tier 2 session enrichment service and background worker."""

from __future__ import annotations

import logging

import trio

from psychoanalyst_app.models.llm_outputs import Tier2Enrichment
from psychoanalyst_app.services.llm_phases import SESSION_ENRICHMENT
from psychoanalyst_app.services.llm_service import LLMService
from psychoanalyst_app.services.session_enrichment_prompts import (
    build_tier2_enrichment_prompt,
)
from psychoanalyst_app.services.trio_db_service import TrioDatabaseService

logger = logging.getLogger(__name__)


class SessionEnrichmentService:
    """Performs Tier 2 session enrichment outside of agent request paths."""

    def __init__(self, llm_service: LLMService, db_service: TrioDatabaseService):
        self.llm_service = llm_service
        self.db_service = db_service

    async def enrich_session_tier2(self, session_id: str) -> bool:
        session = await self.db_service.get_session(session_id)
        if not session:
            logger.warning("Session not found for enrichment: %s", session_id)
            return False

        if getattr(session, "enriched", False):
            return True

        enrichment_prompt = build_tier2_enrichment_prompt(session)

        tier2 = await self.llm_service.generate_structured_output_async(
            enrichment_prompt,
            Tier2Enrichment,
            method="json_schema",
            phase=SESSION_ENRICHMENT,
        )
        if not isinstance(tier2, Tier2Enrichment):
            logger.error(
                "Tier 2 enrichment returned unexpected type for %s",
                session_id,
            )
            return False
        return await self.db_service.update_session_tier2(
            session_id,
            tier2.model_dump(),
        )


async def run_session_enrichment_worker(
    db_service: TrioDatabaseService,
    enrichment_service: SessionEnrichmentService,
    *,
    poll_interval_seconds: float = 0.5,
    max_attempts: int = 3,
) -> None:
    """Background worker that processes queued Tier 2 enrichment jobs.

    Claim one job at a time, enrich, and mark complete/failed with bounded
    retries.
    """
    logger.info("Session enrichment worker started")
    while True:
        job = await db_service.claim_next_session_enrichment_job(
            max_attempts=max_attempts
        )
        if not job:
            await trio.sleep(poll_interval_seconds)
            continue

        session_id = job["session_id"]
        try:
            ok = await enrichment_service.enrich_session_tier2(session_id)
            if ok:
                await db_service.mark_session_enrichment_job_complete(session_id)
            else:
                await db_service.mark_session_enrichment_job_failed(
                    session_id, "Tier 2 enrichment failed"
                )
        except Exception as e:
            logger.error(
                "Enrichment job crashed for %s: %s", session_id, e, exc_info=True
            )
            await db_service.mark_session_enrichment_job_failed(session_id, str(e))
