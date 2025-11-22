import logging
from typing import Any

import trio
from langchain_classic.chains import LLMChain
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

from exceptions import LLMServiceError

logger = logging.getLogger(__name__)


class LLMService:
    """Service for handling LLM API calls."""

    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash"):
        """
        Initialize the LLM service.

        Args:
            api_key (str): Google Gemini API key.
            model_name (str): Name of the LLM model to use.
        """
        self.api_key = api_key
        self.model_name = model_name
        self.llm = ChatGoogleGenerativeAI(
            model=model_name, google_api_key=api_key, temperature=0.7
        )

    def generate_response(
        self, prompt: str, context: list[dict[str, str]] | None = None
    ) -> str:
        """
        Generate a response from the LLM.

        Args:
            prompt (str): The prompt to send to the LLM.
            context (Optional[List[Dict[str, str]]]): Optional conversation history.

        Returns:
            str: The LLM's response.
        """
        try:
            if context:
                # Convert context to LangChain message format
                messages = []
                for msg in context:
                    if msg["role"] == "system":
                        messages.append(SystemMessage(content=msg["content"]))
                    elif msg["role"] == "user":
                        messages.append(HumanMessage(content=msg["content"]))
                    elif msg["role"] == "assistant":
                        messages.append(AIMessage(content=msg["content"]))

                # Add the current prompt
                messages.append(HumanMessage(content=prompt))

                # Generate response
                response = self.llm.invoke(messages)
                logger.info(f"Generated LLM response for prompt: {prompt[:100]}...")
                return response.content
            else:
                # Simple prompt without context
                response = self.llm.invoke([HumanMessage(content=prompt)])
                logger.info(
                    f"Generated LLM response for simple prompt: {prompt[:100]}..."
                )
                return response.content
        except Exception as e:
            import traceback

            tb_str = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            logger.error(f"Error generating LLM response: {e}", exc_info=True)
            # Re-raise the exception with full context instead of hiding it
            raise LLMServiceError(
                f"LLM generation failed: {type(e).__name__}: {str(e)}\n\nSTACKTRACE:\n{tb_str}"
            ) from e

    async def generate_response_stream(
        self, prompt: str, context: list[dict[str, str]] | None = None
    ) -> list[str]:
        """
        Generate a streaming response from the LLM, returning chunks as a list.

        This method runs LangChain's streaming in a thread pool and collects
        all chunks. The caller can then yield them in async context.

        Args:
            prompt: The prompt to send to the LLM
            context: Optional conversation history

        Returns:
            List[str]: List of response chunks in order
        """
        try:
            # Build messages
            messages = []
            if context:
                for msg in context:
                    if msg["role"] == "system":
                        messages.append(SystemMessage(content=msg["content"]))
                    elif msg["role"] == "user":
                        messages.append(HumanMessage(content=msg["content"]))
                    elif msg["role"] == "assistant":
                        messages.append(AIMessage(content=msg["content"]))

            messages.append(HumanMessage(content=prompt))

            # Run LLM streaming in a thread - collect all chunks
            def _stream_blocking():
                chunks = []
                for chunk in self.llm.stream(messages):
                    chunk_text = chunk.content
                    if chunk_text:
                        chunks.append(chunk_text)
                return chunks

            # Execute in thread pool and get all chunks
            chunks = await trio.to_thread.run_sync(_stream_blocking)

            logger.info(
                f"Streamed LLM response: {len(chunks)} chunks, {sum(len(c) for c in chunks)} chars"
            )
            return chunks

        except Exception as e:
            import traceback

            tb_str = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            logger.error(f"Error streaming LLM response: {e}", exc_info=True)
            raise LLMServiceError(
                f"LLM streaming failed: {type(e).__name__}: {str(e)}\n\nSTACKTRACE:\n{tb_str}"
            ) from e

    def generate_structured_response(
        self, prompt: str, output_format: str
    ) -> dict[str, Any]:
        """
        Generate a structured response from the LLM.

        Args:
            prompt (str): The prompt to send to the LLM.
            output_format (str): Description of the expected output format.

        Returns:
            Dict[str, Any]: The structured response.
        """
        try:
            # Create a prompt that instructs the LLM to return JSON
            structured_prompt = f"""
            {prompt}
            
            Please provide your response in JSON format with the following structure:
            {output_format}
            
            Respond ONLY with valid JSON. Do not include any other text.
            """

            response = self.llm.invoke([HumanMessage(content=structured_prompt)])
            response_text = response.content.strip()

            # Attempt to parse JSON (in a real implementation, you'd use json.loads)
            # For now, we'll return the raw text
            return {"raw_response": response_text}
        except Exception as e:
            logger.error(
                f"Error generating structured LLM response: {e}", exc_info=True
            )
            return {"error": "Failed to generate structured response"}

    def create_prompt_template(
        self, template: str, input_variables: list[str]
    ) -> PromptTemplate:
        """
        Create a prompt template for reusable prompts.

        Args:
            template (str): The template string with placeholders.
            input_variables (List[str]): List of variable names in the template.

        Returns:
            PromptTemplate: The created prompt template.
        """
        return PromptTemplate(template=template, input_variables=input_variables)

    def run_prompt_chain(
        self, prompt_template: PromptTemplate, inputs: dict[str, Any]
    ) -> str:
        """
        Run a prompt chain using a template and inputs.

        Args:
            prompt_template (PromptTemplate): The prompt template to use.
            inputs (Dict[str, Any]): The input values for the template.

        Returns:
            str: The LLM's response.
        """
        try:
            chain = LLMChain(llm=self.llm, prompt=prompt_template)
            response = chain.run(**inputs)
            return response
        except Exception as e:
            import traceback

            tb_str = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            logger.error(f"Error running prompt chain: {e}", exc_info=True)
            # Re-raise with full stacktrace
            raise LLMServiceError(
                f"Prompt chain failed: {type(e).__name__}: {str(e)}\n\nSTACKTRACE:\n{tb_str}"
            ) from e
