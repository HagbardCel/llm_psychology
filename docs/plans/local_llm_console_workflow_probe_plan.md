# Plan: Local-LLM Simulated User Workflow Probe for `llm_psychology`

## 1. Purpose

The goal is to reduce repetitive manual console-UI user testing by letting a local LLM act as a realistic but constrained user. The probe should exercise the real console-client workflow as closely as possible while producing structured logs that make workflow failures easy to diagnose.

This should **not** replace deterministic unit/integration/E2E tests. It should become a **local diagnostic workflow probe** that answers:

> “If a plausible user goes through the console UI, does the end-to-end workflow actually proceed without dead ends, protocol errors, missing prompts, or broken state transitions?”

The probe should be close enough to manual console testing that a successful run gives confidence that the real console UI is usable.

---

## 2. Core recommendation

### Recommended approach

Reuse the existing `ConsoleClient` and inject an alternative input source:

```text
ConsoleClient
  ├── HumanInputProvider       # current behavior: input()
  └── LLMSimulatedUserProvider # new behavior: local LLM produces user replies
```

The console client should still:

- call the same HTTP endpoints;
- connect to the same WebSocket endpoint;
- receive and handle the same streaming messages;
- follow the same backend workflow loop;
- call the same `complete_profile` and `select_therapy_style` APIs;
- log the same user-visible console output.

The only meaningful replacement should be:

```python
input().strip()
```

with:

```python
await input_provider.get_input(prompt=..., context=...)
```

This gives much higher fidelity than writing a separate direct WebSocket test, because the probe continues to exercise the real console-client state machine.

---

## 3. Why not simply pipe text into stdin?

Piping LLM responses into stdin is possible, but it is the weaker design.

### Option A: pipe into stdin

Example concept:

```bash
python llm_user_pipe.py | python console-ui/main.py
```

Problems:

- The LLM process does not reliably know when the console is waiting for input.
- It must parse stdout, ANSI formatting, prompts, and partial streaming output.
- Race conditions are likely.
- Workflow-specific prompts such as profile creation and therapy-style selection become hard to handle.
- Debugging becomes harder because there is no structured view of “why did the simulated user answer this?”

This can be useful as a very rough black-box smoke test, but it is brittle.

### Option B: inject an input provider

This is the recommended design.

Benefits:

- Reuses `ConsoleClient.run()` and `_follow_workflow()`.
- Keeps the test close to the real console UI.
- Avoids fragile stdout/stdin parsing.
- Allows deterministic handling of non-chat prompts.
- Allows structured protocol logging.
- Makes failures reproducible enough for debugging.

The user-visible behavior remains almost identical. Internally, the console client asks an injected provider for input instead of reading from `input()`.

---

## 4. Current repo anchors

The existing implementation already has the right seams.

Relevant current components:

```text
console-ui/main.py
console-ui/src/console_client.py
console-ui/src/output.py
console-ui/src/websocket_protocol.py
src/psychoanalyst_app/e2e_server.py
src/psychoanalyst_app/testing/fakes.py
tests/integration/test_console_ui_patient_flow.py
```

Important existing behavior:

- `console-ui/main.py` instantiates `ConsoleClient` and calls `client.run()`.
- `ConsoleClient.run()`:
  - creates an HTTP client;
  - selects or creates a profile;
  - connects to WebSocket;
  - starts `_websocket_receiver()`;
  - calls `_follow_workflow()`.
- `_follow_workflow()` polls `/workflow/next` and handles:
  - `complete_profile`;
  - `select_therapy_style`;
  - `start_intake`;
  - `continue_therapy`;
  - `wait`;
  - `error`.
- `_chat_loop()` asks for user input, sends chat messages, waits for response completion, and handles slash commands.
- `_get_user_input()` is the current input seam.

The probe should keep all of that logic.

---

## 5. Desired test fidelity

The probe should be “console-UI-close” in the following sense:

| Concern | Desired fidelity |
|---|---|
| HTTP API usage | Same as console UI |
| WebSocket protocol | Same as console UI |
| Workflow polling | Same as console UI |
| Profile creation | Same as console UI |
| Therapy-style selection | Same as console UI |
| Chat streaming | Same as console UI |
| Console output | Same `ConsoleOutput` or compatible recorder |
| Input method | Replaced with LLM provider |
| Backend therapist LLM | Real local backend in usertest mode |
| User simulator LLM | Separate local OpenAI-compatible client |

---

## 6. High-level architecture

```text
                         ┌────────────────────────┐
                         │ Local LLM user model    │
                         │ e.g. LM Studio / Ollama │
                         │ / llama.cpp server      │
                         └───────────┬────────────┘
                                     │
                                     v
┌──────────────────┐       ┌─────────────────────────┐
│ Scenario config  │──────▶│ LLMSimulatedUserProvider │
└──────────────────┘       └───────────┬─────────────┘
                                       │
                                       v
                              ┌────────────────┐
                              │ ConsoleClient  │
                              │ real workflow  │
                              └───────┬────────┘
                                      │
                         HTTP + WS    │
                                      v
                          ┌────────────────────┐
                          │ api-usertest        │
                          │ real backend path   │
                          └─────────┬──────────┘
                                    │
                                    v
                          ┌────────────────────┐
                          │ app therapist LLM   │
                          │ local / configured  │
                          └────────────────────┘

All turns, workflow actions, events, errors, timings, and assertions
are written to JSONL + Markdown summary.
```

---

## 7. Separate “therapist model” from “simulated user model”

There are two logically distinct LLM roles:

### 7.1 App / therapist LLM

This is the LLM used by the actual application backend. It should be configured exactly as in your usertest environment.

Example:

```text
api-usertest
  APP_ENV=development or usertest
  LLM provider = local OpenAI-compatible endpoint
  model = your preferred therapy backend model
```

### 7.2 Simulated user LLM

This is the local model that generates user replies. It should be isolated from the backend therapist LLM.

Example environment variables:

```bash
USER_SIM_LLM_BASE_URL=http://host.docker.internal:1234/v1
USER_SIM_LLM_MODEL=qwen3.6-8b-instruct
USER_SIM_LLM_API_KEY=not-needed
USER_SIM_LLM_TEMPERATURE=0
USER_SIM_LLM_MAX_TOKENS=80
```

The two roles can use the same local server, but the prompts and clients should be separate.

---

## 8. New components to add

### 8.1 `console-ui/src/input_providers.py`

Defines the input abstraction.

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class InputContext:
    prompt: str | None
    user_id: str | None
    session_id: str | None
    workflow_action: dict[str, Any] | None
    pending_recommendations: list[dict[str, Any]] | None
    transcript_tail: list[dict[str, str]]
    turn_index: int


class InputProvider(Protocol):
    async def get_input(self, context: InputContext) -> str:
        ...
```

Human provider:

```python
class HumanInputProvider:
    def __init__(self, output):
        self.output = output

    async def get_input(self, context: InputContext) -> str:
        import trio

        if context.prompt:
            self.output.prompt(context.prompt)
        self.output.prompt("\nYour response: ", end="")
        return await trio.to_thread.run_sync(lambda: input().strip())
```

Scripted provider for deterministic harness tests:

```python
class ScriptedInputProvider:
    def __init__(self, responses: list[str]):
        self.responses = list(responses)

    async def get_input(self, context: InputContext) -> str:
        if not self.responses:
            raise RuntimeError("No scripted responses left")
        return self.responses.pop(0)
```

LLM provider:

```python
class LLMSimulatedUserProvider:
    async def get_input(self, context: InputContext) -> str:
        # Non-chat prompts can be answered deterministically.
        # Chat prompts are generated by local LLM.
        ...
```

---

### 8.2 `console-ui/src/protocol_recorder.py`

Records machine-readable traces.

Responsibilities:

- record input prompts;
- record generated user replies;
- record assistant streamed responses;
- record WebSocket event types;
- record workflow next actions;
- record API-level milestones;
- record assertions;
- write JSONL;
- write final Markdown summary.

Suggested JSONL events:

```json
{"ts":"...","kind":"workflow_action","action":"start_intake","prompt":null}
{"ts":"...","kind":"prompt","prompt":"Your response:"}
{"ts":"...","kind":"user_input","source":"llm","text":"I've been anxious about work lately."}
{"ts":"...","kind":"assistant_response","text":"..."}
{"ts":"...","kind":"ws_event","type":"chat_response_chunk","is_complete":true}
{"ts":"...","kind":"assertion","name":"no_error_events","passed":true}
{"ts":"...","kind":"final_state","workflow_state":"THERAPY_IN_PROGRESS"}
```

Suggested output files:

```text
logs/workflow-probes/
  latest.jsonl
  latest.md
  2026-05-28T20-45-00Z_console_llm_probe.jsonl
  2026-05-28T20-45-00Z_console_llm_probe.md
```

---

### 8.3 `console-ui/src/llm_user_simulator.py`

OpenAI-compatible local LLM client.

Keep it deliberately small and dependency-light. Since the backend already uses `httpx`, use `httpx.AsyncClient`.

Pseudo-interface:

```python
class LocalLLMUserSimulator:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 80,
    ):
        ...

    async def generate_user_reply(self, scenario, context) -> str:
        ...
```

Expected endpoint:

```text
POST {USER_SIM_LLM_BASE_URL}/chat/completions
```

This should work with:

- LM Studio OpenAI-compatible server;
- llama.cpp OpenAI-compatible server;
- Ollama OpenAI-compatible endpoint, depending on setup.

---

### 8.4 `console-ui/src/workflow_probe_runner.py`

Dedicated runner for simulated-user console probing.

Responsibilities:

- load scenario YAML/JSON;
- configure `ConsoleOutput`;
- configure `ProtocolRecorder`;
- instantiate `LLMSimulatedUserProvider`;
- instantiate `ConsoleClient`;
- call `client.run()`;
- enforce overall timeout;
- run final assertions;
- write summary.

Example CLI:

```bash
python -m src.workflow_probe_runner \
  --scenario scenarios/console_workflow_probe/basic_intake_to_therapy.yaml \
  --backend-url http://localhost:8001 \
  --websocket-url http://localhost:8001 \
  --output-dir logs/workflow-probes
```

Potential script entry point in `pyproject.toml` or console-ui package config:

```text
psychoanalyst-console-probe = "src.workflow_probe_runner:cli"
```

---

## 9. Refactor `ConsoleClient` minimally

### 9.1 Constructor change

Current constructor:

```python
def __init__(
    self,
    backend_url: str,
    websocket_url: str,
    user_id: str | None,
    output: ConsoleOutput,
):
```

Recommended constructor:

```python
def __init__(
    self,
    backend_url: str,
    websocket_url: str,
    user_id: str | None,
    output: ConsoleOutput,
    input_provider: InputProvider | None = None,
    recorder: ProtocolRecorder | None = None,
):
    ...
```

Default:

```python
self.input_provider = input_provider or HumanInputProvider(output)
self.recorder = recorder
self.transcript_tail: list[dict[str, str]] = []
self.turn_index = 0
```

This preserves normal behavior.

---

### 9.2 Replace `_get_user_input()`

Instead of directly calling `input()`:

```python
user_input = await trio.to_thread.run_sync(lambda: input().strip())
```

build an `InputContext`:

```python
context = InputContext(
    prompt=prompt,
    user_id=self.user_id,
    session_id=self.current_session_id,
    workflow_action=self.latest_workflow_action,
    pending_recommendations=self.pending_recommendations,
    transcript_tail=self.transcript_tail[-8:],
    turn_index=self.turn_index,
)
user_input = await self.input_provider.get_input(context)
```

Then log it using the existing console output:

```python
self.output.log_input(user_input)
```

Also record it:

```python
if self.recorder:
    await self.recorder.record_user_input(
        text=user_input,
        source=self.input_provider.__class__.__name__,
        context=context,
    )
```

---

### 9.3 Capture transcript tail inside `ConsoleClient`

When the user sends a message:

```python
self.transcript_tail.append({"role": "user", "content": user_message})
```

When the assistant stream completes:

```python
self.transcript_tail.append({"role": "assistant", "content": full_message})
```

This gives the simulated user enough context without needing to parse logs.

---

### 9.4 Record WebSocket events

Inside `_handle_websocket_message()`:

```python
if self.recorder:
    await self.recorder.record_ws_event(message)
```

Inside `_handle_workflow_next_action()`:

```python
if self.recorder:
    await self.recorder.record_workflow_action(data)
```

Inside `_handle_error()`:

```python
if self.recorder:
    await self.recorder.record_error(data)
```

This makes failures transparent.

---

## 10. Scenario design

Use declarative scenario files.

Suggested directory:

```text
console-ui/scenarios/workflow-probes/
  basic_new_user_intake_to_therapy.yaml
  returning_user_resume_therapy.yaml
  hesitant_user_long_intake.yaml
  invalid_style_then_valid_style.yaml
  timer_and_quit_command.yaml
```

### 10.1 Basic scenario example

```yaml
id: basic_new_user_intake_to_therapy
description: >
  New user creates a profile, completes intake, selects CBT, and enters therapy.

user:
  name: Fabian
  primary_language: English

persona:
  role: "new therapy-app user"
  age: "adult"
  presenting_problem: "work-related anxiety and sleep disruption"
  style: "cooperative, reflective, concise"
  constraints:
    - "Keep replies under 40 words."
    - "Do not mention that you are an AI."
    - "Do not ask meta-questions about the test."
    - "Do not use slash commands unless instructed."

workflow_preferences:
  therapy_style: cbt
  profile_selection: create_new

limits:
  max_total_turns: 14
  max_intake_turns: 6
  max_therapy_turns: 4
  overall_timeout_seconds: 180
  response_timeout_seconds: 45

success_criteria:
  require_no_ws_errors: true
  require_profile_created: true
  require_assessment_recommendations_seen: true
  require_therapy_style_selected: true
  require_final_action_any_of:
    - continue_therapy
    - start_intake
  require_min_user_messages: 4
  require_min_assistant_messages: 4

stop:
  after_therapy_turns: 3
  send_end_session: true
```

### 10.2 Prompt handling policy

Not every console prompt should go to the LLM.

Use deterministic answers for structural prompts:

| Prompt type | Response source |
|---|---|
| Profile selection | Scenario |
| Name | Scenario |
| Primary language | Scenario |
| Therapy style selection | Scenario |
| `/timer` / `/quit` commands | Scenario/runner |
| Free-form therapy chat | LLM |

This keeps the simulated user realistic where it matters, but stable where the workflow requires exact input.

---

## 11. LLM simulated user prompt

### 11.1 System prompt

```text
You are a simulated user testing a console-based therapy application.

You are NOT the therapist. You are the patient/user.

Your task is to behave like a plausible human user going through onboarding,
intake, assessment, and an initial therapy session.

Rules:
- Reply only with the next user message.
- Keep replies concise: maximum 40 words.
- Do not describe your reasoning.
- Do not mention that this is a test.
- Do not mention being an AI.
- Do not use markdown.
- Do not ask what to do next unless the therapist asks an unclear question.
- Cooperate with the workflow.
- If asked to choose a therapy style, choose the configured preferred style.
- If the console asks for a profile field, answer with the configured profile value.
```

### 11.2 Developer/context message

```text
Scenario:
- Name: Fabian
- Primary language: English
- Presenting problem: work-related anxiety and sleep disruption.
- Preferred therapy style: CBT.
- Personality: cooperative, reflective, slightly anxious, concise.

Current workflow action: {workflow_action}

Recent transcript:
{transcript_tail}

Console prompt:
{prompt}

Return exactly one user response.
```

### 11.3 Output validation

After receiving LLM output:

- strip whitespace;
- remove surrounding quotes;
- reject empty responses;
- reject responses over max length;
- reject meta-responses like “As an AI...”;
- reject multiline outputs if not allowed;
- optionally regenerate once;
- fall back to scripted scenario response if regeneration fails.

Pseudo-code:

```python
reply = sanitize(raw_reply)

if not is_valid(reply):
    reply = await regenerate_once()

if not is_valid(reply):
    reply = scenario.fallback_reply_for(context)
```

---

## 12. Assertions and pass/fail criteria

The LLM should **not** judge whether the test passed. The runner should assert hard invariants.

### 12.1 Core assertions

At minimum:

```text
A1. Console client exits cleanly or reaches configured stop condition.
A2. No WebSocket `error` events occur.
A3. At least one `session_started` event occurs.
A4. Profile is created or selected.
A5. For every chat user message, a completed assistant response is received.
A6. Workflow never remains in `wait` beyond timeout.
A7. Therapy-style selection succeeds when requested.
A8. Transcript contains minimum expected user and assistant turns.
A9. The session is ended cleanly if scenario requests it.
A10. JSONL and Markdown logs are written.
```

### 12.2 Stronger optional assertions

Add after the first version works:

```text
B1. Backend final workflow state is one of allowed states.
B2. Database contains user profile.
B3. Database contains at least one session.
B4. Database transcript count matches recorder transcript count.
B5. Therapy plan exists after style selection.
B6. No duplicate session creation unless expected.
B7. Reconnect/resume works for returning user.
```

### 12.3 Anti-flakiness assertions

Use timeouts everywhere:

```text
- Overall probe timeout.
- Per-response timeout.
- Wait-action timeout.
- Style-recommendation timeout.
- WebSocket-connect timeout.
```

Do not rely on arbitrary sleeps except tiny stabilization delays.

---

## 13. Test modes

### 13.1 Harness smoke mode

Purpose: prove the simulated-user harness works.

Backend:

```text
api-e2e
```

LLMs:

```text
Backend therapist: deterministic fake
Simulated user: scripted or local LLM
```

Run:

```bash
make test-console-probe-deterministic
```

This should be deterministic enough for CI.

---

### 13.2 Local real-LLM workflow mode

Purpose: reduce manual user testing.

Backend:

```text
api-usertest
```

LLMs:

```text
Backend therapist: real local/configured LLM
Simulated user: local LLM
```

Run:

```bash
make probe-console-local-llm
```

This should be optional and local-only by default.

---

### 13.3 Debug/manual comparison mode

Purpose: compare LLM-simulated run with manual run.

Run both:

```bash
make ui-console-test
make probe-console-local-llm
```

Then compare:

```text
logs/console-ui-usertest.log
logs/workflow-probes/latest.md
logs/workflow-probes/latest.jsonl
```

---

## 14. Docker Compose integration

Add a dedicated service:

```yaml
console-ui-probe:
  <<: *console-base
  container_name: psychoanalyst_console_probe
  profiles: ["workflow-probe"]
  environment:
    - PYTHONUNBUFFERED=1
    - BACKEND_URL=http://api-usertest:8000
    - WEBSOCKET_URL=http://api-usertest:8000
    - USER_ID=console_probe_user
    - CONSOLE_LOG_PATH=/app/logs/console-ui-probe.log
    - USER_SIM_LLM_BASE_URL=${USER_SIM_LLM_BASE_URL:-http://host.docker.internal:1234/v1}
    - USER_SIM_LLM_MODEL=${USER_SIM_LLM_MODEL:-qwen3.6-8b-instruct}
    - USER_SIM_LLM_API_KEY=${USER_SIM_LLM_API_KEY:-not-needed}
    - USER_SIM_LLM_TEMPERATURE=${USER_SIM_LLM_TEMPERATURE:-0}
  env_file:
    - .env.usertest
  depends_on:
    api-usertest:
      condition: service_healthy
  command: >
    python -m src.workflow_probe_runner
    --scenario /app/scenarios/workflow-probes/basic_new_user_intake_to_therapy.yaml
    --output-dir /app/logs/workflow-probes
```

This is intentionally separate from `console-ui-usertest`, so the normal manual test path remains untouched.

---

## 15. Makefile targets

Add targets:

```make
.PHONY: probe-console-local-llm probe-console-deterministic probe-console-logs

probe-console-local-llm:
	$(MAKE) check-usertest-key
	docker compose --profile usertest-console up -d --wait --remove-orphans api-usertest
	docker compose --profile workflow-probe run --rm --build console-ui-probe

probe-console-deterministic:
	docker compose --profile test up -d --wait --remove-orphans api-e2e
	docker compose --profile workflow-probe run --rm --build \
		-e BACKEND_URL=http://api-e2e:8000 \
		-e WEBSOCKET_URL=http://api-e2e:8000 \
		console-ui-probe

probe-console-logs:
	@echo "Markdown summary:"
	@ls -t logs/workflow-probes/*.md | head -1 | xargs cat
```

Optionally add:

```make
test-console-probe:
	docker compose --profile test run --rm test \
		pytest tests/real_llm/test_console_llm_workflow_probe.py -v -s
```

---

## 16. Pytest integration

Add:

```text
tests/real_llm/test_console_llm_workflow_probe.py
```

Purpose:

- run the probe as a subprocess;
- assert exit code is 0;
- assert JSONL summary exists;
- assert summary says pass;
- attach log path on failure.

Pseudo-code:

```python
import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.real_llm
@pytest.mark.integration
def test_console_llm_workflow_probe():
    if os.getenv("RUN_LOCAL_LLM_WORKFLOW") != "1":
        pytest.skip("Set RUN_LOCAL_LLM_WORKFLOW=1 to run local LLM workflow probe")

    result = subprocess.run(
        [
            "python",
            "-m",
            "src.workflow_probe_runner",
            "--scenario",
            "scenarios/workflow-probes/basic_new_user_intake_to_therapy.yaml",
            "--output-dir",
            "logs/workflow-probes",
        ],
        text=True,
        capture_output=True,
        timeout=240,
    )

    assert result.returncode == 0, (
        result.stdout
        + "\n\nSTDERR:\n"
        + result.stderr
        + "\n\nSee logs/workflow-probes/latest.md"
    )

    assert Path("logs/workflow-probes/latest.jsonl").exists()
    assert Path("logs/workflow-probes/latest.md").exists()
```

---

## 17. Runner exit codes

Use meaningful exit codes:

| Code | Meaning |
|---:|---|
| 0 | Probe passed |
| 1 | Assertion failure |
| 2 | Configuration error |
| 3 | Local user-simulator LLM unavailable |
| 4 | Backend unavailable |
| 5 | Timeout |
| 6 | Unexpected exception |

This makes Makefile and CI output clearer.

---

## 18. Markdown summary format

Each run should write a summary like:

```markdown
# Console LLM Workflow Probe Result

Status: PASS
Scenario: basic_new_user_intake_to_therapy
Started: 2026-05-28T20:45:00Z
Duration: 73.2s

## Configuration

- Backend URL: http://api-usertest:8000
- WebSocket URL: http://api-usertest:8000
- Simulated user model: qwen3.6-8b-instruct
- User ID: console_probe_user_20260528_204500

## Workflow Milestones

| Milestone | Status | Detail |
|---|---|---|
| Profile created | PASS | Fabian / English |
| WebSocket connected | PASS | session_id=... |
| Intake started | PASS | ... |
| Assessment recommendations | PASS | 3 options |
| Style selected | PASS | cbt |
| Therapy continued | PASS | 3 therapy turns |
| Session ended | PASS | User ended session |

## Assertions

| Assertion | Result |
|---|---|
| No WebSocket errors | PASS |
| No workflow timeout | PASS |
| Every user turn got assistant completion | PASS |
| Minimum transcript length reached | PASS |

## Transcript Excerpt

### User
I've been feeling anxious about work and it has started affecting my sleep.

### Therapist
...

## Files

- JSONL trace: logs/workflow-probes/...
- Console log: logs/console-ui-probe.log
```

---

## 19. Step-by-step implementation plan

### Phase 1: Input-provider seam

**Goal:** make console input replaceable without changing behavior.

Tasks:

1. Add `console-ui/src/input_providers.py`.
2. Implement `InputContext`.
3. Implement `HumanInputProvider`.
4. Modify `ConsoleClient.__init__()` to accept optional `input_provider`.
5. Modify `_get_user_input()` to delegate to the provider.
6. Verify `make ui-console-test` still works exactly as before.

Acceptance criteria:

- Manual console UI still works.
- No behavior changes for human users.
- Existing tests pass.

---

### Phase 2: Transcript tracking and recorder

**Goal:** create enough structured context for the LLM user and enough logs for debugging.

Tasks:

1. Add `console-ui/src/protocol_recorder.py`.
2. Track transcript tail in `ConsoleClient`.
3. Record:
   - workflow actions;
   - prompts;
   - user inputs;
   - assistant completed messages;
   - WebSocket errors;
   - session start/end;
   - assertion results.
4. Write JSONL and Markdown output.
5. Add a tiny scripted-input test to verify logs.

Acceptance criteria:

- A manual console run can optionally produce a JSONL trace.
- Trace contains user and assistant turns.
- Trace contains workflow actions.
- Markdown summary is readable.

---

### Phase 3: Scripted probe

**Goal:** prove the probe runner works before adding LLM nondeterminism.

Tasks:

1. Implement `ScriptedInputProvider`.
2. Add basic scenario file.
3. Implement `workflow_probe_runner.py`.
4. Run against `api-e2e` or `api-usertest`.
5. Add deterministic pytest test.

Acceptance criteria:

- Probe can create/select profile.
- Probe enters chat.
- Probe exits cleanly.
- Probe writes logs.
- Exit code reflects pass/fail.

This phase is important because it validates the harness without involving a local LLM.

---

### Phase 4: Local LLM simulated user

**Goal:** replace scripted chat turns with local LLM-generated replies.

Tasks:

1. Add `console-ui/src/llm_user_simulator.py`.
2. Support OpenAI-compatible `/chat/completions`.
3. Add environment-based config.
4. Add prompt construction from scenario + transcript tail.
5. Add reply sanitization.
6. Add fallback reply behavior.
7. Use deterministic answers for profile/style prompts.
8. Use LLM only for free-form chat prompts.

Acceptance criteria:

- Probe runs with LM Studio or llama.cpp OpenAI-compatible endpoint.
- LLM replies are concise.
- Probe does not stall on structural prompts.
- Failures show model request/response metadata in trace, without leaking secrets.

---

### Phase 5: Real usertest integration

**Goal:** run the simulated-user console against the real usertest backend.

Tasks:

1. Add `console-ui-probe` service to `docker-compose.yml`.
2. Add Make target `probe-console-local-llm`.
3. Use `.env.usertest`.
4. Ensure logs mount into `./logs`.
5. Reset usertest DB before probe or use unique user IDs per run.
6. Add timeout handling.

Acceptance criteria:

- One command runs the full probe.
- No manual input needed.
- Logs are written to `logs/workflow-probes`.
- On failure, user sees the path to `latest.md`.

---

### Phase 6: Assertions and database checks

**Goal:** make the probe useful as a validation tool rather than just a conversation generator.

Tasks:

1. Add final workflow assertion layer.
2. Query `/user/status`.
3. Optionally add backend debug endpoints or direct DB check in test environment.
4. Verify:
   - profile exists;
   - session exists;
   - transcript has expected minimum turns;
   - therapy plan exists after style selection;
   - final workflow action/state is allowed.
5. Add failure summary.

Acceptance criteria:

- Probe can fail because of real workflow defects.
- Failure summary identifies the broken milestone.
- JSONL trace makes reproduction obvious.

---

### Phase 7: Scenario expansion

Add scenarios gradually:

#### Scenario 1: New user, basic intake to therapy

Main happy path.

#### Scenario 2: Returning user resumes therapy

Tests login/profile selection and resumption.

#### Scenario 3: Hesitant user

The simulated user gives shorter, more uncertain answers. Tests whether workflow can still proceed.

#### Scenario 4: Invalid style then valid style

Use scripted structural behavior:

```text
first style answer: invalid
second style answer: cbt
```

Tests validation and recovery.

#### Scenario 5: Timer and quit

User sends:

```text
/timer
/quit
```

Tests slash commands and graceful session ending.

#### Scenario 6: Long intake

Tests whether intake eventually transitions or gets stuck.

---

## 20. Operational workflow

### 20.1 Before a refactor

Run:

```bash
make probe-console-local-llm
```

Save:

```text
logs/workflow-probes/baseline_*.md
```

### 20.2 After a refactor

Run again:

```bash
make probe-console-local-llm
```

Compare summaries:

```bash
diff -u logs/workflow-probes/baseline_*.md logs/workflow-probes/latest.md
```

### 20.3 During prompt/workflow debugging

Run with verbose logging:

```bash
USER_SIM_TRACE_PROMPTS=1 make probe-console-local-llm
```

The trace should include:

- workflow action before each input;
- recent transcript tail;
- simulated user prompt;
- raw LLM output;
- sanitized reply;
- fallback usage if any.

---

## 21. Guardrails

### 21.1 Prevent infinite loops

Use:

```yaml
limits:
  max_total_turns: 14
  max_intake_turns: 6
  max_therapy_turns: 4
  overall_timeout_seconds: 180
```

When limits are reached, the runner should request session end and fail or pass depending on scenario.

---

### 21.2 Keep local LLM output controlled

Use:

```text
temperature=0
max_tokens=80
```

Validate output.

Reject:

```text
"As an AI..."
"I cannot..."
"Here is my response:"
multi-paragraph essays
empty replies
```

Fallback:

```text
I'm feeling anxious about work and would like to understand it better.
```

---

### 21.3 Avoid privacy leakage

The simulated user is artificial, so this is mostly low-risk. Still:

- do not use personal real user details in scenarios unless intentional;
- do not send logs to external APIs;
- keep local LLM endpoints local;
- avoid recording API keys;
- redact environment variables from logs.

---

### 21.4 Keep it out of normal CI by default

Do not make the local LLM probe part of mandatory CI unless you later create a deterministic local model container.

Default:

```text
manual/local only
```

Optional:

```text
nightly/dev-machine only
```

---

## 22. Recommended first implementation slice

The smallest useful slice is:

1. Add `InputProvider`.
2. Refactor `_get_user_input()` to use it.
3. Add `ScriptedInputProvider`.
4. Add protocol recorder.
5. Add `workflow_probe_runner.py`.
6. Run a scripted happy path against `api-e2e`.
7. Add `LLMSimulatedUserProvider`.
8. Run against `api-usertest`.

Do **not** start with the LLM. Start with scripted input so you know the harness is correct.

---

## 23. Example first milestone

### User command

```bash
make probe-console-deterministic
```

### Expected result

```text
PASS: Console workflow probe completed.

Summary:
  Scenario: basic_new_user_intake_to_therapy
  Profile created: yes
  Session started: yes
  User turns: 5
  Assistant turns: 5
  WebSocket errors: 0
  Final action: continue_therapy

See:
  logs/workflow-probes/latest.md
  logs/workflow-probes/latest.jsonl
```

---

## 24. Example second milestone

### User command

```bash
USER_SIM_LLM_BASE_URL=http://host.docker.internal:1234/v1 \
USER_SIM_LLM_MODEL=qwen3.6-8b-instruct \
make probe-console-local-llm
```

### Expected result

```text
PASS: Local-LLM simulated user completed workflow.

Important artifacts:
  logs/workflow-probes/latest.md
  logs/workflow-probes/latest.jsonl
  logs/console-ui-probe.log
```

---

## 25. What “good” looks like

After implementation, you should be able to use the probe like this:

```bash
make reset-usertest
make probe-console-local-llm
```

Then inspect:

```bash
cat logs/workflow-probes/latest.md
```

and see:

- what profile was created;
- what the backend asked the console UI to do;
- what the simulated user answered;
- what the therapist responded;
- whether the style-selection step occurred;
- whether therapy actually started;
- whether the run ended cleanly;
- exactly where it failed if not.

This directly reduces the amount of manual testing while keeping you close to the real console UI path.

---

## 26. Final recommendation

Implement this as a **console workflow probe with injectable input**, not as a separate direct WebSocket integration test and not primarily as a stdin pipe.

The most robust design is:

```text
Existing ConsoleClient
+ InputProvider seam
+ LLMSimulatedUserProvider
+ ProtocolRecorder
+ Scenario YAML
+ Make target
```

This keeps the probe close to the actual console UI while making it controllable, inspectable, and useful for diagnosing workflow regressions.
