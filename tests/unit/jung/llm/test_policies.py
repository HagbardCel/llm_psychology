"""Tests for model policy construction."""

from __future__ import annotations

import pytest

from jung.llm.gateway import LLMSettings, LLMTask
from jung.llm.policies import build_model_policies


def test_build_model_policies_returns_all_tasks() -> None:
    policies = build_model_policies(
        LLMSettings(
            default_model="local-model",
            base_url="http://localhost:1234/v1",
            api_key="not-needed",
        )
    )
    assert set(policies) == set(LLMTask)
    assert policies[LLMTask.ASSESSMENT].model == "local-model"


def test_build_model_policies_maps_task_max_completion_tokens() -> None:
    policies = build_model_policies(
        LLMSettings(
            default_model="local-model",
            base_url="http://localhost:1234/v1",
            api_key="not-needed",
            task_max_completion_tokens={LLMTask.ASSESSMENT: 256},
        )
    )
    assert policies[LLMTask.ASSESSMENT].max_completion_tokens == 256
    assert policies[LLMTask.THERAPY_RESPONSE].max_completion_tokens is None


def test_build_model_policies_rejects_empty_model() -> None:
    with pytest.raises(ValueError):
        build_model_policies(
            LLMSettings(
                default_model=" ",
                base_url="http://localhost:1234/v1",
                api_key="not-needed",
            )
        )
