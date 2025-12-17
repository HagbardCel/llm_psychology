#!/usr/bin/env python3
"""
Deterministic E2E server entry point.

Runs the Trio backend with deterministic, no-network fakes for LLM and RAG so
frontend Playwright E2E can run without API keys or external dependencies.
"""

import logging
import os
import sys
import tempfile
from pathlib import Path

import trio

# Ensure relative paths (logs/, data/, etc.) resolve from repo root even when
# this script is started from another working directory (e.g., `frontend/`).
_REPO_ROOT = Path(__file__).resolve().parent.parent
os.chdir(_REPO_ROOT)

# Add the src directory to the Python path (script can be started from repo root).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import settings, setup_logging
from container.service_container import ServiceContainer
from testing.fakes import DeterministicLLMService, DeterministicRAGService
from trio_server import TrioServer

setup_logging()
logger = logging.getLogger(__name__)


def _configure_e2e_settings(*, db_path: str, vector_db_path: str) -> None:
    # Keep auth enabled so browser flows match production, but avoid any external keys.
    settings.APP_ENV = "e2e"
    settings.DATABASE_PATH = db_path
    settings.VECTOR_DB_PATH = vector_db_path

    # Ensure auth can mint tokens even if secrets are not configured locally.
    if not settings.JWT_SECRET_KEY:
        settings.JWT_SECRET_KEY = "e2e_insecure_dev_secret"

    # Some services may check for a key at creation time; we replace the LLM service,
    # but setting a dummy keeps configuration checks harmless.
    if not settings.GOOGLE_API_KEY:
        settings.GOOGLE_API_KEY = "e2e_dummy_key_not_used"


async def main() -> int:
    host = os.getenv("SERVER_HOST", "127.0.0.1")
    port = int(os.getenv("SERVER_PORT", "8000"))

    db_path = os.getenv("E2E_DB_PATH")
    vector_db_path = os.getenv("E2E_VECTOR_DB_PATH")

    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if not db_path or not vector_db_path:
        temp_dir = tempfile.TemporaryDirectory(prefix="psychoanalyst_e2e_")
        base_dir = Path(temp_dir.name)
        db_path = db_path or str(base_dir / "e2e.db")
        vector_db_path = vector_db_path or str(base_dir / "vector_db")

    _configure_e2e_settings(db_path=db_path, vector_db_path=vector_db_path)

    logger.info("Starting deterministic E2E server on %s:%s", host, port)
    logger.info("E2E DB: %s", db_path)

    container = ServiceContainer(settings)
    container.register("llm_service", DeterministicLLMService())
    container.register("rag_service", DeterministicRAGService())

    server = TrioServer(container, host=host, port=port)
    try:
        await server.run()
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()

    return 0


if __name__ == "__main__":
    raise SystemExit(trio.run(main))
