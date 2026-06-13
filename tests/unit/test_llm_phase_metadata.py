from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from psychoanalyst_app.agents.intake.extraction import extract_tier1_data
from psychoanalyst_app.agents.memory.agent import TrioMemoryAgent
from psychoanalyst_app.agents.reflection.session_summary import generate_session_summary
from psychoanalyst_app.agents.therapist.deep_topic import detect_deep_topic_via_llm
from psychoanalyst_app.context.user_context import UserContext
from psychoanalyst_app.models.domain import (
    AnalyticFrame,
    BasicPatientBackground,
    EducationalWorkHistory,
    FamilyConstellation,
    Message,
    RelationalLifeContext,
    Session,
    UserProfile,
)
from psychoanalyst_app.models.llm_outputs import (
    DeepTopicSignalOutput,
    PatientProfileExtract,
    SessionAnalysis,
    Tier2Enrichment,
)
from psychoanalyst_app.orchestration.models import ConversationContext
from psychoanalyst_app.orchestration.trio_conversation_manager import (
    TrioConversationManager,
)
from psychoanalyst_app.services.llm_phases import (
    INTAKE_EXTRACTION,
    INTAKE_RESPONSE,
    MEMORY_ANALYSIS,
    SESSION_ENRICHMENT,
    SESSION_SUMMARY,
    THERAPY_DEEP_TOPIC_DETECTION,
)
from psychoanalyst_app.services.session_enrichment import SessionEnrichmentService
from psychoanalyst_app.testing.fakes import DeterministicLLMService

pytestmark = [pytest.mark.trio, pytest.mark.unit]


class _PhaseCapturingLLM:
    def __init__(self) -> None:
        self.phases: list[str | None] = []

    async def generate_structured_output_async(
        self,
        _prompt: str,
        schema: type,
        *,
        method: str = "json_schema",
        phase: str,
    ) -> Any:
        _ = method
        self.phases.append(phase)
        if schema is PatientProfileExtract:
            return PatientProfileExtract(
                basic_info=BasicPatientBackground(alias="Probe"),
                family=FamilyConstellation(),
                history=EducationalWorkHistory(),
                context=RelationalLifeContext(),
                frame=AnalyticFrame(),
            )
        if schema is Tier2Enrichment:
            return Tier2Enrichment(
                psychological_summary="summary",
                dominant_affects=["anxiety"],
                key_themes=["work"],
            )
        if schema is SessionAnalysis:
            return SessionAnalysis(
                key_themes=["work"],
                emotional_state="anxious",
                insights=["pressure matters"],
                progress_indicators=["named trigger"],
            )
        if schema is DeepTopicSignalOutput:
            return DeepTopicSignalOutput(in_deep_topic=True, confidence="high")
        raise AssertionError(f"Unexpected schema: {schema}")

    def generate_response(
        self,
        _prompt: str,
        context: list[dict[str, str]] | None = None,
        *,
        phase: str,
    ) -> str:
        _ = context
        self.phases.append(phase)
        return "summary"


class _StreamingLLM:
    def __init__(self) -> None:
        self.phases: list[str | None] = []

    async def stream_response(
        self,
        _prompt: str,
        _context: list[dict[str, str]] | None = None,
        *,
        phase: str,
    ):
        self.phases.append(phase)
        yield "ok"


class _RecordingConversationManager(TrioConversationManager):
    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        agent: str | None = None,
    ) -> Message:
        return Message(
            role=role,
            content=content,
            timestamp=datetime.now(),
            agent=agent,
        )


def _sample_session(*, session_type: str = "therapy") -> Session:
    return Session(
        session_id="session_1",
        user_id="user_1",
        session_type=session_type,
        timestamp=datetime.now(),
        transcript=[
            Message(role="user", content="I felt anxious.", timestamp=datetime.now()),
            Message(role="assistant", content="Tell me more.", timestamp=datetime.now()),
        ],
    )


def _conversation_context(agent_message_history: list[Message]) -> ConversationContext:
    return ConversationContext(
        session_id="session_1",
        user_profile=UserProfile(
            user_id="user_1",
            name="Probe",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        ),
        therapy_plan=None,
        message_history=agent_message_history,
        topics_covered=[],
        session_start_time=datetime.now(),
        duration_minutes=50,
    )


async def test_conversation_manager_phases_intake_streaming() -> None:
    llm = _StreamingLLM()
    manager = _RecordingConversationManager(
        llm_service=llm,
        rag_service=SimpleNamespace(),
        trio_db_service=SimpleNamespace(),
        nursery=SimpleNamespace(),
        config=SimpleNamespace(),
    )

    chunks = [
        chunk
        async for chunk in manager.stream_response(
            "prompt",
            _conversation_context([]),
            use_rag=False,
            agent="INTAKE",
            llm_service=llm,
        )
    ]

    assert chunks == ["ok"]
    assert llm.phases == [INTAKE_RESPONSE]


async def test_intake_extraction_phases_structured_output() -> None:
    llm = _PhaseCapturingLLM()

    result = await extract_tier1_data(llm, _sample_session(session_type="intake").transcript)

    assert result is not None
    assert llm.phases == [INTAKE_EXTRACTION]


async def test_session_enrichment_phases_structured_output() -> None:
    llm = _PhaseCapturingLLM()
    db_service = SimpleNamespace(
        get_session=lambda _session_id: None,
    )

    async def get_session(_session_id: str) -> Session:
        return _sample_session()

    async def update_session_tier2(
        _session_id: str,
        _payload: dict[str, Any],
    ) -> bool:
        return True

    db_service.get_session = get_session
    db_service.update_session_tier2 = update_session_tier2
    service = SessionEnrichmentService(llm, db_service)

    assert await service.enrich_session_tier2("session_1") is True
    assert llm.phases == [SESSION_ENRICHMENT]


async def test_memory_analysis_phases_structured_output() -> None:
    llm = _PhaseCapturingLLM()
    rag_service = SimpleNamespace(retrieve_relevant_knowledge=lambda *_args: [])
    agent = TrioMemoryAgent(
        llm,
        db_service=SimpleNamespace(),
        rag_service=rag_service,
        user_context=UserContext("user_1"),
    )

    context = await agent.analyze_session_context(_sample_session())

    assert context.key_themes == ["work"]
    assert llm.phases == [MEMORY_ANALYSIS]


async def test_deep_topic_detection_phases_structured_output() -> None:
    llm = _PhaseCapturingLLM()

    assert await detect_deep_topic_via_llm(
        llm,
        _conversation_context(
            [
                Message(
                    role="user",
                    content="This feels difficult.",
                    timestamp=datetime.now(),
                )
            ]
        ),
    )
    assert llm.phases == [THERAPY_DEEP_TOPIC_DETECTION]


async def test_session_summary_phases_generate_response() -> None:
    llm = _PhaseCapturingLLM()

    assert await generate_session_summary(llm, _sample_session()) == "summary"
    assert llm.phases == [SESSION_SUMMARY]


async def test_deterministic_llm_accepts_phase_for_session_summary() -> None:
    llm = DeterministicLLMService()

    summary = await generate_session_summary(llm, _sample_session())

    assert summary
