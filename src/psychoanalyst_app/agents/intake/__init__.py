"""Intake agent package."""

from psychoanalyst_app.agents.intake.policy import (
    MAX_INTAKE_PATIENT_TURNS,
    MIN_INTAKE_PATIENT_TURNS,
)

__all__ = [
    "MAX_INTAKE_PATIENT_TURNS",
    "MIN_INTAKE_PATIENT_TURNS",
    "TrioIntakeAgent",
]


def __getattr__(name: str):
    if name == "TrioIntakeAgent":
        from psychoanalyst_app.agents.intake.agent import TrioIntakeAgent

        return TrioIntakeAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
