"""Deterministic post-session analysis context assembly."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from jung.domain.models import Message
from jung.domain.session_artifacts import SessionReview
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


def build_analysis_document(
    input: PostSessionInput,
    *,
    limit: int,
    task: str,
) -> tuple[dict[str, object], frozenset[int]]:
    """Build the analysis user document and visible transcript sequences.

    Priority packing (never evict a selected current-session transcript turn):
    1. minimal current plan + empty completed-session transcript marker
    2. pack completed-session transcript (two-role nucleus required)
    3. enrich current plan without evicting transcript
    4. optional latest supervisor briefing (minimal then enrich)
    5. optional grounded patient turns
    6. optional prior supervisor reviews
    """

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

    baseline = baseline_document(
        current_plan=minimal_plan,
        completed_session=mandatory_completed_session,
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

    longitudinal: dict[str, object] = {}
    if briefing is not None:
        minimal_briefing = minimal_session_briefing_projection(briefing)

        def briefing_fits(briefing_doc: dict[str, object]) -> bool:
            candidate = dict(document)
            candidate["longitudinal_context"] = {
                **longitudinal,
                "latest_supervisor_briefing": briefing_doc,
            }
            return message_fits(candidate)

        if briefing_fits(minimal_briefing):
            longitudinal["latest_supervisor_briefing"] = (
                enrich_session_briefing_projection(
                    briefing,
                    baseline=minimal_briefing,
                    fits=briefing_fits,
                )
            )
            document["longitudinal_context"] = dict(longitudinal)

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
