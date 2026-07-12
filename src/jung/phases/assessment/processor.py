"""Assessment phase processor."""

from __future__ import annotations

from jung.llm.gateway import LLMGateway, ModelPolicy
from jung.phases.assessment.models import AssessmentInput, AssessmentResult
from jung.phases.assessment.prompts import build_assessment_messages


class AssessmentProcessor:
    def __init__(
        self,
        gateway: LLMGateway,
        *,
        assessment_policy: ModelPolicy,
    ) -> None:
        self._gateway = gateway
        self._assessment_policy = assessment_policy

    async def assess(self, input: AssessmentInput) -> AssessmentResult:
        raw = await self._gateway.generate_structured(
            build_assessment_messages(input),
            AssessmentResult,
            self._assessment_policy,
        )
        return normalize_assessment_result(raw, input)


def normalize_assessment_result(
    result: AssessmentResult,
    input: AssessmentInput,
) -> AssessmentResult:
    available_ids = [style.id for style in input.available_styles]
    by_id = {item.style_id: item for item in result.style_recommendations}
    if len(by_id) != len(result.style_recommendations):
        raise ValueError("duplicate style_id in assessment result")
    missing = [style_id for style_id in available_ids if style_id not in by_id]
    unknown = [style_id for style_id in by_id if style_id not in available_ids]
    if missing or unknown:
        raise ValueError("assessment result style coverage mismatch")

    ordered = tuple(
        by_id[style_id]
        for style_id in sorted(
            available_ids,
            key=lambda style_id: (
                -by_id[style_id].score,
                available_ids.index(style_id),
            ),
        )
    )
    return result.model_copy(update={"style_recommendations": ordered})
