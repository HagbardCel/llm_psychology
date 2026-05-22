"""Smoke test for a host-local LM Studio OpenAI-compatible model server."""

from __future__ import annotations

import os

import pytest

from psychoanalyst_app.config import Settings
from psychoanalyst_app.container.service_container import ServiceContainer


pytestmark = [pytest.mark.real_llm]


def test_lmstudio_google_gemma_4_e4b_smoke():
    """Call google/gemma-4-e4b served by LM Studio on the host."""
    if os.getenv("RUN_LMSTUDIO_SMOKE") != "1":
        pytest.skip("Set RUN_LMSTUDIO_SMOKE=1 to call local LM Studio.")

    settings = Settings(_env_file=None).model_copy(
        update={
            "LLM_PROVIDER": "lmstudio",
            "LLM_BASE_URL": "http://host.docker.internal:1234/v1",
            "LLM_API_KEY": "lm-studio",
            "GOOGLE_API_KEY": "",
            "MODEL_NAME": "google/gemma-4-e4b",
            "LLM_RATE_LIMIT_ENABLED": False,
        }
    )
    container = ServiceContainer(settings)
    llm = container.get("llm_service")

    assert llm.provider == "lmstudio"
    assert llm.model_name == "google/gemma-4-e4b"
    assert llm.base_url == "http://host.docker.internal:1234/v1"

    response = llm.generate_response("Reply with exactly: local model ok")

    assert "local model ok" in response.lower()
