"""Pure model policy construction from explicit settings."""

from __future__ import annotations

from jung.llm.gateway import LLMSettings, LLMTask, ModelPolicy, StructuredOutputMode

_DEFAULT_TEMPERATURES: dict[LLMTask, float] = {
    LLMTask.INTAKE_PATCH: 0.1,
    LLMTask.ASSESSMENT: 0.1,
    LLMTask.POST_SESSION_ANALYSIS: 0.1,
    LLMTask.POST_SESSION_UPDATE: 0.1,
    LLMTask.INTAKE_RESPONSE: 0.7,
    LLMTask.THERAPY_RESPONSE: 0.7,
}

_DEFAULT_TIMEOUTS: dict[LLMTask, float] = dict.fromkeys(LLMTask, 120.0)

_DEFAULT_STRUCTURED_MODES: dict[LLMTask, StructuredOutputMode] = {
    LLMTask.INTAKE_PATCH: StructuredOutputMode.JSON_SCHEMA,
    LLMTask.ASSESSMENT: StructuredOutputMode.JSON_SCHEMA,
    LLMTask.POST_SESSION_ANALYSIS: StructuredOutputMode.JSON_SCHEMA,
    LLMTask.POST_SESSION_UPDATE: StructuredOutputMode.JSON_SCHEMA,
    LLMTask.INTAKE_RESPONSE: StructuredOutputMode.PROMPT,
    LLMTask.THERAPY_RESPONSE: StructuredOutputMode.PROMPT,
}


def build_model_policies(settings: LLMSettings) -> dict[LLMTask, ModelPolicy]:
    if not settings.default_model.strip():
        raise ValueError("default_model must be non-empty")
    if not settings.base_url.strip():
        raise ValueError("base_url must be non-empty")

    policies: dict[LLMTask, ModelPolicy] = {}
    for task in LLMTask:
        model = (settings.task_models or {}).get(task, settings.default_model)
        temperature = (settings.task_temperatures or {}).get(
            task, _DEFAULT_TEMPERATURES[task]
        )
        timeout = (settings.task_timeouts or {}).get(task, _DEFAULT_TIMEOUTS[task])
        mode = (settings.task_structured_modes or {}).get(
            task, _DEFAULT_STRUCTURED_MODES[task]
        )
        max_tokens = (settings.task_max_output_tokens or {}).get(task)
        policies[task] = ModelPolicy(
            task=task,
            model=model,
            temperature=temperature,
            timeout_seconds=timeout,
            max_output_tokens=max_tokens,
            structured_output_mode=mode,
        )
    return policies
