import logging

import trio

from psychoanalyst_app.services.session_enrichment_service import SessionEnrichmentService
from psychoanalyst_app.services.trio_db_service import TrioDatabaseService

logger = logging.getLogger(__name__)


async def run_session_enrichment_worker(
    db_service: TrioDatabaseService,
    enrichment_service: SessionEnrichmentService,
    *,
    poll_interval_seconds: float = 0.5,
    max_attempts: int = 3,
) -> None:
    """
    Background worker that processes queued Tier 2 enrichment jobs.

    This worker is intentionally simple: claim one job at a time, enrich,
    and mark complete/failed with bounded retries.
    """
    logger.info("Session enrichment worker started")
    while True:
        job = await db_service.claim_next_session_enrichment_job(max_attempts=max_attempts)
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
            logger.error("Enrichment job crashed for %s: %s", session_id, e, exc_info=True)
            await db_service.mark_session_enrichment_job_failed(session_id, str(e))

