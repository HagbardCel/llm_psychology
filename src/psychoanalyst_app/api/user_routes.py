"""User-related HTTP routes."""

from __future__ import annotations

import logging
from datetime import datetime

from quart import Blueprint, jsonify, request
from pydantic import ValidationError

from psychoanalyst_app.api.cache_utils import CACHE_PRESETS, add_cache_headers
from psychoanalyst_app.api.http_errors import validation_error_response
from psychoanalyst_app.api.request_utils import require_user_id
from psychoanalyst_app.models.http_models import (
    CreateUserProfileRequestDTO,
    PatchUserProfileRequestDTO,
    UpdateUserProfileRequestDTO,
    UserStatusResponseDTO,
    user_profile_to_dto,
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
        state = await server.orchestrator.get_user_state(user_id)
        dto = UserStatusResponseDTO(
            user_id=user_id,
            workflow_state=state,
            timestamp=datetime.utcnow(),
        )
        return jsonify(dto.model_dump(mode="json"))

    @bp.route("/profile", methods=["GET"])
    async def get_user_profile():
        """Get a user profile."""
        user_id, error = require_user_id()
        if error:
            return error

        profile = await server.db_service.get_user_profile(user_id)
        if not profile:
            return jsonify({"error": "User profile not found"}), 404

        dto = user_profile_to_dto(profile)
        response = jsonify(dto.model_dump(mode="json"))
        return add_cache_headers(response, **CACHE_PRESETS["user_data"])

    @bp.route("/profile", methods=["POST"])
    async def create_user_profile():
        """Create a new user profile."""
        try:
            data = await request.get_json() or {}
            try:
                profile_request = CreateUserProfileRequestDTO(**data)
            except ValidationError as error:
                return validation_error_response(error)

            profile = await server.orchestrator.create_user_profile(
                profile_request.model_dump()
            )
            dto = user_profile_to_dto(profile)
            return jsonify(dto.model_dump(mode="json")), 201

        except ValueError as exc:
            logger.error("Validation error creating profile: %s", exc)
            return jsonify({"error": str(exc)}), 400

    @bp.route("/profile", methods=["PUT"])
    async def update_user_profile():
        """Replace a user profile (full update)."""
        try:
            data = await request.get_json() or {}
            try:
                update_request = UpdateUserProfileRequestDTO(**data)
            except ValidationError as error:
                return validation_error_response(error)

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
                    "status": update_request.status or existing.status,
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
                    "session_mode": update_request.session_mode,
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
            try:
                patch_request = PatchUserProfileRequestDTO(**data)
            except ValidationError as error:
                return validation_error_response(error)

            existing = await server.db_service.get_user_profile(patch_request.user_id)
            if not existing:
                return jsonify({"error": "User profile not found"}), 404

            updates = patch_request.model_dump(exclude_unset=True)
            updates.pop("user_id", None)
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
