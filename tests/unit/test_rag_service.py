from __future__ import annotations

import pytest

from psychoanalyst_app.services.rag_service import RAGService


class _StubEmbeddingUtils:
    """
    Deterministic embedding stub for unit tests.

    Produces small non-zero vectors based on keyword presence so FAISS + L2
    normalization behave deterministically and never see a zero vector.
    """

    _keywords = ("apple", "banana", "cherry")

    def generate_embedding(self, text: str) -> list[float]:
        text_lower = text.lower()
        # Bias term keeps vectors non-zero for normalization.
        vec = [0.1]
        vec.extend(1.0 if kw in text_lower else 0.0 for kw in self._keywords)
        return vec

    def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        return [self.generate_embedding(t) for t in texts]


def test_retrieve_relevant_knowledge_ranks_best_match_first(tmp_path):
    domain_knowledge_path = tmp_path / "domain_knowledge"
    vector_db_path = tmp_path / "vector_db"
    domain_knowledge_path.mkdir()
    vector_db_path.mkdir()

    (domain_knowledge_path / "cbt.md").write_text(
        "Intro\n\nApple chunk\n\nBanana chunk", encoding="utf-8"
    )

    rag = RAGService(
        domain_knowledge_path=str(domain_knowledge_path),
        vector_db_path=str(vector_db_path),
        embedding_utils=_StubEmbeddingUtils(),
        styles_dir=None,  # isolate from repository style packs
    )

    results = rag.retrieve_relevant_knowledge("apple", n_results=2)
    assert results
    assert results[0]["source"] == "cbt.md"
    assert results[0]["content"] == "Apple chunk"


def test_retrieve_relevant_knowledge_filter_source(tmp_path):
    domain_knowledge_path = tmp_path / "domain_knowledge"
    vector_db_path = tmp_path / "vector_db"
    domain_knowledge_path.mkdir()
    vector_db_path.mkdir()

    (domain_knowledge_path / "cbt.md").write_text(
        "CBT intro\n\nApple chunk", encoding="utf-8"
    )
    (domain_knowledge_path / "freud.md").write_text(
        "Freud intro\n\nApple in Freud", encoding="utf-8"
    )

    rag = RAGService(
        domain_knowledge_path=str(domain_knowledge_path),
        vector_db_path=str(vector_db_path),
        embedding_utils=_StubEmbeddingUtils(),
        styles_dir=None,
    )

    freud_only = rag.retrieve_relevant_knowledge(
        "apple", n_results=3, filter_source="freud.md"
    )
    assert freud_only
    assert all(r["source"] == "freud.md" for r in freud_only)
    assert freud_only[0]["content"] == "Apple in Freud"


def test_get_knowledge_by_source_returns_all_chunks(tmp_path):
    domain_knowledge_path = tmp_path / "domain_knowledge"
    vector_db_path = tmp_path / "vector_db"
    domain_knowledge_path.mkdir()
    vector_db_path.mkdir()

    (domain_knowledge_path / "cbt.md").write_text(
        "Para 1\n\nPara 2\n\nPara 3", encoding="utf-8"
    )

    rag = RAGService(
        domain_knowledge_path=str(domain_knowledge_path),
        vector_db_path=str(vector_db_path),
        embedding_utils=_StubEmbeddingUtils(),
        styles_dir=None,
    )

    chunks = rag.get_knowledge_by_source("cbt.md")
    assert [c["content"] for c in chunks] == ["Para 1", "Para 2", "Para 3"]


def test_index_persists_and_loads_from_disk(tmp_path):
    domain_knowledge_path = tmp_path / "domain_knowledge"
    vector_db_path = tmp_path / "vector_db"
    domain_knowledge_path.mkdir()
    vector_db_path.mkdir()

    (domain_knowledge_path / "cbt.md").write_text(
        "Intro\n\nApple chunk\n\nBanana chunk", encoding="utf-8"
    )

    rag1 = RAGService(
        domain_knowledge_path=str(domain_knowledge_path),
        vector_db_path=str(vector_db_path),
        embedding_utils=_StubEmbeddingUtils(),
        styles_dir=None,
    )

    assert (vector_db_path / "faiss_index.bin").exists()
    assert (vector_db_path / "data.pkl").exists()

    first = rag1.retrieve_relevant_knowledge("apple", n_results=1)
    assert first

    # New instance should load the persisted index (not rebuild) and still return results.
    rag2 = RAGService(
        domain_knowledge_path=str(domain_knowledge_path),
        vector_db_path=str(vector_db_path),
        embedding_utils=_StubEmbeddingUtils(),
        styles_dir=None,
    )

    second = rag2.retrieve_relevant_knowledge("apple", n_results=1)
    assert second
    assert second[0]["content"] == first[0]["content"]
