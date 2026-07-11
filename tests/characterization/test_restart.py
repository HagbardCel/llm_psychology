import pytest

from . import assertions


@pytest.mark.characterization_full
@pytest.mark.trio
@pytest.mark.parametrize(
    "checkpoint",
    [
        pytest.param("after_intake_messages", id="after_intake_messages"),
        pytest.param("after_ready", id="after_ready"),
        pytest.param("after_post_session", id="after_post_session"),
    ],
)
async def test_restart_preserves_durable_state(legacy_client, checkpoint):
    """must_preserve: reconnect after restart reuses durable profile/session state."""
    if checkpoint == "after_intake_messages":
        await legacy_client.persist_intake_messages()
        session_count = len(legacy_client.server.rows("sessions"))
    elif checkpoint == "after_ready":
        await legacy_client.drive_to_ready()
        session_count = len(legacy_client.server.rows("sessions"))
    else:
        await legacy_client.drive_to_ready()
        therapy = legacy_client.start_therapy()
        therapy_session_id = therapy["session"]["session_id"]
        await legacy_client.therapy_chat_turn("I feel anxious about a work deadline.")
        legacy_client.end_session(therapy_session_id)
        legacy_client.wait_for_job(f"post_session_update:{therapy_session_id}")
        session_count = len(legacy_client.server.rows("sessions"))

    legacy_client.server.restart()
    legacy_client.login()

    assertions.assert_single_profile(legacy_client.server.rows("user_profiles"))
    sessions_after = legacy_client.server.rows("sessions")
    assert len(sessions_after) >= session_count
    assert len(sessions_after) <= session_count + 1

    if checkpoint != "after_intake_messages":
        profile = assertions.assert_single_profile(
            legacy_client.server.rows("user_profiles")
        )
        assertions.assert_ready_status(profile)
