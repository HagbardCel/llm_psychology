"""Deterministic post-session analysis context assembly."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from jung.domain.models import Message
from jung.domain.session_artifacts import SessionBriefing, SessionReview
from jung.llm.prompt_context import rendered_context_user_message_length
from jung.phases.context_projection import (
    ProjectionBudgetError,
    enrich_plan_projection,
    enrich_session_briefing_projection,
    minimal_plan_projection,
    minimal_session_briefing_projection,
    pack_grounded_patient_messages,
    pack_prior_session_reviews,
    pack_transcript_turns,
)
from jung.phases.post_session.models import PostSessionInput

_ANALYSIS_TASK = (
    "Analyze the completed session. For each intervention citation, "
    "include therapist_sequence. For a patient response, also include "
    "patient_sequence from a later user turn. Cite patient turns with "
    "patient_sequence only. Cite only sequences present in the transcript "
    "projection."
)


def analysis_task() -> str:
    return _ANALYSIS_TASK


def _with_longitudinal_context(
    document: dict[str, object],
    longitudinal_context: Mapping[str, object],
) -> dict[str, object]:
    candidate = dict(document)
    merged = dict(candidate.get("longitudinal_context", {}))  # type: ignore[arg-type]
    merged.update(longitudinal_context)
    candidate["longitudinal_context"] = merged
    return candidate


def _pack_optional_longitudinal(
    document: dict[str, object],
    *,
    fits: Callable[[dict[str, object]], bool],
    packer: Callable[[Callable[[dict[str, object]], bool]], dict[str, object] | None],
) -> dict[str, object]:
    packed = packer(
        lambda packed_doc: fits(_with_longitudinal_context(document, packed_doc))
    )
    if packed is None:
        return document
    return _with_longitudinal_context(document, packed)


def _baseline_longitudinal_briefing(
    briefing: SessionBriefing,
    *,
    minimal_plan: dict[str, object],
    mandatory_completed_session: dict[str, object],
    message_fits: Callable[[Mapping[str, object]], bool],
    therapy_style: str,
) -> dict[str, object]:
    longitudinal: dict[str, object] = {}
    minimal_briefing = minimal_session_briefing_projection(briefing)

    def baseline_document(
        longitudinal_context: dict[str, object] | None = None,
    ) -> dict[str, object]:
        document: dict[str, object] = {
            "completed_session": mandatory_completed_session,
            "current_plan": minimal_plan,
            "therapy_style": therapy_style,
        }
        if longitudinal_context is not None:
            document["longitudinal_context"] = longitudinal_context
        return document

    candidate = baseline_document(
        longitudinal_context={
            **longitudinal,
            "latest_supervisor_briefing": minimal_briefing,
        }
    )
    if message_fits(candidate):
        longitudinal["latest_supervisor_briefing"] = minimal_briefing
    return longitudinal


def build_analysis_document(
    input: PostSessionInput,
    *,
    limit: int,
    task: str = _ANALYSIS_TASK,
) -> tuple[dict[str, object], frozenset[int]]:
    """Build the analysis user document and visible transcript sequences."""

    def message_fits(document: Mapping[str, object]) -> bool:
        return rendered_context_user_message_length(document, task=task) <= limit

    minimal_plan = minimal_plan_projection(input.current_plan)
    mandatory_completed_session: dict[str, object] = {
        "transcript": [],
        "transcript_turns_omitted": len(input.transcript),
    }
    therapy_style = input.selected_style.name
    briefing = input.prior_reviews[-1].briefing if input.prior_reviews else None

    def baseline_document(
        *,
        current_plan: dict[str, object],
        completed_session: dict[str, object],
        longitudinal_context: dict[str, object] | None = None,
    ) -> dict[str, object]:
        document: dict[str, object] = {
            "completed_session": completed_session,
            "current_plan": current_plan,
            "therapy_style": therapy_style,
        }
        if longitudinal_context is not None:
            document["longitudinal_context"] = longitudinal_context
        return document

    longitudinal: dict[str, object] = {}
    if briefing is not None:
        longitudinal = _baseline_longitudinal_briefing(
            briefing,
            minimal_plan=minimal_plan,
            mandatory_completed_session=mandatory_completed_session,
            message_fits=message_fits,
            therapy_style=therapy_style,
        )

    baseline = baseline_document(
        current_plan=minimal_plan,
        completed_session=mandatory_completed_session,
        longitudinal_context=longitudinal or None,
    )
    if not message_fits(baseline):
        raise ValueError(
            "post-session analysis minimal plan and transcript marker exceed the "
            f"{limit}-character user-message limit"
        )

    def transcript_fits(transcript_doc: dict[str, object]) -> bool:
        candidate = baseline_document(
            current_plan=minimal_plan,
            completed_session={
                "transcript": transcript_doc["transcript"],
                "transcript_turns_omitted": transcript_doc["transcript_turns_omitted"],
            },
            longitudinal_context=longitudinal or None,
        )
        return message_fits(candidate)

    try:
        packed_transcript = pack_transcript_turns(
            input.transcript,
            fits=transcript_fits,
            require_two_roles=True,
        )
    except ProjectionBudgetError as exc:
        raise ValueError(
            "post-session analysis cannot fit a two-role transcript projection "
            f"within the {limit}-character user-message limit"
        ) from exc

    document = baseline_document(
        current_plan=minimal_plan,
        completed_session={
            "transcript": packed_transcript.document["transcript"],
            "transcript_turns_omitted": packed_transcript.document[
                "transcript_turns_omitted"
            ],
        },
        longitudinal_context=longitudinal or None,
    )

    def plan_fits(plan_doc: dict[str, object]) -> bool:
        candidate = dict(document)
        candidate["current_plan"] = plan_doc
        return message_fits(candidate)

    document["current_plan"] = enrich_plan_projection(
        input.current_plan,
        baseline=document["current_plan"],  # type: ignore[arg-type]
        fits=plan_fits,
    )

    if briefing is not None and "latest_supervisor_briefing" in longitudinal:
        document = _pack_optional_longitudinal(
            document,
            fits=message_fits,
            packer=lambda fits: _enrich_briefing_packed(briefing, longitudinal, fits),
        )

    if input.grounded_patient_messages:
        document = _pack_optional_longitudinal(
            document,
            fits=message_fits,
            packer=lambda fits: _pack_grounded(input.grounded_patient_messages, fits),
        )

    if input.prior_reviews:
        document = _pack_optional_longitudinal(
            document,
            fits=message_fits,
            packer=lambda fits: _pack_reviews(input.prior_reviews, fits),
        )

    if not message_fits(document):
        raise ValueError(
            "post-session analysis user message exceeds the "
            f"{limit}-character user-message limit"
        )

    visible = frozenset(
        int(item["sequence"])  # type: ignore[index, call-overload]
        for item in document["completed_session"]["transcript"]  # type: ignore[index, union-attr]
    )
    return document, visible


def _enrich_briefing_packed(
    briefing: SessionBriefing,
    longitudinal: dict[str, object],
    fits: Callable[[dict[str, object]], bool],
) -> dict[str, object] | None:
    enriched = enrich_session_briefing_projection(
        briefing,
        baseline=longitudinal["latest_supervisor_briefing"],  # type: ignore[arg-type]
        fits=fits,
    )
    return {"latest_supervisor_briefing": enriched}


def _pack_grounded(
    messages: tuple[Message, ...],
    fits: Callable[[dict[str, object]], bool],
) -> dict[str, object] | None:
    packed = pack_grounded_patient_messages(messages, fits=fits)
    return packed.document if packed is not None else None


def _pack_reviews(
    reviews: tuple[SessionReview, ...],
    fits: Callable[[dict[str, object]], bool],
) -> dict[str, object] | None:
    packed = pack_prior_session_reviews(reviews, fits=fits)
    return packed.document if packed is not None else None
