"""Tests for JSON schema generation from Pydantic models."""

import json
from pathlib import Path

import pytest

# Imports from scripts directory (added to path by conftest.py)
from psychoanalyst_app.schemas.generate_schemas import (
    dataclass_to_pydantic,
    enhance_schema_for_typescript,
    generate_enum_schema,
    generate_schema,
    generate_all_schemas,
)

# Imports from src directory (added to path by conftest.py)
from psychoanalyst_app.models.data_models import UserStatus
from psychoanalyst_app.models.http_models import MessageDTO, UserProfileDTO
from psychoanalyst_app.orchestration.models import AgentResponse, WorkflowState


@pytest.mark.unit
class TestSchemaGeneration:
    """Test suite for schema generation."""

    def test_generate_pydantic_schema(self, tmp_path):
        """Test generating schema from Pydantic model."""
        generate_schema(UserProfileDTO, tmp_path, schema_name="UserProfile")

        schema_file = tmp_path / "UserProfile.json"
        assert schema_file.exists(), "Schema file should be created"

        with open(schema_file) as f:
            schema = json.load(f)

        # Verify basic structure
        assert schema["title"] == "UserProfile"
        assert schema["type"] == "object"
        assert "$schema" in schema
        assert "$id" in schema

        # Verify properties exist
        assert "properties" in schema
        assert "user_id" in schema["properties"]
        assert "name" in schema["properties"]
        assert "status" in schema["properties"]
        assert "created_at" in schema["properties"]

        # Verify required fields
        assert "required" in schema
        assert "user_id" in schema["required"]
        assert "name" in schema["required"]

    def test_generate_enum_schema(self, tmp_path):
        """Test generating schema from enum."""
        generate_enum_schema(UserStatus, tmp_path)

        schema_file = tmp_path / "UserStatus.json"
        assert schema_file.exists()

        with open(schema_file) as f:
            schema = json.load(f)

        assert schema["title"] == "UserStatus"
        assert schema["type"] == "string"
        assert "enum" in schema
        assert "PROFILE_ONLY" in schema["enum"]
        assert "INTAKE_IN_PROGRESS" in schema["enum"]

    def test_dataclass_to_pydantic_conversion(self):
        """Test converting dataclass to Pydantic model."""
        pydantic_model = dataclass_to_pydantic(AgentResponse)

        # Verify we got a valid Pydantic model
        assert hasattr(pydantic_model, "model_json_schema")

        # Generate schema from converted model
        schema = pydantic_model.model_json_schema()

        assert "properties" in schema
        assert "content" in schema["properties"]
        assert "next_action" in schema["properties"]

    def test_schema_has_metadata(self, tmp_path):
        """Test that generated schemas have proper metadata."""
        generate_schema(MessageDTO, tmp_path, schema_name="Message")

        schema_file = tmp_path / "Message.json"
        with open(schema_file) as f:
            schema = json.load(f)

        # Verify metadata
        assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert "$id" in schema
        assert schema["$id"].startswith("https://psychoanalyst.app/schemas/")
        assert schema["title"] == "Message"

    def test_enum_enhancement_for_typescript(self, tmp_path):
        """Test that enum fields are enhanced with TypeScript metadata."""
        generate_schema(UserProfileDTO, tmp_path, schema_name="UserProfile")

        schema_file = tmp_path / "UserProfile.json"
        with open(schema_file) as f:
            schema = json.load(f)

        # Check that status field (enum) has TypeScript metadata
        status_field = schema["properties"]["status"]
        assert "tsType" in status_field
        assert status_field["tsType"] == "enum"
        assert "enumValues" in status_field
        assert isinstance(status_field["enumValues"], list)
        assert len(status_field["enumValues"]) > 0

    def test_optional_fields_handled_correctly(self, tmp_path):
        """Test that optional fields are properly represented."""
        generate_schema(UserProfileDTO, tmp_path, schema_name="UserProfile")

        schema_file = tmp_path / "UserProfile.json"
        with open(schema_file) as f:
            schema = json.load(f)

        # data_of_birth is optional
        data_of_birth_field = schema["properties"]["data_of_birth"]
        assert "anyOf" in data_of_birth_field or "type" not in data_of_birth_field

        # It should have a default value or be nullable
        assert "default" in data_of_birth_field or any(
            item.get("type") == "null" for item in data_of_birth_field.get("anyOf", [])
        )

    def test_datetime_fields_serialized_as_strings(self, tmp_path):
        """Test that datetime fields are serialized as ISO strings."""
        generate_schema(UserProfileDTO, tmp_path, schema_name="UserProfile")

        schema_file = tmp_path / "UserProfile.json"
        with open(schema_file) as f:
            schema = json.load(f)

        # created_at should be a string with date-time format
        created_at = schema["properties"]["created_at"]
        assert created_at["type"] == "string"
        assert created_at["format"] == "date-time"

    def test_all_models_have_schemas(self):
        """Test that all expected models can generate schemas."""
        schemas_dir = Path(__file__).parent.parent.parent / "schemas"

        # Check that index.json exists
        index_file = schemas_dir / "index.json"
        assert index_file.exists(), "index.json should exist"

        with open(index_file) as f:
            index = json.load(f)

        # Verify we have models listed
        assert "models" in index
        assert len(index["models"]) > 0

        # Verify each model has a schema file
        for model_name in index["models"]:
            schema_file = schemas_dir / f"{model_name}.json"
            assert schema_file.exists(), f"{model_name}.json should exist"

            # Verify it's valid JSON
            with open(schema_file) as f:
                schema = json.load(f)
                assert "$schema" in schema or "enum" in schema

    def test_committed_schemas_up_to_date(self, tmp_path):
        """Test that committed schema files match generation output."""
        generate_all_schemas(tmp_path)

        custom_schema_files = {"ws_protocol.json"}
        committed_dir = Path(__file__).parent.parent.parent / "schemas"
        committed_files = sorted(
            p.name
            for p in committed_dir.glob("*.json")
            if p.name not in custom_schema_files
        )
        generated_files = sorted(
            p.name
            for p in tmp_path.glob("*.json")
            if p.name not in custom_schema_files
        )

        assert (
            committed_files == generated_files
        ), "Generated schemas differ from committed set"

        for filename in committed_files:
            committed_path = committed_dir / filename
            generated_path = tmp_path / filename

            with open(committed_path) as f:
                committed = json.load(f)
            with open(generated_path) as f:
                generated = json.load(f)

            if filename == "index.json":
                committed = {**committed, "generated_at": "<ignored>"}
                generated = {**generated, "generated_at": "<ignored>"}

            assert (
                committed == generated
            ), f"Committed schema out of date: {filename}"

    def test_session_schema_uses_session_id(self, tmp_path):
        """Session schema should use canonical session_id naming."""
        generate_all_schemas(tmp_path)

        session_schema = tmp_path / "Session.json"
        assert session_schema.exists(), "Session.json should be generated"

        with open(session_schema) as f:
            schema = json.load(f)

        assert "session_id" in schema.get("properties", {})
        assert "session_block_id" not in json.dumps(schema)

    def test_no_legacy_session_block_terms_in_generated_schemas(self, tmp_path):
        """Legacy SessionBlock naming should not appear in generated schemas."""
        generate_all_schemas(tmp_path)

        for schema_file in tmp_path.glob("*.json"):
            if schema_file.name == "index.json":
                continue
            content = schema_file.read_text()
            assert "session_block_id" not in content
            assert "SessionBlock" not in content

    def test_ws_protocol_schema_preserved_during_generation(self, tmp_path):
        """Schema generation should not delete ws_protocol.json."""
        ws_protocol_path = tmp_path / "ws_protocol.json"
        ws_protocol_content = {
            "version": "1.2.3",
            "message_types": {
                "client_to_server": ["chat_message"],
                "server_to_client": ["connected"],
            },
        }
        ws_protocol_path.write_text(json.dumps(ws_protocol_content))

        generate_all_schemas(tmp_path)

        assert ws_protocol_path.exists(), "ws_protocol.json should be preserved"
        with open(ws_protocol_path) as f:
            preserved = json.load(f)
        assert preserved == ws_protocol_content


@pytest.mark.integration
class TestSchemaIntegration:
    """Integration tests for schema generation."""

    def test_backend_models_match_schemas(self):
        """Test that backend Pydantic models match generated schemas."""
        schemas_dir = Path(__file__).parent.parent.parent / "schemas"

        # Test UserProfile
        schema_file = schemas_dir / "UserProfile.json"
        if schema_file.exists():
            with open(schema_file) as f:
                schema = json.load(f)

            # Create a sample UserProfile instance
            from datetime import datetime
            from psychoanalyst_app.models.http_models import UserProfileDTO

            user = UserProfileDTO(
                user_id="test-123",
                name="Test User",
                status=UserStatus.PROFILE_ONLY,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )

            # Serialize to dict
            user_dict = user.model_dump()

            # Verify all required fields from schema are present
            if "required" in schema:
                for field in schema["required"]:
                    assert (
                        field in user_dict
                    ), f"Required field {field} should be in model"

    def test_enum_values_consistent(self):
        """Test that enum values in schemas match Python enums."""
        schemas_dir = Path(__file__).parent.parent.parent / "schemas"

        # Test UserStatus enum
        schema_file = schemas_dir / "UserStatus.json"
        if schema_file.exists():
            with open(schema_file) as f:
                schema = json.load(f)

            schema_values = set(schema["enum"])
            python_values = set(e.value for e in UserStatus)

            assert (
                schema_values == python_values
            ), "Schema enum values should match Python enum"

    def test_workflow_state_enum_consistency(self):
        """Test WorkflowState enum consistency."""
        schemas_dir = Path(__file__).parent.parent.parent / "schemas"

        schema_file = schemas_dir / "WorkflowState.json"
        if schema_file.exists():
            with open(schema_file) as f:
                schema = json.load(f)

            schema_values = set(schema["enum"])
            python_values = set(e.value for e in WorkflowState)

            assert schema_values == python_values
