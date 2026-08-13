"""Deterministic scripted LLM gateway for processor tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable, Sequence
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from jung.llm.errors import InvalidLLMOutput, LLMError
from jung.llm.gateway import ChatMessage, LLMTask, ModelPolicy
from jung.llm.structured import format_semantic_error

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class StreamExpectation:
    task: LLMTask
    chunks: tuple[str, ...]
    message_fragments: tuple[str, ...] = ()
    error_after_chunks: LLMError | None = None


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
            raise AssertionError(f"FakeLLM has unused expectations: {remaining}")

    async def aclose(self) -> None:
        return None

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
    ) -> AsyncGenerator[str, None]:
        if self._expectations and isinstance(self._expectations[0], FailureExpectation):
            failure = self._expectations.pop(0)
            assert failure.task == policy.task
            raise failure.error
        expectation = self._pop(kind=StreamExpectation, task=policy.task)
        assert isinstance(expectation, StreamExpectation)
        self._check_fragments(messages, expectation.message_fragments)
        for index, chunk in enumerate(expectation.chunks):
            yield chunk
            if (
                expectation.error_after_chunks is not None
                and index == len(expectation.chunks) - 1
            ):
                raise expectation.error_after_chunks

    async def generate_structured(
        self,
        messages: Sequence[ChatMessage],
        output_type: type[T],
        policy: ModelPolicy,
        validate_result: Callable[[T], T] | None = None,
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
        parsed = output_type.model_validate(expectation.response.model_dump())
        if validate_result is None:
            return parsed
        try:
            return validate_result(parsed)
        except InvalidLLMOutput:
            raise
        except (ValueError, ValidationError) as exc:
            raise InvalidLLMOutput(format_semantic_error(exc)) from exc


class RecordingFakeLLM:
    """Test-only wrapper; records task/model at outermost LLM entry points."""

    def __init__(self, delegate: FakeLLM) -> None:
        self._delegate = delegate
        self._recorded_calls: list[tuple[LLMTask, str]] = []

    @property
    def recorded_calls(self) -> tuple[tuple[LLMTask, str], ...]:
        return tuple(self._recorded_calls)

    @property
    def recorded_tasks(self) -> tuple[LLMTask, ...]:
        return tuple(task for task, _model in self._recorded_calls)

    async def generate_structured(
        self,
        messages: Sequence[ChatMessage],
        output_type: type[T],
        policy: ModelPolicy,
        validate_result: Callable[[T], T] | None = None,
    ) -> T:
        self._recorded_calls.append((policy.task, policy.model))
        return await self._delegate.generate_structured(
            messages=messages,
            output_type=output_type,
            policy=policy,
            validate_result=validate_result,
        )

    async def stream_text(
        self,
        messages: Sequence[ChatMessage],
        policy: ModelPolicy,
    ) -> AsyncGenerator[str, None]:
        self._recorded_calls.append((policy.task, policy.model))
        async for chunk in self._delegate.stream_text(messages, policy):
            yield chunk

    def assert_exhausted(self) -> None:
        self._delegate.assert_exhausted()

    async def aclose(self) -> None:
        close = getattr(self._delegate, "aclose", None)
        if close is not None:
            await close()
