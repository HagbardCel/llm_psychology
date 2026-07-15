"""Unit tests for console probe support artifacts."""

from __future__ import annotations

from pathlib import Path

from tests.console_probe_support import (
    ProbeRecorder,
    assert_setup_timeline,
    assert_subsequence,
    assert_successful_timeline,
    assert_therapy_timeline,
    snapshot_stages,
)


def test_artifacts_include_failure_summary(tmp_path: Path) -> None:
    recorder = ProbeRecorder("scenario-a")
    recorder.record("snapshot", stage="intake", revision=1)
    failure = RuntimeError("probe failed")
    recorder.write_artifacts(tmp_path, failure=failure)

    assert (tmp_path / "failure_summary.md").exists()
    body = (tmp_path / "failure_summary.md").read_text(encoding="utf-8")
    assert "probe failed" in body
    manifest = (tmp_path / "manifest.json").read_text(encoding="utf-8")
    assert "failure_summary.md" in manifest


def test_artifacts_emit_complete_named_set(tmp_path: Path) -> None:
    recorder = ProbeRecorder("scenario-b")
    recorder.record("snapshot", stage="ready", revision=9)
    recorder.record(
        "chat_send",
        request_id="req-1",
        client_message_id="msg-1",
    )
    recorder.record("ws_event", type="message_in_progress", turn_id="turn-1")
    recorder.record("ws_event", type="token", sequence=1)
    recorder.record("ws_event", type="message_completed", client_message_id="msg-1")
    recorder.write_artifacts(tmp_path, failure=None)

    for name in ProbeRecorder.ARTIFACT_NAMES:
        assert (tmp_path / name).exists(), name
    assert not (tmp_path / ProbeRecorder.FAILURE_ARTIFACT).exists()

    timeline = (tmp_path / "timeline.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(timeline) == 5
    assert_successful_timeline(recorder.timeline)
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "success" in summary


def test_timeline_subsequence_helpers() -> None:
    setup_timeline = [
        {"category": "snapshot", "stage": "setup", "revision": 0},
        {"category": "snapshot", "stage": "intake", "revision": 1},
        {"category": "snapshot", "stage": "style_selection", "revision": 2},
        {"category": "snapshot", "stage": "ready", "revision": 3},
        {"category": "chat_send", "request_id": "r", "client_message_id": "m"},
        {"category": "ws_event", "type": "message_in_progress", "turn_id": "t"},
        {"category": "ws_event", "type": "token", "sequence": 1},
        {"category": "ws_event", "type": "message_completed", "client_message_id": "m"},
    ]
    assert_setup_timeline(setup_timeline)

    therapy_timeline = [
        {"category": "snapshot", "stage": "therapy", "revision": 1},
        {"category": "chat_send", "request_id": "r", "client_message_id": "m"},
        {"category": "ws_event", "type": "message_in_progress", "turn_id": "t"},
        {"category": "ws_event", "type": "token", "sequence": 1},
        {"category": "ws_event", "type": "message_completed", "client_message_id": "m"},
        {"category": "snapshot", "stage": "post_session", "revision": 2},
        {"category": "snapshot", "stage": "ready", "revision": 3},
    ]
    assert_therapy_timeline(therapy_timeline)
    assert_subsequence(snapshot_stages(therapy_timeline), ["therapy", "ready"])
