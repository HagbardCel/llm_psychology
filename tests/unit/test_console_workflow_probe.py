from __future__ import annotations

import importlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest


pytestmark = [pytest.mark.trio, pytest.mark.unit]


@pytest.fixture
def probe_modules(monkeypatch):
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(repo_root / "console-ui"))
    modules = {
        "db_snapshot": importlib.import_module("src.workflow_probe.db_snapshot"),
        "local_user": importlib.import_module("src.workflow_probe.local_user"),
        "recorder": importlib.import_module("src.workflow_probe.recorder"),
        "simulator": importlib.import_module("src.llm_user_simulator"),
    }
    yield modules
    for name in list(sys.modules):
        if name == "src" or name.startswith("src."):
            sys.modules.pop(name, None)


def _context(input_providers, prompt_kind: str = "chat"):
    return input_providers.InputContext(
        prompt=None,
        default=None,
        prompt_kind=prompt_kind,
        user_id="user-1",
        session_id="session-1",
        workflow_action={"required_action": "start_intake"},
        simulator_phase="You are answering intake questions.",
        pending_recommendations=None,
        transcript_tail=[],
        turn_index=0,
    )


async def test_local_user_uses_structural_answers_without_model_call(probe_modules, monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://local/v1")
    monkeypatch.setenv("MODEL_NAME", "local-model")
    input_providers = importlib.import_module("src.input_providers")
    recorder = probe_modules["recorder"].ProbeRecorder(Path("/tmp") / "probe-test", "scenario")
    user = probe_modules["local_user"].LocalUser(
        {"structural_answers": {"therapy_style": "freud"}}, recorder
    )
    assert await user.get_input(_context(input_providers, "therapy_style")) == "freud"


async def test_local_user_tracks_transcript_outside_console_client(probe_modules, monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://local/v1")
    monkeypatch.setenv("MODEL_NAME", "local-model")
    recorder = probe_modules["recorder"].ProbeRecorder(Path("/tmp") / "probe-test", "scenario")
    user = probe_modules["local_user"].LocalUser({}, recorder)
    input_providers = importlib.import_module("src.input_providers")
    context = _context(input_providers)
    await user.emit("user_input", text="I feel tense.", context=context)
    await user.emit("assistant_response", text="Where do you notice that?")
    assert user.transcript == [
        {"role": "user", "content": "I feel tense."},
        {"role": "assistant", "content": "Where do you notice that?"},
    ]


async def test_simulator_retries_invalid_reply_then_fails_explicitly(probe_modules):
    simulator_mod = probe_modules["simulator"]
    simulator = simulator_mod.LocalLLMUserSimulator("http://unused", "model")
    simulator._chat_completion = _invalid_completion(simulator_mod)  # type: ignore[method-assign]
    with pytest.raises(simulator_mod.LocalLLMUserSimulatorError, match="invalid_reply"):
        await simulator.generate_user_reply({}, type("Context", (), {
            "transcript_tail": [], "simulator_phase": "therapy", "prompt": None
        })())


def _invalid_completion(simulator_mod):
    calls = 0

    async def complete(_prompt: str):
        nonlocal calls
        calls += 1
        assert calls <= 2
        return simulator_mod.ChatCompletionResult(
            content="As an AI, I cannot roleplay.",
            http_status=200,
            raw_preview="invalid",
            response_shape="choices[0].message.content",
        )

    return complete


async def test_recorder_writes_required_text_artifacts(probe_modules, tmp_path):
    recorder = probe_modules["recorder"].ProbeRecorder(tmp_path, "scenario")
    await recorder.emit("assistant_response", text="Hello")
    await recorder.write_artifacts("PASS", {"id": "scenario"})
    assert (tmp_path / "trace.jsonl").exists()
    assert (tmp_path / "summary.md").exists()
    assert (tmp_path / "transcript.md").exists()
    assert json.loads((tmp_path / "metadata.json").read_text())["status"] == "PASS"


async def test_db_snapshot_uses_backup_integrity_and_attributable_rows(probe_modules, tmp_path):
    source = tmp_path / "runtime.sqlite"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE user_profiles (user_id TEXT, name TEXT)")
        conn.execute("CREATE TABLE sessions (session_id TEXT, user_id TEXT)")
        conn.execute("INSERT INTO user_profiles VALUES ('probe', 'Probe')")
        conn.execute("INSERT INTO user_profiles VALUES ('other', 'Other')")
        conn.execute("INSERT INTO sessions VALUES ('s1', 'probe')")
        conn.execute("INSERT INTO sessions VALUES ('s2', 'other')")
    payload = probe_modules["db_snapshot"].snapshot_and_extract(source, tmp_path, "probe", ["s1"])
    assert payload["user_profiles"] == [{"user_id": "probe", "name": "Probe"}]
    assert payload["sessions"] == [{"session_id": "s1", "user_id": "probe"}]
    with sqlite3.connect(tmp_path / "db_snapshot.sqlite") as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
