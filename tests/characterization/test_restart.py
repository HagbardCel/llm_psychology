import pytest

from . import assertions


@pytest.mark.characterization_full
@pytest.mark.trio
@pytest.mark.parametrize(
    "checkpoint",
    [
        pytest.param("after_intake_messages", id="after_intake_messages"),
        pytest.param("after_post_session", id="after_post_session"),
    ],
)
async def test_restart_preserves_durable_state(legacy_client, checkpoint):
    """must_preserve: reconnect after restart reuses durable profile/session state."""
    if checkpoint == "after_intake_messages":
        await legacy_client.persist_intake_messages()
        intake_session = assertions.assert_one_intake_session(
            legacy_client.server.rows("sessions")
        )
        baseline_session_ids = {
            row["session_id"] for row in legacy_client.server.rows("sessions")
        }
        baseline_transcript = assertions.transcript_messages(intake_session)
        baseline_plan_count = len(legacy_client.server.rows("therapy_plans"))
    else:
        await legacy_client.drive_to_ready()
        therapy = legacy_client.start_therapy()
        therapy_session_id = therapy["session"]["session_id"]
        await legacy_client.chat_turn(
            "I feel anxious about a work deadline.",
            register_first=False,
        )
        legacy_client.end_session(therapy_session_id)
        legacy_client.wait_for_job(f"post_session_update:{therapy_session_id}")
        baseline_session_ids = {
            row["session_id"] for row in legacy_client.server.rows("sessions")
        }
        baseline_plan_count = len(legacy_client.server.rows("therapy_plans"))
        baseline_assessment_count = len(
            legacy_client.server.rows("assessment_recommendations")
        )

    legacy_client.server.restart()
    login_payload = legacy_client.login()

    profile = assertions.assert_single_profile(legacy_client.server.rows("user_profiles"))
    sessions_after = legacy_client.server.rows("sessions")
    session_ids_after = {row["session_id"] for row in sessions_after}
    assert baseline_session_ids.issubset(session_ids_after), (
        "restart dropped persisted session ids"
    )

    if checkpoint == "after_intake_messages":
        assert len(sessions_after) == len(baseline_session_ids)
        assert len(legacy_client.server.rows("therapy_plans")) == baseline_plan_count
        intake_session = assertions.assert_one_intake_session(sessions_after)
        transcript = assertions.transcript_messages(intake_session)
        assert any(row.get("role") == "assistant" for row in transcript)
        assert transcript == baseline_transcript
    else:
        login_session_id = login_payload["session"]["session_id"]
        assert login_session_id not in baseline_session_ids
        assert len(sessions_after) == len(baseline_session_ids) + 1
        assert session_ids_after - baseline_session_ids == {login_session_id}
        assert len(legacy_client.server.rows("therapy_plans")) == baseline_plan_count
        assert (
            len(legacy_client.server.rows("assessment_recommendations"))
            == baseline_assessment_count
        )
        assertions.assert_ready_status(profile)
