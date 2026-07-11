import pytest


@pytest.mark.characterization_full
@pytest.mark.xfail(strict=True, reason="Phase 4: target operation model is not implemented")
def test_assessment_completion_is_idempotent():
    raise NotImplementedError
