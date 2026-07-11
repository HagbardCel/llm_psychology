import pytest


@pytest.mark.characterization_smoke
@pytest.mark.xfail(strict=True, reason="Phase 4: application-owned chat turns are not implemented")
def test_accepted_chat_survives_socket_disconnect():
    """Target-only: disconnect never cancels an accepted persisted chat turn."""
    raise NotImplementedError
