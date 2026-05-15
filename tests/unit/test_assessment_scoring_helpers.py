from __future__ import annotations

from psychoanalyst_app.agents.assessment.recommendation_payloads import (
    build_recommendation_metadata,
    build_structured_recommendations,
    format_recommendations,
)
from psychoanalyst_app.agents.assessment.scoring import resolve_recommendation_score
from psychoanalyst_app.agents.assessment.topic_extraction import extract_key_topics


def test_resolve_recommendation_score_clamps_and_falls_back() -> None:
    assert resolve_recommendation_score({"score": 2.0}) == 1.0
    assert resolve_recommendation_score({"score": -1.0}) == 0.0
    assert resolve_recommendation_score({}) == 0.5


def test_extract_key_topics_uses_payload_and_skips_text_parsing() -> None:
    assert extract_key_topics({"key_topics": ["anxiety", "work"]}) == [
        "anxiety",
        "work",
    ]
    assert extract_key_topics({"topics": ["sleep", "avoidance"]}) == [
        "sleep",
        "avoidance",
    ]
    assert extract_key_topics({"assessment": "- Work stress.\nGeneral insight"}) == []


def test_recommendation_payload_helpers_build_expected_shapes() -> None:
    recommendations = [
        {
            "style_id": "freud",
            "assessment": "Depth-oriented approach",
            "key_topics": ["childhood"],
        },
        {
            "style_id": "cbt",
            "assessment": "Structured coping skills",
        },
    ]

    structured = build_structured_recommendations(recommendations)
    assert len(structured) == 2
    assert structured[0].style_name == "freud"
    assert structured[0].key_topics == ["childhood"]

    metadata = build_recommendation_metadata(structured)
    assert metadata[0]["style_id"] == "freud"
    assert "score" in metadata[1]

    rendered = format_recommendations(structured)
    assert "FREUD Therapy" in rendered
    assert "Which approach resonates most with you?" in rendered
