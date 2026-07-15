"""HTTP route happy-path integration tests for /api/v1."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from httpx import AsyncClient

from jung.domain.models import OperationStatus, Stage
from jung.llm.errors import LLMTimeout
from jung.llm.fake import FailureExpectation, FakeLLM, StructuredExpectation
from jung.llm.gateway import LLMTask
from jung.persistence.sqlite_store import SQLiteStore
from jung.phases.assessment.models import AssessmentResult
from tests.integration.jung.application_fixtures import (
    assessment_result,
    wait_for_operation_status,
    wait_for_stage,
)
from tests.integration.jung.scenarios import (
    advance_to_ready,
    complete_intake_for_assessment,
    open_intake,
)
from tests.jung_api_fixtures import runtime_factory


@pytest.mark.asyncio
async def test_get_state_on_fresh_database(started_api_client: AsyncClient) -> None:
    response = await started_api_client.get("/api/v1/state")
    assert response.status_code == 200
    payload = response.json()
    assert payload["stage"] == "setup"
    assert "update_profile" in payload["available_commands"]
    assert response.headers["X-Request-ID"]
    for optional_field in (
        "selected_style",
        "active_session",
        "operation",
        "active_chat_turn",
    ):
        assert optional_field not in payload


@pytest.mark.asyncio
async def test_get_profile_returns_seeded_profile(started_api_client: AsyncClient) -> None:
    response = await started_api_client.get("/api/v1/profile")
    assert response.status_code == 200
    payload = response.json()
    assert "name" in payload["profile"]
    assert payload["snapshot"]["stage"] == "setup"


@pytest.mark.asyncio
async def test_put_profile_success(started_api_client: AsyncClient) -> None:
    revision = (await started_api_client.get("/api/v1/state")).json()["revision"]
    response = await started_api_client.put(
        "/api/v1/profile",
        json={
            "expected_revision": revision,
            "profile": {
                "name": "Alex",
                "primary_language": "English",
                "date_of_birth": None,
                "notes": None,
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["profile_complete"] is True


@pytest.mark.asyncio
async def test_get_styles_before_and_after_assessment(
    store: SQLiteStore,
    started_api_client: AsyncClient,
) -> None:
    before = await started_api_client.get("/api/v1/styles")
    assert before.status_code == 200
    assert before.json()["recommendations"] == []

    advance_to_ready(store)
    after = await started_api_client.get("/api/v1/styles")
    assert after.status_code == 200
    assert after.json()["recommendations"]


@pytest.mark.asyncio
async def test_select_style_invalid_stage(started_api_client: AsyncClient) -> None:
    revision = (await started_api_client.get("/api/v1/state")).json()["revision"]
    response = await started_api_client.put(
        "/api/v1/style",
        json={"expected_revision": revision, "style_id": "cbt"},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "invalid_command"


@pytest.mark.asyncio
async def test_session_list_and_detail(
    store: SQLiteStore,
    started_api_client: AsyncClient,
) -> None:
    ready = advance_to_ready(store)
    listing = await started_api_client.get("/api/v1/sessions")
    assert listing.status_code == 200
    sessions = listing.json()["sessions"]
    assert sessions

    detail = await started_api_client.get(f"/api/v1/sessions/{ready.intake_session_id}")
    assert detail.status_code == 200
    assert detail.json()["session"]["id"] == str(ready.intake_session_id)


@pytest.mark.asyncio
async def test_get_unknown_session_returns_not_found(
    started_api_client: AsyncClient,
) -> None:
    response = await started_api_client.get(f"/api/v1/sessions/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


@pytest.mark.asyncio
async def test_start_session_returns_atomic_body(
    store: SQLiteStore,
    started_api_client: AsyncClient,
) -> None:
    advance_to_ready(store)
    revision = (await started_api_client.get("/api/v1/state")).json()["revision"]
    response = await started_api_client.post(
        "/api/v1/sessions",
        json={"expected_revision": revision},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["session"]["id"] == payload["snapshot"]["active_session"]["id"]


@pytest.mark.asyncio
async def test_end_session_returns_accepted_snapshot(
    store: SQLiteStore,
    started_api_client: AsyncClient,
) -> None:
    ready = advance_to_ready(store)
    therapy_id = uuid4()
    store.start_therapy_session(
        expected_revision=store.get_app_state().revision,
        session_id=therapy_id,
        now=ready.now,
    )
    revision = store.get_app_state().revision
    response = await started_api_client.post(
        f"/api/v1/sessions/{therapy_id}/end",
        json={"expected_revision": revision},
    )
    assert response.status_code == 202
    assert response.json()["stage"] == "post_session"


@pytest.mark.asyncio
async def test_end_unknown_session_returns_not_found(
    store: SQLiteStore,
    started_api_client: AsyncClient,
) -> None:
    ready = advance_to_ready(store)
    therapy_id = uuid4()
    store.start_therapy_session(
        expected_revision=store.get_app_state().revision,
        session_id=therapy_id,
        now=ready.now,
    )
    revision = store.get_app_state().revision
    response = await started_api_client.post(
        f"/api/v1/sessions/{uuid4()}/end",
        json={"expected_revision": revision},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cors_preflight_and_cross_origin_get(api_app, store: SQLiteStore) -> None:
    transport = httpx.ASGITransport(app=api_app, raise_app_exceptions=False)
    async with api_app.router.lifespan_context(api_app):
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            preflight = await client.options(
                "/api/v1/state",
                headers={
                    "Origin": "http://frontend.test",
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "X-Request-ID",
                },
            )
            assert preflight.status_code == 200
            assert preflight.headers.get("access-control-allow-origin") == (
                "http://frontend.test"
            )

            response = await client.get(
                "/api/v1/state",
                headers={"Origin": "http://frontend.test"},
            )
            assert response.status_code == 200
            assert response.headers.get("access-control-allow-origin") == (
                "http://frontend.test"
            )
            assert response.headers.get("X-Request-ID")

            malformed = await client.get(
                "/api/v1/state",
                headers={
                    "Origin": "http://frontend.test",
                    "X-Request-ID": "not-a-uuid",
                },
            )
            assert malformed.status_code == 422
            assert malformed.headers.get("access-control-allow-origin") == (
                "http://frontend.test"
            )
            assert malformed.json()["request_id"] == malformed.headers["X-Request-ID"]


@pytest.mark.asyncio
async def test_retry_operation_returns_accepted_snapshot(
    store: SQLiteStore,
    api_settings,
) -> None:
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
    )
    fake_llm = FakeLLM(
        [
            FailureExpectation(
                task=LLMTask.ASSESSMENT,
                error=LLMTimeout("timeout"),
            ),
            StructuredExpectation(
                task=LLMTask.ASSESSMENT,
                output_type=AssessmentResult,
                response=assessment_result(),
            ),
        ]
    )
    from jung.api.app import create_app

    app = create_app(
        api_settings,
        runtime_factory=runtime_factory(store, fake_llm),
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            application = app.state.api.runtime.application
            await wait_for_operation_status(
                application,
                operation_id,
                OperationStatus.FAILED,
            )
            revision = (await client.get("/api/v1/state")).json()["revision"]
            response = await client.post(
                "/api/v1/operations/current/retry",
                json={"expected_revision": revision},
            )

            assert response.status_code == 202
            payload = response.json()
            assert payload["stage"] == "assessment"
            assert payload["operation"]["id"] == str(operation_id)
            assert payload["operation"]["status"] == "pending"

            await wait_for_stage(application, Stage.STYLE_SELECTION)

    fake_llm.assert_exhausted()
