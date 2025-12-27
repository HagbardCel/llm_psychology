"""Unit tests for workflow next-action logic."""

from __future__ import annotations

from enum import Enum

from psychoanalyst_app.api.workflow_routes import determine_next_action
from psychoanalyst_app.models.api_models import WorkflowNextActionResponse
from psychoanalyst_app.orchestration.models import WorkflowState


class DummyProfile:
    """Minimal user profile stub for next-action tests."""

    def __init__(self, status: str = "profile_only"):
        self.status = status


def test_plan_complete_navigates_to_new_session():
    profile = DummyProfile()
    response = determine_next_action(
        WorkflowState.PLAN_COMPLETE, profile, current_route="/dashboard"
    )

    assert isinstance(response, WorkflowNextActionResponse)
    assert response.action == "navigate"
    assert response.route == "/session/new"
    assert "start therapy" in response.reason.lower()


def test_same_route_returns_wait():
    profile = DummyProfile()
    response = determine_next_action(
        WorkflowState.INTAKE_IN_PROGRESS, profile, current_route="/intake"
    )

    assert response.action == "wait"
    assert response.route == "/intake"


def test_unknown_state_defaults_to_profile():
    profile = DummyProfile()
    FakeState = Enum("FakeState", "UNKNOWN")
    response = determine_next_action(
        FakeState.UNKNOWN, profile, current_route="/nowhere"
    )

    assert response.action == "navigate"
    assert response.route == "/profile"


def test_noncanonical_current_route_redirects():
    profile = DummyProfile()
    response = determine_next_action(
        WorkflowState.ASSESSMENT_COMPLETE, profile, current_route="/custom-path"
    )

    assert response.action == "navigate"
    assert response.route == "/assessment"
