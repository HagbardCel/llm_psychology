"""Persistence helpers tailored for the reflection agent."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psychoanalyst_app.models.data_models import PatientAnalysisVersion, Session, TherapyPlan
from psychoanalyst_app.services.trio_db_service import TrioDatabaseService


@dataclass(slots=True)
class ReflectionPersistenceService:
    """Coordinates DB writes required by the reflection agent."""

    db_service: TrioDatabaseService

    async def apply_tier2_enrichment(
        self, session: Session, tier2_data: dict[str, Any]
    ) -> bool:
        """Persist Tier 2 enrichment and update the in-memory session."""
        success = await self.db_service.update_session_tier2(
            session.session_id, tier2_data
        )
        if not success:
            return False

        session.psychological_summary = tier2_data.get("psychological_summary")
        session.dominant_affects = tier2_data.get("dominant_affects", [])
        session.key_themes = tier2_data.get("key_themes", [])
        session.notable_interactions = tier2_data.get("notable_interactions")
        session.interpretations = tier2_data.get("interpretations")
        session.patient_reactions = tier2_data.get("patient_reactions")
        session.enriched = True
        return True

    async def save_therapy_plan(self, plan: TherapyPlan) -> bool:
        """Persist the updated therapy plan (including briefing data)."""
        plan.updated_at = datetime.now()
        return await self.db_service.save_therapy_plan(plan)

    async def get_latest_analysis(
        self, user_id: str
    ) -> PatientAnalysisVersion | None:
        return await self.db_service.get_latest_patient_analysis(user_id)

    async def save_analysis_next_version_and_supersede(
        self,
        *,
        analysis_id: str,
        user_id: str,
        analysis_data: Any,
        created_at: datetime,
        created_by_session: str | None,
        change_summary: str | None,
        supersede_analysis_id: str,
    ) -> PatientAnalysisVersion | None:
        return await self.db_service.save_patient_analysis_next_version_and_supersede(
            analysis_id=analysis_id,
            user_id=user_id,
            analysis_data=analysis_data,
            created_at=created_at,
            created_by_session=created_by_session,
            change_summary=change_summary,
            supersede_analysis_id=supersede_analysis_id,
        )

    async def save_analysis_version_and_supersede(
        self, analysis: PatientAnalysisVersion, supersede_analysis_id: str
    ) -> bool:
        return await self.db_service.save_patient_analysis_version_and_supersede(
            analysis, supersede_analysis_id
        )

    async def save_analysis_version(
        self, analysis: PatientAnalysisVersion
    ) -> bool:
        return await self.db_service.save_patient_analysis_version(analysis)

    async def mark_analysis_superseded(
        self, old_analysis_id: str, new_analysis_id: str
    ) -> bool:
        return await self.db_service.mark_analysis_superseded(
            old_analysis_id, new_analysis_id
        )
