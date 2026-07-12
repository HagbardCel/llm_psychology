"""Assessment phase processor."""

from __future__ import annotations

from jung.llm.gateway import LLMGateway, ModelPolicy
from jung.phases.assessment.models import AssessmentInput, AssessmentResult
from jung.phases.assessment.prompts import build_assessment_messages
from jung.phases.assessment.validation import validate_and_normalize_assessment


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
        available_ids = tuple(style.id for style in input.available_styles)
        return await self._gateway.generate_structured(
            build_assessment_messages(input),
            AssessmentResult,
            self._assessment_policy,
            validate_result=lambda result: validate_and_normalize_assessment(
                result,
                available_ids,
            ),
        )
