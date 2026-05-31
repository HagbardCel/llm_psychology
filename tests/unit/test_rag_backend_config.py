from __future__ import annotations

import sys

import pytest

from psychoanalyst_app.config import Settings
from psychoanalyst_app.container.service_container import ServiceContainer
from psychoanalyst_app.exceptions import ConfigurationError
from psychoanalyst_app.services.rag import NoOpRAGService

pytestmark = pytest.mark.unit


def test_default_rag_backend_is_noop_without_heavy_imports(monkeypatch):
    sys.modules.pop("faiss", None)
    sys.modules.pop("sentence_transformers", None)

    def fail_import(name, *args, **kwargs):
        if name in {"faiss", "sentence_transformers"}:
            raise AssertionError(f"{name} should not be imported for RAG_BACKEND=none")
        return original_import(name, *args, **kwargs)

    original_import = __import__
    monkeypatch.setattr("builtins.__import__", fail_import)

    container = ServiceContainer(Settings(_env_file=None))
    rag_service = container.get("rag_service")

    assert isinstance(rag_service, NoOpRAGService)
    assert rag_service.retrieve_relevant_knowledge("anything") == []


def test_faiss_rag_backend_is_deferred_without_optional_imports(monkeypatch):
    def fail_import(name, *args, **kwargs):
        if name in {"faiss", "sentence_transformers"}:
            raise AssertionError(
                f"{name} should not be imported for unsupported RAG_BACKEND=faiss"
            )
        return original_import(name, *args, **kwargs)

    original_import = __import__
    monkeypatch.setattr("builtins.__import__", fail_import)

    settings = Settings(_env_file=None).model_copy(
        update={"RAG_BACKEND": "faiss"}
    )
    container = ServiceContainer(settings)

    with pytest.raises(ConfigurationError, match="future extension"):
        container.get("rag_service")
