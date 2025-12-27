"""Therapy style and plan routes."""

from __future__ import annotations

import logging
from quart import Blueprint, jsonify, request
from pydantic import ValidationError

from psychoanalyst_app.api.cache_utils import CACHE_PRESETS, add_cache_headers
from psychoanalyst_app.api.http_errors import validation_error_response
from psychoanalyst_app.api.request_utils import require_user_id
from psychoanalyst_app.models.http_models import (
    CreateTherapyPlanRequestDTO,
    TherapyStyleDTO,
    therapy_plan_to_dto,
)


def create_therapy_routes(server) -> Blueprint:
    """Create blueprint for therapy style and plan endpoints."""
    logger = logging.getLogger(__name__)
    bp = Blueprint("therapy", __name__, url_prefix="/api/therapy")
    @bp.route("/styles", methods=["GET"])
    async def get_therapy_styles():
        """Get available therapy styles with descriptions."""
        style_service = server.container.get("style_service")
        styles = style_service.get_available_styles()

        result = []
        for style_id in styles:
            style_pack = style_service.get_style_pack(style_id)
            result.append(
                TherapyStyleDTO(
                    style=style_id,
                    name=style_id.capitalize(),
                    description=(
                        style_pack.description
                        if style_pack
                        else f"{style_id} therapy approach"
                    ),
                ).model_dump(mode="json")
            )

        response = jsonify(result)
        return add_cache_headers(response, **CACHE_PRESETS["static_long"])

    @bp.route("/plan", methods=["GET"])
    async def get_therapy_plan():
        """Get therapy plan for a user."""
        user_id, error = require_user_id()
        if error:
            return error
        plan = await server.db_service.get_latest_therapy_plan(user_id)
        if not plan:
            return jsonify(None)
        dto = therapy_plan_to_dto(plan)
        return jsonify(dto.model_dump(mode="json"))

    @bp.route("/plan", methods=["POST"])
    async def create_therapy_plan():
        """Create a therapy plan for a user."""
        data = await request.get_json() or {}
        try:
            plan_request = CreateTherapyPlanRequestDTO(**data)
        except ValidationError as error:
            return validation_error_response(error)

        try:
            plan = await server.orchestrator.create_therapy_plan(
                plan_request.user_id, plan_request.therapy_style
            )
            dto = therapy_plan_to_dto(plan)
            return jsonify(dto.model_dump(mode="json")), 201
        except ValueError as exc:
            logger.error("Validation error creating therapy plan: %s", exc)
            status = 404 if "not found" in str(exc).lower() else 400
            return jsonify({"error": str(exc)}), status

    return bp
