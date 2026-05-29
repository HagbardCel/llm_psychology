from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import pytest


pytestmark = [pytest.mark.trio, pytest.mark.unit]


@pytest.fixture
def console_modules(monkeypatch):
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(repo_root / "console-ui"))
    modules = {
        "input_providers": importlib.import_module("src.input_providers"),
        "llm_user_simulator": importlib.import_module("src.llm_user_simulator"),
        "protocol_recorder": importlib.import_module("src.protocol_recorder"),
        "console_client": importlib.import_module("src.console_client"),
        "workflow_probe_runner": importlib.import_module("src.workflow_probe_runner"),
    }
    yield modules
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)


class _StubOutput:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.logged_inputs: list[str] = []

    def prompt(self, message: str, **_kwargs: Any) -> None:
        self.prompts.append(message)

    def log_input(self, text: str) -> None:
        self.logged_inputs.append(text)

    def system(self, _message: str) -> None:
        return None

    def user_text(self, _message: str, **_kwargs: Any) -> None:
        return None

    def error(self, _message: str) -> None:
        return None

    def log_chat(self, _role: str, _text: str) -> None:
        return None


async def test_scripted_input_provider_uses_structural_prompt_response(console_modules):
    input_providers = console_modules["input_providers"]
    context = input_providers.InputContext(
        prompt="Enter the number or style id: ",
        default=None,
        prompt_kind="therapy_style",
        user_id="user-1",
        session_id="session-1",
        workflow_action=None,
        pending_recommendations=None,
        transcript_tail=[],
        turn_index=0,
    )
    provider = input_providers.ScriptedInputProvider(
        responses=["chat response"],
        prompt_responses={"therapy_style": "cbt"},
    )

    assert await provider.get_input(context) == "cbt"


async def test_console_client_delegates_get_user_input_to_provider(console_modules):
    console_client = console_modules["console_client"]

    class Provider:
        async def get_input(self, context: Any) -> str:
            assert context.prompt_kind == "profile_name"
            return "Probe User"

    output = _StubOutput()
    client = console_client.ConsoleClient(
        backend_url="http://localhost:8000",
        websocket_url="http://localhost:8000",
        user_id="user-1",
        output=output,
        input_provider=Provider(),
    )

    assert await client._get_user_input("Enter your name (required): ") == "Probe User"
    assert output.logged_inputs == ["Probe User"]


async def test_llm_input_provider_uses_scripted_chat_fallbacks(console_modules):
    input_providers = console_modules["input_providers"]

    class Simulator:
        async def generate_user_reply(
            self,
            scenario: dict[str, Any],
            context: Any,
            fallback_response: str,
        ) -> dict[str, str]:
            assert scenario is not None
            assert context is not None
            return {
                "text": fallback_response,
                "input_origin": "fallback",
                "fallback_reason": "invalid_reply",
            }

    context = input_providers.InputContext(
        prompt=None,
        default=None,
        prompt_kind="chat",
        user_id="user-1",
        session_id="session-1",
        workflow_action=None,
        pending_recommendations=None,
        transcript_tail=[],
        turn_index=0,
    )
    provider = input_providers.LLMSimulatedUserProvider(
        simulator=Simulator(),
        scenario={"scripted_responses": ["first", "second", "/quit"]},
        fallback_response="default",
    )

    first = await provider.get_input(context)
    second = await provider.get_input(context)
    third = await provider.get_input(context)

    assert first.text == "first"
    assert first.input_origin == "fallback"
    assert second.text == "second"
    assert third.text == "default"


async def test_probe_chat_loop_reraises_provider_errors(console_modules):
    console_client = console_modules["console_client"]

    class Provider:
        async def get_input(self, _context: Any) -> str:
            raise RuntimeError("model failed")

    client = console_client.ConsoleClient(
        backend_url="http://localhost:8000",
        websocket_url="http://localhost:8000",
        user_id="user-1",
        output=_StubOutput(),
        input_provider=Provider(),
        probe_limits={"max_total_turns": 2},
    )
    client.current_session_id = "session-1"

    async def fake_get_next_action() -> dict[str, Any]:
        return {"required_action": "start_intake"}

    client._get_next_action = fake_get_next_action  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="model failed"):
        await client._chat_loop(ws=None)


async def test_recorder_writes_jsonl_and_markdown_summary(console_modules, tmp_path):
    protocol_recorder = console_modules["protocol_recorder"]
    recorder = protocol_recorder.ProtocolRecorder(tmp_path, "scenario")

    await recorder.record("ws_event", type="session_started")
    await recorder.record_user_input(
        "hello",
        "ScriptedInputProvider",
        type(
            "Context",
            (),
            {"prompt_kind": "chat", "turn_index": 0},
        )(),
    )
    await recorder.record_assistant_response("hi")
    await recorder.record_model_call(
        prompt="prompt",
        raw_response="",
        sanitized_response="hello",
        fallback_used=True,
        fallback_reason="empty_response",
    )
    await recorder.record_error(
        "Local user simulator failed",
        {"reason": "content_blank_after_strip", "http_status": 200},
    )
    await recorder.record_assertion("example", True)
    await recorder.write_summary("PASS", {"id": "scenario"})

    assert recorder.latest_jsonl_path.exists()
    assert recorder.latest_md_path.exists()
    summary = recorder.latest_md_path.read_text(encoding="utf-8")
    assert "Status: PASS" in summary
    assert "Fallback reasons: empty_response: 1" in summary
    assert "## Errors" in summary
    assert "content_blank_after_strip" in summary


async def test_probe_user_ids_are_unique(console_modules):
    runner = console_modules["workflow_probe_runner"]

    assert runner.new_probe_user_id() != runner.new_probe_user_id()


async def test_runner_finds_simulator_errors_inside_exception_groups(console_modules):
    runner = console_modules["workflow_probe_runner"]
    simulator_mod = console_modules["llm_user_simulator"]
    simulator_error = simulator_mod.LocalLLMUserSimulatorError(
        "content_blank_after_strip",
        "Local user simulator failed: content_blank_after_strip",
        {"http_status": 200},
    )
    grouped = ExceptionGroup(
        "outer",
        [
            ValueError("unrelated"),
            ExceptionGroup("inner", [simulator_error]),
        ],
    )

    assert (
        runner._find_nested_exception(
            grouped, simulator_mod.LocalLLMUserSimulatorError
        )
        is simulator_error
    )
    assert (
        runner._find_nested_exception(
            ValueError("nope"), simulator_mod.LocalLLMUserSimulatorError
        )
        is None
    )


async def test_runner_detects_recorded_simulator_failure(console_modules, tmp_path):
    runner = console_modules["workflow_probe_runner"]
    recorder_mod = console_modules["protocol_recorder"]
    recorder = recorder_mod.ProtocolRecorder(tmp_path, "scenario")

    assert runner._recorded_simulator_failure(recorder) is None

    await recorder.record_error(
        "Local user simulator failed",
        {"reason": "content_blank_after_strip", "http_status": 200},
    )

    failure = runner._recorded_simulator_failure(recorder)
    assert failure["reason"] == "content_blank_after_strip"
    assert failure["http_status"] == 200


async def test_assertions_fail_when_required_workflow_action_missing(
    console_modules, tmp_path
):
    runner = console_modules["workflow_probe_runner"]
    recorder_mod = console_modules["protocol_recorder"]
    recorder = recorder_mod.ProtocolRecorder(tmp_path, "scenario")

    await recorder.record("ws_event", type="session_started")
    await recorder.record_workflow_action({"required_action": "start_intake"})
    await recorder.record_user_input(
        "one",
        "ScriptedInputProvider",
        type("Context", (), {"prompt_kind": "chat", "turn_index": 0})(),
    )
    await recorder.record_assistant_response("hello")

    passed = await runner.run_assertions(
        recorder=recorder,
        scenario={
            "success_criteria": {
                "require_workflow_actions": ["start_intake", "continue_therapy"]
            }
        },
        backend_url="http://unused",
        user_id="user-1",
    )

    assert passed is False
    assert any(
        assertion["name"] == "workflow_action_continue_therapy"
        and assertion["passed"] is False
        for assertion in recorder.assertions
    )


async def test_assertions_fail_on_fallback_and_repetition(console_modules, tmp_path):
    runner = console_modules["workflow_probe_runner"]
    recorder_mod = console_modules["protocol_recorder"]
    recorder = recorder_mod.ProtocolRecorder(tmp_path, "scenario")
    context = type("Context", (), {"prompt_kind": "chat", "turn_index": 0})()

    await recorder.record("ws_event", type="session_started")
    await recorder.record_user_input("same", "LLMSimulatedUserProvider", context)
    await recorder.record_user_input("same", "LLMSimulatedUserProvider", context)
    await recorder.record_assistant_response("same therapist")
    await recorder.record_assistant_response("same therapist")
    await recorder.record_model_call(
        prompt="prompt",
        raw_response="raw",
        sanitized_response="same",
        fallback_used=True,
    )

    passed = await runner.run_assertions(
        recorder=recorder,
        scenario={
            "success_criteria": {
                "require_min_user_messages": 2,
                "require_min_assistant_messages": 2,
                "require_unique_user_messages": 2,
                "require_assistant_response_variation": 2,
                "fail_on_user_sim_fallback": True,
            }
        },
        backend_url="http://unused",
        user_id="user-1",
    )

    assert passed is False
    failed_names = {
        assertion["name"]
        for assertion in recorder.assertions
        if assertion["passed"] is False
    }
    assert "unique_user_messages" in failed_names
    assert "assistant_response_variation" in failed_names
    assert "user_sim_fallback_rate" in failed_names


async def test_assertions_fail_on_wait_threshold_and_assistant_meta_phrase(
    console_modules, tmp_path
):
    runner = console_modules["workflow_probe_runner"]
    recorder_mod = console_modules["protocol_recorder"]
    recorder = recorder_mod.ProtocolRecorder(tmp_path, "scenario")

    await recorder.record("ws_event", type="session_started")
    await recorder.record_workflow_action({"required_action": "wait"})
    await recorder.record(
        "workflow_action",
        action="wait",
        total_wait_seconds=181.0,
    )
    await recorder.record_assistant_response(
        "Sometimes system messages can slip through, but we can keep going."
    )

    passed = await runner.run_assertions(
        recorder=recorder,
        scenario={
            "success_criteria": {
                "max_wait_seconds_before_style_selection": 180,
                "forbid_assistant_phrases": ["system messages can slip through"],
            }
        },
        backend_url="http://unused",
        user_id="user-1",
    )

    assert passed is False
    failed_names = {
        assertion["name"]
        for assertion in recorder.assertions
        if assertion["passed"] is False
    }
    assert "wait_before_style_selection" in failed_names
    assert any(name.startswith("forbid_assistant_phrase_") for name in failed_names)


async def test_assertions_fail_on_premature_time_up_phrase(
    console_modules, tmp_path
):
    runner = console_modules["workflow_probe_runner"]
    recorder_mod = console_modules["protocol_recorder"]
    recorder = recorder_mod.ProtocolRecorder(tmp_path, "scenario")

    await recorder.record("ws_event", type="session_started")
    await recorder.record_assistant_response(
        "Our time is up for today. We will continue this intake next time."
    )

    passed = await runner.run_assertions(
        recorder=recorder,
        scenario={
            "success_criteria": {
                "forbid_assistant_phrases_before_turn": [
                    {"phrase": "Our time is up", "min_turn": 4}
                ]
            }
        },
        backend_url="http://unused",
        user_id="user-1",
    )

    assert passed is False
    assert any(
        assertion["name"].startswith("forbid_assistant_phrase_before_turn_")
        and assertion["passed"] is False
        for assertion in recorder.assertions
    )


async def test_assertions_check_final_workflow_state(
    console_modules, tmp_path, monkeypatch
):
    runner = console_modules["workflow_probe_runner"]
    recorder_mod = console_modules["protocol_recorder"]
    recorder = recorder_mod.ProtocolRecorder(tmp_path, "scenario")

    await recorder.record("ws_event", type="session_started", data={"session_id": "s1"})

    async def fake_fetch_user_status(
        _backend_url: str, _user_id: str, _session_id: str | None
    ) -> dict[str, Any]:
        return {"workflow_state": "intake_in_progress"}

    monkeypatch.setattr(runner, "fetch_user_status", fake_fetch_user_status)

    passed = await runner.run_assertions(
        recorder=recorder,
        scenario={
            "success_criteria": {
                "require_final_workflow_state": "therapy_in_progress"
            }
        },
        backend_url="http://unused",
        user_id="user-1",
    )

    assert passed is False
    assert any(
        assertion["name"] == "final_workflow_state"
        and assertion["passed"] is False
        for assertion in recorder.assertions
    )


async def test_final_workflow_state_allows_completed_session_therapy_signal(
    console_modules, tmp_path, monkeypatch
):
    runner = console_modules["workflow_probe_runner"]
    recorder_mod = console_modules["protocol_recorder"]
    recorder = recorder_mod.ProtocolRecorder(tmp_path, "scenario")

    await recorder.record("ws_event", type="session_started", data={"session_id": "s1"})
    await recorder.record_workflow_action(
        {
            "required_action": "select_therapy_style",
            "workflow_state": "assessment_complete",
        }
    )
    await recorder.record("therapy_style_selected", selected_therapy_style="cbt")
    await recorder.record_user_input(
        "I want to keep working on this.",
        "LLMSimulatedUserProvider",
        type("Context", (), {"prompt_kind": "chat", "turn_index": 0})(),
    )
    await recorder.record_workflow_action(
        {"required_action": "continue_therapy", "workflow_state": "plan_complete"}
    )
    await recorder.record_assistant_response("Let's continue therapy.")
    await recorder.record(
        "session_ended",
        data={"workflow_state": "plan_complete", "reason": "Probe limit"},
    )

    async def fake_fetch_user_status(
        _backend_url: str, _user_id: str, _session_id: str | None
    ) -> dict[str, Any]:
        return {"error": "Session is not active for user"}

    monkeypatch.setattr(runner, "fetch_user_status", fake_fetch_user_status)

    passed = await runner.run_assertions(
        recorder=recorder,
        scenario={
            "success_criteria": {
                "require_final_workflow_state": "therapy_in_progress"
            }
        },
        backend_url="http://unused",
        user_id="user-1",
    )

    assert passed is True
    assert any(
        assertion["name"] == "final_workflow_state"
        and assertion["passed"] is True
        for assertion in recorder.assertions
    )


async def test_local_llm_simulator_records_fallback_reasons(console_modules):
    simulator_mod = console_modules["llm_user_simulator"]

    class Recorder:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def record_model_call(self, **kwargs: Any) -> None:
            self.calls.append(kwargs)

        async def record_user_simulator_raw_response(self, **kwargs: Any) -> None:
            self.calls.append({"raw": kwargs})

    async def run_with_completion(
        completion: Any, scenario: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], Recorder]:
        recorder = Recorder()
        simulator = simulator_mod.LocalLLMUserSimulator(
            base_url="http://unused",
            model="unused",
            recorder=recorder,
        )
        simulator._chat_completion = completion  # type: ignore[method-assign]
        result = await simulator.generate_user_reply(
            scenario=scenario or {},
            context=type(
                "Context",
                (),
                {
                    "transcript_tail": [],
                    "workflow_action": None,
                    "prompt": None,
                },
            )(),
            fallback_response="fallback",
        )
        return result, recorder

    async def timeout_completion(_prompt: str) -> str:
        return simulator_mod.ChatCompletionResult(
            content="slow",
            http_status=None,
            raw_preview="slow",
            response_shape="request_timeout",
            failure_reason="local_llm_timeout",
        )

    with pytest.raises(
        simulator_mod.LocalLLMUserSimulatorError, match="local_llm_timeout"
    ):
        await run_with_completion(timeout_completion)

    result, recorder = await run_with_completion(
        timeout_completion,
        {"allow_user_sim_fallback": True},
    )
    assert result["input_origin"] == "fallback"
    assert result["fallback_reason"] == "local_llm_timeout"
    assert recorder.calls[-1]["fallback_reason"] == "local_llm_timeout"

    async def invalid_completion(_prompt: str) -> str:
        return simulator_mod.ChatCompletionResult(
            content="As an AI, I cannot roleplay this.",
            http_status=200,
            raw_preview="As an AI, I cannot roleplay this.",
            response_shape="choices[0].message.content",
        )

    result, recorder = await run_with_completion(
        invalid_completion,
        {"allow_user_sim_fallback": True},
    )
    assert result["fallback_reason"] == "invalid_reply"
    assert recorder.calls[-1]["fallback_reason"] == "invalid_reply"

    async def empty_completion(_prompt: str) -> str:
        return simulator_mod.ChatCompletionResult(
            content="",
            http_status=200,
            raw_preview="",
            response_shape="choices[0].message.content",
        )

    result, _recorder = await run_with_completion(
        empty_completion,
        {"allow_user_sim_fallback": True},
    )
    assert result["fallback_reason"] == "content_blank_after_strip"


async def test_local_llm_response_shape_extraction(console_modules):
    simulator_mod = console_modules["llm_user_simulator"]
    simulator = simulator_mod.LocalLLMUserSimulator(
        base_url="http://unused",
        model="unused",
    )

    message = simulator._extract_content(
        {"choices": [{"message": {"content": "I feel anxious."}}]},
        200,
        '{"choices": []}',
    )
    assert message.content == "I feel anxious."
    assert message.response_shape == "choices[0].message.content"

    delta = simulator._extract_content(
        {"choices": [{"delta": {"content": "I feel stuck."}}]},
        200,
        '{"choices": []}',
    )
    assert delta.content == "I feel stuck."
    assert delta.response_shape == "choices[0].delta.content"

    missing = simulator._extract_content({}, 200, "{}")
    assert missing.failure_reason == "missing_choices"

    missing_message = simulator._extract_content(
        {"choices": [{"finish_reason": "stop"}]},
        200,
        "{}",
    )
    assert missing_message.failure_reason == "missing_message_field"


async def test_resolve_user_sim_max_tokens(console_modules, monkeypatch):
    simulator_mod = console_modules["llm_user_simulator"]

    monkeypatch.delenv("USER_SIM_LLM_MAX_TOKENS", raising=False)
    monkeypatch.setenv("APP_ENV", "testing")
    assert simulator_mod.resolve_user_sim_max_tokens() == 8192

    monkeypatch.setenv("APP_ENV", "production")
    assert simulator_mod.resolve_user_sim_max_tokens() is None

    monkeypatch.setenv("USER_SIM_LLM_MAX_TOKENS", "0")
    assert simulator_mod.resolve_user_sim_max_tokens() is None

    monkeypatch.setenv("USER_SIM_LLM_MAX_TOKENS", "4096")
    assert simulator_mod.resolve_user_sim_max_tokens() == 4096


async def test_local_llm_simulator_disables_thinking_in_request(
    console_modules, monkeypatch
):
    simulator_mod = console_modules["llm_user_simulator"]
    captured: dict[str, Any] = {}

    class _FakeResponse:
        is_error = False
        status_code = 200
        text = (
            '{"choices":[{"message":{"content":"I feel anxious."},'
            '"finish_reason":"stop"}]}'
        )

        def json(self) -> dict[str, Any]:
            return {
                "choices": [
                    {
                        "message": {"content": "I feel anxious."},
                        "finish_reason": "stop",
                    }
                ]
            }

    class _FakeClient:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def post(self, _url: str, json: dict[str, Any], headers: dict[str, str]):
            captured["json"] = json
            captured["headers"] = headers
            return _FakeResponse()

    monkeypatch.setattr(simulator_mod.httpx, "AsyncClient", _FakeClient)

    simulator = simulator_mod.LocalLLMUserSimulator(
        base_url="http://unused",
        model="unused",
    )
    result = await simulator._chat_completion("prompt")

    assert captured["json"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert result.content == "I feel anxious."


async def test_local_llm_reasoning_budget_extraction_and_failure(console_modules):
    simulator_mod = console_modules["llm_user_simulator"]
    simulator = simulator_mod.LocalLLMUserSimulator(
        base_url="http://unused",
        model="unused",
    )

    reasoning_response = simulator._extract_content(
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": "Let me think through this step by step.",
                    },
                    "finish_reason": "length",
                }
            ]
        },
        200,
        "{}",
    )
    assert reasoning_response.content == ""
    assert reasoning_response.finish_reason == "length"
    assert reasoning_response.reasoning_content_chars > 0
    assert reasoning_response.response_shape == "choices[0].message.content"

    failure = simulator._reply_failure_reason(reasoning_response, "")
    assert failure == "content_blank_after_reasoning_budget_exhausted"

    empty_no_reasoning = simulator_mod.ChatCompletionResult(
        content="",
        http_status=200,
        raw_preview="",
        response_shape="choices[0].message.content",
    )
    assert (
        simulator._reply_failure_reason(empty_no_reasoning, "")
        == "content_blank_after_strip"
    )


async def test_local_llm_recorder_records_finish_reason_metadata(console_modules):
    simulator_mod = console_modules["llm_user_simulator"]

    class Recorder:
        def __init__(self) -> None:
            self.raw_calls: list[dict[str, Any]] = []

        async def record_user_simulator_raw_response(self, **kwargs: Any) -> None:
            self.raw_calls.append(kwargs)

    recorder = Recorder()
    simulator = simulator_mod.LocalLLMUserSimulator(
        base_url="http://unused",
        model="unused",
        recorder=recorder,
    )
    result = simulator_mod.ChatCompletionResult(
        content="",
        http_status=200,
        raw_preview="preview",
        response_shape="choices[0].message.content",
        finish_reason="length",
        reasoning_content_chars=42,
    )
    await simulator._record_raw_result(result)

    assert len(recorder.raw_calls) == 1
    call = recorder.raw_calls[0]
    assert call["finish_reason"] == "length"
    assert call["reasoning_content_chars"] == 42


async def test_llm_user_reply_sanitization_rejects_meta_response(console_modules):
    simulator = console_modules["llm_user_simulator"]

    assert simulator.sanitize_user_reply('User: "I feel anxious."') == "I feel anxious."
    assert (
        simulator.sanitize_user_reply(
            "Here is my response:\nPatient: I notice my chest gets tight at night."
        )
        == "I notice my chest gets tight at night."
    )
    assert simulator.is_valid_user_reply("As an AI, I cannot do that.") is False
    assert simulator.is_valid_user_reply("I feel anxious about work.") is True
