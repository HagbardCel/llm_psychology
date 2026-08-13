"""Deterministic therapy context assembly."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from jung.domain.models import Message
from jung.domain.session_artifacts import SessionBriefing
from jung.domain.text import normalize_content
from jung.llm.prompt_context import serialize_context_json
from jung.phases.context_bounds import bounded_text
from jung.phases.context_projection import (
    ProjectionBudgetError,
    compact_session_briefing,
    enrich_plan_projection,
    minimal_plan_projection,
    pack_grounded_patient_messages,
    pack_transcript_turns,
    project_primary_language,
)
from jung.phases.therapy.models import TherapyTurnInput
from jung.phases.transcript import TranscriptTurn


@dataclass(frozen=True, slots=True)
class HistoricalTranscriptSource:
    """Deduplicated, optionally capped transcript candidates for packing."""

    candidates: tuple[TranscriptTurn, ...]
    total_after_deduplication: int
    pre_omitted: int


def prepare_historical_transcript(
    input: TherapyTurnInput,
    *,
    include_current_message: bool,
) -> HistoricalTranscriptSource:
    """Prepare historical transcript candidates with pre-cap omission math.

    Order: full transcript → remove separately represented current message →
    establish source total → retain newest max_transcript_turns candidates.
    """
    turns = list(input.transcript)
    latest = input.latest_user_message if include_current_message else None
    if turns and latest and turns[-1].role == "user":
        final_content = normalize_content(turns[-1].content)
        if final_content == normalize_content(latest):
            turns = turns[:-1]
    total_after_deduplication = len(turns)
    cap = input.context_limits.max_transcript_turns
    candidates = tuple(turns[-cap:])
    pre_omitted = total_after_deduplication - len(candidates)
    return HistoricalTranscriptSource(
        candidates=candidates,
        total_after_deduplication=total_after_deduplication,
        pre_omitted=pre_omitted,
    )


def _pack_historical_transcript(
    historical: dict[str, object],
    source: HistoricalTranscriptSource,
    *,
    historical_limit: int,
) -> None:
    if source.total_after_deduplication == 0:
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
            source.candidates,
            fits=transcript_fits,
            require_two_roles=False,
            omitted_base=source.pre_omitted,
        )
    except ProjectionBudgetError as exc:
        raise ValueError(
            "therapy transcript omission projection exceeds the "
            f"{historical_limit}-character historical context limit"
        ) from exc
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


def _pack_historical_grounded_messages(
    historical: dict[str, object],
    messages: Sequence[Message],
    *,
    historical_limit: int,
) -> None:
    def profile_fits(profile_doc: dict[str, object]) -> bool:
        candidate = dict(historical)
        # Temporary prompt-document key until Phase 7D redesigns packing.
        candidate["derived_profile"] = profile_doc
        return len(serialize_context_json(candidate)) <= historical_limit

    packed = pack_grounded_patient_messages(
        messages,
        fits=profile_fits,
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

    Historical packing priority (intentional product policy):
    mandatory transcript omission marker → richest fitting plan →
    actual transcript content. Plan detail may omit every historical turn
    while the omission marker remains; the current patient message stays exempt.
    """
    limits = input.context_limits
    historical_limit = limits.max_historical_context_chars

    transcript_source = prepare_historical_transcript(
        input,
        include_current_message=include_current_message,
    )
    mandatory_transcript: dict[str, object] = {}
    if transcript_source.total_after_deduplication:
        mandatory_transcript = {
            "active_session_transcript": [],
            "active_session_transcript_turns_omitted": (
                transcript_source.total_after_deduplication
            ),
        }

    minimal_plan = minimal_plan_projection(input.current_plan)

    def plan_fits(plan_doc: dict[str, object]) -> bool:
        if len(serialize_context_json(plan_doc)) > limits.max_plan_context_chars:
            return False
        candidate = {"current_plan": plan_doc, **mandatory_transcript}
        return len(serialize_context_json(candidate)) <= historical_limit

    if not plan_fits(minimal_plan):
        raise ValueError(
            "therapy minimal plan and transcript marker exceed the "
            f"{historical_limit}-character historical context limit"
        )

    # Prefer richest plan that still leaves room for the mandatory transcript
    # omission marker; transcript *content* is packed afterward and may be empty.
    plan = enrich_plan_projection(
        input.current_plan,
        baseline=minimal_plan,
        fits=plan_fits,
    )
    historical: dict[str, object] = {"current_plan": plan, **mandatory_transcript}

    _pack_historical_transcript(
        historical,
        transcript_source,
        historical_limit=historical_limit,
    )
    if input.latest_supervisor_briefing is not None:
        _pack_historical_briefing(
            historical,
            input.latest_supervisor_briefing,
            historical_limit=historical_limit,
        )
    if input.grounded_patient_messages:
        _pack_historical_grounded_messages(
            historical,
            input.grounded_patient_messages,
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
