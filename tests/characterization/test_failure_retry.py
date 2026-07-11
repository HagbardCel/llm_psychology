import pytest


@pytest.mark.characterization_full
@pytest.mark.xfail(strict=True, reason="Phase 4: durable operation retry is not implemented")
def test_retryable_failed_turn_reuses_client_message_id():
    raise NotImplementedError
