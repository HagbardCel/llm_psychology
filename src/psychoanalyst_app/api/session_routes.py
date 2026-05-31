"""Session management HTTP routes."""

from __future__ import annotations

import logging
from datetime import datetime

from quart import Blueprint, jsonify, request
from pydantic import ValidationError

from psychoanalyst_app.api._helpers import (
    require_session_id,
    require_user_id,
    validate_session_for_user,
    validation_error_response,
)
from psychoanalyst_app.models.http import (
    CreateSessionRequestDTO,
    EndSessionRequestDTO,
    EndSessionResponseDTO,
    SessionTimerResponseDTO,
    StatusMessageResponseDTO,
    session_to_dto,
)
from psychoanalyst_app.orchestration.orchestrator_helpers import (
    session_type_for_workflow_state,
)


def create_session_routes(server) -> Blueprint:
    """Create blueprint for session CRUD endpoints."""
    logger = logging.getLogger(__name__)
    bp = Blueprint("sessions", __name__, url_prefix="/api/sessions")
    @bp.route("", methods=["GET"])
    async def get_sessions():
        """Get all sessions for a user."""
        user_id, error = require_user_id()
        if error:
            return error
        session_id, error = require_session_id()
        if error:
            return error
        session_error = await validate_session_for_user(server, user_id, session_id)
        if session_error:
            return session_error
        sessions = await server.db_service.get_user_sessions(user_id)
        payload = [
            session_to_dto(session).model_dump(mode="json") for session in sessions
        ]
        return jsonify(payload)

    @bp.route("/<session_id>", methods=["GET"])
    async def get_session(session_id):
        """Get a specific session."""
        user_id, error = require_user_id()
        if error:
            return error
        active_session_id, error = require_session_id()
        if error:
            return error
        session_error = await validate_session_for_user(
            server, user_id, active_session_id
        )
        if session_error:
            return session_error
        session = await server.db_service.get_session(session_id)
        if not session:
            return jsonify({"error": "Session not found"}), 404
        if session.user_id != user_id:
            return jsonify({"error": "Session not found"}), 404
        dto = session_to_dto(session)
        return jsonify(dto.model_dump(mode="json"))

    @bp.route("", methods=["POST"])
    async def create_session():
        """Create a new session."""
        data = await request.get_json() or {}
        try:
            session_request = CreateSessionRequestDTO(**data)
        except ValidationError as error:
            return validation_error_response(error)

        user_profile = await server.db_service.get_user_profile(
            session_request.user_id
        )
        if not user_profile:
            return jsonify({"error": "User profile not found"}), 404

        workflow_state = await server.orchestrator.get_user_state(
            session_request.user_id
        )
        session_type = session_type_for_workflow_state(workflow_state)
        session_info = await server.orchestrator.start_session(
            session_request.user_id,
            session_type=session_type,
            send_initial_message=False,
        )
        await server.orchestrator.ensure_assessment_job(
            session_request.user_id,
            session_info.session_id,
        )
        created_session = await server.db_service.get_session(session_info.session_id)
        if not created_session:
            logger.error(
                "Session %s could not be retrieved after creation",
                session_info.session_id,
            )
            return jsonify({"error": "Failed to load created session"}), 500

        dto = session_to_dto(created_session)
        return jsonify(dto.model_dump(mode="json")), 201

    @bp.route("/<session_id>/extend", methods=["POST"])
    async def extend_session(session_id):
        """Extend a session (placeholder)."""
        user_id, error = require_user_id()
        if error:
            return error
        active_session_id, error = require_session_id()
        if error:
            return error
        session_error = await validate_session_for_user(
            server, user_id, active_session_id
        )
        if session_error:
            return session_error
        dto = StatusMessageResponseDTO(
            message="Session extended",
            session_id=session_id,
        )
        return jsonify(dto.model_dump(mode="json"))

    @bp.route("/<session_id>/end", methods=["POST"])
    async def end_session(session_id):
        """End the active session and acknowledge its transitional workflow state."""
        data = await request.get_json() or {}
        try:
            end_request = EndSessionRequestDTO(**data)
        except ValidationError as error:
            return validation_error_response(error)
        if end_request.session_id != session_id:
            return jsonify({"error": "Session ID does not match request path"}), 400
        session_error = await validate_session_for_user(
            server, end_request.user_id, end_request.session_id
        )
        if session_error:
            return session_error
        await server.orchestrator.end_session(
            end_request.user_id,
            end_request.session_id,
            reason=end_request.reason,
        )
        state = await server.orchestrator.get_user_state(end_request.user_id)
        dto = EndSessionResponseDTO(
            session_id=end_request.session_id,
            workflow_state=state.value,
            reason=end_request.reason or "Session ended",
        )
        return jsonify(dto.model_dump(mode="json"))

    @bp.route("/<session_id>/timer", methods=["GET"])
    async def get_session_timer(session_id):
        """Get session timing information."""
        user_id, error = require_user_id()
        if error:
            return error
        active_session_id, error = require_session_id()
        if error:
            return error
        if active_session_id != session_id:
            return jsonify({"error": "Session ID does not match active session"}), 400
        session_error = await validate_session_for_user(
            server, user_id, active_session_id
        )
        if session_error:
            return session_error
        try:
            context = await server.conversation_manager.get_context(session_id)
            elapsed_minutes = context.time_elapsed_minutes
            remaining_minutes = context.time_remaining_minutes
            total_duration = context.duration_minutes + (
                context.extensions_used * 5
            )

            timer_dto = SessionTimerResponseDTO(
                session_id=session_id,
                elapsed_minutes=round(elapsed_minutes, 1),
                remaining_minutes=round(remaining_minutes, 1),
                total_duration_minutes=total_duration,
                extensions_used=context.extensions_used,
                max_extensions=context.max_extensions,
                can_extend=context.can_extend,
                is_time_up=context.is_time_up,
                timestamp=datetime.utcnow(),
            )

            return jsonify(timer_dto.model_dump(mode="json"))
        except ValueError as exc:
            logger.error("Session not found for timer: %s", session_id)
            return jsonify({"error": str(exc)}), 404
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Error getting session timer: %s", exc, exc_info=True)
            return jsonify({"error": "Internal server error"}), 500

    return bp
