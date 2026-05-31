"""Infrastructure factory functions for ServiceContainer."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from psychoanalyst_app.services.db.executor import TrioSQLiteExecutor
from psychoanalyst_app.services.migration_service import MigrationService
from psychoanalyst_app.services.rag import NoOpRAGService
from psychoanalyst_app.services.style_service import StyleService
from psychoanalyst_app.services.trio_db_service import TrioDatabaseService

if TYPE_CHECKING:
    from psychoanalyst_app.container.service_container import ServiceContainer

logger = logging.getLogger(__name__)


def create_migration_service(container: ServiceContainer) -> MigrationService:
    """Create MigrationService."""
    logger.debug("Creating MigrationService")
    migration_service = MigrationService(
        db_path=container.config.DATABASE_PATH,
        busy_timeout_seconds=float(container.config.DATABASE_POOL_TIMEOUT),
    )
    logger.info("Created MigrationService for %s", container.config.DATABASE_PATH)
    return migration_service


def create_trio_db_service(container: ServiceContainer) -> TrioDatabaseService:
    """Create TrioDatabaseService."""
    logger.debug("Creating pure TrioDatabaseService")
    migration_service = container.get("migration_service")
    executor = container.get("db_executor")
    trio_db_service = TrioDatabaseService(
        db_path=container.config.DATABASE_PATH,
        migration_service=migration_service,
        executor=executor,
    )
    logger.info(
        "Created pure TrioDatabaseService for %s", container.config.DATABASE_PATH
    )
    return trio_db_service


def create_db_executor(container: ServiceContainer) -> TrioSQLiteExecutor:
    """Create shared TrioSQLiteExecutor."""
    return TrioSQLiteExecutor(
        container.config.DATABASE_PATH,
        pool_size=container.config.DATABASE_POOL_SIZE,
        connect_timeout_seconds=float(container.config.DATABASE_POOL_TIMEOUT),
        pool_acquire_timeout_seconds=float(container.config.DATABASE_POOL_TIMEOUT),
    )


def create_rag_service(container: ServiceContainer) -> NoOpRAGService:
    """Create RAGService."""
    backend = getattr(container.config, "RAG_BACKEND", "none").lower()
    if backend in {"", "none"}:
        logger.info("Created no-op RAGService (RAG_BACKEND=none)")
        return NoOpRAGService()
    raise ValueError(
        "RAG_BACKEND currently supports only 'none'. "
        "Local FAISS retrieval is deferred to a future extension."
    )


def create_style_service(container: ServiceContainer) -> StyleService:
    """Create StyleService."""
    logger.debug("Creating StyleService")
    style_dir = getattr(container.config, "STYLES_DIR", None) or None
    style_service = StyleService(styles_dir=style_dir)
    logger.info(
        "Created StyleService with %s styles directory",
        style_dir or "package",
    )
    return style_service
