"""Shared LLM-facing projections for plans, briefings, and transcripts."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise

from jung.domain.models import Message, Plan
from jung.domain.session_artifacts import SessionBriefing
from jung.domain.text import normalize_content
from jung.phases.context_bounds import bounded_text
from jung.phases.transcript import TranscriptTurn

_PRIMARY_LANGUAGE_PROJECTION_LIMIT = 80
_SUMMARY_BASELINE_CHARS = 400
_MIN_PLAN_TEXT_CHARS = 80
_MIN_PLAN_ITEM_CHARS = 80

_PLAN_LIST_FIELDS = (
    "themes",
    "goals",
    "planned_interventions",
    "revision_recommendations",
)
_REQUIRED_PLAN_LIST_FIELDS = frozenset({"goals", "planned_interventions"})
_PLAN_KEYS = frozenset(
    {
        "focus",
        "themes",
        "goals",
        "current_progress",
        "planned_interventions",
        "revision_recommendations",
    }
)


class ProjectionBudgetError(ValueError):
    """Raised when a projection cannot fit a caller-owned budget predicate."""


@dataclass(frozen=True, slots=True)
class PackedProjection:
    document: dict[str, object]
    omitted: int


def project_primary_language(value: str) -> str | None:
    """Return a bounded language label, or None when absent/oversized."""
    normalized = normalize_content(value)
    if not normalized or len(normalized) > _PRIMARY_LANGUAGE_PROJECTION_LIMIT:
        return None
    return normalized


def _compact_string_list(
    items: Sequence[str],
    *,
    max_items: int,
    max_item_chars: int,
    keep_at_least_one: bool,
) -> list[str]:
    selected = list(items[:max_items])
    compacted = [
        bounded_text(item, max_item_chars) for item in selected if item.strip()
    ]
    if keep_at_least_one and items and not compacted:
        compacted = [bounded_text(str(items[0]), max_item_chars)]
    return compacted


def minimal_plan_projection(plan: Plan) -> dict[str, object]:
    """Return the canonical smallest semantic projection.

    Preserves all plan keys; optional collections may be empty.
    """
    return {
        "focus": bounded_text(plan.focus, _MIN_PLAN_TEXT_CHARS),
        "themes": [],
        "goals": _compact_string_list(
            plan.goals,
            max_items=1,
            max_item_chars=_MIN_PLAN_ITEM_CHARS,
            keep_at_least_one=True,
        ),
        "current_progress": bounded_text(
            plan.current_progress,
            _MIN_PLAN_TEXT_CHARS,
        ),
        "planned_interventions": _compact_string_list(
            plan.planned_interventions,
            max_items=1,
            max_item_chars=_MIN_PLAN_ITEM_CHARS,
            keep_at_least_one=True,
        ),
        "revision_recommendations": [],
    }


def _iter_rich_plan_candidates(plan: Plan) -> Iterator[dict[str, object]]:
    """Yield progressively richer plan projections, richest first.

    Search order is ``max_items`` descending, then ``max_item_chars``
    descending. Consecutive identical candidates are skipped.
    """
    longest_list_len = max(
        (len(getattr(plan, field)) for field in _PLAN_LIST_FIELDS),
        default=0,
    )
    max_items_start = min(20, max(1, longest_list_len))
    previous: dict[str, object] | None = None
    for max_items in range(max_items_start, 0, -1):
        for max_item_chars in range(500, 20, -20):
            candidate: dict[str, object] = {
                "focus": bounded_text(plan.focus, max_item_chars),
                "current_progress": bounded_text(
                    plan.current_progress,
                    max_item_chars,
                ),
            }
            for field in _PLAN_LIST_FIELDS:
                candidate[field] = _compact_string_list(
                    getattr(plan, field),
                    max_items=max_items,
                    max_item_chars=max_item_chars,
                    keep_at_least_one=field in _REQUIRED_PLAN_LIST_FIELDS,
                )
            if candidate == previous:
                continue
            previous = candidate
            yield candidate


def enrich_plan_projection(
    plan: Plan,
    *,
    baseline: Mapping[str, object],
    fits: Callable[[dict[str, object]], bool],
) -> dict[str, object]:
    """Return the richest candidate fitting the caller's complete context.

    Precondition: ``fits(dict(baseline))`` is true.
    Returns ``baseline`` when no richer candidate fits.
    """
    baseline_doc = dict(baseline)
    if set(baseline_doc) != _PLAN_KEYS:
        raise ValueError(
            "plan enrichment baseline must expose canonical plan keys: "
            f"{sorted(_PLAN_KEYS)}"
        )
    if not fits(baseline_doc):
        raise ValueError("plan enrichment baseline must already fit")

    best = baseline_doc
    for candidate in _iter_rich_plan_candidates(plan):
        if fits(candidate):
            return candidate
    return best


def grounded_message_payload(message: Message) -> dict[str, object]:
    """Cross-session grounded-message projection is content-only."""
    return {"content": normalize_content(message.content)}


def transcript_turn_payload(turn: TranscriptTurn) -> dict[str, object]:
    return {
        "sequence": turn.sequence,
        "role": turn.role,
        "content": normalize_content(turn.content),
    }


def compact_summary(text: str, *, limit: int = _SUMMARY_BASELINE_CHARS) -> str:
    return bounded_text(normalize_content(text), limit)


def project_session_briefing(briefing: SessionBriefing) -> dict[str, object]:
    """Project a validated briefing's handoff fields."""
    return {
        "narrative_handoff": bounded_text(briefing.narrative_handoff, 400),
        "continuity_points": [
            bounded_text(item, 200)
            for item in briefing.continuity_points
            if item.strip()
        ],
        "unresolved_issues": [
            bounded_text(item, 200)
            for item in briefing.unresolved_issues
            if item.strip()
        ],
        "recommended_opening_focus": bounded_text(
            briefing.recommended_opening_focus, 400
        ),
        "things_to_avoid": [
            bounded_text(item, 200) for item in briefing.things_to_avoid if item.strip()
        ],
        "emotional_context": [
            bounded_text(item, 200)
            for item in briefing.emotional_context
            if item.strip()
        ],
    }


def compact_session_briefing(
    briefing: SessionBriefing,
    *,
    fits: Callable[[dict[str, object]], bool],
) -> PackedProjection | None:
    """Project briefing handoff fields under a caller-owned fitness predicate."""
    document = project_session_briefing(briefing)
    if not fits(document):
        return None
    return PackedProjection(document=document, omitted=0)


def _validate_transcript_sequences(source: Sequence[TranscriptTurn]) -> None:
    sequences = [turn.sequence for turn in source]
    if any(current >= following for current, following in pairwise(sequences)):
        raise ValueError(
            "transcript projection input must have unique, "
            "strictly increasing sequences"
        )


def pack_transcript_turns(
    turns: Sequence[TranscriptTurn],
    *,
    fits: Callable[[dict[str, object]], bool],
    require_two_roles: bool = False,
    omitted_base: int = 0,
) -> PackedProjection:
    """Pack complete transcript turns newest-first.

    When ``require_two_roles`` is true, seed with the newest fitting
    user/assistant pair, then add remaining turns newest-first.
    """
    if omitted_base < 0:
        raise ValueError("omitted_base must be non-negative")

    source = tuple(turns)
    _validate_transcript_sequences(source)

    def build_document(
        selected: Sequence[TranscriptTurn],
    ) -> dict[str, object]:
        return {
            "transcript": [transcript_turn_payload(turn) for turn in selected],
            "transcript_turns_omitted": (omitted_base + len(source) - len(selected)),
        }

    empty = build_document(())
    if not fits(empty):
        raise ProjectionBudgetError("empty transcript projection does not fit")

    if require_two_roles:
        nucleus: tuple[TranscriptTurn, TranscriptTurn] | None = None
        for newer_index in range(len(source) - 1, -1, -1):
            newer = source[newer_index]
            for older_index in range(newer_index - 1, -1, -1):
                older = source[older_index]
                if newer.role == older.role:
                    continue
                candidate = (older, newer)
                if fits(build_document(candidate)):
                    nucleus = candidate
                    break
            if nucleus is not None:
                break
        if nucleus is None:
            raise ProjectionBudgetError("no two-role transcript projection fits")

        selected_sequences = {turn.sequence for turn in nucleus}
        selected_reverse: list[TranscriptTurn] = list(reversed(nucleus))
        for turn in reversed(source):
            if turn.sequence in selected_sequences:
                continue
            candidate = tuple(reversed([*selected_reverse, turn]))
            if fits(build_document(candidate)):
                selected_reverse.append(turn)
                selected_sequences.add(turn.sequence)
        selected_tuple = tuple(sorted(selected_reverse, key=lambda item: item.sequence))
    else:
        selected_reverse = []
        for turn in reversed(source):
            candidate = tuple(reversed([*selected_reverse, turn]))
            if fits(build_document(candidate)):
                selected_reverse.append(turn)
        selected_tuple = tuple(reversed(selected_reverse))

    document = build_document(selected_tuple)
    return PackedProjection(
        document=document,
        omitted=int(document["transcript_turns_omitted"]),
    )


def pack_grounded_patient_messages(
    messages: Sequence[Message],
    *,
    fits: Callable[[dict[str, object]], bool],
) -> PackedProjection | None:
    """Pack grounded patient messages under a caller-owned fitness predicate.

    Emits the temporary prompt-document key ``grounded_patient_turns`` until
    Phase 7D redesigns the packing surface.
    """
    source = tuple(messages)
    total = len(source)

    def build_document(
        selected: Sequence[Message],
    ) -> dict[str, object]:
        return {
            "grounded_patient_turns": [
                grounded_message_payload(item) for item in selected
            ],
            "grounded_patient_turns_omitted": total - len(selected),
        }

    empty = build_document(())
    if not fits(empty):
        return None

    selected_reverse: list[Message] = []
    for item in reversed(source):
        candidate = tuple(reversed([*selected_reverse, item]))
        if fits(build_document(candidate)):
            selected_reverse.append(item)

    selected = tuple(reversed(selected_reverse))
    return PackedProjection(
        document=build_document(selected),
        omitted=total - len(selected),
    )
