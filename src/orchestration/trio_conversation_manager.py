"""
Trio-native conversation manager for streaming responses and context management.

This module manages conversation context, streams LLM responses using Trio,
and integrates RAG retrieval for enhanced responses.
"""

import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import trio

from config import settings
from models.data_models import Message, TherapyPlan
from orchestration.models import ConversationContext
from services.llm_service import LLMService
from services.rag_service import RAGService
from services.trio_db_service import TrioDatabaseService

logger = logging.getLogger(__name__)


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
        rag_service: RAGService,
        trio_db_service: TrioDatabaseService,
        nursery: trio.Nursery,
    ):
        """
        Initialize the Trio conversation manager.

        Args:
            llm_service: Service for LLM API calls (synchronous)
            rag_service: Service for RAG knowledge retrieval (synchronous)
            trio_db_service: Trio database service
            nursery: The Trio nursery for spawning background tasks.
        """
        self.llm_service = llm_service
        self.rag_service = rag_service
        self.db_service = trio_db_service
        self.active_contexts: dict[str, ConversationContext] = {}
        self.nursery = nursery
        self.websockets: dict[str, Any] = {}

    def register_websocket(self, session_id: str, ws: Any):
        """Registers a websocket for a given session."""
        self.websockets[session_id] = ws
        logger.info(f"Registered websocket for session {session_id}")

    def unregister_websocket(self, session_id: str):
        """Unregisters a websocket for a given session."""
        if session_id in self.websockets:
            del self.websockets[session_id]
            logger.info(f"Unregistered websocket for session {session_id}")

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
        ws = self.websockets.get(session_id)
        if ws:
            try:
                await ws.send(
                    json.dumps(
                        {
                            "type": "chat_response_chunk",
                            "data": {"chunk": chunk, "is_complete": is_complete},
                        }
                    )
                )
            except Exception as e:
                logger.error(f"Error sending chunk to session {session_id}: {e}")

    async def send_typing_indicator(self, session_id: str, is_typing: bool):
        """
        Sends typing indicator to the session's websocket.

        Args:
            session_id: Session identifier
            is_typing: Whether typing started (True) or stopped (False)
        """
        ws = self.websockets.get(session_id)
        if ws:
            try:
                msg_type = "typing_start" if is_typing else "typing_stop"
                await ws.send(json.dumps({"type": msg_type}))
            except Exception as e:
                logger.error(
                    f"Error sending typing indicator to session {session_id}: {e}"
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
        ws = self.websockets.get(session_id)
        if not ws:
            logger.error(
                f"No websocket registered for session {session_id}. "
                f"Cannot stream background response."
            )
            return

        context = await self.get_context(session_id)
        is_streaming = False
        try:
            async for chunk in self.stream_response(prompt, context, use_rag):
                if not is_streaming:
                    is_streaming = True
                    await ws.send(json.dumps({"type": "typing_start"}))

                response_chunk = {
                    "type": "chat_response_chunk",
                    "data": {"chunk": chunk, "is_complete": False},
                }
                await ws.send(json.dumps(response_chunk))

            # Send completion message
            completion_message = {
                "type": "chat_response_chunk",
                "data": {"chunk": "", "is_complete": True},
            }
            await ws.send(json.dumps(completion_message))

        except Exception as e:
            logger.error(
                f"Error in background streamer for session {session_id}: {e}",
                exc_info=True,
            )
            error_message = {
                "type": "error",
                "data": {
                    "message": (
                        f"An error occurred while generating the initial response: {e}"
                    )
                },
            }
            await ws.send(json.dumps(error_message))
        finally:
            if is_streaming:
                await ws.send(json.dumps({"type": "typing_stop"}))

    async def stream_response(
        self, prompt: str, context: ConversationContext, use_rag: bool = True
    ) -> AsyncIterator[str]:
        """
        Stream LLM response chunks using Trio.

        Args:
            prompt: The prompt to send to LLM
            context: Conversation context
            use_rag: Whether to use RAG for enhanced responses

        Yields:
            Response chunks as they're generated
        """
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
                augmented_prompt, conversation_history
            ):
                full_response += chunk
                chunk_count += 1
                yield chunk

            logger.info(
                f"Streamed response complete: {len(full_response)} chars, "
                f"{chunk_count} chunks"
            )

            # Save assistant message to database
            await self.add_message(context.session_id, "assistant", full_response)

        except Exception as e:
            import traceback

            tb_str = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            logger.error(f"Error streaming response: {e}", exc_info=True)

            # Yield detailed error with stacktrace
            error_message = f"""
ERROR in trio_conversation_manager.stream_response: {type(e).__name__}: {str(e)}

Session ID: {context.session_id if context else "NO_CONTEXT"}

STACKTRACE:
{tb_str}
"""
            yield error_message
            # Save error message for debugging
            await self.add_message(context.session_id, "assistant", error_message)

    async def _stream_llm_response(
        self, prompt: str, conversation_history: list
    ) -> AsyncIterator[str]:
        """
        Stream response from LLM service using Trio.

        Gets chunks from LLMService (which runs streaming in a thread)
        and yields them in the Trio async context.

        Args:
            prompt: The prompt to send
            conversation_history: Previous conversation messages

        Yields:
            Response chunks from LLM
        """
        try:
            # Get all chunks from LLM service (runs in thread pool)
            chunks = await self.llm_service.generate_response_stream(
                prompt, conversation_history
            )

            # Yield chunks one by one in async context
            for chunk in chunks:
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
            # Run synchronous RAG call in thread
            relevant_docs = await trio.to_thread.run_sync(
                self.rag_service.retrieve_relevant_knowledge,
                query,
                3,  # n_results
                therapy_plan.selected_therapy_style,  # filter_source
            )

            if not relevant_docs:
                logger.warning("No relevant documents found in RAG")
                return ""

            # Format context
            context_parts = []
            for i, doc in enumerate(relevant_docs[:3], 1):  # Top 3 docs
                # Extract text content from doc dict
                if isinstance(doc, dict):
                    text = doc.get("text", str(doc))
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

    async def add_message(self, session_id: str, role: str, content: str) -> None:
        """
        Add message to conversation history and persist to database.

        Args:
            session_id: Session identifier
            role: Message role ("user" or "assistant")
            content: Message content
        """
        try:
            # Create message
            message = Message(role=role, content=content, timestamp=datetime.now())

            # Update active context if exists
            if session_id in self.active_contexts:
                self.active_contexts[session_id].message_history.append(message)
                logger.debug(f"Added message to active context: {session_id} ({role})")

            # Persist to database
            session = await self.db_service.get_session(session_id)
            if session:
                session.transcript.append(message)
                await self.db_service.save_session(session)
                logger.info(f"Persisted message for session {session_id}: {role}")
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
            session = await self.db_service.get_session(session_id)
            if not session:
                raise ValueError(f"Session not found: {session_id}")

            user_profile = await self.db_service.get_user_profile(session.user_id)
            if not user_profile:
                raise ValueError(f"User profile not found: {session.user_id}")

            # Get current therapy plan if exists
            therapy_plan = None
            try:
                therapy_plan = await self.db_service.get_latest_therapy_plan(
                    session.user_id
                )
            except Exception as e:
                logger.warning(f"No therapy plan found for user {session.user_id}: {e}")

            # Build context
            context = ConversationContext(
                session_id=session_id,
                user_profile=user_profile,
                therapy_plan=therapy_plan,
                message_history=session.transcript,
                topics_covered=[topic.name for topic in session.topics],
                session_start_time=session.timestamp,
                duration_minutes=settings.SESSION_DURATION_MINUTES,
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

    def get_active_sessions(self) -> list:
        """
        Get list of active session IDs.

        Returns:
            List of session IDs with cached contexts
        """
        return list(self.active_contexts.keys())
