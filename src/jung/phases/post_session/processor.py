"""Post-session phase processor."""

from __future__ import annotations

from jung.llm.gateway import LLMGateway, ModelPolicy
from jung.phases.post_session.models import (
    PostSessionInput,
    PostSessionResult,
    SessionAnalysisResult,
)
from jung.phases.post_session.prompts import (
    build_analysis_messages,
    build_update_messages,
)


class PostSessionProcessor:
    def __init__(
        self,
        gateway: LLMGateway,
        *,
        analysis_policy: ModelPolicy,
        update_policy: ModelPolicy,
    ) -> None:
        self._gateway = gateway
        self._analysis_policy = analysis_policy
        self._update_policy = update_policy

    async def process(self, input: PostSessionInput) -> PostSessionResult:
        analysis = await self._gateway.generate_structured(
            build_analysis_messages(input),
            SessionAnalysisResult,
            self._analysis_policy,
        )
        return await self._gateway.generate_structured(
            build_update_messages(input, analysis),
            PostSessionResult,
            self._update_policy,
        )
