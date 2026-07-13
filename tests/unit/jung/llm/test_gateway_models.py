"""Gateway model validation tests."""

from __future__ import annotations

import pytest

from jung.llm.gateway import ChatMessage, ChatRole, LLMTask, ModelPolicy


def test_chat_message_rejects_empty_content() -> None:
    with pytest.raises(ValueError):
        ChatMessage(role=ChatRole.USER, content="   ")


def test_model_policy_validates_timeout() -> None:
    with pytest.raises(ValueError):
        ModelPolicy(
            task=LLMTask.INTAKE_PATCH,
            model="fake",
            temperature=0.0,
            timeout_seconds=0.0,
        )
