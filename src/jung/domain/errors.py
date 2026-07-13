"""Internal domain errors for the target core."""

from __future__ import annotations


class DomainError(Exception):
    """Base class for domain-layer failures."""


class InvalidCommand(DomainError):
    """Command is not permitted in the current workflow state."""


class RevisionConflict(DomainError):
    """Optimistic concurrency check failed."""

    def __init__(self, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"expected revision {expected}, found {actual}")


class Busy(DomainError):
    """Conflicting session, mutation, operation, or generation."""


class NotFound(DomainError):
    """Requested durable resource does not exist."""


class InvariantViolation(DomainError):
    """Operation would violate a persistence or workflow invariant."""


class PersistenceFailure(DomainError):
    """Stable wrapper around an unexpected persistence failure."""


class StoredWorkFailure(DomainError):
    """Durable failed chat or operation surfaced to callers."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        retryable: bool,
    ) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(message)

    @classmethod
    def from_chat_turn(cls, turn: object) -> StoredWorkFailure:
        from jung.domain.models import ChatTurn

        if not isinstance(turn, ChatTurn):
            raise TypeError("expected ChatTurn")
        return cls(
            code=turn.error_code or "operation_failed",
            message=turn.error_message or "chat turn failed",
            retryable=turn.retryable,
        )
