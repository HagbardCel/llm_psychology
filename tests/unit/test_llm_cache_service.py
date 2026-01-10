import pytest


pytestmark = [pytest.mark.trio, pytest.mark.unit]


async def test_llm_cache_service_round_trip(trio_db_service):
    from psychoanalyst_app.services.llm_cache_service import LLMCacheService

    cache_service = LLMCacheService(
        db_service=trio_db_service,
        enabled=True,
        max_age_days=7,
        max_rows=100,
        sources=["assessment"],
        require_context=True,
    )
    call_context = {
        "user_id": "user-1",
        "session_block_id": "session-1",
        "source": "assessment",
    }

    await cache_service.store_response(
        call_type="generate_response",
        model_name="test-model",
        prompt="Hello",
        context=None,
        schema=None,
        method=None,
        call_context=call_context,
        response="World",
    )

    cached = await cache_service.get_cached_response(
        call_type="generate_response",
        model_name="test-model",
        prompt="Hello",
        context=None,
        schema=None,
        method=None,
        call_context=call_context,
    )

    assert cached == "World"


async def test_llm_cache_service_requires_context(trio_db_service):
    from psychoanalyst_app.services.llm_cache_service import LLMCacheService

    cache_service = LLMCacheService(
        db_service=trio_db_service,
        enabled=True,
        max_age_days=7,
        max_rows=100,
        sources=["assessment"],
        require_context=True,
    )

    await cache_service.store_response(
        call_type="generate_response",
        model_name="test-model",
        prompt="Hello",
        context=None,
        schema=None,
        method=None,
        call_context=None,
        response="World",
    )

    cached = await cache_service.get_cached_response(
        call_type="generate_response",
        model_name="test-model",
        prompt="Hello",
        context=None,
        schema=None,
        method=None,
        call_context=None,
    )

    assert cached is None
