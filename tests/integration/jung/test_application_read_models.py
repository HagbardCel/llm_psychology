"""TherapyApplication read-model integration tests for Phase 5 WP1."""

from __future__ import annotations

import json
from copy import deepcopy
from uuid import uuid4

import pytest

from jung.domain.commands import UpdateProfile
from jung.domain.errors import InvariantViolation, NotFound
from jung.domain.models import Profile, Stage
from jung.llm.fake import FakeLLM
from jung.persistence.sqlite_store import SQLiteStore

from .application_fixtures import build_test_application
from .assessment_test_data import assessment_result_data
from .scenarios import (
    advance_to_ready,
    complete_intake_for_assessment,
    open_intake,
)

pytestmark = pytest.mark.asyncio


async def test_fresh_style_options_returns_catalog_without_recommendations(
    store: SQLiteStore,
) -> None:
    async with build_test_application(store, FakeLLM([]), recover=False) as runtime:
        options = await runtime.application.get_style_options()

    assert tuple(style.id for style in options.styles) == ("jung", "cbt", "freud")
    assert options.recommendations == ()


async def test_running_assessment_returns_empty_recommendations(
    store: SQLiteStore,
) -> None:
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
    )
    store.mark_operation_running(operation_id, now=now)

    async with build_test_application(
        store,
        FakeLLM([]),
        recover=False,
    ) as runtime:
        options = await runtime.application.get_style_options()

    assert options.recommendations == ()


async def test_completed_assessment_returns_normalized_recommendation_order(
    store: SQLiteStore,
) -> None:
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
    )
    store.mark_operation_running(operation_id, now=now)
    store.complete_assessment(
        operation_id,
        result=assessment_result_data(),
        now=now,
    )

    async with build_test_application(
        store,
        FakeLLM([]),
        recover=False,
    ) as runtime:
        options = await runtime.application.get_style_options()

    assert tuple(
        recommendation.style_id for recommendation in options.recommendations
    ) == ("cbt", "jung", "freud")


async def test_style_options_remain_readable_after_style_selection(
    store: SQLiteStore,
) -> None:
    advance_to_ready(store)

    async with build_test_application(store, FakeLLM([])) as runtime:
        snapshot = await runtime.application.get_snapshot()
        options = await runtime.application.get_style_options()

        assert snapshot.stage is Stage.READY
        assert tuple(
            recommendation.style_id for recommendation in options.recommendations
        ) == ("cbt", "jung", "freud")


async def test_get_style_options_redacts_assessment_internals(
    store: SQLiteStore,
) -> None:
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
    )
    store.mark_operation_running(operation_id, now=now)
    store.complete_assessment(
        operation_id,
        result=assessment_result_data(),
        now=now,
    )

    async with build_test_application(
        store,
        FakeLLM([]),
        recover=False,
    ) as runtime:
        options = await runtime.application.get_style_options()

    payload = json.loads(options.model_dump_json())
    serialized = json.dumps(payload)
    for forbidden in (
        "initial_plan",
        "formulation",
        "presenting_concerns",
        "risk_or_boundary_notes",
        "strengths_and_resources",
    ):
        assert forbidden not in serialized


async def test_get_style_options_rejects_missing_catalog_style(
    store: SQLiteStore,
) -> None:
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
    )
    store.mark_operation_running(operation_id, now=now)
    corrupt = deepcopy(assessment_result_data())
    recommendations = list(corrupt["style_recommendations"])
    recommendations.pop()
    corrupt["style_recommendations"] = recommendations
    store.complete_assessment(operation_id, result=corrupt, now=now)

    async with build_test_application(
        store,
        FakeLLM([]),
        recover=False,
    ) as runtime:
        with pytest.raises(InvariantViolation):
            await runtime.application.get_style_options()


async def test_get_style_options_rejects_unnormalized_recommendation_order(
    store: SQLiteStore,
) -> None:
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
    )
    store.mark_operation_running(operation_id, now=now)
    raw = deepcopy(assessment_result_data())
    raw["style_recommendations"] = list(reversed(raw["style_recommendations"]))
    store.complete_assessment(operation_id, result=raw, now=now)

    async with build_test_application(
        store,
        FakeLLM([]),
        recover=False,
    ) as runtime:
        with pytest.raises(InvariantViolation):
            await runtime.application.get_style_options()


async def test_get_style_options_rejects_invalid_assessment_schema(
    store: SQLiteStore,
) -> None:
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
    )
    store.mark_operation_running(operation_id, now=now)
    store.complete_assessment(
        operation_id,
        result={"initial_plan": {"focus": "anxiety"}},
        now=now,
    )

    async with build_test_application(
        store,
        FakeLLM([]),
        recover=False,
    ) as runtime:
        with pytest.raises(InvariantViolation):
            await runtime.application.get_style_options()


async def test_get_profile_raises_not_found_on_fresh_database(
    store: SQLiteStore,
) -> None:
    async with build_test_application(store, FakeLLM([]), recover=False) as runtime:
        with pytest.raises(NotFound):
            await runtime.application.get_profile()


async def test_get_profile_returns_profile_view_after_update(
    store: SQLiteStore,
) -> None:
    async with build_test_application(store, FakeLLM([]), recover=False) as runtime:
        await runtime.application.update_profile(
            UpdateProfile(
                expected_revision=0,
                profile=Profile(name="Alex", primary_language="English"),
            )
        )
        view = await runtime.application.get_profile()

    assert view.profile.name == "Alex"
    assert view.current_plan is None
