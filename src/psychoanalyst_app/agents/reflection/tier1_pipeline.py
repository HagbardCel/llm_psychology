"""Tier 1 patient profile update pipeline helpers."""

from __future__ import annotations

import json
import logging
from typing import Any

from psychoanalyst_app.agents.reflection.prompts import (
    TIER1_CHANGE_DETECTION_PROMPT,
    TIER1_UPDATE_GENERATION_PROMPT,
)
from psychoanalyst_app.models.domain import Session, UserProfile
from psychoanalyst_app.models.llm_outputs import (
    ChangeDetectionDecision,
    StructuredUserProfileOutput,
    Tier1ProfilePatch,
)
from psychoanalyst_app.services.llm_service import LLMService
from psychoanalyst_app.services.llm_phases import (
    TIER1_PROFILE_CHANGE_DETECTION,
    TIER1_PROFILE_UPDATE,
)

logger = logging.getLogger(__name__)


async def maybe_update_tier1_profile(
    llm_service: LLMService,
    profile: UserProfile,
    session: Session,
) -> StructuredUserProfileOutput | None:
    """Run Tier 1 profile change detection/update pipeline."""
    try:
        if getattr(session, "enriched", False) and getattr(
            session, "psychological_summary", None
        ):
            session_summary = session.psychological_summary or ""
        else:
            session_summary = (
                f"Session {session.session_id} with {len(session.transcript)} messages"
            )

        current_profile_json = {
            "basic_info": {
                "alias": profile.alias,
                "date_of_birth": profile.date_of_birth,
                "gender": profile.gender,
                "cultural_background": profile.cultural_background,
                "primary_language": profile.primary_language,
            },
            "family": {
                "parents": profile.parents,
                "siblings": profile.siblings,
                "family_atmosphere": profile.family_atmosphere,
                "significant_events": profile.significant_events,
            },
            "history": {
                "education": profile.education,
                "work_history": profile.work_history,
                "relationship_to_work": profile.relationship_to_work,
            },
            "context": {
                "relationships": profile.relationships,
                "social_context": profile.social_context,
                "current_situation": profile.current_situation,
            },
            "frame": {
                "preferred_school": profile.preferred_school,
                "boundary_notes": profile.boundary_notes,
                "frame_notes": profile.frame_notes,
            },
        }

        detection_prompt = TIER1_CHANGE_DETECTION_PROMPT.format(
            current_profile_json=json.dumps(current_profile_json),
            session_summary=session_summary,
        )
        decision = await llm_service.generate_structured_output_async(
            detection_prompt,
            ChangeDetectionDecision,
            method="json_schema",
            phase=TIER1_PROFILE_CHANGE_DETECTION,
        )
        if not isinstance(decision, ChangeDetectionDecision):
            return None
        if not decision.update_needed:
            return None

        change_summary = decision.change_summary or ""
        update_prompt = TIER1_UPDATE_GENERATION_PROMPT.format(
            current_profile_json=json.dumps(current_profile_json),
            session_summary=session_summary,
            change_summary=change_summary,
        )
        patch = await llm_service.generate_structured_output_async(
            update_prompt,
            Tier1ProfilePatch,
            method="json_schema",
            phase=TIER1_PROFILE_UPDATE,
        )
        if not isinstance(patch, Tier1ProfilePatch):
            return None

        updates: dict[str, Any] = {}
        if patch.basic_info:
            info = patch.basic_info
            if info.alias is not None and info.alias.strip():
                updates["alias"] = info.alias
            if info.date_of_birth is not None:
                updates["date_of_birth"] = info.date_of_birth
            if info.gender is not None and info.gender.strip():
                updates["gender"] = info.gender
            if (
                info.cultural_background is not None
                and info.cultural_background.strip()
            ):
                updates["cultural_background"] = info.cultural_background
            if info.primary_language is not None and info.primary_language.strip():
                updates["primary_language"] = info.primary_language

        if patch.family:
            family = patch.family
            if family.parents is not None and family.parents.strip():
                updates["parents"] = family.parents
            if family.siblings is not None and family.siblings.strip():
                updates["siblings"] = family.siblings
            if (
                family.family_atmosphere is not None
                and family.family_atmosphere.strip()
            ):
                updates["family_atmosphere"] = family.family_atmosphere
            if (
                family.significant_events is not None
                and family.significant_events.strip()
            ):
                updates["significant_events"] = family.significant_events

        if patch.history:
            history = patch.history
            if history.education is not None and history.education.strip():
                updates["education"] = history.education
            if history.work_history is not None and history.work_history.strip():
                updates["work_history"] = history.work_history
            if (
                history.relationship_to_work is not None
                and history.relationship_to_work.strip()
            ):
                updates["relationship_to_work"] = history.relationship_to_work

        if patch.context:
            context_patch = patch.context
            if (
                context_patch.relationships is not None
                and context_patch.relationships.strip()
            ):
                updates["relationships"] = context_patch.relationships
            if (
                context_patch.social_context is not None
                and context_patch.social_context.strip()
            ):
                updates["social_context"] = context_patch.social_context
            if (
                context_patch.current_situation is not None
                and context_patch.current_situation.strip()
            ):
                updates["current_situation"] = context_patch.current_situation

        if patch.frame:
            frame = patch.frame
            if frame.preferred_school is not None and frame.preferred_school.strip():
                updates["preferred_school"] = frame.preferred_school
            if frame.boundary_notes is not None and frame.boundary_notes.strip():
                updates["boundary_notes"] = frame.boundary_notes
            if frame.frame_notes is not None and frame.frame_notes.strip():
                updates["frame_notes"] = frame.frame_notes

        if not updates:
            return None

        return StructuredUserProfileOutput.model_validate(updates)

    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Error updating Tier 1 profile: %s", exc, exc_info=True)
        return None
