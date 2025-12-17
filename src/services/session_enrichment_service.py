import logging

from models.structured_output_models import Tier2Enrichment
from prompts.reflection_prompts import TIER2_ENRICHMENT_PROMPT
from services.llm_service import LLMService
from services.trio_db_service import TrioDatabaseService

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

        transcript_lines: list[str] = []
        for msg in session.transcript:
            role = "Therapist" if msg.role == "assistant" else "Patient"
            transcript_lines.append(f"{role}: {msg.content}")

        enrichment_prompt = TIER2_ENRICHMENT_PROMPT.format(
            session_transcript="\n".join(transcript_lines)
        )

        tier2 = await self.llm_service.generate_structured_output_async(
            enrichment_prompt,
            Tier2Enrichment,
            method="json_schema",
        )
        if not isinstance(tier2, Tier2Enrichment):
            logger.error("Tier 2 enrichment returned unexpected type for %s", session_id)
            return False
        return await self.db_service.update_session_tier2(session_id, tier2.model_dump())
