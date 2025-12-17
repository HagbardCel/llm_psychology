from __future__ import annotations

from datetime import datetime
from typing import Any


class DeterministicLLMService:
    """
    Deterministic, no-network LLM service replacement.

    Implements the subset of the production LLMService interface used by agents
    and orchestration so the backend can run in CI/E2E without API keys.
    """

    def generate_response(self, prompt: str, context: list[dict[str, str]] | None = None) -> str:
        prompt_preview = (prompt or "").strip().replace("\n", " ")[:80]
        return f"[deterministic-llm] {prompt_preview}"

    async def generate_response_stream(
        self, prompt: str, context: list[dict[str, str]] | None = None
    ) -> list[str]:
        text = self.generate_response(prompt, context)
        # Chunk deterministically to exercise streaming paths.
        return [text[:20], text[20:40], text[40:]]

    async def generate_response_async(
        self, prompt: str, context: list[dict[str, str]] | None = None
    ) -> str:
        return self.generate_response(prompt, context)

    def generate_structured_output(
        self,
        prompt: str,
        schema: dict | type["BaseModel"],
        *,
        method: str = "json_schema",
    ) -> Any:
        # Imported lazily to keep this module lightweight.
        from pydantic import BaseModel

        if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
            return {}

        payload = self._structured_payload(prompt, schema)
        return schema.model_validate(payload)

    async def generate_structured_output_async(
        self,
        prompt: str,
        schema: dict | type["BaseModel"],
        *,
        method: str = "json_schema",
    ) -> Any:
        return self.generate_structured_output(prompt, schema, method=method)

    def _structured_payload(self, prompt: str, schema: type["BaseModel"]) -> dict[str, Any]:
        schema_name = getattr(schema, "__name__", "")
        prompt_lower = (prompt or "").lower()

        if schema_name == "SessionAnalysis":
            return {
                "key_themes": ["anxiety", "work stress"],
                "emotional_state": "anxious",
                "insights": ["pattern recognition"],
                "progress_indicators": ["engagement"],
            }

        if schema_name == "Tier2Enrichment":
            return {
                "psychological_summary": "Deterministic summary",
                "dominant_affects": ["anxiety"],
                "key_themes": ["work stress"],
                "notable_interactions": None,
                "interpretations": None,
                "patient_reactions": None,
            }

        if schema_name == "PlanUpdate":
            return {
                "focus": "Anxiety management",
                "goals": "- Reduce anxiety\n- Improve sleep",
                "techniques": "- Cognitive restructuring\n- Mindfulness",
                "themes": "Anxiety, coping, work stress",
                "timeline": "12 weeks",
            }

        if schema_name == "PatientProfileExtract":
            alias = "Alex"
            if "sarah" in prompt_lower:
                alias = "Sarah"
            return {
                "basic_info": {
                    "alias": alias,
                    "date_of_birth": None,
                    "gender": None,
                    "cultural_background": None,
                    "primary_language": "English",
                },
                "family": {
                    "parents": None,
                    "siblings": None,
                    "family_atmosphere": None,
                    "significant_events": None,
                },
                "history": {
                    "education": None,
                    "work_history": None,
                    "relationship_to_work": None,
                },
                "context": {
                    "relationships": None,
                    "social_context": None,
                    "current_situation": None,
                },
                "frame": {
                    "preferred_school": None,
                    "session_mode": "virtual",
                    "boundary_notes": None,
                    "frame_notes": None,
                },
            }

        if schema_name == "PatientAnalysis":
            return {
                "current_focus": {
                    "theme": "Work-related anxiety",
                    "salience": "Patient reports anxiety escalating in professional settings",
                },
                "transference": {
                    "idealization": None,
                    "devaluation": None,
                    "boundaries": None,
                    "other_patterns": "Developing therapeutic alliance",
                },
                "narratives": [],
                "defenses": {
                    "primary_defenses": ["intellectualization"],
                    "defensive_style": "Cerebral",
                    "flexibility": "Moderate",
                },
                "orientation": {
                    "pacing": "Gradual",
                    "risk_areas": ["perfectionism"],
                    "key_questions": ["What triggers the anxiety?"],
                },
            }

        if schema_name == "Tier4Extract":
            return {
                "initial_goals": ["Reduce work-related anxiety"],
                "current_progress": "Baseline established",
                "planned_interventions": ["Supportive listening"],
                "status": "active",
            }

        if schema_name == "ChangeDetectionDecision":
            return {
                "update_needed": False,
                "change_summary": None,
                "confidence": "high",
            }

        if schema_name == "Tier1ProfilePatch":
            return {}

        if schema_name == "SessionBriefing":
            today = datetime.now()
            return {
                "briefing_type": "resumption",
                "generated_at": today.isoformat(),
                "session_count": 1,
                "last_session_id": "session_001",
                "last_session_date": today.date().isoformat(),
                "narrative_handoff": (
                    "Patient discussed work-related anxiety and stress. "
                    "We explored triggers, automatic thoughts, and early patterns. "
                    "Focus remains on building coping skills and insight."
                ),
                "patient_observations": "Patient was engaged and communicative.",
                "plan_progression_notes": "Session aligned with the current plan.",
                "relationship_quality": "developing",
                "continuity_points": ["Follow up on workplace triggers"],
                "emotional_summary": {
                    "last_session": "anxious but engaged",
                    "trend": "stable",
                    "note": "Anxiety levels steady; patient shows engagement.",
                },
                "key_themes": [
                    {
                        "theme": "work stress",
                        "status": "ongoing",
                        "priority": "high",
                        "frequency": 1,
                        "first_appearance": "session_001",
                        "last_discussed": "session_001",
                    }
                ],
                "progress_highlights": ["Identified trigger situations"],
                "unresolved_issues": ["Perfectionism"],
                "recommended_approach": {
                    "opening_tone": "Warm and supportive",
                    "opening_focus": "Check in on workplace anxiety",
                    "things_to_avoid": "Overwhelming with too many questions",
                    "suggested_questions": ["What stood out from last time?"],
                    "therapeutic_goals_for_session": ["Build on prior insights"],
                },
            }

        # Default: return an empty object and let validation reveal missing fields if any.
        return {}


class DeterministicRAGService:
    """Deterministic RAG service replacement (no FAISS/embeddings)."""

    def retrieve_relevant_knowledge(
        self, query: str, n_results: int = 3, filter_source: str | None = None
    ) -> list[dict[str, Any]]:
        source = filter_source or "deterministic.md"
        return [
            {
                "id": "chunk_0",
                "content": f"[deterministic-rag] {source}: {query}",
                "source": source,
                "distance": 0.0,
            }
        ]

    def get_knowledge_by_source(self, source: str) -> list[dict[str, Any]]:
        return [
            {
                "id": "chunk_0",
                "content": f"[deterministic-rag] {source}",
                "source": source,
            }
        ]

