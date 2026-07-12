"""Deterministic scripted LLM gateway for processor tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

from jung.llm.errors import LLMError
from jung.llm.gateway import ChatMessage, LLMTask, ModelPolicy

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class StreamExpectation:
    task: LLMTask
    chunks: tuple[str, ...]
    message_fragments: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StructuredExpectation:
    task: LLMTask
    output_type: type[BaseModel]
    response: BaseModel
    message_fragments: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FailureExpectation:
    task: LLMTask
    error: LLMError


Expectation = StreamExpectation | StructuredExpectation | FailureExpectation


class FakeLLM:
    """Strict ordered queue of scripted gateway interactions."""

    def __init__(self, expectations: Sequence[Expectation]) -> None:
        self._expectations: list[Expectation] = list(expectations)

    def assert_exhausted(self) -> None:
        if self._expectations:
            remaining = [type(item).__name__ for item in self._expectations]
            raise AssertionError(
                f"FakeLLM has unused expectations: {remaining}"
            )

    def _pop(self, *, kind: type[Expectation], task: LLMTask) -> Expectation:
        if not self._expectations:
            raise AssertionError(f"FakeLLM received unexpected {task.value} call")
        next_item = self._expectations.pop(0)
        if not isinstance(next_item, kind):
            raise AssertionError(
                f"Expected {kind.__name__}, got {type(next_item).__name__}"
            )
        if next_item.task != task:
            raise AssertionError(
                f"Expected task {next_item.task.value}, got {task.value}"
            )
        return next_item

    def _check_fragments(
        self,
        messages: Sequence[ChatMessage],
        fragments: tuple[str, ...],
    ) -> None:
        if not fragments:
            return
        combined = "\n".join(message.content for message in messages)
        for fragment in fragments:
            if fragment not in combined:
                raise AssertionError(
                    f"Expected message fragment not found: {fragment!r}"
                )

    async def stream_text(
        self,
        messages: Sequence[ChatMessage],
        policy: ModelPolicy,
    ) -> AsyncIterator[str]:
        if self._expectations and isinstance(self._expectations[0], FailureExpectation):
            failure = self._expectations.pop(0)
            assert failure.task == policy.task
            raise failure.error
        expectation = self._pop(kind=StreamExpectation, task=policy.task)
        assert isinstance(expectation, StreamExpectation)
        self._check_fragments(messages, expectation.message_fragments)
        for chunk in expectation.chunks:
            yield chunk

    async def generate_structured(
        self,
        messages: Sequence[ChatMessage],
        output_type: type[T],
        policy: ModelPolicy,
    ) -> T:
        if self._expectations and isinstance(self._expectations[0], FailureExpectation):
            failure = self._expectations.pop(0)
            assert failure.task == policy.task
            raise failure.error
        expectation = self._pop(kind=StructuredExpectation, task=policy.task)
        assert isinstance(expectation, StructuredExpectation)
        if expectation.output_type is not output_type:
            raise AssertionError(
                "Structured output type mismatch: "
                f"expected {expectation.output_type.__name__}, "
                f"got {output_type.__name__}"
            )
        self._check_fragments(messages, expectation.message_fragments)
        return output_type.model_validate(expectation.response.model_dump())
