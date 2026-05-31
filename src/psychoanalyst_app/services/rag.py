"""Retrieval-augmented generation service (no-op default)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class RAGServiceProtocol(Protocol):
    """Protocol for RAG service implementations."""

    backend: str

    def retrieve_relevant_knowledge(
        self, query: str, n_results: int = 3, filter_source: str | None = None
    ) -> list[dict[str, Any]]: ...

    def get_knowledge_by_source(self, source: str) -> list[dict[str, Any]]: ...

    def add_user_session_to_rag(
        self, session_summary: str, keywords: list[str], session_id: str
    ) -> None: ...

    def retrieve_relevant_user_history(
        self, query: str, user_id: str, n_results: int = 2
    ) -> list[dict[str, Any]]: ...


class NoOpRAGService:
    """RAG service implementation used when local retrieval is disabled."""

    backend = "none"

    def retrieve_relevant_knowledge(
        self, query: str, n_results: int = 3, filter_source: str | None = None
    ) -> list[dict[str, Any]]:
        return []

    def get_knowledge_by_source(self, source: str) -> list[dict[str, Any]]:
        return []

    def add_user_session_to_rag(
        self, session_summary: str, keywords: list[str], session_id: str
    ) -> None:
        return None

    def retrieve_relevant_user_history(
        self, query: str, user_id: str, n_results: int = 2
    ) -> list[dict[str, Any]]:
        return []
