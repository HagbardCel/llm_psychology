"""Immutable therapy-style catalog loaded from packaged text assets."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from types import MappingProxyType

_STYLE_ORDER = ("jung", "cbt", "freud")
_REQUIRED_FILES = (
    "description.txt",
    "assessment_prompt.txt",
    "therapist_prompt.txt",
    "reflection_prompt.txt",
)
_DISPLAY_NAMES = {
    "jung": "Jungian Analytical Psychology",
    "cbt": "Cognitive Behavioral Therapy",
    "freud": "Psychoanalysis",
}


@dataclass(frozen=True, slots=True)
class StyleDefinition:
    id: str
    name: str
    description: str
    assessment_instructions: str
    therapist_instructions: str
    post_session_instructions: str | None = None


def _read_asset(style_id: str, filename: str) -> str:
    package = resources.files("jung.styles").joinpath(style_id, filename)
    text = package.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Style asset {style_id}/{filename} is empty")
    return text


def load_styles() -> MappingProxyType[str, StyleDefinition]:
    """Load all therapy styles in deterministic order."""
    styles: dict[str, StyleDefinition] = {}
    for style_id in _STYLE_ORDER:
        for filename in _REQUIRED_FILES:
            path = resources.files("jung.styles").joinpath(style_id, filename)
            if not path.is_file():
                raise FileNotFoundError(f"Missing style asset: {style_id}/{filename}")
        if style_id in styles:
            raise ValueError(f"Duplicate style id: {style_id}")
        reflection = _read_asset(style_id, "reflection_prompt.txt")
        styles[style_id] = StyleDefinition(
            id=style_id,
            name=_DISPLAY_NAMES.get(style_id, style_id),
            description=_read_asset(style_id, "description.txt"),
            assessment_instructions=_read_asset(style_id, "assessment_prompt.txt"),
            therapist_instructions=_read_asset(style_id, "therapist_prompt.txt"),
            post_session_instructions=reflection,
        )
    return MappingProxyType(styles)
