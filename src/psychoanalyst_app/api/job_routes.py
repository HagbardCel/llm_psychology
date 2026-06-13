"""Backend job/progress status endpoints."""

from __future__ import annotations

from quart import Blueprint, jsonify

from psychoanalyst_app.api._helpers import require_user_id
from psychoanalyst_app.orchestration.job_status import (
    JobStatusNotFound,
    resolve_job_status,
)


def create_job_routes(server) -> Blueprint:
    """Create blueprint for workflow job status endpoints."""
    bp = Blueprint("jobs", __name__, url_prefix="/api/jobs")

    @bp.route("/<path:job_id>", methods=["GET"])
    async def get_job_status(job_id: str):
        user_id, error = require_user_id()
        if error:
            return error
        try:
            status = await resolve_job_status(
                job_id=job_id,
                user_id=user_id,
                db_service=server.db_service,
                workflow_engine=server.workflow_engine,
                response_handler=server.orchestrator.response_handler,
            )
        except JobStatusNotFound:
            return jsonify({"error": "Job not found"}), 404
        return jsonify(status.model_dump(mode="json")), 200

    return bp
