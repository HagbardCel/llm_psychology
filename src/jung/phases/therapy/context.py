"""Deterministic therapy context assembly."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from jung.domain.models import Message
from jung.domain.text import normalize_content
from jung.llm.prompt_context import serialize_context_json
from jung.phases.context_projection import (
    ProjectionBudgetError,
    enrich_plan_projection,
    enrich_session_briefing_projection,
    minimal_plan_projection,
    minimal_session_briefing_projection,
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


def _pack_historical_grounded_messages(
    historical: dict[str, object],
    messages: Sequence[Message],
    *,
    historical_limit: int,
) -> None:
    def grounded_fits(grounded_doc: dict[str, object]) -> bool:
        candidate = dict(historical)
        candidate.update(grounded_doc)
        return len(serialize_context_json(candidate)) <= historical_limit

    packed = pack_grounded_patient_messages(
        messages,
        fits=grounded_fits,
    )
    if packed is not None:
        historical.update(packed.document)


def build_untrusted_therapy_document(
    input: TherapyTurnInput,
    *,
    include_current_message: bool,
) -> dict[str, object]:
    """Build the untrusted JSON context for therapy prompts.

    The historical_context subtree is bounded by
    ``max_historical_context_chars``. Patient metadata, the current patient
    message, and the static task (rendered outside this document) are exempt.

    Mandatory baseline:
    - minimal current plan
    - transcript omission marker when applicable
    - minimal latest supervisor briefing when one exists and it fits alongside
      the mandatory baseline; otherwise omit the briefing

    Priority packing (never evict a selected live-transcript turn):
    1. newest complete active-session transcript turns
    2. enrich latest supervisor briefing without evicting transcript
    3. enrich current plan without evicting transcript/briefing
    4. newest fitting grounded patient turns
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

    def baseline_fits(historical: Mapping[str, object]) -> bool:
        return len(serialize_context_json(historical)) <= historical_limit

    def plan_fits_in_baseline(plan_doc: dict[str, object]) -> bool:
        if len(serialize_context_json(plan_doc)) > limits.max_plan_context_chars:
            return False
        candidate: dict[str, object] = {
            "current_plan": plan_doc,
            **mandatory_transcript,
        }
        briefing = input.latest_supervisor_briefing
        if briefing is not None:
            minimal_briefing = minimal_session_briefing_projection(briefing)

            def briefing_fits(briefing_doc: dict[str, object]) -> bool:
                with_briefing = dict(candidate)
                with_briefing["latest_supervisor_briefing"] = briefing_doc
                return baseline_fits(with_briefing)

            if briefing_fits(minimal_briefing):
                candidate["latest_supervisor_briefing"] = minimal_briefing
        return baseline_fits(candidate)

    if not plan_fits_in_baseline(minimal_plan):
        raise ValueError(
            "therapy minimal plan and transcript marker exceed the "
            f"{historical_limit}-character historical context limit"
        )

    historical: dict[str, object] = {
        "current_plan": minimal_plan,
        **mandatory_transcript,
    }
    briefing = input.latest_supervisor_briefing
    if briefing is not None:
        minimal_briefing = minimal_session_briefing_projection(briefing)

        def baseline_briefing_fits(briefing_doc: dict[str, object]) -> bool:
            candidate = dict(historical)
            candidate["latest_supervisor_briefing"] = briefing_doc
            return baseline_fits(candidate)

        if baseline_briefing_fits(minimal_briefing):
            historical["latest_supervisor_briefing"] = minimal_briefing

    _pack_historical_transcript(
        historical,
        transcript_source,
        historical_limit=historical_limit,
    )

    if briefing is not None and "latest_supervisor_briefing" in historical:

        def briefing_fits(briefing_doc: dict[str, object]) -> bool:
            candidate = dict(historical)
            candidate["latest_supervisor_briefing"] = briefing_doc
            return baseline_fits(candidate)

        historical["latest_supervisor_briefing"] = enrich_session_briefing_projection(
            briefing,
            baseline=historical["latest_supervisor_briefing"],  # type: ignore[arg-type]
            fits=briefing_fits,
        )

    def plan_fits(plan_doc: dict[str, object]) -> bool:
        if len(serialize_context_json(plan_doc)) > limits.max_plan_context_chars:
            return False
        candidate = dict(historical)
        candidate["current_plan"] = plan_doc
        return baseline_fits(candidate)

    historical["current_plan"] = enrich_plan_projection(
        input.current_plan,
        baseline=historical["current_plan"],  # type: ignore[arg-type]
        fits=plan_fits,
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
