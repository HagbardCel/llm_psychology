"""
Version information for the Psychoanalyst application.

This module defines the current API version and provides utilities
for version comparison and compatibility checking.
"""

from typing import NamedTuple


class Version(NamedTuple):
    """Semantic version tuple (MAJOR, MINOR, PATCH)."""

    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        """Return version as string (e.g., '1.2.3')."""
        return f"{self.major}.{self.minor}.{self.patch}"

    @classmethod
    def from_string(cls, version_str: str) -> "Version":
        """
        Parse version from string format 'MAJOR.MINOR.PATCH'.

        Args:
            version_str: Version string (e.g., '1.2.3')

        Returns:
            Version instance

        Raises:
            ValueError: If version string format is invalid
        """
        try:
            parts = version_str.split(".")
            if len(parts) != 3:
                raise ValueError(f"Invalid version format: {version_str}")
            return cls(int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, IndexError) as e:
            raise ValueError(f"Invalid version string '{version_str}': {e}")

    def is_compatible_with(self, client_version: "Version") -> bool:
        """
        Check if this backend version is compatible with a client version.

        Compatibility rules:
        - MAJOR version must match exactly (breaking changes)
        - MINOR version: client can be lower or equal (backward compatible)
        - PATCH version: any combination is okay (bug fixes only)

        Args:
            client_version: Client's version

        Returns:
            True if versions are compatible, False otherwise
        """
        # Major version must match
        if self.major != client_version.major:
            return False

        # Client's minor version must be <= backend's minor version
        if client_version.minor > self.minor:
            return False

        # Patch version doesn't affect compatibility
        return True


# Current backend API version
# Update this when making changes to the API
API_VERSION = Version(1, 0, 0)

# Minimum supported client version
# Clients older than this will be rejected
MIN_CLIENT_VERSION = Version(1, 0, 0)
