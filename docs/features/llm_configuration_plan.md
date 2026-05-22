# Implementation Plan - Multi-Model Support for Agents

This plan outlines the changes required to allow configuring different LLM models for different agents, providing flexibility in cost and performance optimization.

## User Question Resolution

> "Which of these agents do actually use LLMs? Do we really need LLMs for each of these?"

**Answer**:

- **TrioIntakeAgent**: Does **NOT** use `LLMService` internaly. It returns prompts, and the **Orchestrator** streams the response.
- **TrioAssessmentAgent**: Uses `LLMService` for internal reasoning (analyzing session history).
- **TrioMemoryAgent**: Uses `LLMService` for analyzing session context and health checks.
- **TrioPlanningAgent**: Uses `LLMService` for generating plans.
- **TrioReflectionAgent**: Uses `LLMService` for generating summaries and briefings.
- **TrioPsychoanalystAgent**: Uses `LLMService` for closing sessions and legacy features.

> "Add a default model that is used for each relevant agent for which no custom model has been set."

**Resolution**: The configuration will be implemented such that if a specific agent model is not set, it defaults to the main `MODEL_NAME`.

> "Explain why this is needed [ConversationManager update]."

**Answer**: The `ConversationManager` handles the actual streaming of responses to the user. Since the `IntakeAgent` (and potentially others) rely on this streaming mechanism, the `ConversationManager` needs to know _which_ LLM model to use. By allowing an optional `llm_service` to be passed to `stream_response`, the **Orchestrator** can ensure that when the Intake Agent is active, the `INTAKE_MODEL` is used for the stream, rather than the default model.

## User Review Required

> [!IMPORTANT]
> This change introduces new configuration environment variables. While defaults will be provided (falling back to the main `MODEL_NAME`), you may want to update your `.env` file to take advantage of this feature.

## Proposed Changes

### Configuration

#### [MODIFY] [config.py](file:///app/src/config.py)

- Add new fields to `Settings` class for agent-specific models.
  - `INTAKE_MODEL`: Defaults to `MODEL_NAME` if not set.
  - `ASSESSMENT_MODEL`: Defaults to `MODEL_NAME` if not set.
  - `PSYCHOANALYST_MODEL`: Defaults to `MODEL_NAME` if not set.
  - `REFLECTION_MODEL`: Defaults to `MODEL_NAME` if not set.
  - `MEMORY_MODEL`: Defaults to `MODEL_NAME` if not set.
  - `PLANNING_MODEL`: Defaults to `MODEL_NAME` if not set.
- Add logic in `Settings` or `ServiceContainer` to ensure a valid model string is always returned (fallback to default).

#### [MODIFY] [orchestration/trio_agent_orchestrator.py](file:///app/src/orchestration/trio_agent_orchestrator.py)

- Update `process_message` to retrieve the specific `LLMService` for the current agent type from the `ServiceContainer`.
- Pass this specific `llm_service` to `conversation_manager.stream_response`.

**Implementation Details** (around line 150 in `process_message`):

```python
# Determine which LLM service to use based on agent type
llm_service_key_map = {
    "INTAKE": "llm_service_intake",
    "ASSESSMENT": "llm_service_assessment",
    "PSYCHOANALYST": "llm_service_psychoanalyst",
    "REFLECTION": "llm_service_reflection",
    "MEMORY": "llm_service_memory",
    "PLANNING": "llm_service_planning",
}

# Get agent-specific LLM service, fallback to default
llm_service_key = llm_service_key_map.get(agent_type, "llm_service")
llm_service = self.service_container.get(llm_service_key)

# Pass to stream_response
async for chunk in self.conversation_manager.stream_response(
    agent_response.content,
    context,
    agent=agent_type,
    llm_service=llm_service  # NEW PARAMETER
):
    yield chunk
```

#### [MODIFY] [orchestration/trio_conversation_manager.py](file:///app/src/orchestration/trio_conversation_manager.py)

- Update `stream_response` to accept an optional `llm_service`.
- If provided, use it; otherwise, fall back to the default `self.llm_service`.

### Service Container

#### [MODIFY] [service_container.py](file:///app/src/container/service_container.py)

- Update `_setup_factories` to register specific LLM services for each agent (e.g., `llm_service_intake`, `llm_service_psychoanalyst`).
- Create a helper method `_create_agent_llm_service(agent_config_name: str)` to reduce duplication.
- Update `create_intake_agent` to **REMOVE** `llm_service` injection (it doesn't use it).
- Update other `create_*_agent` methods to inject the specific LLM service:
  - `create_assessment_agent` -> uses `llm_service_assessment`
  - `create_psychoanalyst_agent` -> uses `llm_service_psychoanalyst`
  - `create_reflection_agent` -> uses `llm_service_reflection`
  - `create_memory_agent` -> uses `llm_service_memory`
  - `create_planning_agent` -> uses `llm_service_planning`

## Verification Plan

### Automated Tests

#### Regression Testing
- Run existing test suite to ensure no regression:
  ```bash
  make test
  ```

#### New Unit Tests

**Create**: `tests/unit/test_multi_model_config.py`

```python
import pytest
from unittest.mock import patch
from container.service_container import ServiceContainer


def test_agent_specific_models_from_config(monkeypatch):
    """Test that agents get correct model configurations from env vars."""
    monkeypatch.setenv("MODEL_NAME", "gemini-2.5-flash")
    monkeypatch.setenv("INTAKE_MODEL", "gemini-pro")
    monkeypatch.setenv("PSYCHOANALYST_MODEL", "gemini-2.5-pro")

    container = ServiceContainer()

    # Test intake agent gets specific model
    intake_service = container.get("llm_service_intake")
    assert intake_service.model_name == "gemini-pro"

    # Test psychoanalyst agent gets specific model
    psychoanalyst_service = container.get("llm_service_psychoanalyst")
    assert psychoanalyst_service.model_name == "gemini-2.5-pro"


def test_fallback_to_default_model(monkeypatch):
    """Test that missing agent models fall back to MODEL_NAME."""
    monkeypatch.setenv("MODEL_NAME", "gemini-2.5-flash")
    # Don't set INTAKE_MODEL - should fall back to MODEL_NAME

    container = ServiceContainer()
    intake_service = container.get("llm_service_intake")
    assert intake_service.model_name == "gemini-2.5-flash"


def test_all_agent_models_configurable(monkeypatch):
    """Test that all 6 agent models can be individually configured."""
    monkeypatch.setenv("MODEL_NAME", "default-model")
    monkeypatch.setenv("INTAKE_MODEL", "intake-model")
    monkeypatch.setenv("ASSESSMENT_MODEL", "assessment-model")
    monkeypatch.setenv("PSYCHOANALYST_MODEL", "psychoanalyst-model")
    monkeypatch.setenv("REFLECTION_MODEL", "reflection-model")
    monkeypatch.setenv("MEMORY_MODEL", "memory-model")
    monkeypatch.setenv("PLANNING_MODEL", "planning-model")

    container = ServiceContainer()

    assert container.get("llm_service_intake").model_name == "intake-model"
    assert container.get("llm_service_assessment").model_name == "assessment-model"
    assert container.get("llm_service_psychoanalyst").model_name == "psychoanalyst-model"
    assert container.get("llm_service_reflection").model_name == "reflection-model"
    assert container.get("llm_service_memory").model_name == "memory-model"
    assert container.get("llm_service_planning").model_name == "planning-model"


def test_config_class_fields(monkeypatch):
    """Test that Settings class properly loads agent model fields."""
    monkeypatch.setenv("INTAKE_MODEL", "test-intake-model")
    monkeypatch.setenv("ASSESSMENT_MODEL", "test-assessment-model")

    from config import Settings
    settings = Settings()

    assert settings.INTAKE_MODEL == "test-intake-model"
    assert settings.ASSESSMENT_MODEL == "test-assessment-model"
    # Fields not set should default to MODEL_NAME
    assert settings.REFLECTION_MODEL == settings.MODEL_NAME
```

#### Integration Tests

**Update**: `tests/integration/test_trio_flow.py`

Add test to verify orchestrator passes correct LLM service:

```python
@pytest.mark.trio
async def test_orchestrator_uses_agent_specific_model(monkeypatch, tmp_path):
    """Verify orchestrator passes agent-specific LLM service to conversation manager."""
    monkeypatch.setenv("INTAKE_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))

    # Set up orchestrator with custom config
    # Mock conversation_manager.stream_response to capture llm_service parameter
    # Verify it receives llm_service with model_name="gemini-2.5-flash"
    # Full implementation TBD during actual coding
```

### Manual Verification

- N/A (Automated verification is sufficient for this backend logic).

## Documentation Updates

The following documentation files must be updated to reflect the multi-model configuration feature:

### Required Updates

- [ ] **[.env.example]** - Add commented examples for agent-specific model configuration
- [ ] **[docs/README.md](file:///app/docs/README.md)** - Add section on multi-model configuration in "Configuration" section
- [ ] **[docs/TECH_STACK.md](file:///app/docs/TECH_STACK.md)** - Document multi-model support under "LLM Integration"

### .env.example Content

Add the following section to `.env.example`:

```bash
# =============================================================================
# Agent-Specific LLM Models (Optional)
# =============================================================================
# Configure different models for different agents to optimize cost/performance.
# If not set, all agents use MODEL_NAME as the default.
#
# Recommended configuration for cost optimization:
# - Use gemini-2.5-flash for simple agents (intake, reflection, memory, planning)
# - Use gemini-2.5-pro for complex agents (assessment, psychoanalyst)
#
# INTAKE_MODEL=gemini-2.5-flash
# ASSESSMENT_MODEL=gemini-2.5-pro
# PSYCHOANALYST_MODEL=gemini-2.5-pro
# REFLECTION_MODEL=gemini-2.5-flash
# MEMORY_MODEL=gemini-2.5-flash
# PLANNING_MODEL=gemini-2.5-flash
```

### Documentation Content Guidelines

**For docs/README.md** - Add subsection under "Configuration":

```markdown
#### Multi-Model Configuration

The application supports configuring different LLM models for different agents, allowing you to optimize costs while maintaining quality where it matters most.

**Environment Variables**:
- `INTAKE_MODEL` - Model for intake conversations (default: MODEL_NAME)
- `ASSESSMENT_MODEL` - Model for session analysis (default: MODEL_NAME)
- `PSYCHOANALYST_MODEL` - Model for main therapy sessions (default: MODEL_NAME)
- `REFLECTION_MODEL` - Model for session summaries (default: MODEL_NAME)
- `MEMORY_MODEL` - Model for memory extraction (default: MODEL_NAME)
- `PLANNING_MODEL` - Model for therapy plan generation (default: MODEL_NAME)

**Example** - Using Flash for simple tasks, Pro for complex therapy:
```bash
INTAKE_MODEL=gemini-2.5-flash
PSYCHOANALYST_MODEL=gemini-2.5-pro
REFLECTION_MODEL=gemini-2.5-flash
```
```

**For docs/TECH_STACK.md** - Add to "LLM Integration" section:

```markdown
### Multi-Model Support

The application supports configuring different LLM models for different agents:
- Each agent can use a dedicated model via environment variables
- Falls back to `MODEL_NAME` if agent-specific model is not configured
- Enables cost optimization by using cheaper models for simpler tasks
```
