"""Unit tests for workflow route validations."""

import uuid
from datetime import datetime

import pytest
import trio

from psychoanalyst_app.exceptions import PlanningError
from psychoanalyst_app.models.domain import Message, Session, UserProfile, UserStatus
from psychoanalyst_app.orchestration.models import WorkflowState
from psychoanalyst_app.trio_server import TrioServer


class DummyWebSocket:
    """Minimal websocket stub for registering active sessions in tests."""

    async def send(self, _payload: str) -> None:
        return None


@pytest.fixture
async def trio_server(mock_service_container):
    """Create Trio server instance for workflow route tests."""
    async with trio.open_nursery() as nursery:
        server = TrioServer(mock_service_container, host="127.0.0.1", port=8002)
        server.nursery = nursery
        server._initialize_orchestration(nursery)
        yield server
        nursery.cancel_scope.cancel()


@pytest.mark.trio
async def test_select_therapy_style_rejects_wrong_state(trio_server):
    """Workflow should reject therapy style selection outside assessment_complete."""
    app = trio_server.app
    trio_db_service = trio_server.db_service

    user_profile = UserProfile(
        user_id="workflow_routes_user",
        name="Workflow User",
        date_of_birth=None,
        profession="Tester",
        status=UserStatus.INTAKE_IN_PROGRESS,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await trio_db_service.save_user_profile(user_profile)

    session_info = await trio_server.orchestrator.start_session(
        user_profile.user_id,
        session_type="intake",
        send_initial_message=False,
    )
    trio_server.conversation_manager.register_websocket(
        session_info.session_id, DummyWebSocket()
    )

    async with app.test_client() as client:
        response = await client.post(
            "/api/workflow/select_therapy_style",
            json={
                "user_id": user_profile.user_id,
                "session_id": session_info.session_id,
                "selected_therapy_style": "freud",
            },
        )

        assert response.status_code == 400
        data = await response.get_json()
        assert data["workflow_state"] == "intake_in_progress"


@pytest.mark.trio
async def test_select_therapy_style_accepts_assessment_complete(trio_server):
    """Workflow should allow therapy style selection after assessment."""
    app = trio_server.app
    trio_db_service = trio_server.db_service

    user_profile = UserProfile(
        user_id="workflow_routes_user_complete",
        name="Workflow User",
        date_of_birth=None,
        profession="Tester",
        status=UserStatus.ASSESSMENT_COMPLETE,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await trio_db_service.save_user_profile(user_profile)

    intake_session = Session(
        session_id=str(uuid.uuid4()),
        user_id=user_profile.user_id,
        timestamp=datetime.now(),
        transcript=[
            Message(
                role="assistant",
                content="Intake session started.",
                timestamp=datetime.now(),
                agent="INTAKE",
            )
        ],
        topics=[],
    )
    await trio_db_service.save_session(intake_session)

    session_info = await trio_server.orchestrator.start_session(
        user_profile.user_id,
        session_type="intake",
        send_initial_message=False,
    )
    trio_server.conversation_manager.register_websocket(
        session_info.session_id, DummyWebSocket()
    )

    async with app.test_client() as client:
        response = await client.post(
            "/api/workflow/select_therapy_style",
            json={
                "user_id": user_profile.user_id,
                "session_id": session_info.session_id,
                "selected_therapy_style": "jung",
            },
        )

        assert response.status_code == 200
        data = await response.get_json()
        assert data["required_action"] == "start_therapy"

        response = await client.post(
            "/api/workflow/start_therapy",
            json={
                "user_id": user_profile.user_id,
                "session_id": session_info.session_id,
            },
        )
        assert response.status_code == 201
        data = await response.get_json()
        assert data["session"]["session_id"] != session_info.session_id
        assert data["session"]["session_type"] == "therapy"
        assert data["session"]["plan_id"]
        assert data["workflow_next_action"]["required_action"] == "continue_therapy"

    plan = await trio_db_service.get_current_therapy_plan(user_profile.user_id)
    assert plan is not None
    assert plan.selected_therapy_style == "jung"


@pytest.mark.trio
async def test_select_therapy_style_generation_failure_returns_json_502(trio_server):
    """Initial plan generation failures should fail transparently, not as HTML 500."""
    app = trio_server.app
    trio_db_service = trio_server.db_service

    user_profile = UserProfile(
        user_id="workflow_routes_generation_failure",
        name="Workflow User",
        date_of_birth=None,
        profession="Tester",
        status=UserStatus.ASSESSMENT_COMPLETE,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await trio_db_service.save_user_profile(user_profile)

    intake_session = Session(
        session_id=str(uuid.uuid4()),
        user_id=user_profile.user_id,
        timestamp=datetime.now(),
        transcript=[
            Message(
                role="assistant",
                content="Intake session started.",
                timestamp=datetime.now(),
                agent="INTAKE",
            )
        ],
        topics=[],
    )
    await trio_db_service.save_session(intake_session)

    session_info = await trio_server.orchestrator.start_session(
        user_profile.user_id,
        session_type="intake",
        send_initial_message=False,
    )
    trio_server.conversation_manager.register_websocket(
        session_info.session_id, DummyWebSocket()
    )

    async def fail_create_therapy_plan(_user_id: str, _style: str):
        raise PlanningError("Initial plan creation failed")

    trio_server.orchestrator.create_therapy_plan = fail_create_therapy_plan

    async with app.test_client() as client:
        response = await client.post(
            "/api/workflow/select_therapy_style",
            json={
                "user_id": user_profile.user_id,
                "session_id": session_info.session_id,
                "selected_therapy_style": "jung",
            },
        )

    assert response.status_code == 502
    data = await response.get_json()
    assert data == {
        "error": "Initial therapy plan generation failed",
        "code": "initial_plan_generation_failed",
        "workflow_state": "assessment_complete",
        "phase": "initial_plan_generation",
    }
    assert await trio_db_service.get_current_therapy_plan(user_profile.user_id) is None
    assert (
        await trio_server.orchestrator.get_user_state(user_profile.user_id)
        == WorkflowState.ASSESSMENT_COMPLETE
    )


@pytest.mark.trio
async def test_post_session_job_status_complete_requires_plan_and_enrichment(
    trio_server,
):
    app = trio_server.app
    trio_db_service = trio_server.db_service
    user_profile = UserProfile(
        user_id="job_status_complete_user",
        name="Workflow User",
        date_of_birth=None,
        profession="Tester",
        status=UserStatus.PLAN_UPDATE_COMPLETE,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await trio_db_service.save_user_profile(user_profile)
    session = Session(
        session_id=str(uuid.uuid4()),
        user_id=user_profile.user_id,
        session_type="therapy",
        timestamp=datetime.now(),
        transcript=[],
        topics=[],
        enriched=True,
    )
    await trio_db_service.save_session(session)
    await trio_db_service.enqueue_session_enrichment_job(
        session.session_id, user_profile.user_id
    )
    await trio_db_service.mark_session_enrichment_job_complete(session.session_id)

    async with app.test_client() as client:
        response = await client.get(
            f"/api/jobs/post_session_update:{session.session_id}",
            query_string={"user_id": user_profile.user_id},
        )

    assert response.status_code == 200
    data = await response.get_json()
    assert data["status"] == "complete"
    assert data["current_step"] == "post_session_update_complete"
    assert [child["job_type"] for child in data["children"]] == [
        "plan_update",
        "session_enrichment",
    ]


@pytest.mark.trio
async def test_post_session_job_status_failed_when_enrichment_fails(trio_server):
    app = trio_server.app
    trio_db_service = trio_server.db_service
    user_profile = UserProfile(
        user_id="job_status_failed_user",
        name="Workflow User",
        date_of_birth=None,
        profession="Tester",
        status=UserStatus.PLAN_UPDATE_COMPLETE,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await trio_db_service.save_user_profile(user_profile)
    session = Session(
        session_id=str(uuid.uuid4()),
        user_id=user_profile.user_id,
        session_type="therapy",
        timestamp=datetime.now(),
        transcript=[],
        topics=[],
    )
    await trio_db_service.save_session(session)
    await trio_db_service.enqueue_session_enrichment_job(
        session.session_id, user_profile.user_id
    )
    await trio_db_service.mark_session_enrichment_job_failed(
        session.session_id, "tier2 failed"
    )

    async with app.test_client() as client:
        response = await client.get(
            f"/api/jobs/post_session_update:{session.session_id}",
            query_string={"user_id": user_profile.user_id},
        )

    assert response.status_code == 200
    data = await response.get_json()
    assert data["status"] == "failed"
    assert data["current_step"] == "enrichment_failed"
    assert data["last_error"] == "tier2 failed"


@pytest.mark.trio
async def test_job_status_rejects_wrong_user(trio_server):
    app = trio_server.app
    trio_db_service = trio_server.db_service
    owner = UserProfile(
        user_id="job_status_owner",
        name="Owner",
        date_of_birth=None,
        profession="Tester",
        status=UserStatus.PLAN_UPDATE_IN_PROGRESS,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    other = UserProfile(
        user_id="job_status_other",
        name="Other",
        date_of_birth=None,
        profession="Tester",
        status=UserStatus.PLAN_UPDATE_IN_PROGRESS,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await trio_db_service.save_user_profile(owner)
    await trio_db_service.save_user_profile(other)
    session = Session(
        session_id=str(uuid.uuid4()),
        user_id=owner.user_id,
        session_type="therapy",
        timestamp=datetime.now(),
        transcript=[],
        topics=[],
    )
    await trio_db_service.save_session(session)

    async with app.test_client() as client:
        response = await client.get(
            f"/api/jobs/plan_update:{session.session_id}",
            query_string={"user_id": other.user_id},
        )

    assert response.status_code == 404


@pytest.mark.trio
async def test_retry_plan_update_rejects_non_failed_state(trio_server):
    """Retry endpoint is only available after a persisted reflection failure."""
    profile = UserProfile(
        user_id="workflow_retry_wrong_state",
        name="Workflow User",
        status=UserStatus.INTAKE_IN_PROGRESS,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await trio_server.db_service.save_user_profile(profile)

    async with trio_server.app.test_client() as client:
        response = await client.post(
            "/api/workflow/retry_plan_update",
            json={"user_id": profile.user_id, "session_id": "ended-session"},
        )

    assert response.status_code == 400
    data = await response.get_json()
    assert "only allowed after reflection failure" in data["error"]
