import pytest


@pytest.mark.characterization_full
@pytest.mark.xfail(strict=True, reason="Phase 4: chat-turn restart recovery is not implemented")
def test_restart_marks_pending_chat_turn_retryable_without_duplicate_user_message():
    raise NotImplementedError
