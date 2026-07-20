"""Unit tests for test-only RecordingFakeLLM wrapper."""

from __future__ import annotations

import inspect

from jung.llm.fake import FakeLLM
from jung.llm.gateway import LLMGateway
from tests.jung_api_fixtures import RecordingFakeLLM


def test_recording_fake_exposes_gateway_methods() -> None:
    """Public LLMGateway methods are present — not full protocol conformance."""
    wrapper = RecordingFakeLLM(FakeLLM(()))
    required_methods = {
        name
        for name, _value in inspect.getmembers(
            LLMGateway,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    }
    assert all(callable(getattr(wrapper, name, None)) for name in required_methods)
