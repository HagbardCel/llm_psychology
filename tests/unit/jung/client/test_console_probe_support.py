"""Unit tests for console probe support artifacts."""

from __future__ import annotations

from pathlib import Path

from tests.console_probe_support import ProbeRecorder


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
    recorder.write_artifacts(tmp_path, failure=None)

    for name in ProbeRecorder.ARTIFACT_NAMES:
        assert (tmp_path / name).exists(), name
    assert not (tmp_path / ProbeRecorder.FAILURE_ARTIFACT).exists()

    timeline = (tmp_path / "timeline.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(timeline) == 1
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "success" in summary
