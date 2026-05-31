#!/usr/bin/env python3
"""
Deterministic workflow-probe server entry point.

Runs the Trio backend with deterministic, no-network fakes for LLM and RAG so
console workflow probes can run without API keys or external dependencies.
"""

import logging
import os
import tempfile
from pathlib import Path

import trio

from psychoanalyst_app.config import Settings, setup_logging
from psychoanalyst_app.container.service_container import ServiceContainer
from psychoanalyst_app.testing.fakes import (
    DeterministicLLMService,
    DeterministicRAGService,
)
from psychoanalyst_app.trio_server import TrioServer

logger = logging.getLogger(__name__)


def _configure_e2e_settings(
    settings: Settings, *, db_path: str, vector_db_path: str
) -> None:
    settings.APP_ENV = "e2e"
    settings.DATABASE_PATH = db_path
    settings.VECTOR_DB_PATH = vector_db_path

    # Some services may check for a key at creation time; we replace the LLM service,
    # but setting a dummy keeps configuration checks harmless.
    if not settings.GOOGLE_API_KEY:
        settings.GOOGLE_API_KEY = "e2e_dummy_key_not_used"


async def main() -> int:
    host = os.getenv("SERVER_HOST", "127.0.0.1")
    port = int(os.getenv("SERVER_PORT", "8000"))

    settings = Settings()
    setup_logging(settings)

    db_path = os.getenv("E2E_DB_PATH")
    vector_db_path = os.getenv("E2E_VECTOR_DB_PATH")

    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if not db_path or not vector_db_path:
        temp_dir = tempfile.TemporaryDirectory(prefix="psychoanalyst_e2e_")
        base_dir = Path(temp_dir.name)
        db_path = db_path or str(base_dir / "e2e.db")
        vector_db_path = vector_db_path or str(base_dir / "vector_db")

    _configure_e2e_settings(settings, db_path=db_path, vector_db_path=vector_db_path)

    logger.info("Starting deterministic workflow-probe server on %s:%s", host, port)
    logger.info("Deterministic probe DB: %s", db_path)

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


def cli() -> int:
    """CLI adapter so this module can be used as a console script."""
    return trio.run(main)


if __name__ == "__main__":
    raise SystemExit(cli())
