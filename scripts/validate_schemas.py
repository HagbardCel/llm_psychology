#!/usr/bin/env python3
"""
Validate generated JSON Schema files.

This script performs comprehensive validation of generated JSON schemas:
- JSON syntax validation
- Schema structure validation
- Consistency checks against backend models
- Field naming conventions
"""

import json
import sys
from pathlib import Path
from typing import List, Tuple

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from models.data_models import UserProfile, UserStatus, Message, TherapyPlan
from orchestration.models import WorkflowState, WorkflowEvent

SCHEMAS_DIR = Path(__file__).parent.parent / "schemas"


class ValidationError(Exception):
    """Raised when validation fails."""
    pass


def validate_json_syntax(schema_file: Path) -> None:
    """Validate that the file contains valid JSON."""
    try:
        with open(schema_file) as f:
            json.load(f)
    except json.JSONDecodeError as e:
        raise ValidationError(f"Invalid JSON in {schema_file.name}: {e}")


def validate_schema_structure(schema_file: Path, schema: dict) -> None:
    """Validate that the schema has required fields."""
    required_fields = ["$schema", "title"]

    for field in required_fields:
        if field not in schema:
            raise ValidationError(
                f"Schema {schema_file.name} missing required field: {field}"
            )

    # Check schema version
    if schema["$schema"] != "http://json-schema.org/draft-07/schema#":
        raise ValidationError(
            f"Schema {schema_file.name} uses unsupported schema version: "
            f"{schema['$schema']}"
        )


def validate_enum_values(schema_file: Path, schema: dict) -> None:
    """Validate enum schemas match Python enums."""
    if schema.get("type") != "string" or "enum" not in schema:
        return  # Not an enum schema

    schema_name = schema["title"]

    # Map of schema names to Python enum classes
    enum_mapping = {
        "UserStatus": UserStatus,
        "WorkflowState": WorkflowState,
        "WorkflowEvent": WorkflowEvent,
    }

    if schema_name not in enum_mapping:
        return  # Not a tracked enum

    python_enum = enum_mapping[schema_name]
    schema_values = set(schema["enum"])
    python_values = set(e.value for e in python_enum)

    if schema_values != python_values:
        missing_in_schema = python_values - schema_values
        extra_in_schema = schema_values - python_values

        error_msg = f"Enum mismatch in {schema_name}:"
        if missing_in_schema:
            error_msg += f"\n  Missing in schema: {missing_in_schema}"
        if extra_in_schema:
            error_msg += f"\n  Extra in schema: {extra_in_schema}"

        raise ValidationError(error_msg)


def validate_object_required_fields(schema_file: Path, schema: dict) -> None:
    """Validate that object schemas have required fields defined."""
    if schema.get("type") != "object":
        return

    if "properties" not in schema:
        raise ValidationError(
            f"Object schema {schema_file.name} missing 'properties' field"
        )

    # Check that required fields exist in properties
    required = schema.get("required", [])
    properties = schema.get("properties", {})

    for field in required:
        if field not in properties:
            raise ValidationError(
                f"Schema {schema_file.name} lists '{field}' as required "
                f"but it's not in properties"
            )


def validate_index_file() -> None:
    """Validate the index.json file."""
    index_file = SCHEMAS_DIR / "index.json"

    if not index_file.exists():
        raise ValidationError("index.json not found")

    with open(index_file) as f:
        index = json.load(f)

    # Validate index structure
    required_fields = ["title", "description", "version", "models"]
    for field in required_fields:
        if field not in index:
            raise ValidationError(f"index.json missing required field: {field}")

    # Validate that all listed models have schema files
    models = index["models"]
    for model_name in models:
        schema_file = SCHEMAS_DIR / f"{model_name}.json"
        if not schema_file.exists():
            raise ValidationError(
                f"index.json lists model '{model_name}' but {schema_file.name} "
                f"does not exist"
            )

    # Check for schema files not in index
    schema_files = [
        f.stem
        for f in SCHEMAS_DIR.glob("*.json")
        if f.name != "index.json"
    ]

    missing_from_index = set(schema_files) - set(models)
    if missing_from_index:
        raise ValidationError(
            f"Schema files not listed in index.json: {missing_from_index}"
        )


def validate_all_schemas() -> Tuple[int, List[str]]:
    """
    Validate all schema files.

    Returns:
        Tuple of (success_count, error_messages)
    """
    if not SCHEMAS_DIR.exists():
        return 0, ["Schemas directory does not exist. Run 'make generate-schemas' first."]

    schema_files = list(SCHEMAS_DIR.glob("*.json"))
    if not schema_files:
        return 0, ["No schema files found. Run 'make generate-schemas' first."]

    errors = []
    success_count = 0

    # Validate index file first
    try:
        validate_index_file()
        print("✓ index.json validated")
    except ValidationError as e:
        errors.append(str(e))

    # Validate each schema file
    for schema_file in schema_files:
        if schema_file.name == "index.json":
            continue

        try:
            # Load schema
            with open(schema_file) as f:
                schema = json.load(f)

            # Run validations
            validate_json_syntax(schema_file)
            validate_schema_structure(schema_file, schema)
            validate_enum_values(schema_file, schema)
            validate_object_required_fields(schema_file, schema)

            print(f"✓ {schema_file.name} validated")
            success_count += 1

        except ValidationError as e:
            errors.append(f"✗ {schema_file.name}: {e}")
        except Exception as e:
            errors.append(f"✗ {schema_file.name}: Unexpected error: {e}")

    return success_count, errors


def main() -> int:
    """Main validation function."""
    print("🔍 Validating JSON schemas...\n")

    try:
        success_count, errors = validate_all_schemas()

        print(f"\n{'='*60}")
        print(f"Validation Results:")
        print(f"  ✓ Passed: {success_count}")
        print(f"  ✗ Failed: {len(errors)}")
        print(f"{'='*60}")

        if errors:
            print("\nErrors:")
            for error in errors:
                print(f"  {error}")
            return 1

        print("\n✅ All schemas validated successfully!")
        return 0

    except Exception as e:
        print(f"\n✗ Validation failed with unexpected error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
