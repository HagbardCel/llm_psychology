import pytest

from . import assertions

CHAT_MESSAGE = "I feel anxious about a work deadline."


@pytest.mark.characterization_smoke
@pytest.mark.trio
async def test_intake_chat_streams_and_persists_assistant_message(legacy_client):
    """must_preserve: intake chat streams token chunks and persists its assistant turn."""
    streamed = await legacy_client.chat_turn(CHAT_MESSAGE)

    assert streamed.strip()
    intake_session = assertions.assert_one_intake_session(
        legacy_client.server.rows("sessions")
    )
    transcript = assertions.transcript_messages(intake_session)
    assertions.assert_user_followed_by_assistant(
        transcript, CHAT_MESSAGE, assistant_content=streamed
    )


@pytest.mark.characterization_full
@pytest.mark.trio
async def test_therapy_lifecycle_closes_session_and_revises_plan(legacy_client):
    """must_preserve: ending therapy closes the session and creates one new plan revision."""
    await legacy_client.drive_to_ready()
    profile_before = assertions.assert_single_profile(
        legacy_client.server.rows("user_profiles")
    )
    plans_before = legacy_client.server.rows("therapy_plans")
    initial_plan = assertions.assert_exactly_one_initial_plan(plans_before)
    initial_plan_id = initial_plan["plan_id"]

    therapy = legacy_client.start_therapy()
    therapy_session_id = therapy["session"]["session_id"]
    therapy_plan_id = next(
        row["plan_id"]
        for row in legacy_client.server.rows("sessions")
        if row.get("session_id") == therapy_session_id
    )
    streamed = await legacy_client.chat_turn(
        CHAT_MESSAGE,
        register_first=False,
    )
    assert streamed.strip()

    therapy_row = next(
        row
        for row in legacy_client.server.rows("sessions")
        if row.get("session_id") == therapy_session_id
    )
    transcript = assertions.transcript_messages(therapy_row)
    assertions.assert_user_followed_by_assistant(
        transcript, CHAT_MESSAGE, assistant_content=streamed
    )

    legacy_client.end_session(therapy_session_id)
    legacy_client.wait_for_job(f"post_session_update:{therapy_session_id}")

    sessions = legacy_client.server.rows("sessions")
    therapy_row = next(
        row for row in sessions if row.get("session_id") == therapy_session_id
    )
    assertions.assert_therapy_session_closed(therapy_row)
    assert therapy_row.get("plan_id") == therapy_plan_id

    plans_after = legacy_client.server.rows("therapy_plans")
    assert len(plans_after) == len(plans_before) + 1
    prior_plan = next(
        row for row in plans_after if row.get("plan_id") == initial_plan_id
    )
    profile = assertions.assert_single_profile(legacy_client.server.rows("user_profiles"))
    new_plan = assertions.current_plan_for_user(plans_after, profile_before["user_id"])
    assertions.assert_plan_revision_link(prior_plan, new_plan)
    assertions.assert_plan_belongs_to_profile(new_plan, profile)
