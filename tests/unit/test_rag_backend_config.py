from __future__ import annotations

import sys

import pytest

from psychoanalyst_app.config import Settings
from psychoanalyst_app.container.service_container import ServiceContainer
from psychoanalyst_app.exceptions import ConfigurationError
from psychoanalyst_app.services.rag_service import NoOpRAGService


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


def test_faiss_rag_backend_surfaces_missing_optional_dependency(
    monkeypatch, tmp_path
):
    def fail_import(name, *args, **kwargs):
        if name == "faiss":
            raise ModuleNotFoundError("No module named 'faiss'")
        return original_import(name, *args, **kwargs)

    original_import = __import__
    monkeypatch.setattr("builtins.__import__", fail_import)

    vector_db = tmp_path / "vector_db"
    vector_db.mkdir()
    (vector_db / "faiss_index.bin").write_bytes(b"fake")
    (vector_db / "data.pkl").write_bytes(b"fake")
    settings = Settings(_env_file=None).model_copy(
        update={
            "RAG_BACKEND": "faiss",
            "VECTOR_DB_PATH": str(vector_db),
        }
    )
    container = ServiceContainer(settings)

    with pytest.raises(ConfigurationError, match="faiss"):
        container.get("rag_service")
