"""
Shared helpers for serializing and deserializing DB JSON columns.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, TypeVar

from psychoanalyst_app.models.domain import (
    Message,
    PatientAnalysisVersion,
    Session,
    TherapyPlan,
    Topic,
)
from psychoanalyst_app.models.intake_record import IntakeRecord

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


def dump_intake_record(record: IntakeRecord | None) -> str | None:
    if record is None:
        return None
    return dump_json(record.model_dump(mode="json"))


def load_intake_record(payload: str | None) -> IntakeRecord | None:
    if payload is None:
        return None
    return IntakeRecord.model_validate(json.loads(payload))


SESSION_COLUMNS = (
    "session_id, user_id, session_type, plan_id, timestamp, transcript, topics, "
    "session_summary, session_briefing, intake_record, intake_record_updated_at, "
    "psychological_summary, "
    "dominant_affects, key_themes, notable_interactions, "
    "interpretations, patient_reactions, enriched"
)

THERAPY_PLAN_COLUMNS = (
    "plan_id, user_id, created_at, updated_at, focus, themes, timeline, initial_goals, "
    "current_progress, planned_interventions, status, version, "
    "selected_therapy_style, session_briefing, supersedes_plan_id, "
    "superseded_by_plan_id, revision_recommendations"
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
        session_type=row["session_type"],
        plan_id=row["plan_id"],
        timestamp=iso_to_datetime(row["timestamp"]),
        transcript=transcript,
        topics=topics,
        session_summary=row["session_summary"],
        session_briefing=load_json(row["session_briefing"], default=None),
        intake_record=load_intake_record(row["intake_record"]),
        intake_record_updated_at=(
            iso_to_datetime(row["intake_record_updated_at"])
            if row["intake_record_updated_at"]
            else None
        ),
        psychological_summary=row["psychological_summary"],
        dominant_affects=load_json(row["dominant_affects"], default=[]),
        key_themes=load_json(row["key_themes"], default=[]),
        notable_interactions=row["notable_interactions"],
        interpretations=row["interpretations"],
        patient_reactions=row["patient_reactions"],
        enriched=bool(row["enriched"]),
    )


def therapy_plan_from_row(row, iso_to_datetime) -> TherapyPlan:
    themes = load_json(row["themes"], default=[])
    initial_goals = load_json(row["initial_goals"], default=[])
    planned_interventions = load_json(row["planned_interventions"], default=[])
    session_briefing = load_json(row["session_briefing"], default=None)
    status = row["status"] or "active"
    return TherapyPlan(
        plan_id=row["plan_id"],
        user_id=row["user_id"],
        created_at=iso_to_datetime(row["created_at"]),
        updated_at=iso_to_datetime(row["updated_at"]),
        focus=row["focus"],
        themes=themes,
        timeline=row["timeline"],
        initial_goals=initial_goals,
        current_progress=row["current_progress"] or "",
        planned_interventions=planned_interventions,
        status=status,
        version=row["version"],
        supersedes_plan_id=row["supersedes_plan_id"],
        superseded_by_plan_id=row["superseded_by_plan_id"],
        selected_therapy_style=row["selected_therapy_style"],
        session_briefing=session_briefing,
        revision_recommendations=load_json(row["revision_recommendations"], default=[]),
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
