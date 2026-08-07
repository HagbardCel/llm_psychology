"""Fixtures for real-model evaluations.

Connection details come from the same `LOCAL_LLM_SMOKE_*` variables the manual
smoke uses; there is no separate eval environment to configure. Every read
happens inside a fixture so that collecting this package without a local model
configured stays side-effect free.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from evals.harness import EvalRunner, request_extra_body, request_timeout_seconds
from tests.support.local_llm import (
    LocalModelEnvironment,
    MissingLocalModelEnv,
    build_local_model_client,
    build_local_model_policies,
    resolve_local_model_environment,
)


@pytest.fixture(scope="session")
def eval_environment() -> LocalModelEnvironment:
    try:
        return resolve_local_model_environment()
    except MissingLocalModelEnv as exc:
        pytest.fail(f"{exc.name} must be set for real-model evaluations")


@pytest_asyncio.fixture
async def runner(eval_environment: LocalModelEnvironment) -> AsyncIterator[EvalRunner]:
    try:
        timeout_seconds = request_timeout_seconds()
        extra_body = request_extra_body()
    except ValueError as exc:
        pytest.fail(str(exc))

    client = build_local_model_client(eval_environment, extra_body=extra_body)
    try:
        yield EvalRunner(
            gateway=client.gateway,
            policies=build_local_model_policies(
                eval_environment,
                request_timeout_seconds=timeout_seconds,
            ),
        )
    finally:
        await client.aclose()
