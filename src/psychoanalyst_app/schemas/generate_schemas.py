#!/usr/bin/env python3
"""
Generate JSON Schema files from Pydantic models.

This script exports all API-facing Pydantic models to JSON Schema format.
"""

import argparse
import json
import sys
from dataclasses import MISSING, fields, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, create_model

# Import all models
from psychoanalyst_app.models.domain import UserStatus
from psychoanalyst_app.models.http import (
    CreateSessionRequestDTO,
    CreateUserProfileRequestDTO,
    EndSessionRequestDTO,
    EndSessionResponseDTO,
    HealthCheckResponseDTO,
    JobStatusDTO,
    MessageDTO,
    PatchUserProfileRequestDTO,
    RequiredWorkflowAction,
    SessionDTO,
    SessionTimerResponseDTO,
    StatusMessageResponseDTO,
    TherapyPlanDTO,
    TherapyStyleDTO,
    TopicDTO,
    UpdateUserProfileRequestDTO,
    UserProfileDTO,
    UserRegisterResponseDTO,
    UserStatusResponseDTO,
    VersionCheckRequest,
    VersionCheckResponse,
    VersionInfo,
    WorkflowCompleteProfileRequestDTO,
    WorkflowNextActionDTO,
    WorkflowRetryPlanUpdateRequestDTO,
    WorkflowSelectTherapyStyleRequestDTO,
    WorkflowStartTherapyRequestDTO,
    WorkflowStartTherapyResponseDTO,
)
from psychoanalyst_app.orchestration.models import WorkflowEvent, WorkflowState

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = REPO_ROOT / "schemas"
PRESERVED_SCHEMA_FILES = {"ws_protocol.json"}


def dataclass_to_pydantic(dataclass_type: type) -> type[BaseModel]:
    """
    Convert a dataclass to a Pydantic model for schema generation.

    Args:
        dataclass_type: Dataclass type to convert

    Returns:
        Pydantic BaseModel class with equivalent fields
    """
    if not is_dataclass(dataclass_type):
        raise ValueError(f"{dataclass_type} is not a dataclass")

    # Build field definitions for Pydantic
    field_definitions = {}
    for field in fields(dataclass_type):
        field_type = field.type

        # Correctly handle default vs default_factory
        if field.default_factory is not MISSING:
            default = Field(default_factory=field.default_factory)
        elif field.default is not MISSING:
            default = field.default
        else:
            default = ...

        field_definitions[field.name] = (field_type, default)

    # Create Pydantic model
    model_name = f"{dataclass_type.__name__}Model"
    pydantic_model = create_model(
        model_name,
        __module__=__name__,
        __doc__=dataclass_type.__doc__,
        **field_definitions,
    )

    return pydantic_model


def generate_schema(
    model: type[BaseModel], output_dir: Path, schema_name: str | None = None
) -> None:
    """
    Generate JSON Schema for a single model.

    Args:
        model: Pydantic model to generate schema for
        output_dir: Directory to write schema file to
        schema_name: Optional custom schema name (defaults to model.__name__)
    """
    name = schema_name or model.__name__

    # Generate base schema
    schema = model.model_json_schema()

    # Add metadata
    schema["$schema"] = "http://json-schema.org/draft-07/schema#"
    schema["$id"] = f"https://psychoanalyst.app/schemas/{name}.json"
    schema["title"] = name

    # Write to file
    output_file = output_dir / f"{name}.json"
    with open(output_file, "w") as f:
        json.dump(schema, f, indent=2)

    print(f"✓ Generated schema: {output_file.name}")


def generate_enum_schema(enum_type: type[Enum], output_dir: Path) -> None:
    """
    Generate JSON Schema for an enum.

    Args:
        enum_type: Enum type to generate schema for
        output_dir: Directory to write schema file to
    """
    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": f"https://psychoanalyst.app/schemas/{enum_type.__name__}.json",
        "title": enum_type.__name__,
        "description": enum_type.__doc__ or f"{enum_type.__name__} enum",
        "type": "string",
        "enum": [e.value for e in enum_type],
    }

    output_file = output_dir / f"{enum_type.__name__}.json"
    with open(output_file, "w") as f:
        json.dump(schema, f, indent=2)

    print(f"✓ Generated enum schema: {output_file.name}")


def generate_all_schemas(output_dir: Path = OUTPUT_DIR) -> None:
    """Generate JSON Schemas for all API models."""
    output_dir.mkdir(exist_ok=True, parents=True)

    # Remove previous schema files to avoid stale models
    for existing in output_dir.glob("*.json"):
        if existing.name in PRESERVED_SCHEMA_FILES:
            continue
        existing.unlink()

    print(f"Generating schemas in {output_dir.absolute()}...\n")

    # Pydantic models (model, optional schema name override)
    pydantic_models: list[tuple[type[BaseModel], str | None]] = [
        (UserProfileDTO, "UserProfile"),
        (MessageDTO, "Message"),
        (TopicDTO, "Topic"),
        (SessionDTO, "Session"),
        (TherapyPlanDTO, "TherapyPlan"),
        (SessionTimerResponseDTO, "SessionTimerResponse"),
        (HealthCheckResponseDTO, "HealthCheckResponse"),
        (CreateUserProfileRequestDTO, "CreateUserProfileRequest"),
        (UpdateUserProfileRequestDTO, "UpdateUserProfileRequest"),
        (PatchUserProfileRequestDTO, "PatchUserProfileRequest"),
        (CreateSessionRequestDTO, "CreateSessionRequest"),
        (EndSessionRequestDTO, "EndSessionRequest"),
        (EndSessionResponseDTO, "EndSessionResponse"),
        (WorkflowCompleteProfileRequestDTO, "WorkflowCompleteProfileRequest"),
        (WorkflowRetryPlanUpdateRequestDTO, "RetryPlanUpdateRequest"),
        (WorkflowSelectTherapyStyleRequestDTO, "SelectTherapyStyleRequest"),
        (WorkflowStartTherapyRequestDTO, "StartTherapyRequest"),
        (WorkflowStartTherapyResponseDTO, "StartTherapyResponse"),
        (UserStatusResponseDTO, "UserStatusResponse"),
        (TherapyStyleDTO, None),
        (StatusMessageResponseDTO, "StatusMessageResponse"),
        (UserRegisterResponseDTO, "UserRegisterResponse"),
        (WorkflowNextActionDTO, "WorkflowNextAction"),
        (JobStatusDTO, "JobStatus"),
        (VersionInfo, None),
        (VersionCheckRequest, None),
        (VersionCheckResponse, None),
    ]

    # Enums
    enums: list[type[Enum]] = [
        UserStatus,
        WorkflowState,
        WorkflowEvent,
        RequiredWorkflowAction,
    ]

    print("Generating Pydantic model schemas...")
    for model, schema_name in pydantic_models:
        try:
            generate_schema(model, output_dir, schema_name=schema_name)
        except Exception as e:
            print(f"✗ Failed to generate schema for {model.__name__}: {e}")

    print("\nGenerating enum schemas...")
    for enum_type in enums:
        try:
            generate_enum_schema(enum_type, output_dir)
        except Exception as e:
            print(f"✗ Failed to generate enum schema for {enum_type.__name__}: {e}")

    # Generate index file
    all_models = [schema_name or m.__name__ for m, schema_name in pydantic_models] + [
        e.__name__ for e in enums
    ]

    index = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "Local Therapist Tool API Schema Index",
        "description": "Index of all API data models",
        "version": "1.0.0",
        "generated_at": datetime.now().isoformat(),
        "models": sorted(all_models),
    }

    with open(output_dir / "index.json", "w") as f:
        json.dump(index, f, indent=2)

    print(f"\n{'='*60}")
    print(f"✓ Successfully generated {len(all_models)} schemas")
    print(f"  Output directory: {output_dir.absolute()}")
    print("  Index file: index.json")
    print(f"{'='*60}")


def main(argv: list[str] | None = None) -> None:
    """Entry point that can be used by CLI scripts or tests."""
    parser = argparse.ArgumentParser(
        description="Generate JSON schemas from Pydantic models"
    )
    parser.add_argument(
        "--output-dir",
        default=str(OUTPUT_DIR),
        help="Directory to write schema files to (default: ./schemas)",
    )
    args = parser.parse_args(argv)

    try:
        generate_all_schemas(Path(args.output_dir))
    except Exception as exc:
        print(f"\n✗ Schema generation failed: {exc}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
