"""Workflow navigation routes."""

from __future__ import annotations

from quart import Blueprint, jsonify, request
from pydantic import ValidationError

from psychoanalyst_app.api.http_errors import validation_error_response
from psychoanalyst_app.models.api_models import WorkflowNextActionRequest, WorkflowNextActionResponse
from psychoanalyst_app.orchestration.models import WorkflowState


def create_workflow_routes(server) -> Blueprint:
    """Create blueprint for workflow navigation endpoints."""
    bp = Blueprint("workflow", __name__, url_prefix="/api/workflow")
    @bp.route("/next-action", methods=["POST"])
    async def get_next_action():
        """Determine next action for frontend based on user's workflow state."""
        data = await request.get_json() or {}
        try:
            req = WorkflowNextActionRequest(**data)
        except ValidationError as error:
            return validation_error_response(error)

        profile = await server.db_service.get_user_profile(req.user_id)
        if not profile:
            response = determine_next_action(
                WorkflowState.NEW,
                profile,
                req.current_route,
            )
            return jsonify(response.model_dump()), 200

        workflow_state = server.workflow_engine.USER_STATUS_TO_WORKFLOW_STATE.get(
            profile.status, WorkflowState.NEW
        )
        response = determine_next_action(workflow_state, profile, req.current_route)
        return jsonify(response.model_dump()), 200

    return bp


def determine_next_action(
    workflow_state: WorkflowState, profile, current_route: str | None = None
) -> WorkflowNextActionResponse:
    """Map workflow state to frontend action."""
    canonical_routes = {
        "/profile",
        "/intake",
        "/assessment",
        "/dashboard",
        "/session/new",
    }

    state_action_map = {
        WorkflowState.NEW: ("navigate", "/profile", "User needs to create profile"),
        WorkflowState.INTAKE_IN_PROGRESS: (
            "navigate",
            "/intake",
            "User needs to complete intake",
        ),
        WorkflowState.INTAKE_COMPLETE: (
            "navigate",
            "/assessment",
            "User needs assessment",
        ),
        WorkflowState.ASSESSMENT_IN_PROGRESS: (
            "navigate",
            "/assessment",
            "User is completing assessment",
        ),
        WorkflowState.ASSESSMENT_COMPLETE: (
            "navigate",
            "/assessment",
            "User needs to select therapy style",
        ),
        WorkflowState.PLAN_COMPLETE: (
            "navigate",
            "/session/new",
            "User can start therapy session",
        ),
        WorkflowState.THERAPY_IN_PROGRESS: ("wait", None, "Session in progress"),
        WorkflowState.REFLECTION_IN_PROGRESS: ("wait", None, "Reflection in progress"),
    }

    action_type, route, reason = state_action_map.get(
        workflow_state,
        ("navigate", "/profile", "Unknown state - redirecting to profile"),
    )

    if action_type == "navigate":
        if route and current_route == route:
            return WorkflowNextActionResponse(
                action="wait", route=route, reason=reason
            )

        if (
            route
            and current_route
            and current_route not in canonical_routes
            and route != current_route
        ):
            # Log indirectly through server logger in calling code if needed.
            return WorkflowNextActionResponse(
                action="navigate", route=route, reason=reason
            )

        return WorkflowNextActionResponse(action="navigate", route=route, reason=reason)

    return WorkflowNextActionResponse(action=action_type, reason=reason)
