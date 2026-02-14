from __future__ import annotations

from types import SimpleNamespace

from psychoanalyst_app.agents.psychoanalyst.topic_detection import is_in_deep_topic


def test_topic_detection_defaults_false_until_heuristics_added() -> None:
    context = SimpleNamespace(message_history=["anything"])
    assert is_in_deep_topic(context) is False
