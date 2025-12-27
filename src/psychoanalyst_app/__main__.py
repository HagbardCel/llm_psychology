"""Console entry point for ``python -m psychoanalyst_app``."""

import sys

import trio

from .main import main


def cli() -> int:
    """Run the terminal UI using Trio."""
    try:
        trio.run(main)
    except KeyboardInterrupt:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
