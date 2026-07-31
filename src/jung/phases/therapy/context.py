"""Deterministic therapy context assembly."""

from __future__ import annotations

from collections.abc import Sequence

from jung.domain.grounding import GroundedPatientTurn, parse_grounded_patient_turns
from jung.domain.session_artifacts import SessionBriefing, parse_session_briefing
from jung.llm.prompt_context import serialize_context_json
from jung.phases.context_bounds import bounded_text
from jung.phases.context_projection import (
    compact_plan_document,
    compact_session_briefing,
    pack_grounded_profile_turns,
    pack_transcript_turns,
    project_primary_language,
    transcript_turn_payload,
)
from jung.phases.therapy.models import TherapyTurnInput
from jung.phases.transcript import TranscriptTurn, normalize_transcript_content


def _historical_transcript_source(
    input: TherapyTurnInput,
    *,
    include_current_message: bool,
) -> tuple[TranscriptTurn, ...]:
    """Transcript after intentional current-message deduplication."""
    turns = list(input.transcript[-input.context_limits.max_transcript_turns :])
    latest = input.latest_user_message if include_current_message else None
    if turns and latest and turns[-1].role == "user":
        final_content = normalize_transcript_content(turns[-1].content)
        if final_content == normalize_transcript_content(latest):
            turns = turns[:-1]
    return tuple(turns)


def _pack_historical_transcript(
    historical: dict[str, object],
    source_turns: Sequence[TranscriptTurn],
    *,
    historical_limit: int,
) -> None:
    if not source_turns:
        return

    def transcript_fits(transcript_doc: dict[str, object]) -> bool:
        candidate = dict(historical)
        candidate["active_session_transcript"] = transcript_doc["transcript"]
        candidate["active_session_transcript_turns_omitted"] = transcript_doc[
            "transcript_turns_omitted"
        ]
        return len(serialize_context_json(candidate)) <= historical_limit

    try:
        packed = pack_transcript_turns(
            source_turns,
            fits=transcript_fits,
            require_two_roles=False,
        )
    except ValueError:
        return
    historical["active_session_transcript"] = packed.document["transcript"]
    historical["active_session_transcript_turns_omitted"] = packed.document[
        "transcript_turns_omitted"
    ]


def _pack_historical_briefing(
    historical: dict[str, object],
    briefing: SessionBriefing,
    *,
    historical_limit: int,
) -> None:
    def briefing_fits(briefing_doc: dict[str, object]) -> bool:
        candidate = dict(historical)
        candidate["session_briefing"] = briefing_doc
        return len(serialize_context_json(candidate)) <= historical_limit

    packed = compact_session_briefing(briefing, fits=briefing_fits)
    if packed is not None:
        historical["session_briefing"] = packed.document


def _pack_historical_profile(
    historical: dict[str, object],
    turns: Sequence[GroundedPatientTurn],
    *,
    historical_limit: int,
) -> None:
    def profile_fits(profile_doc: dict[str, object]) -> bool:
        candidate = dict(historical)
        candidate["derived_profile"] = profile_doc
        return len(serialize_context_json(candidate)) <= historical_limit

    packed = pack_grounded_profile_turns(
        turns,
        fits=profile_fits,
        content_only=True,
    )
    if packed is not None:
        historical["derived_profile"] = packed.document


def _pack_historical_summaries(
    historical: dict[str, object],
    summaries: Sequence[str],
    *,
    historical_limit: int,
) -> None:
    selected: list[str] = []
    for summary in reversed(summaries):
        text = bounded_text(str(summary), 400)
        if not text.strip():
            continue
        candidate_list = [text, *selected]
        candidate = dict(historical)
        candidate["recent_session_summaries"] = candidate_list
        if len(serialize_context_json(candidate)) <= historical_limit:
            selected = candidate_list
            historical["recent_session_summaries"] = selected
        else:
            break


def build_untrusted_therapy_document(
    input: TherapyTurnInput,
    *,
    include_current_message: bool,
) -> dict[str, object]:
    """Build the untrusted JSON context for therapy prompts.

    The historical_context subtree is bounded by
    ``max_historical_context_chars``. Patient metadata, the current patient
    message, and the static task (rendered outside this document) are exempt.
    """
    limits = input.context_limits
    historical_limit = limits.max_historical_context_chars

    grounded_turns = ()
    if input.derived_profile is not None:
        grounded_turns = parse_grounded_patient_turns(input.derived_profile)
    briefing = None
    if input.session_briefing is not None:
        briefing = parse_session_briefing(input.session_briefing)

    plan = compact_plan_document(
        input.current_plan,
        limit=min(limits.max_section_chars, historical_limit),
    )
    historical: dict[str, object] = {"current_plan": plan}
    if len(serialize_context_json(historical)) > historical_limit:
        length = len(serialize_context_json(historical))
        raise ValueError(
            "therapy minimal historical context exceeds budget: "
            f"{length} > {historical_limit}"
        )

    _pack_historical_transcript(
        historical,
        _historical_transcript_source(
            input,
            include_current_message=include_current_message,
        ),
        historical_limit=historical_limit,
    )
    if briefing is not None:
        _pack_historical_briefing(
            historical,
            briefing,
            historical_limit=historical_limit,
        )
    if input.derived_profile is not None:
        _pack_historical_profile(
            historical,
            grounded_turns,
            historical_limit=historical_limit,
        )
    if input.recent_session_summaries:
        _pack_historical_summaries(
            historical,
            input.recent_session_summaries,
            historical_limit=historical_limit,
        )

    final_historical_len = len(serialize_context_json(historical))
    if final_historical_len > historical_limit:
        raise ValueError(
            "therapy historical context exceeds budget: "
            f"{final_historical_len} > {historical_limit}"
        )

    document: dict[str, object] = {"historical_context": historical}
    language = project_primary_language(input.profile.primary_language)
    if language is not None:
        document["patient_metadata"] = {"primary_language": language}
    if include_current_message and input.latest_user_message:
        document["current_patient_message"] = input.latest_user_message
    return document


def project_transcript_atoms(
    turns: Sequence[TranscriptTurn],
) -> list[dict[str, object]]:
    return [transcript_turn_payload(turn) for turn in turns]
