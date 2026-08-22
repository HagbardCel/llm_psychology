"""Unit tests for patient.response metric roll-ups."""

from __future__ import annotations

from evals.simulation.audit import (
    roll_up_patient_metrics,
    sanitize_patient_extra_body_provenance,
)


def test_sanitize_patient_extra_body_provenance_preserves_non_sensitive_keys() -> None:
    body = {"chat_template_kwargs": {"enable_thinking": False}, "top_p": 0.95}
    assert sanitize_patient_extra_body_provenance(body) == body


def test_sanitize_patient_extra_body_provenance_redacts_sensitive_keys() -> None:
    body = {
        "top_p": 0.95,
        "api_key": "SECRET",
        "authorization": "Bearer SECRET",
        "nested": {"access_token": "SECRET"},
    }
    sanitized = sanitize_patient_extra_body_provenance(body)
    assert sanitized == {
        "top_p": 0.95,
        "api_key": "[REDACTED]",
        "authorization": "[REDACTED]",
        "nested": {"access_token": "[REDACTED]"},
    }


def test_sanitize_patient_extra_body_provenance_empty_object() -> None:
    assert sanitize_patient_extra_body_provenance({}) == {}


def test_sanitize_patient_extra_body_provenance_none() -> None:
    assert sanitize_patient_extra_body_provenance(None) is None


def test_sanitize_patient_extra_body_provenance_redacts_non_json() -> None:
    class _NotJson:
        pass

    assert sanitize_patient_extra_body_provenance({"x": _NotJson()}) == {
        "__redacted__": True
    }


def test_roll_up_patient_metrics_from_journey_records() -> None:
    journey_records = [
        {
            "kind": "patient.response",
            "data": {
                "latency_seconds": 1.0,
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "resolved_prompt": "abc",
                "submitted_text": "hi",
            },
        },
        {
            "kind": "patient.response",
            "data": {
                "latency_seconds": 3.0,
                "prompt_tokens": 20,
                "completion_tokens": None,
                "resolved_prompt": "defgh",
                "submitted_text": "hello",
            },
        },
        {"kind": "patient.request", "data": {}},
    ]
    metrics = roll_up_patient_metrics(
        journey_records,
        patient_model="model-a",
        patient_endpoint="http://127.0.0.1:8000/v1",
        patient_extra_body={"thinking": False},
    )
    assert metrics["calls"] == 2
    assert metrics["latency_seconds_total"] == 4.0
    assert metrics["latency_seconds_mean"] == 2.0
    assert metrics["latency_seconds_max"] == 3.0
    assert metrics["usage_complete_calls"] == 1
    assert metrics["usage_coverage"] == 0.5
    assert metrics["prompt_tokens_complete_usage"] == 10
    assert metrics["completion_tokens_complete_usage"] == 5
    assert metrics["prompt_chars_total"] == 8
    assert metrics["submitted_chars_total"] == 7
    assert metrics["patient_model"] == "model-a"
    assert metrics["patient_endpoint"] == "http://127.0.0.1:8000/v1"
    assert metrics["patient_extra_body"] == {"thinking": False}


def test_roll_up_patient_metrics_zero_calls() -> None:
    metrics = roll_up_patient_metrics(
        [],
        patient_model="m",
        patient_endpoint="http://test/v1",
        patient_extra_body=None,
    )
    assert metrics["calls"] == 0
    assert metrics["usage_coverage"] == 0.0
    assert metrics["latency_seconds_mean"] is None
    assert metrics["latency_seconds_max"] is None
    assert metrics["prompt_tokens_complete_usage"] == 0
    assert metrics["completion_tokens_complete_usage"] == 0
