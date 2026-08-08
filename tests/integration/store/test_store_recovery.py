"""Reset and startup recovery tests."""

from __future__ import annotations

from uuid import uuid4

from jung.domain.models import OperationStatus
from jung.persistence.sqlite_store import SQLiteStore
from tests.integration.application.scenarios import (
    complete_intake_for_assessment,
    open_intake,
)


def test_recover_stale_operations_is_idempotent(store: SQLiteStore) -> None:
    intake_id, now = open_intake(store)
    operation_id = uuid4()
    complete_intake_for_assessment(
        store,
        intake_session_id=intake_id,
        now=now,
        operation_id=operation_id,
    )
    store.mark_operation_running(operation_id, now=now)
    recovered = store.recover_stale_operations(now=now)
    assert len(recovered) == 1
    assert recovered[0].status == OperationStatus.PENDING
    again = store.recover_stale_operations(now=now)
    assert again == []
    operation = store.get_operation(operation_id)
    assert operation is not None
    assert operation.status == OperationStatus.PENDING
