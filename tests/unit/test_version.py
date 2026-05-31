"""
Unit tests for version module (version checking and compatibility).
"""

import pytest

from psychoanalyst_app.version import API_VERSION, MIN_CLIENT_VERSION, Version


class TestVersion:
    """Tests for Version class."""

    def test_version_creation(self):
        """Test creating a Version instance."""
        version = Version(1, 2, 3)
        assert version.major == 1
        assert version.minor == 2
        assert version.patch == 3

    def test_version_string_representation(self):
        """Test Version string conversion."""
        version = Version(1, 2, 3)
        assert str(version) == "1.2.3"

    def test_version_from_string_valid(self):
        """Test parsing valid version string."""
        version = Version.from_string("1.2.3")
        assert version.major == 1
        assert version.minor == 2
        assert version.patch == 3

    def test_version_from_string_invalid_format(self):
        """Test parsing invalid version string."""
        with pytest.raises(ValueError, match="Invalid version format"):
            Version.from_string("1.2")

        with pytest.raises(ValueError, match="Invalid version"):
            Version.from_string("invalid")

        with pytest.raises(ValueError, match="Invalid version"):
            Version.from_string("1.2.3.4")

    def test_version_equality(self):
        """Test version equality."""
        v1 = Version(1, 2, 3)
        v2 = Version(1, 2, 3)
        v3 = Version(1, 2, 4)

        assert v1 == v2
        assert v1 != v3

    def test_version_comparison(self):
        """Test version comparison operators."""
        v1 = Version(1, 2, 3)
        v2 = Version(1, 2, 4)
        v3 = Version(1, 3, 0)
        v4 = Version(2, 0, 0)

        # Less than
        assert v1 < v2
        assert v1 < v3
        assert v1 < v4

        # Greater than
        assert v2 > v1
        assert v3 > v1
        assert v4 > v1

        # Less than or equal
        assert v1 <= v1
        assert v1 <= v2

        # Greater than or equal
        assert v1 >= v1
        assert v2 >= v1


class TestVersionCompatibility:
    """Tests for version compatibility checking."""

    def test_compatible_same_version(self):
        """Test compatibility with same version."""
        backend = Version(1, 2, 3)
        client = Version(1, 2, 3)
        assert backend.is_compatible_with(client)

    def test_compatible_older_minor_version(self):
        """Test compatibility with older client minor version (backward compatible)."""
        backend = Version(1, 2, 0)
        client = Version(1, 1, 0)
        assert backend.is_compatible_with(client)

    def test_compatible_different_patch_version(self):
        """Test compatibility with different patch versions (always compatible)."""
        backend = Version(1, 2, 3)
        client_older = Version(1, 2, 1)
        client_newer = Version(1, 2, 5)

        assert backend.is_compatible_with(client_older)
        assert backend.is_compatible_with(client_newer)

    def test_incompatible_different_major_version(self):
        """Test incompatibility with different major version (breaking change)."""
        backend = Version(2, 0, 0)
        client_v1 = Version(1, 9, 9)

        assert not backend.is_compatible_with(client_v1)

        backend_v1 = Version(1, 0, 0)
        client_v2 = Version(2, 0, 0)

        assert not backend_v1.is_compatible_with(client_v2)

    def test_incompatible_newer_minor_version(self):
        """Test incompatibility with newer client minor version."""
        backend = Version(1, 2, 0)
        client = Version(1, 3, 0)

        # Client expects features from 1.3.0 that backend doesn't have
        assert not backend.is_compatible_with(client)

    def test_edge_case_zero_versions(self):
        """Test compatibility with zero versions."""
        backend = Version(0, 1, 0)
        client_same = Version(0, 1, 0)
        client_older = Version(0, 0, 1)

        assert backend.is_compatible_with(client_same)
        assert backend.is_compatible_with(client_older)


class TestAPIVersionConstants:
    """Tests for API version constants."""

    def test_api_version_defined(self):
        """Test that API_VERSION is properly defined."""
        assert API_VERSION is not None
        assert isinstance(API_VERSION, Version)
        assert API_VERSION.major >= 0
        assert API_VERSION.minor >= 0
        assert API_VERSION.patch >= 0

    def test_min_client_version_defined(self):
        """Test that MIN_CLIENT_VERSION is properly defined."""
        assert MIN_CLIENT_VERSION is not None
        assert isinstance(MIN_CLIENT_VERSION, Version)
        assert MIN_CLIENT_VERSION.major >= 0
        assert MIN_CLIENT_VERSION.minor >= 0
        assert MIN_CLIENT_VERSION.patch >= 0

    def test_min_client_version_not_greater_than_api_version(self):
        """Test that minimum client version is not greater than current API version."""
        assert MIN_CLIENT_VERSION <= API_VERSION
