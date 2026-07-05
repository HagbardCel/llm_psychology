"""Note-taking agent package for intake patches and session clinical notes."""

from psychoanalyst_app.agents.note_taker.intake_patch import (
    IntakePatchExtractionResult,
    extract_intake_record_patch,
)

__all__ = [
    "IntakePatchExtractionResult",
    "NoteTakerAgent",
    "extract_intake_record_patch",
]


def __getattr__(name: str):
    if name == "NoteTakerAgent":
        from psychoanalyst_app.agents.note_taker.agent import NoteTakerAgent

        return NoteTakerAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
