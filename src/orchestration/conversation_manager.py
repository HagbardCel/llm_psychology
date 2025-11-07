"""
Conversation manager for handling streaming responses and context management.

This module manages conversation context, streams LLM responses, and integrates
RAG retrieval for enhanced responses.
"""

import logging
from datetime import datetime
from typing import AsyncIterator, Dict, Optional

from src.models.data_models import Message, TherapyPlan
from src.orchestration.models import ConversationContext
from src.services.db_service import DatabaseService
from src.services.llm_service import LLMService
from src.services.rag_service import RAGService

logger = logging.getLogger(__name__)


class ConversationManager:
    """
    Manages conversation context and streaming LLM responses.

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
        db_service: DatabaseService,
    ):
        """
        Initialize the conversation manager.

        Args:
            llm_service: Service for LLM API calls
            rag_service: Service for RAG knowledge retrieval
            db_service: Service for database operations
        """
        self.llm_service = llm_service
        self.rag_service = rag_service
        self.db_service = db_service
        self.active_contexts: Dict[str, ConversationContext] = {}

    async def stream_response(
        self, prompt: str, context: ConversationContext, use_rag: bool = True
    ) -> AsyncIterator[str]:
        """
        Stream LLM response chunks.

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
                    f"{context.therapy_plan.selected_style}"
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
            logger.error(f"Error streaming response: {e}", exc_info=True)
            error_message = (
                "I apologize, but I'm having trouble processing your "
                "request right now."
            )
            yield error_message
            # Save error message
            await self.add_message(context.session_id, "assistant", error_message)

    async def _stream_llm_response(
        self, prompt: str, conversation_history: list
    ) -> AsyncIterator[str]:
        """
        Stream response from LLM service.

        This is a wrapper around LLMService to add async streaming support.

        Args:
            prompt: The prompt to send
            conversation_history: Previous conversation messages

        Yields:
            Response chunks
        """
        # For now, simulate streaming by chunking the synchronous response
        # TODO: Update LLMService to support native async streaming
        try:
            # Get synchronous response
            response = self.llm_service.generate_response(
                prompt, conversation_history
            )

            # Simulate streaming by yielding chunks
            chunk_size = 20  # Characters per chunk
            for i in range(0, len(response), chunk_size):
                chunk = response[i : i + chunk_size]
                yield chunk

        except Exception as e:
            logger.error(f"Error in LLM streaming: {e}", exc_info=True)
            raise

    async def _retrieve_rag_context(
        self, query: str, therapy_plan: TherapyPlan
    ) -> str:
        """
        Retrieve relevant context from RAG system.

        Args:
            query: User's message/query
            therapy_plan: Current therapy plan with style info

        Returns:
            Relevant context from knowledge base
        """
        try:
            # Retrieve relevant documents
            relevant_docs = await self.rag_service.retrieve_relevant_knowledge(
                query, therapy_plan.selected_style
            )

            if not relevant_docs:
                logger.warning("No relevant documents found in RAG")
                return ""

            # Format context
            context_parts = []
            for i, doc in enumerate(relevant_docs[:3], 1):  # Top 3 docs
                context_parts.append(f"[Context {i}]: {doc}")

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

    def _build_conversation_history(
        self, context: ConversationContext
    ) -> list:
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
        self, session_id: str, role: str, content: str
    ) -> None:
        """
        Add message to conversation history and persist to database.

        Args:
            session_id: Session identifier
            role: Message role ("user" or "assistant")
            content: Message content
        """
        try:
            # Create message
            message = Message(
                role=role,
                content=content,
                timestamp=datetime.now()
            )

            # Update active context if exists
            if session_id in self.active_contexts:
                self.active_contexts[session_id].message_history.append(message)
                logger.debug(
                    f"Added message to active context: {session_id} ({role})"
                )

            # Persist to database
            await self.db_service.add_message_to_session(session_id, message)
            logger.info(f"Persisted message for session {session_id}: {role}")

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
                therapy_plan = await self.db_service.get_current_therapy_plan(
                    session.user_id
                )
            except Exception as e:
                logger.warning(f"No therapy plan found: {e}")

            # Create context
            context = ConversationContext(
                session_id=session_id,
                user_profile=user_profile,
                therapy_plan=therapy_plan,
                message_history=session.messages or [],
                topics_covered=[],  # TODO: Extract from session metadata
                session_start_time=session.created_at,
                duration_minutes=30,  # Default duration
            )

            # Cache context
            self.active_contexts[session_id] = context
            logger.info(f"Loaded and cached context for session: {session_id}")

            return context

        except Exception as e:
            logger.error(f"Error getting context: {e}", exc_info=True)
            raise

    async def update_context(
        self, session_id: str, updates: Dict
    ) -> None:
        """
        Update conversation context.

        Args:
            session_id: Session identifier
            updates: Dictionary of updates to apply
        """
        if session_id not in self.active_contexts:
            logger.warning(f"Attempted to update non-cached context: {session_id}")
            return

        context = self.active_contexts[session_id]

        # Apply updates
        for key, value in updates.items():
            if hasattr(context, key):
                setattr(context, key, value)
                logger.debug(f"Updated context {session_id}: {key} = {value}")
            else:
                logger.warning(f"Invalid context attribute: {key}")

    def clear_context(self, session_id: str) -> None:
        """
        Clear cached context for a session.

        Args:
            session_id: Session identifier
        """
        if session_id in self.active_contexts:
            del self.active_contexts[session_id]
            logger.info(f"Cleared context cache for session: {session_id}")
