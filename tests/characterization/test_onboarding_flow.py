import pytest

from . import assertions


@pytest.mark.characterization_smoke
@pytest.mark.trio
async def test_onboarding_persists_profile_and_intake_messages(legacy_client):
    """must_preserve: fresh install persists profile, session, and intake messages."""
    legacy_client.register()
    await legacy_client.persist_intake_messages()

    assertions.assert_single_profile(legacy_client.server.rows("user_profiles"))
    intake_session = assertions.assert_one_intake_session(
        legacy_client.server.rows("sessions")
    )
    messages = assertions.transcript_messages(intake_session)
    assert any(row.get("role") == "assistant" for row in messages), (
        "expected at least one persisted assistant intake turn"
    )


@pytest.mark.characterization_full
@pytest.mark.trio
async def test_onboarding_reaches_ready_state(legacy_client):
    """must_preserve: onboarding reaches assessment, style selection, and initial plan."""
    await legacy_client.drive_to_ready()

    profile = assertions.assert_single_profile(legacy_client.server.rows("user_profiles"))
    assertions.assert_ready_status(profile)

    intake_session = assertions.assert_one_intake_session(
        legacy_client.server.rows("sessions")
    )
    messages = assertions.transcript_messages(intake_session)
    assert messages
    assertions.assert_intake_evidence(intake_session)
    assertions.assert_assessment_results(
        legacy_client.server.rows("assessment_recommendations")
    )
    assertions.assert_plans(legacy_client.server.rows("therapy_plans"))
    plan = legacy_client.server.rows("therapy_plans")[-1]
    assert plan.get("selected_therapy_style") == "cbt"
