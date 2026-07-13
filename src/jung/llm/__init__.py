"""Project-owned LLM gateway and test doubles."""

from jung.llm.errors import (
    InvalidLLMOutput,
    LLMError,
    LLMProtocolError,
    LLMTimeout,
    LLMUnavailable,
)
from jung.llm.fake import (
    FailureExpectation,
    FakeLLM,
    StreamExpectation,
    StructuredExpectation,
)
from jung.llm.gateway import (
    AdapterConfig,
    ChatMessage,
    ChatRole,
    LLMGateway,
    LLMSettings,
    LLMTask,
    ModelPolicy,
    StructuredOutputMode,
)
from jung.llm.openai_compatible import OpenAICompatibleLLM, ProviderAttemptEvent
from jung.llm.policies import build_model_policies
from jung.llm.tracing import TracingLLMGateway

__all__ = [
    "AdapterConfig",
    "ChatMessage",
    "ChatRole",
    "FailureExpectation",
    "FakeLLM",
    "InvalidLLMOutput",
    "LLMError",
    "LLMGateway",
    "LLMProtocolError",
    "LLMSettings",
    "LLMTask",
    "LLMTimeout",
    "LLMUnavailable",
    "ModelPolicy",
    "OpenAICompatibleLLM",
    "ProviderAttemptEvent",
    "StreamExpectation",
    "StructuredExpectation",
    "StructuredOutputMode",
    "TracingLLMGateway",
    "build_model_policies",
]
