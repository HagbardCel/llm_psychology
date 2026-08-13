"""Post-session phase processor."""

from __future__ import annotations

from jung.domain.session_artifacts import (
    PlanPatch,
    SessionAnalysis,
    SessionBriefing,
    SessionReview,
    SessionReviewGeneration,
)
from jung.llm.gateway import LLMGateway, ModelPolicy
from jung.phases.post_session.evidence_validation import (
    resolve_session_analysis,
    validate_session_analysis,
)
from jung.phases.post_session.merge import validate_update_result
from jung.phases.post_session.models import (
    PostSessionInput,
    PostSessionResult,
    PostSessionUpdateResult,
    ResolvedSessionAnalysis,
)
from jung.phases.post_session.prompts import (
    ANALYSIS_PROMPT_VERSION,
    UPDATE_PROMPT_VERSION,
    build_analysis_request,
    build_update_messages,
)


def _has_conversational_content(input: PostSessionInput) -> bool:
    has_user = any(turn.role == "user" for turn in input.transcript)
    has_assistant = any(turn.role == "assistant" for turn in input.transcript)
    return has_user and has_assistant


def _minimal_session_result(input: PostSessionInput) -> PostSessionResult:
    has_user = any(turn.role == "user" for turn in input.transcript)
    has_assistant = any(turn.role == "assistant" for turn in input.transcript)

    if not has_user and not has_assistant:
        summary = "The session ended without conversational content."
        unresolved = (
            "No conversational content was available for post-session review.",
        )
        opening = "Invite the patient to share what they would like to work on."
    elif has_user and not has_assistant:
        summary = (
            "The patient sent one or more messages, but the session ended "
            "before a therapist response occurred."
        )
        unresolved = (
            "The concern was not explored because no therapist response occurred.",
        )
        opening = "Revisit the patient's final message from the source session."
    else:
        summary = "The therapist opened the session, but no patient response occurred."
        unresolved = ("No patient response occurred in the session.",)
        opening = "Invite the patient to share what they would like to work on."

    return PostSessionResult(
        review=SessionReview(
            analysis=SessionAnalysis(
                summary=summary,
                key_themes=(),
                unresolved_topics=unresolved,
            ),
            briefing=SessionBriefing(
                narrative_handoff=summary,
                continuity_points=(),
                unresolved_issues=unresolved,
                recommended_opening_focus=opening,
            ),
            plan_recommendation=PlanPatch(),
            generation=None,
        ),
    )


def _compose_result(
    resolved: ResolvedSessionAnalysis,
    update: PostSessionUpdateResult,
    *,
    analysis_policy: ModelPolicy,
    update_policy: ModelPolicy,
) -> PostSessionResult:
    return PostSessionResult(
        review=SessionReview(
            analysis=resolved.analysis,
            briefing=update.session_briefing,
            plan_recommendation=update.plan_patch,
            generation=SessionReviewGeneration(
                analysis_model=analysis_policy.model,
                analysis_prompt_version=ANALYSIS_PROMPT_VERSION,
                update_model=update_policy.model,
                update_prompt_version=UPDATE_PROMPT_VERSION,
            ),
        ),
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
        if not _has_conversational_content(input):
            return _minimal_session_result(input)

        request = build_analysis_request(input)
        analysis = await self._gateway.generate_structured(
            list(request.messages),
            SessionAnalysis,
            self._analysis_policy,
            validate_result=lambda result: validate_session_analysis(
                result,
                input.transcript,
                allowed_sequences=request.visible_sequences,
            ),
        )
        resolved = resolve_session_analysis(analysis, input.transcript)
        update = await self._gateway.generate_structured(
            build_update_messages(input, resolved),
            PostSessionUpdateResult,
            self._update_policy,
            validate_result=lambda result: validate_update_result(
                result,
                current_plan=input.current_plan,
            ),
        )
        return _compose_result(
            resolved,
            update,
            analysis_policy=self._analysis_policy,
            update_policy=self._update_policy,
        )
