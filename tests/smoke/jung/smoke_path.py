"""Smoke path runner for local-model smoke."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from jung.llm.errors import LLMTimeout
from tests.smoke.jung.smoke_env import smoke_strict_acceptance
from tests.smoke.jung.smoke_evidence import SmokeEvidenceCollector, SmokePathResult

T = TypeVar("T")

SmokePathName = Literal["therapy", "assessment", "post_session"]


@dataclass(frozen=True, slots=True)
class SmokeOperationResult(Generic[T]):
    value: T
    ttfc_seconds: float | None = None


async def run_smoke_path(
    *,
    collector: SmokeEvidenceCollector,
    name: SmokePathName,
    budget_seconds: float,
    operation: Callable[[], Awaitable[SmokeOperationResult[T]]],
) -> T:
    started = time.perf_counter()
    strict = smoke_strict_acceptance()
    status = "error"
    success = False
    error_type: str | None = None
    ttfc_seconds: float | None = None
    operation_result: SmokeOperationResult[T] | None = None

    try:
        if strict:
            timeout_context = asyncio.timeout(budget_seconds)
            try:
                async with timeout_context:
                    operation_result = await operation()
            except TimeoutError:
                if timeout_context.expired():
                    status = "path_timeout"
                    error_type = "PathTimeout"
                else:
                    status = "error"
                    error_type = "TimeoutError"
                raise
        else:
            operation_result = await operation()
        status = "success"
        success = True
    except asyncio.CancelledError as exc:
        status = "cancelled"
        error_type = type(exc).__name__
        raise
    except TimeoutError:
        raise
    except LLMTimeout:
        status = "timeout"
        error_type = "LLMTimeout"
        raise
    except Exception as exc:
        status = "error"
        error_type = type(exc).__name__
        raise
    else:
        assert operation_result is not None
        ttfc_seconds = operation_result.ttfc_seconds
        return operation_result.value
    finally:
        operation_completed_at = time.perf_counter()
        latency = operation_completed_at - started
        if strict:
            acceptance_passed = success
        else:
            acceptance_passed = latency <= budget_seconds if success else False
        path_result = SmokePathResult(
            success=success,
            status=status,
            latency_seconds=latency,
            ttfc_seconds=ttfc_seconds,
            acceptance_passed=acceptance_passed,
            acceptance_max_seconds=budget_seconds,
            error_type=error_type,
        )
        setattr(collector, name, path_result)
