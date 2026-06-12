# Plan: Per-Patient Model for Workflow Probe

## Objective

Enable `make probe` to use a different model for the simulated patient than for the therapist agents.

Currently the console user simulator hardcodes `MODEL_NAME`, which means both the therapist and the patient share the same local LLM model. This makes it impossible to, for example, test the workflow with a more capable or differently-behaved patient model while keeping the therapist configuration unchanged.

---

## Current State

`LocalUser` (in `console-ui/src/workflow_probe/local_user.py`) reads `MODEL_NAME` and `LLM_BASE_URL` directly from env in `__init__` (lines 17-18), then passes them to `LocalLLMUserSimulator.__init__()`:

```python
base_url = os.getenv("LLM_BASE_URL")
model = os.getenv("MODEL_NAME")
# ...
LocalLLMUserSimulator(base_url=base_url, model=model, ...)
```

`LocalLLMUserSimulator` already has a `.from_env()` factory method (in `console-ui/src/llm_user_simulator.py:56-73`) that checks `USER_SIM_LLM_MODEL` and `USER_SIM_LLM_BASE_URL` first, falling back to `MODEL_NAME` and `LLM_BASE_URL`. This factory is never called by `LocalUser`.

The `.env.example` file documents user-simulator options in the "Console User Simulator" section, but it was missing `USER_SIM_LLM_MODEL`. The probe also ignored the simulator factory that already supports `USER_SIM_LLM_MODEL` and `USER_SIM_LLM_BASE_URL`.

---

## Changes

### 1. `console-ui/src/workflow_probe/local_user.py`

Replace the manual env reads in `__init__` with a call to `LocalLLMUserSimulator.from_env(recorder=recorder)`:

**Before:**
```python
def __init__(self, scenario: dict[str, Any], recorder: Any):
    base_url = os.getenv("LLM_BASE_URL")
    model = os.getenv("MODEL_NAME")
    self.deterministic = os.getenv("PROBE_DETERMINISTIC_USER", "").lower() == "true"
    # ...
    self.simulator = (
        None
        if self.deterministic
        else LocalLLMUserSimulator(
            base_url=base_url,
            model=model,
            api_key=os.getenv("LLM_API_KEY"),
            temperature=float(os.getenv("USER_SIM_LLM_TEMPERATURE", "0")),
            recorder=recorder,
        )
    )
```

**After:**
```python
def __init__(self, scenario: dict[str, Any], recorder: Any):
    self.deterministic = os.getenv("PROBE_DETERMINISTIC_USER", "").lower() == "true"
    # ...
    self.simulator = (
        None
        if self.deterministic
        else LocalLLMUserSimulator.from_env(recorder=recorder)
    )
```

This removes 6 lines of manual env reading and delegates to the existing factory.

### 2. `.env.example`

Document `USER_SIM_LLM_MODEL` and clarify the fallback behavior for `USER_SIM_LLM_BASE_URL`.

### 3. No changes required to:

- **`.env`** — omitting `USER_SIM_LLM_MODEL` preserves the fallback to `MODEL_NAME` (same as current behavior)
- **`.env.test`** — no change needed
- **Deterministic probe** (`make probe-console-deterministic`) — `PROBE_DETERMINISTIC_USER=true` bypasses the simulator entirely, so no impact

### 4. Tests

Add focused unit tests for `LocalUser` to verify:

- `USER_SIM_LLM_MODEL` takes precedence over `MODEL_NAME`
- `USER_SIM_LLM_BASE_URL` takes precedence over `LLM_BASE_URL`
- omitted `USER_SIM_LLM_MODEL` falls back to `MODEL_NAME`
- deterministic mode does not construct a simulator or require patient LLM env values

---

## Environment Variable Resolution Order

After this change, the patient model is resolved by `LocalLLMUserSimulator.from_env()`:

| Priority | Env Var | Fallback |
|---|---|---|
| 1 | `USER_SIM_LLM_MODEL` | — |
| 2 | `MODEL_NAME` | `"local-model"` |
| 3 | `USER_SIM_LLM_BASE_URL` | — |
| 4 | `LLM_BASE_URL` | `"http://host.docker.internal:1234/v1"` |

Other settings are also delegated to the factory: `USER_SIM_LLM_TEMPERATURE`, `USER_SIM_LLM_MAX_TOKENS`, and `USER_SIM_LLM_API_KEY`. This differs from the previous direct constructor call, which used `LLM_API_KEY` and the constructor default max-token value.

---

## Behavior Matrix

| `USER_SIM_LLM_MODEL` | Result |
|---|---|
| unset / empty | Falls back to `MODEL_NAME` — same as therapist (current behavior) |
| `unsloth/Qwen3-8B-Instruct:Q5_K_M` | Uses that model for patient responses |
| Any valid model string | Uses that model for patient responses |

Same pattern applies to `USER_SIM_LLM_BASE_URL` for routing the patient to a different server while the therapist stays on `LLM_BASE_URL`. The existing probe preflight still checks only the therapist `LLM_BASE_URL` / `MODEL_NAME` endpoint; patient endpoint failures surface through the simulator's diagnostic error path.

---

## Impact Assessment

- **Narrow behavior change** — patient model/base URL selection now honors the simulator factory, including its API-key and max-token env handling
- **Enables per-patient model** — set `USER_SIM_LLM_MODEL` in `.env` or inline
- **Probe artifact logging** — `.from_env()` passes the recorder, so LLM call metadata is still recorded to probe output (same as before)
- **Documentation updated** — `.env.example` now documents `USER_SIM_LLM_MODEL` and fallback behavior
