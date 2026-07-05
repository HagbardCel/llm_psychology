"""Reflection agent package."""

__all__ = ["TrioReflectionAgent"]


def __getattr__(name: str):
    if name == "TrioReflectionAgent":
        from psychoanalyst_app.agents.reflection.agent import TrioReflectionAgent

        return TrioReflectionAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
