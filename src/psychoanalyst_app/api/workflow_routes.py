"""Workflow-driven navigation endpoints."""

from __future__ import annotations

import logging

from quart import Blueprint, jsonify, request
from pydantic import ValidationError

from psychoanalyst_app.api.http_errors import validation_error_response
from psychoanalyst_app.api.request_utils import (
    require_session_id,
    require_user_id,
    validate_session_for_user,
)
from psychoanalyst_app.models.http_models import (
    WorkflowCompleteProfileRequestDTO,
    WorkflowSelectTherapyStyleRequestDTO,
)
from psychoanalyst_app.orchestration.models import WorkflowState


def create_workflow_routes(server) -> Blueprint:
    """Create blueprint for workflow navigation endpoints."""
    logger = logging.getLogger(__name__)
    bp = Blueprint("workflow", __name__, url_prefix="/api/workflow")

    @bp.route("/next", methods=["GET"])
    async def get_next_action():
        """Return the next workflow action for a user."""
        user_id, error = require_user_id()
        if error:
            return error
        session_id, error = require_session_id()
        if error:
            return error

        session_error = await validate_session_for_user(
            server, user_id, session_id
        )
        if session_error:
            return session_error

        action = await server.orchestrator.get_workflow_next_action(
            user_id,
            session_id=session_id,
        )
        return jsonify(action.model_dump(mode="json")), 200

    @bp.route("/complete_profile", methods=["POST"])
    async def complete_profile():
        """Create or update a profile and return the next action."""
        data = await request.get_json() or {}
        try:
            profile_request = WorkflowCompleteProfileRequestDTO(**data)
        except ValidationError as error:
            return validation_error_response(error)

        session_error = await validate_session_for_user(
            server, profile_request.user_id, profile_request.session_id
        )
        if session_error:
            return session_error

        state = await server.orchestrator.get_user_state(profile_request.user_id)
        if state not in (
            WorkflowState.NEW,
            WorkflowState.INTAKE_IN_PROGRESS,
        ):
            return (
                jsonify(
                    {
                        "error": "Profile completion is only allowed during intake",
                        "workflow_state": state.value,
                    }
                ),
                400,
            )

        try:
            profile = await server.orchestrator.create_user_profile(
                profile_request.model_dump()
            )
        except ValueError as exc:
            logger.error("Validation error completing profile: %s", exc)
            return jsonify({"error": str(exc)}), 400

        action = await server.orchestrator.get_workflow_next_action(
            profile.user_id, session_id=profile_request.session_id
        )
        await server.orchestrator.emit_workflow_next_action(
            profile.user_id, profile_request.session_id
        )
        return jsonify(action.model_dump(mode="json")), 200

    @bp.route("/select_therapy_style", methods=["POST"])
    async def select_therapy_style():
        """Persist selected therapy style and return the next action."""
        data = await request.get_json() or {}
        try:
            style_request = WorkflowSelectTherapyStyleRequestDTO(**data)
        except ValidationError as error:
            return validation_error_response(error)

        session_error = await validate_session_for_user(
            server, style_request.user_id, style_request.session_id
        )
        if session_error:
            return session_error

        state = await server.orchestrator.get_user_state(style_request.user_id)
        if state != WorkflowState.ASSESSMENT_COMPLETE:
            return (
                jsonify(
                    {
                        "error": "Therapy style selection is only allowed after assessment",
                        "workflow_state": state.value,
                    }
                ),
                400,
            )

        try:
            await server.orchestrator.create_therapy_plan(
                style_request.user_id, style_request.selected_therapy_style
            )
        except ValueError as exc:
            logger.error("Validation error selecting therapy style: %s", exc)
            status = 404 if "not found" in str(exc).lower() else 400
            return jsonify({"error": str(exc)}), status

        action = await server.orchestrator.get_workflow_next_action(
            style_request.user_id, session_id=style_request.session_id
        )
        await server.orchestrator.emit_workflow_next_action(
            style_request.user_id, style_request.session_id
        )
        return jsonify(action.model_dump(mode="json")), 200

    return bp
