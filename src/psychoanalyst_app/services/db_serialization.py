"""
Shared helpers for serializing and deserializing DB JSON columns.
"""

from __future__ import annotations

import json
from typing import Any, Sequence, TypeVar

from psychoanalyst_app.models.data_models import (
    DetailedSession,
    Message,
    PatientAnalysisVersion,
    Session,
    TherapyPlan,
    Topic,
)

T = TypeVar("T")


def dump_messages(messages: Sequence[Message]) -> str:
    return json.dumps([message.model_dump(mode="json") for message in messages])


def load_messages(payload: str | None) -> list[Message]:
    if not payload:
        return []
    data = json.loads(payload)
    return [Message.model_validate(item) for item in data]


def dump_topics(topics: Sequence[Topic]) -> str:
    return json.dumps([topic.model_dump(mode="json") for topic in topics])


def load_topics(payload: str | None) -> list[Topic]:
    if not payload:
        return []
    data = json.loads(payload)
    return [Topic.model_validate(item) for item in data]


def dump_json(value: Any) -> str:
    return json.dumps(value)


def load_json(payload: str | None, *, default: T) -> T:
    if not payload:
        return default
    return json.loads(payload)


SESSION_COLUMNS = (
    "session_id, user_id, timestamp, transcript, topics, "
    "psychological_summary, dominant_affects, key_themes, "
    "notable_interactions, interpretations, patient_reactions, enriched"
)

THERAPY_PLAN_COLUMNS = (
    "plan_id, user_id, created_at, updated_at, plan_details, initial_goals, "
    "current_progress, planned_interventions, status, version, "
    "selected_therapy_style, session_briefing"
)

PATIENT_ANALYSIS_COLUMNS = (
    "analysis_id, user_id, version, analysis_data, created_at, "
    "created_by_session, change_summary, superseded_by"
)


def session_from_row(
    row,
    iso_to_datetime,
    *,
    model_cls: type[Session] = Session,
) -> Session:
    transcript = load_messages(row["transcript"])
    topics = load_topics(row["topics"])
    return model_cls(
        session_id=row["session_id"],
        user_id=row["user_id"],
        timestamp=iso_to_datetime(row["timestamp"]),
        transcript=transcript,
        topics=topics,
        psychological_summary=row["psychological_summary"],
        dominant_affects=load_json(row["dominant_affects"], default=[]),
        key_themes=load_json(row["key_themes"], default=[]),
        notable_interactions=row["notable_interactions"],
        interpretations=row["interpretations"],
        patient_reactions=row["patient_reactions"],
        enriched=bool(row["enriched"]),
    )


def detailed_session_from_row(row, iso_to_datetime) -> DetailedSession:
    return session_from_row(row, iso_to_datetime, model_cls=DetailedSession)


def therapy_plan_from_row(row, iso_to_datetime) -> TherapyPlan:
    plan_details_data = load_json(row["plan_details"], default={})
    initial_goals = load_json(row["initial_goals"], default=[])
    planned_interventions = load_json(row["planned_interventions"], default=[])
    session_briefing = load_json(row["session_briefing"], default=None)
    status = row["status"] or "active"
    return TherapyPlan(
        plan_id=row["plan_id"],
        user_id=row["user_id"],
        created_at=iso_to_datetime(row["created_at"]),
        updated_at=iso_to_datetime(row["updated_at"]),
        plan_details=plan_details_data,
        initial_goals=initial_goals,
        current_progress=row["current_progress"] or "",
        planned_interventions=planned_interventions,
        status=status,
        version=row["version"],
        selected_therapy_style=row["selected_therapy_style"],
        session_briefing=session_briefing,
    )


def analysis_version_from_row(row, iso_to_datetime) -> PatientAnalysisVersion:
    analysis_data = load_json(row["analysis_data"], default={})
    return PatientAnalysisVersion(
        analysis_id=row["analysis_id"],
        user_id=row["user_id"],
        version=row["version"],
        analysis_data=analysis_data,
        created_at=iso_to_datetime(row["created_at"]),
        created_by_session=row["created_by_session"],
        change_summary=row["change_summary"],
        superseded_by=row["superseded_by"],
    )
