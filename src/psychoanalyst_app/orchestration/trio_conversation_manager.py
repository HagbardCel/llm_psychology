"""Trio-native conversation context, streaming, and RAG integration."""
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import trio
from werkzeug.local import LocalProxy

from psychoanalyst_app.config import Settings
from psychoanalyst_app.models.domain import Message, TherapyPlan
from psychoanalyst_app.orchestration.models import ConversationContext
from psychoanalyst_app.orchestration.runtime.session_bootstrap import (
    load_conversation_context,
)
from psychoanalyst_app.orchestration.runtime.stream_dispatch import (
    run_background_streamer,
    send_json_message,
    send_stream_chunk,
    send_typing_indicator,
)
from psychoanalyst_app.services.llm_service import LLMService
from psychoanalyst_app.services.rag import RAGServiceProtocol
from psychoanalyst_app.services.trio_db_service import TrioDatabaseService

logger = logging.getLogger(__name__)

MAX_CONSECUTIVE_LLM_FAILURES = 2
LLM_RETRY_ERROR_MESSAGE = (
    "I ran into a problem while generating that response. Let's try again."
)
LLM_TERMINAL_ERROR_MESSAGE = (
    "I am unable to generate a response right now. Please pause and try again later."
)


class TrioConversationManager:
    """
    Trio-native manager for conversation context and streaming LLM responses.

    This class handles:
    - Streaming LLM responses token-by-token
    - Managing conversation context and history
    - RAG retrieval integration
    - Topic tracking
    - Time-aware session management
    """

    def __init__(
        self,
        llm_service: LLMService,
        rag_service: RAGServiceProtocol,
        trio_db_service: TrioDatabaseService,
        nursery: trio.Nursery,
        config: Settings,
    ):
        """
        Initialize the Trio conversation manager.

        Args:
            llm_service: Service for LLM API calls (synchronous)
            rag_service: Service for RAG knowledge retrieval (synchronous)
            trio_db_service: Trio database service
            nursery: The Trio nursery for spawning background tasks.
            config: Application settings
        """
        self.llm_service = llm_service
        self.rag_service = rag_service
        self.db_service = trio_db_service
        self.active_contexts: dict[str, ConversationContext] = {}
        self.nursery = nursery
        self.websockets: dict[str, Any] = {}
        self._websocket_ready_events: dict[str, trio.Event] = {}
        self._initial_greeting_sent: set[str] = set()
        self._initial_greeting_pending: set[str] = set()
        self._llm_failure_counts: dict[str, int] = {}
        self.config = config

    def register_websocket(self, session_id: str, ws: Any):
        """Registers a websocket for a given session."""
        self.websockets[session_id] = ws._get_current_object() if isinstance(ws, LocalProxy) else ws
        event = self._websocket_ready_events.get(session_id)
        if event is None:
            event = trio.Event()
            self._websocket_ready_events[session_id] = event
        event.set()
        if session_id not in self._initial_greeting_pending:
            self._initial_greeting_sent.discard(session_id)
        logger.info(f"Registered websocket for session {session_id}")

    def unregister_websocket(self, session_id: str):
        """Unregisters a websocket for a given session."""
        if session_id in self.websockets:
            del self.websockets[session_id]
        if session_id in self._websocket_ready_events:
            del self._websocket_ready_events[session_id]
        self._llm_failure_counts.pop(session_id, None)
        logger.info(f"Unregistered websocket for session {session_id}")

    def mark_initial_greeting_sent(self, session_id: str) -> None:
        """Record that an initial greeting was scheduled for a session."""
        self._initial_greeting_sent.add(session_id)

    def has_initial_greeting_sent(self, session_id: str) -> bool:
        """Check whether the initial greeting was already scheduled."""
        return session_id in self._initial_greeting_sent

    def claim_initial_greeting(self, session_id: str) -> bool:
        if session_id in self._initial_greeting_sent:
            return False
        self.mark_initial_greeting_pending(session_id)
        return True

    def mark_initial_greeting_pending(self, session_id: str) -> None:
        self._initial_greeting_sent.add(session_id)
        self._initial_greeting_pending.add(session_id)

    def mark_initial_greeting_complete(self, session_id: str) -> None:
        """Allow chat input after initial greeting delivery finishes."""
        self._initial_greeting_pending.discard(session_id)

    def is_initial_greeting_pending(self, session_id: str) -> bool:
        """Return whether a session is still delivering its initial greeting."""
        return session_id in self._initial_greeting_pending

    async def wait_for_websocket(self, session_id: str, *, timeout_seconds: float) -> bool:
        """Wait until a websocket is registered for the given session."""
        if session_id in self.websockets:
            return True

        event = self._websocket_ready_events.get(session_id)
        if event is None:
            event = trio.Event()
            self._websocket_ready_events[session_id] = event

        with trio.move_on_after(timeout_seconds) as scope:
            await event.wait()

        return not scope.cancelled_caught and session_id in self.websockets

    async def send_stream_chunk(
        self, session_id: str, chunk: str, is_complete: bool = False
    ):
        """
        Sends a response chunk to the session's websocket.

        Args:
            session_id: Session identifier
            chunk: Text chunk to send
            is_complete: Whether this is the final chunk
        """
        await send_stream_chunk(
            websockets=self.websockets,
            session_id=session_id,
            chunk=chunk,
            is_complete=is_complete,
        )

    async def send_typing_indicator(self, session_id: str, is_typing: bool):
        """
        Sends typing indicator to the session's websocket.

        Args:
            session_id: Session identifier
            is_typing: Whether typing started (True) or stopped (False)
        """
        await send_typing_indicator(
            websockets=self.websockets,
            session_id=session_id,
            is_typing=is_typing,
        )

    async def send_json_message(
        self, session_id: str, message_type: str, data: dict[str, Any]
    ):
        """
        Sends an arbitrary JSON message to the session websocket.

        Args:
            session_id: Session identifier
            message_type: Type string for the payload
            data: JSON-serializable payload
        """
        await send_json_message(
            websockets=self.websockets,
            session_id=session_id,
            message_type=message_type,
            data=data,
        )

    def stream_response_in_background(
        self, prompt: str, session_id: str, use_rag: bool = True
    ):
        """
        Starts a background task to stream a response to the client.

        Args:
            prompt: The prompt to generate a response for.
            session_id: The session ID to send the response to.
            use_rag: Whether to use RAG for the response.
        """
        self.nursery.start_soon(self._background_streamer, prompt, session_id, use_rag)

    async def _background_streamer(self, prompt: str, session_id: str, use_rag: bool):
        """The actual background task that streams the response."""
        async def _stream(context: ConversationContext):
            async for chunk in self.stream_response(prompt, context, use_rag):
                yield chunk

        await run_background_streamer(
            session_id=session_id,
            websockets=self.websockets,
            get_context=self.get_context,
            stream_response=_stream,
        )

    async def stream_response(
        self,
        prompt: str,
        context: ConversationContext,
        use_rag: bool = True,
        agent: str | None = None,
        llm_service: LLMService | None = None,
    ) -> AsyncIterator[str]:
        """
        Stream LLM response chunks using Trio.

        Args:
            prompt: The prompt to send to LLM
            context: Conversation context
            use_rag: Whether to use RAG for enhanced responses
            agent: Name of the agent generating the response
            llm_service: Optional agent-specific LLM service
                (defaults to self.llm_service)

        Yields:
            Response chunks as they're generated
        """
        service = llm_service if llm_service is not None else self.llm_service
        try:
            # Retrieve RAG context if needed and therapy plan exists
            augmented_prompt = prompt
            if use_rag and context.therapy_plan:
                logger.info(
                    f"Retrieving RAG context for style: "
                    f"{context.therapy_plan.selected_therapy_style}"
                )
                rag_context = await self._retrieve_rag_context(
                    prompt, context.therapy_plan
                )
                augmented_prompt = self._augment_prompt(prompt, rag_context)
                logger.debug(f"Augmented prompt: {augmented_prompt[:200]}...")

            # Convert message history to context format
            conversation_history = self._build_conversation_history(context)

            # Stream LLM response
            full_response = ""
            chunk_count = 0

            async for chunk in self._stream_llm_response(
                augmented_prompt,
                conversation_history,
                service,
                phase=(
                    "therapy_opening"
                    if agent == "THERAPIST"
                    and not any(message.role == "user" for message in context.message_history)
                    else "therapy_response" if agent == "THERAPIST" else None
                ),
            ):
                full_response += chunk
                chunk_count += 1
                yield chunk

            logger.info(
                f"Streamed response complete: {len(full_response)} chars, "
                f"{chunk_count} chunks"
            )

            # Save assistant message to database
            await self.add_message(
                context.session_id, "assistant", full_response, agent
            )
            self._reset_llm_failure_count(context.session_id)

        except Exception as e:
            import traceback

            tb_str = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            failure_count = self._record_llm_failure(context.session_id, service, e)
            logger.error(
                "Error streaming response for session %s "
                "(consecutive_llm_failures=%s): %s\n%s",
                context.session_id,
                failure_count,
                e,
                tb_str,
                exc_info=True,
            )

            error_summary = LLM_RETRY_ERROR_MESSAGE
            if failure_count >= MAX_CONSECUTIVE_LLM_FAILURES:
                error_summary = LLM_TERMINAL_ERROR_MESSAGE
                logger.error(
                    "Consecutive LLM failure limit reached for session %s",
                    context.session_id,
                )

            yield error_summary
            await self.add_message(
                context.session_id,
                "assistant",
                f"{error_summary}\n\nDetails logged as {type(e).__name__}.",
                agent,
            )

    def _reset_llm_failure_count(self, session_id: str) -> None:
        self._llm_failure_counts.pop(session_id, None)

    def _record_llm_failure(
        self, session_id: str, llm_service: LLMService, exc: Exception
    ) -> int:
        failure_count = self._llm_failure_counts.get(session_id, 0) + 1
        self._llm_failure_counts[session_id] = failure_count

        llm_client = getattr(llm_service, "llm", None)
        extra_body = getattr(llm_client, "extra_body", None)
        extra_body_keys = (
            sorted(str(key) for key in extra_body)
            if isinstance(extra_body, dict)
            else []
        )
        logger.error(
            "LLM generation failure metadata: provider=%s model=%s base_url=%s "
            "exception_type=%s exception_message=%s request_extra_body_keys=%s",
            getattr(llm_service, "provider", "unknown"),
            getattr(llm_service, "model_name", "unknown"),
            getattr(llm_service, "base_url", None),
            type(exc).__name__,
            str(exc),
            extra_body_keys,
        )
        return failure_count

    async def stream_static_response(
        self, content: str, context: ConversationContext, agent: str | None = None
    ) -> AsyncIterator[str]:
        """
        Stream static content as if it were an LLM response.

        Args:
            content: The static content to stream
            context: Conversation context
            agent: Name of the agent generating the response

        Yields:
            Content chunks
        """
        try:
            # Split content into chunks (e.g., by words or small segments)
            # For simplicity, we can just yield the whole thing or split by lines/spaces
            # Let's simulate streaming for better UX
            chunk_size = 10
            for i in range(0, len(content), chunk_size):
                chunk = content[i : i + chunk_size]
                yield chunk
                await trio.sleep(0.01)  # Small delay for effect

            # Save assistant message to database
            logger.info(
                f"DEBUG: stream_static_response calling add_message for session {context.session_id}"
            )
            await self.add_message(context.session_id, "assistant", content, agent)

        except Exception as e:
            logger.error(f"Error streaming static response: {e}", exc_info=True)
            yield f"Error: {str(e)}"

    async def _stream_llm_response(
        self,
        prompt: str,
        conversation_history: list,
        llm_service: LLMService,
        *,
        phase: str | None = None,
    ) -> AsyncIterator[str]:
        """
        Stream response from LLM service using Trio.

        Gets chunks from LLMService (which runs streaming in a thread)
        and yields them in the Trio async context.

        Args:
            prompt: The prompt to send
            conversation_history: Previous conversation messages
            llm_service: LLM service to use for streaming

        Yields:
            Response chunks from LLM
        """
        try:
            stream = (
                llm_service.stream_response(prompt, conversation_history)
                if phase is None
                else llm_service.stream_response(
                    prompt, conversation_history, phase=phase
                )
            )
            async for chunk in stream:
                yield chunk

        except Exception as e:
            logger.error(f"Error in LLM streaming: {e}", exc_info=True)
            raise

    async def _retrieve_rag_context(self, query: str, therapy_plan: TherapyPlan) -> str:
        """
        Retrieve relevant context from RAG system using Trio.

        Args:
            query: User's message/query
            therapy_plan: Current therapy plan with style info

        Returns:
            Relevant context from knowledge base
        """
        try:
            filter_source = therapy_plan.selected_therapy_style
            if filter_source and not filter_source.endswith(".md"):
                filter_source = f"{filter_source}.md"

            # Run synchronous RAG call in thread
            relevant_docs = await trio.to_thread.run_sync(
                self.rag_service.retrieve_relevant_knowledge,
                query,
                3,  # n_results
                filter_source,
            )

            if not relevant_docs:
                logger.warning("No relevant documents found in RAG")
                return ""

            # Format context
            context_parts = []
            for i, doc in enumerate(relevant_docs[:3], 1):  # Top 3 docs
                # Extract text content from doc dict
                if isinstance(doc, dict):
                    text = doc.get("content") or doc.get("text") or str(doc)
                else:
                    text = str(doc)
                context_parts.append(f"[Context {i}]: {text}")

            return "\n\n".join(context_parts)

        except Exception as e:
            logger.error(f"Error retrieving RAG context: {e}", exc_info=True)
            return ""

    def _augment_prompt(self, prompt: str, rag_context: str) -> str:
        """
        Augment prompt with RAG context.

        Args:
            prompt: Original prompt
            rag_context: Context from RAG system

        Returns:
            Augmented prompt
        """
        if not rag_context:
            return prompt

        return f"""
Relevant theoretical context:
{rag_context}

Based on the above context and your therapeutic approach, respond to:
{prompt}
"""

    def _build_conversation_history(self, context: ConversationContext) -> list:
        """
        Build conversation history in format expected by LLMService.

        Args:
            context: Conversation context

        Returns:
            List of message dictionaries
        """
        history = []
        for msg in context.message_history[-10:]:  # Last 10 messages
            history.append({"role": msg.role, "content": msg.content})
        return history

    async def add_message(
        self, session_id: str, role: str, content: str, agent: str | None = None
    ) -> None:
        """
        Add message to conversation history and persist to database.

        Args:
            session_id: Session identifier
            role: Message role ("user" or "assistant")
            content: Message content
            agent: Name of the agent that generated this message (optional)
        """
        try:
            logger.info(
                f"DEBUG: add_message called for {session_id} role={role} agent={agent}"
            )
            # Create message
            message = Message(
                role=role, content=content, timestamp=datetime.now(), agent=agent
            )

            # Update active context if exists
            if session_id in self.active_contexts:
                self.active_contexts[session_id].message_history.append(message)
                logger.debug(f"Added message to active context: {session_id} ({role})")

            # Persist to database
            session = await self.db_service.get_session(session_id)
            if session:
                session.transcript.append(message)
                saved = await self.db_service.save_session(session)
                if saved:
                    logger.info(f"Persisted message for session {session_id}: {role}")
                else:
                    logger.warning(
                        "Did not persist message for session %s (session may be immutable/enriched)",
                        session_id,
                    )
            else:
                logger.warning(
                    f"Session not found for message persistence: {session_id}"
                )

        except Exception as e:
            logger.error(f"Error adding message: {e}", exc_info=True)
            # Don't raise - message persistence is non-critical

    async def get_context(self, session_id: str) -> ConversationContext:
        """
        Get conversation context for a session.

        Args:
            session_id: Session identifier

        Returns:
            Conversation context

        Raises:
            ValueError: If session not found
        """
        # Check cache first
        if session_id in self.active_contexts:
            logger.debug(f"Retrieved context from cache: {session_id}")
            return self.active_contexts[session_id]

        # Load from database
        try:
            context = await load_conversation_context(
                db_service=self.db_service,
                config=self.config,
                session_id=session_id,
            )

            # Cache it
            self.active_contexts[session_id] = context
            logger.info(f"Loaded and cached context for session {session_id}")

            return context

        except Exception as e:
            logger.error(f"Error loading context: {e}", exc_info=True)
            raise

    def clear_context(self, session_id: str) -> None:
        """
        Clear cached context for a session.

        Args:
            session_id: Session identifier
        """
        if session_id in self.active_contexts:
            del self.active_contexts[session_id]
            logger.info(f"Cleared cached context for session {session_id}")
        self._llm_failure_counts.pop(session_id, None)

    def get_active_sessions(self) -> list:
        """
        Get list of active session IDs.

        Returns:
            List of session IDs with cached contexts
        """
        return list(self.active_contexts.keys())
