import pytest

pytestmark = [pytest.mark.trio, pytest.mark.unit]


async def test_generate_structured_output_async_passes_method_to_target_callable():
    """
    Regression test: trio.to_thread.run_sync does not accept arbitrary kwargs.

    We ensure LLMService.generate_structured_output_async passes `method=` to the
    underlying generate_structured_output callable (not to run_sync).
    """
    from psychoanalyst_app.services.llm_service import LLMService

    llm_service = LLMService.__new__(LLMService)

    async def _noop_rate_limit():
        return None

    llm_service._acquire_rate_limit = _noop_rate_limit  # type: ignore[attr-defined]

    calls: dict[str, str] = {}

    def _generate_structured_output(prompt, schema, *, method="json_schema"):
        calls["method"] = method
        return {"ok": True}

    llm_service.generate_structured_output = _generate_structured_output  # type: ignore[assignment]

    result = await llm_service.generate_structured_output_async(
        "prompt", {"type": "object"}, method="json_mode"
    )

    assert result == {"ok": True}
    assert calls["method"] == "json_mode"

