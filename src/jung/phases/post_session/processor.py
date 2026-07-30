"""Post-session phase processor."""

from __future__ import annotations

from jung.llm.gateway import LLMGateway, ModelPolicy
from jung.phases.context_bounds import bounded_text
from jung.phases.post_session.evidence_validation import validate_session_analysis
from jung.phases.post_session.merge import validate_update_result
from jung.phases.post_session.models import (
    DerivedProfilePatch,
    GroundedPatientStatement,
    PlanPatch,
    PostSessionInput,
    PostSessionResult,
    PostSessionUpdateResult,
    SessionAnalysisResult,
    SessionBriefing,
)
from jung.phases.post_session.prompts import (
    build_analysis_messages,
    build_update_messages,
)
from jung.phases.transcript import normalize_transcript_content


def _has_conversational_content(input: PostSessionInput) -> bool:
    has_user = any(turn.role == "user" for turn in input.transcript)
    has_assistant = any(turn.role == "assistant" for turn in input.transcript)
    return has_user and has_assistant


def _minimal_session_result(input: PostSessionInput) -> PostSessionResult:
    has_user = any(turn.role == "user" for turn in input.transcript)
    has_assistant = any(turn.role == "assistant" for turn in input.transcript)

    if not has_user and not has_assistant:
        summary = "The session ended without conversational content."
        continuity_points: tuple[str, ...] = ()
        unresolved = (
            "No conversational content was available for post-session review.",
        )
        opening = "Invite the patient to share what they would like to work on."
    elif has_user and not has_assistant:
        latest_user = next(
            turn for turn in reversed(input.transcript) if turn.role == "user"
        )
        latest = bounded_text(
            normalize_transcript_content(latest_user.content),
            500,
        )
        summary = (
            "The patient provided a message, but the concern was not explored "
            f"because no therapist response occurred. The patient's final "
            f'message was: "{latest}"'
        )
        continuity_points = (latest,)
        unresolved = (
            "The concern was not explored because no therapist response occurred.",
        )
        opening = (
            "Revisit the patient's last message and clarify what support is needed."
        )
    else:
        summary = "The therapist opened the session, but no patient response occurred."
        continuity_points = ()
        unresolved = ("No patient response occurred in the session.",)
        opening = "Invite the patient to share what they would like to work on."

    return PostSessionResult(
        session_summary=summary,
        session_briefing=SessionBriefing(
            narrative_handoff=summary,
            continuity_points=continuity_points,
            unresolved_issues=unresolved,
            recommended_opening_focus=opening,
            intervention_evidence=(),
        ),
        derived_profile_patch=DerivedProfilePatch(),
        plan_patch=PlanPatch(),
    )


def _compose_result(
    input: PostSessionInput,
    analysis: SessionAnalysisResult,
    update: PostSessionUpdateResult,
) -> PostSessionResult:
    turns_by_sequence = {turn.sequence: turn for turn in input.transcript}
    grounded = tuple(
        GroundedPatientStatement(
            source_message_id=turns_by_sequence[citation.patient_sequence].message_id,
            source_sequence=citation.patient_sequence,
            quote=normalize_transcript_content(citation.patient_quote),
        )
        for citation in analysis.patient_statements
    )
    return PostSessionResult(
        session_summary=analysis.summary,
        session_briefing=SessionBriefing(
            **update.session_briefing.model_dump(),
            intervention_evidence=analysis.intervention_evidence,
        ),
        derived_profile_patch=DerivedProfilePatch(
            grounded_patient_statements=grounded,
        ),
        plan_patch=update.plan_patch,
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

        analysis = await self._gateway.generate_structured(
            build_analysis_messages(input),
            SessionAnalysisResult,
            self._analysis_policy,
            validate_result=lambda result: validate_session_analysis(
                result,
                input.transcript,
            ),
        )
        update = await self._gateway.generate_structured(
            build_update_messages(input, analysis),
            PostSessionUpdateResult,
            self._update_policy,
            validate_result=lambda result: validate_update_result(
                result,
                current_plan=input.current_plan,
            ),
        )
        return _compose_result(input, analysis, update)
