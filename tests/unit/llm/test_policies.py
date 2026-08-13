"""Tests for model policy construction and gateway model validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jung.llm.gateway import (
    ChatMessage,
    ChatRole,
    LLMRole,
    LLMTask,
    ModelPolicy,
    StructuredOutputMode,
    role_for_task,
)
from jung.llm.policies import TaskOverride, build_model_policies


def test_role_for_task_covers_every_task() -> None:
    assert set(LLMRole) == {LLMRole.SESSION, LLMRole.SUPERVISOR}
    assert {task: role_for_task(task) for task in LLMTask} == {
        LLMTask.INTAKE_PATCH: LLMRole.SESSION,
        LLMTask.INTAKE_RESPONSE: LLMRole.SESSION,
        LLMTask.THERAPY_RESPONSE: LLMRole.SESSION,
        LLMTask.ASSESSMENT: LLMRole.SUPERVISOR,
        LLMTask.POST_SESSION_ANALYSIS: LLMRole.SUPERVISOR,
        LLMTask.POST_SESSION_UPDATE: LLMRole.SUPERVISOR,
    }


def test_build_model_policies_returns_all_tasks() -> None:
    policies = build_model_policies(
        session_model="local-model",
        supervisor_model="local-model",
        task_overrides={},
    )
    assert set(policies) == set(LLMTask)
    assert policies[LLMTask.ASSESSMENT].model == "local-model"


def test_build_model_policies_uses_role_owned_models() -> None:
    policies = build_model_policies(
        session_model="session-model",
        supervisor_model="supervisor-model",
        task_overrides={},
    )
    assert policies[LLMTask.INTAKE_PATCH].model == "session-model"
    assert policies[LLMTask.INTAKE_RESPONSE].model == "session-model"
    assert policies[LLMTask.THERAPY_RESPONSE].model == "session-model"
    assert policies[LLMTask.ASSESSMENT].model == "supervisor-model"
    assert policies[LLMTask.POST_SESSION_ANALYSIS].model == "supervisor-model"
    assert policies[LLMTask.POST_SESSION_UPDATE].model == "supervisor-model"


def test_build_model_policies_maps_task_max_completion_tokens() -> None:
    policies = build_model_policies(
        session_model="local-model",
        supervisor_model="local-model",
        task_overrides={
            LLMTask.ASSESSMENT: TaskOverride(max_completion_tokens=256),
        },
    )
    assert policies[LLMTask.ASSESSMENT].max_completion_tokens == 256
    assert policies[LLMTask.THERAPY_RESPONSE].max_completion_tokens is None


def test_build_model_policies_applies_remaining_overrides() -> None:
    policies = build_model_policies(
        session_model="session-model",
        supervisor_model="supervisor-model",
        task_overrides={
            LLMTask.ASSESSMENT: TaskOverride(
                temperature=0.2,
                timeout_seconds=90.0,
                structured_output_mode=StructuredOutputMode.JSON_OBJECT,
                extra_body={"flag": True},
            ),
        },
    )
    assessment = policies[LLMTask.ASSESSMENT]
    assert assessment.model == "supervisor-model"
    assert assessment.temperature == 0.2
    assert assessment.timeout_seconds == 90.0
    assert assessment.structured_output_mode is StructuredOutputMode.JSON_OBJECT


def test_task_override_rejects_model_field() -> None:
    with pytest.raises(ValidationError):
        TaskOverride.model_validate({"model": "other-model"})


def test_task_override_rejects_role_field() -> None:
    with pytest.raises(ValidationError):
        TaskOverride.model_validate({"role": "session"})


def test_build_model_policies_rejects_empty_session_model() -> None:
    with pytest.raises(ValueError):
        build_model_policies(
            session_model=" ",
            supervisor_model="local-model",
            task_overrides={},
        )


def test_build_model_policies_rejects_empty_supervisor_model() -> None:
    with pytest.raises(ValueError):
        build_model_policies(
            session_model="local-model",
            supervisor_model=" ",
            task_overrides={},
        )


def test_chat_message_rejects_blank_content() -> None:
    with pytest.raises(ValueError):
        ChatMessage(role=ChatRole.USER, content="   ")


def test_model_policy_rejects_zero_timeout() -> None:
    with pytest.raises(ValueError):
        ModelPolicy(
            task=LLMTask.INTAKE_PATCH,
            model="fake",
            temperature=0.0,
            timeout_seconds=0.0,
        )
