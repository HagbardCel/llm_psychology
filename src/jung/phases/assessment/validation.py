"""Assessment result semantic validation and normalization."""

from __future__ import annotations

from jung.phases.assessment.models import AssessmentResult


def validate_exact_coverage(
    result: AssessmentResult,
    available_style_ids: tuple[str, ...],
) -> None:
    by_id = {item.style_id: item for item in result.style_recommendations}
    if len(by_id) != len(result.style_recommendations):
        raise ValueError("duplicate style_id in assessment result")
    missing = [style_id for style_id in available_style_ids if style_id not in by_id]
    unknown = [style_id for style_id in by_id if style_id not in available_style_ids]
    if missing or unknown:
        raise ValueError("assessment result style coverage mismatch")


def sort_by_score_then_catalog_order(
    result: AssessmentResult,
    available_style_ids: tuple[str, ...],
) -> AssessmentResult:
    by_id = {item.style_id: item for item in result.style_recommendations}
    ordered = tuple(
        by_id[style_id]
        for style_id in sorted(
            available_style_ids,
            key=lambda style_id: (
                -by_id[style_id].score,
                available_style_ids.index(style_id),
            ),
        )
    )
    return result.model_copy(update={"style_recommendations": ordered})


def validate_and_normalize_assessment(
    result: AssessmentResult,
    available_style_ids: tuple[str, ...],
) -> AssessmentResult:
    validate_exact_coverage(result, available_style_ids)
    return sort_by_score_then_catalog_order(result, available_style_ids)
