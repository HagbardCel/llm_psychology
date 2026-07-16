"""Test-only helpers for Phase 5 resilience integration tests."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from collections.abc import AsyncIterator, Callable
from typing import TypeVar
from uuid import UUID

from jung.api.contracts import (
    AppSnapshotResponse,
    MessageResponse,
    ServerEvent,
    StyleOptionsResponse,
)
from jung.client.api_client import JungApiClient, JungTransportError
from jung.domain.models import OperationKind
from jung.persistence.sqlite_store import SQLiteStore

TEvent = TypeVar("TEvent", bound=ServerEvent)
TPredicate = Callable[[AppSnapshotResponse], bool]

DEFAULT_POLL_TIMEOUT = 30.0


def count_assessment_operations(
    store: SQLiteStore,
    source_session_id: UUID,
) -> int:
    with sqlite3.connect(
        f"file:{store.database_path}?mode=ro",
        uri=True,
    ) as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) FROM operations
            WHERE kind = ? AND source_session_id = ?
            """,
            (OperationKind.ASSESSMENT.value, str(source_session_id)),
        ).fetchone()
    assert row is not None
    return int(row[0])


def count_chat_turns_for_session(store: SQLiteStore, session_id: UUID) -> int:
    with sqlite3.connect(
        f"file:{store.database_path}?mode=ro",
        uri=True,
    ) as connection:
        row = connection.execute(
            "SELECT COUNT(*) FROM chat_turns WHERE session_id = ?",
            (str(session_id),),
        ).fetchone()
    assert row is not None
    return int(row[0])


def style_selection_projection(
    snapshot: AppSnapshotResponse,
) -> tuple[str, bool, frozenset[str]]:
    return (
        snapshot.stage,
        snapshot.profile_complete,
        frozenset(snapshot.available_commands),
    )


def expected_style_options_response() -> StyleOptionsResponse:
    from jung.api.contracts import to_style_options_response
    from jung.domain.results import StyleOptions, StyleRecommendationView, StyleSummary
    from jung.styles import load_styles
    from tests.integration.jung.application_fixtures import assessment_result

    styles = load_styles()
    result = assessment_result()
    return to_style_options_response(
        StyleOptions(
            styles=tuple(
                StyleSummary(
                    id=style.id,
                    name=style.name,
                    description=style.description,
                )
                for style in styles.values()
            ),
            recommendations=tuple(
                StyleRecommendationView(
                    style_id=recommendation.style_id,
                    score=recommendation.score,
                    rationale=recommendation.rationale,
                    key_topics=recommendation.key_topics,
                )
                for recommendation in result.style_recommendations
            ),
        )
    )


def assert_styles_equivalent(
    actual: StyleOptionsResponse,
    expected: StyleOptionsResponse,
) -> None:
    assert len(actual.recommendations) == len(expected.recommendations)
    for actual_item, expected_item in zip(
        actual.recommendations,
        expected.recommendations,
        strict=True,
    ):
        assert actual_item.style_id == expected_item.style_id
        assert actual_item.score == expected_item.score
        assert frozenset(actual_item.key_topics) == frozenset(
            expected_item.key_topics
        )


async def wait_for_snapshot(
    client: JungApiClient,
    *,
    predicate: TPredicate,
    description: str,
    timeout: float = DEFAULT_POLL_TIMEOUT,
) -> AppSnapshotResponse:
    deadline = time.monotonic() + timeout
    last: AppSnapshotResponse | None = None
    while time.monotonic() < deadline:
        try:
            snapshot = await client.get_state()
        except JungTransportError:
            await asyncio.sleep(0.05)
            continue
        last = snapshot
        if predicate(snapshot):
            return snapshot
        await asyncio.sleep(0.05)
    raise TimeoutError(
        f"timed out waiting for snapshot: {description}; last={last!r}"
    )


async def receive_event(
    events: AsyncIterator[ServerEvent],
    event_type: type[TEvent],
    *,
    predicate: Callable[[TEvent], bool] | None = None,
    timeout: float = 5.0,
) -> TEvent:
    deadline = time.monotonic() + timeout

    async def _next_matching() -> TEvent:
        async for event in events:
            if not isinstance(event, event_type):
                continue
            if predicate is None or predicate(event):
                return event
        raise TimeoutError(
            f"event stream ended before {event_type.__name__} was observed"
        )

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError(f"timed out waiting for {event_type.__name__}")
    return await asyncio.wait_for(_next_matching(), timeout=remaining)


async def wait_for_session_message(
    client: JungApiClient,
    *,
    session_id: UUID,
    client_message_id: UUID,
    role: str,
    timeout: float = DEFAULT_POLL_TIMEOUT,
) -> MessageResponse:
    deadline = time.monotonic() + timeout
    last_count = 0
    while time.monotonic() < deadline:
        history = await client.get_session(session_id)
        last_count = len(history.messages)
        for message in history.messages:
            if (
                message.client_message_id == client_message_id
                and message.role == role
            ):
                return message
        await asyncio.sleep(0.05)
    raise TimeoutError(
        "timed out waiting for session message "
        f"session_id={session_id} client_message_id={client_message_id} "
        f"role={role}; message_count={last_count}"
    )


async def wait_for_health(
    client: JungApiClient,
    *,
    timeout: float = 10.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        health = await client.get_health()
        if health.status == "healthy":
            return
        await asyncio.sleep(0.05)
    raise TimeoutError("timed out waiting for healthy API")
