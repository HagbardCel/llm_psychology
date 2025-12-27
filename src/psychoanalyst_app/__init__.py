"""Psychoanalyst application package."""

from importlib import metadata

try:
    __version__ = metadata.version("psychoanalyst-app")
except metadata.PackageNotFoundError:  # pragma: no cover - fallback for editable installs
    from .version import API_VERSION

    __version__ = str(API_VERSION)

__all__ = ["__version__"]
