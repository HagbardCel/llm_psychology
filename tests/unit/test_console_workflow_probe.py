from __future__ import annotations

import importlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.trio, pytest.mark.unit]


@pytest.fixture
def probe_modules(monkeypatch):
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(repo_root / "console-ui"))
    modules = {
        "assertions": importlib.import_module("src.workflow_probe.assertions"),
        "db_snapshot": importlib.import_module("src.workflow_probe.db_snapshot"),
        "local_user": importlib.import_module("src.workflow_probe.local_user"),
        "recorder": importlib.import_module("src.workflow_probe.recorder"),
        "runner": importlib.import_module("src.workflow_probe.runner"),
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


async def test_local_user_uses_user_sim_model_over_model_name(probe_modules, monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://therapist/v1")
    monkeypatch.setenv("MODEL_NAME", "therapist-model")
    monkeypatch.setenv("USER_SIM_LLM_MODEL", "patient-model")
    recorder = probe_modules["recorder"].ProbeRecorder(Path("/tmp") / "probe-test", "scenario")

    user = probe_modules["local_user"].LocalUser({}, recorder)

    assert user.simulator is not None
    assert user.simulator.model == "patient-model"


async def test_local_user_uses_user_sim_base_url_over_llm_base_url(
    probe_modules, monkeypatch
):
    monkeypatch.setenv("LLM_BASE_URL", "http://therapist/v1")
    monkeypatch.setenv("MODEL_NAME", "therapist-model")
    monkeypatch.setenv("USER_SIM_LLM_BASE_URL", "http://patient/v1")
    recorder = probe_modules["recorder"].ProbeRecorder(Path("/tmp") / "probe-test", "scenario")

    user = probe_modules["local_user"].LocalUser({}, recorder)

    assert user.simulator is not None
    assert user.simulator.base_url == "http://patient/v1"


async def test_local_user_falls_back_to_model_name_for_user_sim_model(
    probe_modules, monkeypatch
):
    monkeypatch.setenv("LLM_BASE_URL", "http://therapist/v1")
    monkeypatch.setenv("MODEL_NAME", "therapist-model")
    monkeypatch.delenv("USER_SIM_LLM_MODEL", raising=False)
    recorder = probe_modules["recorder"].ProbeRecorder(Path("/tmp") / "probe-test", "scenario")

    user = probe_modules["local_user"].LocalUser({}, recorder)

    assert user.simulator is not None
    assert user.simulator.model == "therapist-model"


async def test_local_user_deterministic_mode_does_not_construct_simulator(
    probe_modules, monkeypatch
):
    monkeypatch.setenv("PROBE_DETERMINISTIC_USER", "true")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.delenv("USER_SIM_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("USER_SIM_LLM_MODEL", raising=False)
    recorder = probe_modules["recorder"].ProbeRecorder(Path("/tmp") / "probe-test", "scenario")

    user = probe_modules["local_user"].LocalUser({}, recorder)

    assert user.simulator is None


async def test_simulator_retries_invalid_reply_then_fails_explicitly(probe_modules):
    simulator_mod = probe_modules["simulator"]
    simulator = simulator_mod.LocalLLMUserSimulator("http://unused", "model")
    simulator._chat_completion = _invalid_completion(simulator_mod)  # type: ignore[method-assign]
    with pytest.raises(simulator_mod.LocalLLMUserSimulatorError, match="invalid_reply"):
        await simulator.generate_user_reply({}, type("Context", (), {
            "transcript_tail": [], "simulator_phase": "therapy", "prompt": None
        })())


async def test_simulator_prompt_instructs_direct_screening_answers(probe_modules):
    simulator_mod = probe_modules["simulator"]
    simulator = simulator_mod.LocalLLMUserSimulator("http://unused", "model")
    context = type(
        "Context",
        (),
        {
            "transcript_tail": [],
            "simulator_phase": "You are answering intake questions.",
            "prompt": "Your response:",
        },
    )()

    prompt = simulator._build_prompt(
        {
            "persona": {
                "presenting_problem": "work anxiety",
                "coping_attempt": "tried breathing exercises",
            },
            "workflow_preferences": {"therapy_style": "cbt"},
        },
        context,
    )

    assert "Coping attempt: tried breathing exercises" in prompt
    assert "answer it directly before adding emotional detail" in prompt


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
    assert (tmp_path / "timeline.md").exists()
    assert (tmp_path / "run_manifest.json").exists()
    metadata = json.loads((tmp_path / "metadata.json").read_text())
    manifest = json.loads((tmp_path / "run_manifest.json").read_text())
    assert metadata["status"] == "PASS"
    assert manifest == metadata


async def test_recorder_writes_intake_diagnostics_and_failure_summary(
    probe_modules, tmp_path
):
    recorder = probe_modules["recorder"].ProbeRecorder(tmp_path, "scenario")
    recorder.created_rows = {
        "sessions": [
            {
                "session_id": "intake-1",
                "session_type": "intake",
                "timestamp": "2026-06-12T00:00:00+00:00",
                "transcript": json.dumps(
                    [
                        {
                            "role": "user",
                            "content": (
                                "I have been anxious about work for several "
                                "months and sleeping badly."
                            ),
                        },
                        {
                            "role": "assistant",
                            "content": (
                                "Before we continue, I want to check your safety "
                                "directly. Have you had any thoughts of harming "
                                "yourself or someone else?"
                            ),
                        },
                        {
                            "role": "user",
                            "content": "No thoughts of harm. I want to sleep better.",
                        },
                        {
                            "role": "assistant",
                            "content": (
                                "What would you most want to be different as a "
                                "result of therapy, and what would feel like the "
                                "most useful place for us to start?"
                            ),
                        },
                        {
                            "role": "user",
                            "content": "I want to sleep better and feel calmer at work.",
                        },
                    ]
                ),
            }
        ],
        "user_profiles": [{"status": "INTAKE_IN_PROGRESS"}],
    }
    await recorder.record_assertion("workflow_action_select_therapy_style", False)
    await recorder.record_assertion("therapy_plan_persisted", False)
    await recorder.write_artifacts("FAIL", {"id": "scenario"})

    diagnostics = json.loads(
        (tmp_path / "intake_completion_diagnostics.json").read_text()
    )
    failure_summary = (tmp_path / "failure_summary.md").read_text()
    summary = (tmp_path / "summary.md").read_text()

    assert diagnostics["workflow_state"] == "intake_in_progress"
    assert diagnostics["missing_required_slots"] == ["coping_attempts"]
    assert diagnostics["slot_evidence"]["duration"]["status"] == "covered"
    assert diagnostics["next_required_follow_up"] == "coping_attempts"
    assert "Intake did not complete" in failure_summary
    assert "Cascade failures" in failure_summary
    assert "Root Cause Summary" in summary


async def test_recorder_rejects_vague_duration_evidence(probe_modules, tmp_path):
    recorder = probe_modules["recorder"].ProbeRecorder(tmp_path, "scenario")
    recorder.created_rows = {
        "sessions": [
            {
                "session_id": "intake-1",
                "session_type": "intake",
                "timestamp": "2026-06-12T00:00:00+00:00",
                "transcript": json.dumps(
                    [
                        {
                            "role": "user",
                            "content": (
                                "Recently the anxiety affects work and sleep, "
                                "and I tried breathing exercises."
                            ),
                        },
                        {
                            "role": "assistant",
                            "content": (
                                "Before we continue, I want to check your safety "
                                "directly. Have you had any thoughts of harming "
                                "yourself or someone else?"
                            ),
                        },
                        {
                            "role": "user",
                            "content": "No thoughts of harm. I feel safe.",
                        },
                        {
                            "role": "assistant",
                            "content": (
                                "What would you most want to be different as a "
                                "result of therapy?"
                            ),
                        },
                        {
                            "role": "user",
                            "content": "I want to sleep better.",
                        },
                    ]
                ),
            }
        ],
        "user_profiles": [{"status": "INTAKE_IN_PROGRESS"}],
    }

    diagnostics = recorder._intake_completion_diagnostics()

    assert diagnostics is not None
    assert "duration" not in diagnostics["covered_slots"]
    assert "duration" in diagnostics["missing_hard_slots"]
    assert diagnostics["slot_evidence"]["duration"]["status"] == "missing"
    assert diagnostics["slot_evidence"]["duration"]["evidence_quote"] is None


async def test_recorder_omits_slash_commands_from_clinical_transcript(probe_modules, tmp_path):
    recorder = probe_modules["recorder"].ProbeRecorder(tmp_path, "scenario")
    await recorder.record("user_input", text="/quit", prompt_kind="chat")
    await recorder.write_artifacts("PASS", {"id": "scenario"})

    assert "/quit" not in (tmp_path / "transcript.md").read_text()


async def test_recorder_renders_timeline_with_scalar_error_data(probe_modules, tmp_path):
    recorder = probe_modules["recorder"].ProbeRecorder(tmp_path, "scenario")
    await recorder.record(
        "error",
        message="Workflow probe failed",
        data="RuntimeError('Timed out waiting for post-session plan update')",
    )
    await recorder.write_artifacts("FAIL", {"id": "scenario"})

    timeline = (tmp_path / "timeline.md").read_text()
    assert "Workflow Timeline" in timeline
    assert "Workflow probe failed" in timeline
    assert "Timed out waiting for post-session plan update" in timeline


async def test_recorder_escapes_timeline_table_cells(probe_modules, tmp_path):
    recorder = probe_modules["recorder"].ProbeRecorder(tmp_path, "scenario")
    await recorder.record("warning", message="left|right", workflow_state="a|b")

    timeline = recorder._render_timeline()

    assert "left\\|right" in timeline
    assert "a\\|b" in timeline


async def test_probe_post_session_follow_up_requires_plan_update_state(probe_modules):
    runner = probe_modules["runner"]
    assert not runner._needs_post_session_follow_up(
        [
            {
                "kind": "session_ended",
                "data": {"workflow_state": "intake_in_progress"},
            },
            {
                "kind": "error",
                "data": "RuntimeError('Timed out waiting for post-session plan update')",
            },
        ]
    )
    assert runner._needs_post_session_follow_up(
        [
            {
                "kind": "session_ended",
                "data": {"workflow_state": "plan_update_in_progress"},
            }
        ]
    )


async def test_probe_assertion_event_data_helper_tolerates_scalar_data(probe_modules):
    assertions = probe_modules["assertions"]
    assert assertions._event_data({"kind": "error", "data": "boom"}) == {}
    assert assertions._event_data({"kind": "event", "data": {"session_id": "s1"}}) == {
        "session_id": "s1"
    }


async def test_probe_concrete_step_terms_accept_breath(probe_modules):
    assertions = probe_modules["assertions"]
    response = "Try taking a breath and naming what you notice."

    assert any(
        term in response.lower()
        for term in assertions.DEFAULT_CONCRETE_STEP_TERMS
    )


async def test_recorder_counts_unphased_finish_events(probe_modules, tmp_path):
    recorder = probe_modules["recorder"].ProbeRecorder(tmp_path, "scenario")
    metrics_path = tmp_path / "backend_llm_calls.jsonl"
    metrics_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "status": "finish",
                        "call_type": "stream_response",
                        "phase": "intake_response",
                        "latency_ms": 12.5,
                    }
                ),
                json.dumps(
                    {
                        "status": "finish",
                        "call_type": "generate_response",
                        "phase": None,
                        "latency_ms": 7.25,
                    }
                ),
                json.dumps(
                    {
                        "status": "start",
                        "call_type": "generate_response",
                        "phase": None,
                        "latency_ms": None,
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    summary = recorder._load_llm_timing_summary()

    assert summary["phase_timings_ms"] == {"intake_response_ms": 12.5}
    assert summary["llm_finished_count"] == 2
    assert summary["llm_unphased_finish_count"] == 1
    assert summary["llm_unphased_latency_ms"] == 7.25


async def test_recorder_prefers_total_wall_latency_when_present(
    probe_modules, tmp_path
):
    recorder = probe_modules["recorder"].ProbeRecorder(tmp_path, "scenario")
    metrics_path = tmp_path / "backend_llm_calls.jsonl"
    metrics_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "status": "finish",
                        "call_type": "stream_response",
                        "phase": "therapy_response",
                        "latency_ms": 2000.0,
                        "total_wall_ms": 57000.0,
                    }
                ),
                json.dumps(
                    {
                        "status": "finish",
                        "call_type": "generate_response",
                        "phase": None,
                        "latency_ms": 10.0,
                        "total_wall_ms": 30.0,
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    summary = recorder._load_llm_timing_summary()

    assert summary["phase_timings_ms"] == {"therapy_response_ms": 57000.0}
    assert summary["phase_provider_timings_ms"] == {"therapy_response_ms": 2000.0}
    assert summary["llm_total_latency_ms"] == 57030.0
    assert summary["llm_provider_latency_ms"] == 2010.0
    assert summary["llm_unphased_latency_ms"] == 30.0


async def test_recorder_aggregates_extended_llm_timing_fields(
    probe_modules, tmp_path
):
    recorder = probe_modules["recorder"].ProbeRecorder(tmp_path, "scenario")
    metrics_path = tmp_path / "backend_llm_calls.jsonl"
    metrics_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "status": "finish",
                        "call_type": "stream_response",
                        "phase": "intake_response",
                        "latency_ms": 120.0,
                        "provider_latency_ms": 100.0,
                        "total_wall_ms": 150.0,
                        "request_boundary_ms": 90.0,
                        "prompt_eval_ms": 30.0,
                        "generation_ms": 60.0,
                        "chunk_count": 3,
                        "completion_chars": 42,
                        "token_count_status": "complete",
                    }
                ),
                json.dumps(
                    {
                        "status": "finish",
                        "call_type": "generate_response",
                        "phase": "assessment_style_scoring",
                        "latency_ms": 20.0,
                        "completion_chars": 12,
                        "token_count_status": "unavailable",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    summary = recorder._load_llm_timing_summary()

    assert summary["phase_provider_boundary_timings_ms"] == {
        "intake_response_ms": 90.0,
        "assessment_style_scoring_ms": 0.0,
    }
    assert summary["phase_prompt_eval_timings_ms"]["intake_response_ms"] == 30.0
    assert summary["phase_generation_timings_ms"]["intake_response_ms"] == 60.0
    assert summary["llm_stream_chunk_count"] == 3
    assert summary["phase_stream_chunk_counts"]["intake_response_ms"] == 3
    assert summary["llm_completion_chars"] == 54
    assert summary["phase_completion_chars"]["assessment_style_scoring_ms"] == 12
    assert summary["token_count_status_counts"] == {
        "complete": 1,
        "unavailable": 1,
    }


async def test_recorder_computes_user_visible_response_timings(
    probe_modules, tmp_path
):
    recorder = probe_modules["recorder"].ProbeRecorder(tmp_path, "scenario")
    recorder.events = [
        {
            "ts": "2026-06-12T21:00:00+00:00",
            "kind": "session_started",
            "data": {"session_type": "intake"},
        },
        {
            "ts": "2026-06-12T21:00:01+00:00",
            "kind": "user_input",
            "prompt_kind": "chat",
            "text": "Hello",
        },
        {
            "ts": "2026-06-12T21:00:01.500000+00:00",
            "kind": "ws_event",
            "type": "chat_response_chunk",
            "is_complete": False,
        },
        {
            "ts": "2026-06-12T21:00:02+00:00",
            "kind": "ws_event",
            "type": "chat_response_chunk",
            "is_complete": True,
        },
        {
            "ts": "2026-06-12T21:00:02.250000+00:00",
            "kind": "assistant_response",
            "text": "Hi",
        },
        {
            "ts": "2026-06-12T21:01:00+00:00",
            "kind": "session_started",
            "data": {"session_type": "therapy"},
        },
        {
            "ts": "2026-06-12T21:01:01+00:00",
            "kind": "user_input",
            "prompt_kind": "chat",
            "text": "I feel tense",
        },
        {
            "ts": "2026-06-12T21:01:31+00:00",
            "kind": "ws_event",
            "type": "chat_response_chunk",
            "is_complete": False,
        },
        {
            "ts": "2026-06-12T21:01:33+00:00",
            "kind": "ws_event",
            "type": "chat_response_chunk",
            "is_complete": True,
        },
        {
            "ts": "2026-06-12T21:01:33.100000+00:00",
            "kind": "assistant_response",
            "text": "Tell me more",
        },
    ]

    summary = recorder._response_latency_summary()

    assert summary["overall"]["count"] == 2
    assert summary["by_session_type"]["intake"]["user_visible_max_ms"] == 1250.0
    assert summary["by_session_type"]["intake"]["ttft_p95_ms"] == 500.0
    assert summary["by_session_type"]["therapy"]["user_visible_max_ms"] == 32100.0
    assert summary["by_session_type"]["therapy"]["ttft_p95_ms"] == 30000.0
    assert summary["by_session_type"]["therapy"]["stream_p95_ms"] == 2000.0


async def test_recorder_reports_latency_undercoverage_without_failing_by_default(
    probe_modules, tmp_path
):
    recorder = probe_modules["recorder"].ProbeRecorder(tmp_path, "scenario")
    recorder.events = [
        {
            "ts": "2026-06-12T21:00:00+00:00",
            "kind": "session_started",
            "data": {"session_type": "intake"},
        },
        {
            "ts": "2026-06-12T21:00:01+00:00",
            "kind": "user_input",
            "prompt_kind": "chat",
            "text": "Hello",
        },
        {
            "ts": "2026-06-12T21:00:03+00:00",
            "kind": "assistant_response",
            "text": "Hi",
        },
    ]
    metrics_path = tmp_path / "backend_llm_calls.jsonl"
    metrics_path.write_text(
        json.dumps(
            {
                "status": "finish",
                "call_type": "stream_response",
                "phase": "intake_response",
                "latency_ms": 100.0,
                "total_wall_ms": 200.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    await recorder.write_artifacts("PASS", {"id": "scenario"})

    metadata = json.loads((tmp_path / "metadata.json").read_text())
    undercoverage = metadata["timing"]["latency_undercoverage"]
    assert undercoverage["scopes"]["intake"]["coverage_ratio"] == 0.1
    assert undercoverage["warnings"]
    assert undercoverage["failures"] == []
    assert "Latency Undercoverage" in (tmp_path / "summary.md").read_text()


async def test_probe_assertions_fail_undercoverage_only_with_scenario_threshold(
    probe_modules, tmp_path
):
    assertions = probe_modules["assertions"]
    recorder = probe_modules["recorder"].ProbeRecorder(tmp_path, "scenario")
    recorder.events = [
        {
            "ts": "2026-06-12T21:00:00+00:00",
            "kind": "session_started",
            "data": {"session_type": "intake"},
        },
        {
            "ts": "2026-06-12T21:00:01+00:00",
            "kind": "user_input",
            "prompt_kind": "chat",
            "text": "Hello",
        },
        {
            "ts": "2026-06-12T21:00:03+00:00",
            "kind": "assistant_response",
            "text": "Hi",
        },
    ]
    metrics_path = tmp_path / "backend_llm_calls.jsonl"
    metrics_path.write_text(
        json.dumps(
            {
                "status": "finish",
                "call_type": "stream_response",
                "phase": "intake_response",
                "latency_ms": 100.0,
                "total_wall_ms": 200.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    await assertions.run_assertions(
        recorder,
        {
            "timing_undercoverage_thresholds": {
                "intake_min_coverage_ratio": 0.8,
            },
            "milestones": {"required_actions": []},
        },
    )

    failed = [
        assertion
        for assertion in recorder.assertions
        if assertion["name"] == "timing_latency_undercoverage_within_threshold"
    ][0]
    assert failed["passed"] is False


async def test_recorder_separates_raw_and_logical_workflow_actions(
    probe_modules, tmp_path
):
    recorder = probe_modules["recorder"].ProbeRecorder(tmp_path, "scenario")
    action = {
        "user_id": "user-1",
        "session_id": "session-1",
        "workflow_state": "initial_plan_complete",
        "required_action": "start_therapy",
        "state_signature": "sig-1",
    }

    await recorder.emit("workflow_action", action=action, delivery_source="websocket")
    await recorder.emit("workflow_action", action=action, delivery_source="http_poll")

    raw = [event for event in recorder.events if event["kind"] == "raw_workflow_action"]
    logical = [event for event in recorder.events if event["kind"] == "workflow_action"]

    assert len(raw) == 2
    assert len(logical) == 1
    assert recorder._workflow_action_summary()["duplicate_delivery_count"] == 1


async def test_wait_for_post_session_update_uses_job_status(
    probe_modules, monkeypatch, tmp_path
):
    runner = probe_modules["runner"]
    recorder = probe_modules["recorder"].ProbeRecorder(tmp_path, "scenario")
    responses = [
        {
            "job_id": "post_session_update:s1",
            "job_type": "post_session_update",
            "user_id": "u1",
            "session_id": "s1",
            "status": "running",
            "current_step": "running_reflection",
            "children": [],
        },
        {
            "job_id": "post_session_update:s1",
            "job_type": "post_session_update",
            "user_id": "u1",
            "session_id": "s1",
            "status": "complete",
            "current_step": "post_session_update_complete",
            "children": [],
        },
    ]

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class Client:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *_args, **_kwargs):
            return Response(responses.pop(0))

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(runner.httpx, "AsyncClient", Client)
    monkeypatch.setattr(runner.trio, "sleep", fake_sleep)

    await runner.wait_for_post_session_update(
        "http://backend",
        "u1",
        "s1",
        {"limits": {"plan_update_timeout_seconds": 5}},
        recorder,
    )

    assert not responses
    await recorder._flush_pending_poll()
    summary = [
        event
        for event in recorder.events
        if event["kind"] == "post_session_job_status_summary"
    ]
    assert summary


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


async def test_probe_requires_completed_therapy_enrichment(probe_modules, tmp_path):
    source = tmp_path / "runtime.sqlite"
    with sqlite3.connect(source) as conn:
        conn.execute(
            "CREATE TABLE sessions "
            "(session_id TEXT, user_id TEXT, session_type TEXT, enriched INTEGER)"
        )
        conn.execute(
            "CREATE TABLE session_enrichment_jobs "
            "(session_id TEXT, user_id TEXT, status TEXT)"
        )
        conn.execute("INSERT INTO sessions VALUES ('s1', 'probe', 'therapy', 1)")
        conn.execute(
            "INSERT INTO session_enrichment_jobs VALUES ('s1', 'probe', 'complete')"
        )

    assert probe_modules["db_snapshot"].session_enrichment_complete(
        source, "probe", ["s1"]
    )
