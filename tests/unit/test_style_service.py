import tempfile
from pathlib import Path

from psychoanalyst_app.services.style_service import StylePack, StyleService


class TestStyleService:
    """Unit tests for StyleService."""

    def test_init_with_default_directory(self):
        """Test StyleService initialization with default directory."""
        # This test will use the actual styles directory
        style_service = StyleService()
        assert style_service is not None
        assert hasattr(style_service, "styles_dir")
        assert hasattr(style_service, "style_packs")

    def test_get_available_styles(self):
        """Test getting available therapy styles."""
        style_service = StyleService()
        styles = style_service.get_available_styles()

        # Should return a list of style IDs
        assert isinstance(styles, list)
        # Should include the expected styles (cbt, freud, jung)
        expected_styles = {"cbt", "freud", "jung"}
        assert expected_styles.issubset(set(styles))

    def test_get_style_pack(self):
        """Test getting a specific style pack."""
        style_service = StyleService()

        # Test getting an existing style pack
        cbt_pack = style_service.get_style_pack("cbt")
        assert cbt_pack is not None
        assert cbt_pack.style_id == "cbt"
        assert isinstance(cbt_pack, StylePack)

        # Test getting a non-existent style pack
        non_existent_pack = style_service.get_style_pack("non_existent")
        assert non_existent_pack is None

    def test_get_style_description(self):
        """Test getting style descriptions."""
        style_service = StyleService()

        # Test getting description for existing style
        cbt_description = style_service.get_style_description("cbt")
        assert isinstance(cbt_description, str)
        assert len(cbt_description) > 0

        # Test getting description for non-existent style
        non_existent_desc = style_service.get_style_description("non_existent")
        assert non_existent_desc == ""

    def test_get_agent_prompts(self):
        """Test getting agent prompts for different styles."""
        style_service = StyleService()

        # Test psychoanalyst prompt
        cbt_prompt = style_service.get_therapist_prompt("cbt")
        assert isinstance(cbt_prompt, str)

        # Test reflection prompt
        reflection_prompt = style_service.get_reflection_prompt("cbt")
        assert isinstance(reflection_prompt, str)

        # Test assessment prompt
        assessment_prompt = style_service.get_assessment_prompt("cbt")
        assert isinstance(assessment_prompt, str)

        # Test prompts for non-existent style
        assert style_service.get_therapist_prompt("non_existent") == ""
        assert style_service.get_reflection_prompt("non_existent") == ""
        assert style_service.get_assessment_prompt("non_existent") == ""

    def test_get_knowledge_source(self):
        """Test getting knowledge source identifier."""
        style_service = StyleService()

        # Test getting knowledge source for existing style
        cbt_source = style_service.get_knowledge_source("cbt")
        assert cbt_source == "cbt.md"

        # Test getting knowledge source for non-existent style
        non_existent_source = style_service.get_knowledge_source("non_existent")
        assert non_existent_source == "non_existent.md"


class TestStylePack:
    """Unit tests for StylePack."""

    def test_style_pack_loading(self):
        """Test loading a style pack from files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            style_dir = Path(temp_dir) / "test_style"
            style_dir.mkdir()

            # Create test files
            (style_dir / "knowledge.md").write_text("# Test Knowledge\nTest content")
            (style_dir / "description.txt").write_text("Test description")
            (style_dir / "therapist_prompt.txt").write_text(
                "Test psychoanalyst prompt"
            )
            (style_dir / "reflection_prompt.txt").write_text("Test reflection prompt")
            (style_dir / "assessment_prompt.txt").write_text("Test assessment prompt")

            # Create StylePack
            style_pack = StylePack("test_style", style_dir)

            # Verify components were loaded
            assert style_pack.style_id == "test_style"
            assert "Test Knowledge" in style_pack.knowledge
            assert style_pack.description == "Test description"
            assert style_pack.therapist_prompt == "Test psychoanalyst prompt"
            assert style_pack.reflection_prompt == "Test reflection prompt"
            assert style_pack.assessment_prompt == "Test assessment prompt"

            # Verify it's valid
            assert style_pack.is_valid() is True

    def test_style_pack_missing_components(self):
        """Test StylePack with missing components."""
        with tempfile.TemporaryDirectory() as temp_dir:
            style_dir = Path(temp_dir) / "incomplete_style"
            style_dir.mkdir()

            # Create only some files
            (style_dir / "knowledge.md").write_text("# Knowledge")
            (style_dir / "description.txt").write_text("Description")
            # Missing prompt files

            # Create StylePack
            style_pack = StylePack("incomplete_style", style_dir)

            # Should not be valid due to missing prompts
            assert style_pack.is_valid() is False

    def test_style_pack_empty_directory(self):
        """Test StylePack with empty directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            style_dir = Path(temp_dir) / "empty_style"
            style_dir.mkdir()

            # Create StylePack
            style_pack = StylePack("empty_style", style_dir)

            # Should not be valid
            assert style_pack.is_valid() is False

            # All components should be empty strings
            assert style_pack.knowledge == ""
            assert style_pack.description == ""
            assert style_pack.therapist_prompt == ""
            assert style_pack.reflection_prompt == ""
            assert style_pack.assessment_prompt == ""


# Integration tests with temporary style packs
class TestStyleServiceIntegration:
    """Integration tests for StyleService with temporary directories."""

    def test_load_style_packs_from_custom_directory(self):
        """Test loading style packs from a custom directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            styles_dir = Path(temp_dir) / "styles"
            styles_dir.mkdir()

            # Create a test style pack
            test_style_dir = styles_dir / "test_therapy"
            test_style_dir.mkdir()

            (test_style_dir / "knowledge.md").write_text("# Test Therapy Knowledge")
            (test_style_dir / "description.txt").write_text("Test therapy description")
            (test_style_dir / "therapist_prompt.txt").write_text(
                "Test therapy prompt"
            )
            (test_style_dir / "reflection_prompt.txt").write_text(
                "Test reflection prompt"
            )
            (test_style_dir / "assessment_prompt.txt").write_text(
                "Test assessment prompt"
            )

            # Create StyleService with custom directory
            style_service = StyleService(str(styles_dir))

            # Verify the style pack was loaded
            available_styles = style_service.get_available_styles()
            assert "test_therapy" in available_styles

            # Verify components can be retrieved
            test_pack = style_service.get_style_pack("test_therapy")
            assert test_pack is not None
            assert "Test Therapy Knowledge" in test_pack.knowledge

            test_description = style_service.get_style_description("test_therapy")
            assert test_description == "Test therapy description"


# Edge case tests
class TestStyleServiceEdgeCases:
    """Edge case tests for StyleService."""

    def test_nonexistent_styles_directory(self):
        """Test StyleService with non-existent styles directory."""
        style_service = StyleService("nonexistent_directory")

        # Should handle gracefully
        styles = style_service.get_available_styles()
        assert isinstance(styles, list)

        # Should return empty pack for non-existent style
        pack = style_service.get_style_pack("any_style")
        assert pack is None

    def test_style_pack_with_empty_files(self):
        """Test StylePack with empty component files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            style_dir = Path(temp_dir) / "empty_files_style"
            style_dir.mkdir()

            # Create empty files
            (style_dir / "knowledge.md").touch()
            (style_dir / "description.txt").touch()
            (style_dir / "therapist_prompt.txt").touch()
            (style_dir / "reflection_prompt.txt").touch()
            (style_dir / "assessment_prompt.txt").touch()

            # Create StylePack
            style_pack = StylePack("empty_files_style", style_dir)

            # Should be valid (files exist, even if empty)
            assert style_pack.is_valid() is True

            # All components should be empty strings
            assert style_pack.knowledge == ""
            assert style_pack.description == ""
            assert style_pack.therapist_prompt == ""
            assert style_pack.reflection_prompt == ""
            assert style_pack.assessment_prompt == ""
