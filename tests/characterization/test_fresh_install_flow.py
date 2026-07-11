import pytest


@pytest.mark.characterization_smoke
@pytest.mark.xfail(strict=True, reason="Phase 4: target single-user API is not implemented")
def test_fresh_install_reaches_intake_through_public_api():
    """Target-only: fresh storage exposes SETUP then accepts profile completion."""
    raise NotImplementedError
