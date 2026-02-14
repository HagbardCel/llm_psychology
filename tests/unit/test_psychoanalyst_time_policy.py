from __future__ import annotations

from types import SimpleNamespace

from psychoanalyst_app.agents.psychoanalyst.response_mode import resolve_response_mode
from psychoanalyst_app.agents.psychoanalyst.time_policy import should_offer_extension
from psychoanalyst_app.models.data_models import UserStatus
from psychoanalyst_app.orchestration.models import WorkflowEvent


def test_should_offer_extension_requires_short_extendable_window() -> None:
    context = SimpleNamespace(time_remaining_minutes=4, can_extend=True)
    assert should_offer_extension(context, in_deep_topic=False) is True
    assert should_offer_extension(context, in_deep_topic=True) is False

    exhausted = SimpleNamespace(time_remaining_minutes=0, can_extend=True)
    assert should_offer_extension(exhausted, in_deep_topic=False) is False


def test_resolve_response_mode_handles_transitions_and_extensions() -> None:
    transition_context = SimpleNamespace(
        user_profile=SimpleNamespace(status=UserStatus.ASSESSMENT_COMPLETE),
        is_time_up=False,
    )
    next_action, event = resolve_response_mode(
        transition_context,
        should_offer_extension=False,
    )
    assert next_action == "transition"
    assert event == WorkflowEvent.START_THERAPY

    timeout_context = SimpleNamespace(
        user_profile=SimpleNamespace(status=UserStatus.THERAPY_IN_PROGRESS),
        is_time_up=True,
    )
    next_action, event = resolve_response_mode(
        timeout_context,
        should_offer_extension=False,
    )
    assert next_action == "transition"
    assert event == WorkflowEvent.COMPLETE_SESSION

    extension_context = SimpleNamespace(
        user_profile=SimpleNamespace(status=UserStatus.THERAPY_IN_PROGRESS),
        is_time_up=False,
    )
    next_action, event = resolve_response_mode(
        extension_context,
        should_offer_extension=True,
    )
    assert next_action == "offer_extension"
    assert event is None
