from __future__ import annotations

from dataclasses import dataclass

import pytest
from google.api_core.exceptions import ResourceExhausted

from psychoanalyst_app.exceptions import LLMQuotaExhaustedError
from psychoanalyst_app.services import llm_service as llm_module
from psychoanalyst_app.services.llm_service import LLMService


@dataclass
class _FakeResponse:
    content: str


class _FakeLLM:
    def __init__(self, *, model: str, google_api_key: str, temperature: float):
        self._api_key = google_api_key

    def invoke(self, messages):
        if self._api_key == "exhausted":
            raise ResourceExhausted("quota exhausted")
        return _FakeResponse(content=f"ok:{self._api_key}")


def test_generate_response_rotates_on_quota(monkeypatch):
    monkeypatch.setattr(llm_module, "ChatGoogleGenerativeAI", _FakeLLM)
    service = LLMService(api_keys=["exhausted", "available"], model_name="test-model")

    response = service.generate_response("hello")

    assert response == "ok:available"


def test_generate_response_all_keys_exhausted(monkeypatch):
    monkeypatch.setattr(llm_module, "ChatGoogleGenerativeAI", _FakeLLM)
    service = LLMService(api_keys=["exhausted"], model_name="test-model")

    with pytest.raises(LLMQuotaExhaustedError):
        service.generate_response("hello")
