"""RAG augmentation helpers for conversation orchestration."""

from __future__ import annotations

import logging

import trio

from psychoanalyst_app.models.domain import TherapyPlan
from psychoanalyst_app.services.rag import RAGServiceProtocol

logger = logging.getLogger(__name__)


async def retrieve_rag_context(
    rag_service: RAGServiceProtocol,
    query: str,
    therapy_plan: TherapyPlan,
) -> str:
    """Retrieve and format optional theoretical context."""
    try:
        filter_source = therapy_plan.selected_therapy_style
        if filter_source and not filter_source.endswith(".md"):
            filter_source = f"{filter_source}.md"
        relevant_docs = await trio.to_thread.run_sync(
            rag_service.retrieve_relevant_knowledge,
            query,
            3,
            filter_source,
        )
        context_parts = []
        for index, doc in enumerate(relevant_docs[:3], 1):
            text = (
                doc.get("content") or doc.get("text") or str(doc)
                if isinstance(doc, dict)
                else str(doc)
            )
            context_parts.append(f"[Context {index}]: {text}")
        return "\n\n".join(context_parts)
    except Exception as exc:
        logger.error("Error retrieving RAG context: %s", exc, exc_info=True)
        return ""


def augment_prompt(prompt: str, rag_context: str) -> str:
    """Add retrieved context when the configured retriever returns any."""
    if not rag_context:
        return prompt
    return f"""
Relevant theoretical context:
{rag_context}

Based on the above context and your therapeutic approach, respond to:
{prompt}
"""
