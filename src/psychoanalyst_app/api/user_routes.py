"""User-related HTTP routes."""

from __future__ import annotations

import logging
from datetime import datetime

from quart import Blueprint, jsonify, request
from pydantic import ValidationError

from psychoanalyst_app.api.cache_utils import CACHE_PRESETS, add_cache_headers
from psychoanalyst_app.api.http_errors import validation_error_response
from psychoanalyst_app.api.request_utils import (
    require_session_id,
    require_user_id,
    validate_session_for_user,
)
from psychoanalyst_app.models.http_models import (
    CreateUserProfileRequestDTO,
    PatchUserProfileRequestDTO,
    UpdateUserProfileRequestDTO,
    UserLoginRequestDTO,
    UserProfileListResponseDTO,
    UserRegisterResponseDTO,
    UserStatusResponseDTO,
    session_to_dto,
    user_profile_to_dto,
    user_profile_summary_to_dto,
)
from psychoanalyst_app.orchestration.orchestrator_helpers import (
    session_type_for_workflow_state,
)


def create_user_routes(server) -> Blueprint:
    """Create blueprint with user profile/status endpoints."""
    logger = logging.getLogger(__name__)
    bp = Blueprint("user", __name__, url_prefix="/api/user")
    @bp.route("/status", methods=["GET"])
    async def get_user_status():
        """Get user workflow state."""
        user_id, error = require_user_id()
        if error:
            return error
        session_id, error = require_session_id()
        if error:
            return error
        session_error = await validate_session_for_user(server, user_id, session_id)
        if session_error:
            return session_error
        state = await server.orchestrator.get_user_state(user_id)
        dto = UserStatusResponseDTO(
            user_id=user_id,
            workflow_state=state,
            timestamp=datetime.utcnow(),
        )
        return jsonify(dto.model_dump(mode="json"))

    @bp.route("/register", methods=["POST"])
    async def register_user():
        """Register a user profile and return a session + next action."""
        data = await request.get_json() or {}
        try:
            register_request = CreateUserProfileRequestDTO(**data)
        except ValidationError as error:
            return validation_error_response(error)

        try:
            profile = await server.orchestrator.create_user_profile(
                register_request.model_dump()
            )
        except ValueError as exc:
            logger.error("Validation error registering profile: %s", exc)
            return jsonify({"error": str(exc)}), 400

        workflow_state = await server.orchestrator.get_user_state(profile.user_id)
        session_type = session_type_for_workflow_state(workflow_state)
        session_info = await server.orchestrator.start_session(
            profile.user_id,
            session_type=session_type,
            send_initial_message=False,
        )
        created_session = await server.db_service.get_session(session_info.session_id)
        if not created_session:
            logger.error(
                "Session %s could not be retrieved after registration",
                session_info.session_id,
            )
            return jsonify({"error": "Failed to load created session"}), 500

        action = await server.orchestrator.get_workflow_next_action(
            profile.user_id,
            session_id=session_info.session_id,
        )
        response = UserRegisterResponseDTO(
            session=session_to_dto(created_session),
            workflow_next_action=action,
        )
        return jsonify(response.model_dump(mode="json")), 201

    @bp.route("/profiles", methods=["GET"])
    async def list_user_profiles():
        """List lightweight user profile summaries."""
        profiles = await server.db_service.list_user_profiles()
        response = UserProfileListResponseDTO(
            profiles=[user_profile_summary_to_dto(profile) for profile in profiles]
        )
        return jsonify(response.model_dump(mode="json"))

    @bp.route("/login", methods=["POST"])
    async def login_user():
        """Log in an existing profile and return a session + next action."""
        data = await request.get_json() or {}
        try:
            login_request = UserLoginRequestDTO(**data)
        except ValidationError as error:
            return validation_error_response(error)

        profile = await server.db_service.get_user_profile(login_request.user_id)
        if not profile:
            return jsonify({"error": "User profile not found"}), 404

        workflow_state = await server.orchestrator.get_user_state(profile.user_id)
        session_type = session_type_for_workflow_state(workflow_state)
        session_info = await server.orchestrator.start_session(
            profile.user_id,
            session_type=session_type,
            send_initial_message=False,
        )
        created_session = await server.db_service.get_session(session_info.session_id)
        if not created_session:
            logger.error(
                "Session %s could not be retrieved after login",
                session_info.session_id,
            )
            return jsonify({"error": "Failed to load created session"}), 500

        action = await server.orchestrator.get_workflow_next_action(
            profile.user_id,
            session_id=session_info.session_id,
        )
        response = UserRegisterResponseDTO(
            session=session_to_dto(created_session),
            workflow_next_action=action,
        )
        return jsonify(response.model_dump(mode="json"))

    @bp.route("/profile", methods=["GET"])
    async def get_user_profile():
        """Get a user profile."""
        user_id, error = require_user_id()
        if error:
            return error
        session_id, error = require_session_id()
        if error:
            return error
        session_error = await validate_session_for_user(server, user_id, session_id)
        if session_error:
            return session_error

        profile = await server.db_service.get_user_profile(user_id)
        if not profile:
            return jsonify({"error": "User profile not found"}), 404

        dto = user_profile_to_dto(profile)
        response = jsonify(dto.model_dump(mode="json"))
        return add_cache_headers(response, **CACHE_PRESETS["user_data"])

    @bp.route("/profile", methods=["PUT"])
    async def update_user_profile():
        """Replace a user profile (full update)."""
        try:
            data = await request.get_json() or {}
            if "status" in data:
                return jsonify({"error": "Status updates are not allowed"}), 400
            try:
                update_request = UpdateUserProfileRequestDTO(**data)
            except ValidationError as error:
                return validation_error_response(error)

            session_error = await validate_session_for_user(
                server, update_request.user_id, update_request.session_id
            )
            if session_error:
                return session_error

            existing = await server.db_service.get_user_profile(update_request.user_id)
            if not existing:
                return jsonify({"error": "User profile not found"}), 404

            new_profile = existing.model_copy(
                update={
                    "name": update_request.name,
                    "alias": update_request.alias,
                    "data_of_birth": update_request.data_of_birth,
                    "gender": update_request.gender,
                    "cultural_background": update_request.cultural_background,
                    "primary_language": update_request.primary_language,
                    "profession": update_request.profession,
                    "parents": update_request.parents,
                    "siblings": update_request.siblings,
                    "family_atmosphere": update_request.family_atmosphere,
                    "significant_events": update_request.significant_events,
                    "education": update_request.education,
                    "work_history": update_request.work_history,
                    "relationship_to_work": update_request.relationship_to_work,
                    "relationships": update_request.relationships,
                    "social_context": update_request.social_context,
                    "current_situation": update_request.current_situation,
                    "preferred_school": update_request.preferred_school,
                    "boundary_notes": update_request.boundary_notes,
                    "frame_notes": update_request.frame_notes,
                    "updated_at": datetime.now(),
                }
            )

            saved = await server.db_service.update_user_profile(new_profile)
            if not saved:
                return jsonify({"error": "Failed to update user profile"}), 500

            dto = user_profile_to_dto(new_profile)
            return jsonify(dto.model_dump(mode="json"))

        except ValueError as exc:
            logger.error("Validation error updating profile: %s", exc)
            return jsonify({"error": str(exc)}), 400

    @bp.route("/profile", methods=["PATCH"])
    async def patch_user_profile():
        """Apply partial updates to a user profile."""
        try:
            data = await request.get_json() or {}
            if "status" in data:
                return jsonify({"error": "Status updates are not allowed"}), 400
            try:
                patch_request = PatchUserProfileRequestDTO(**data)
            except ValidationError as error:
                return validation_error_response(error)

            session_error = await validate_session_for_user(
                server, patch_request.user_id, patch_request.session_id
            )
            if session_error:
                return session_error

            existing = await server.db_service.get_user_profile(patch_request.user_id)
            if not existing:
                return jsonify({"error": "User profile not found"}), 404

            updates = patch_request.model_dump(exclude_unset=True)
            updates.pop("user_id", None)
            updates.pop("session_id", None)
            updates["updated_at"] = datetime.now()

            new_profile = existing.model_copy(update=updates)

            saved = await server.db_service.update_user_profile(new_profile)
            if not saved:
                return jsonify({"error": "Failed to update user profile"}), 500

            dto = user_profile_to_dto(new_profile)
            return jsonify(dto.model_dump(mode="json"))

        except ValueError as exc:
            logger.error("Validation error updating profile: %s", exc)
            return jsonify({"error": str(exc)}), 400

    return bp
