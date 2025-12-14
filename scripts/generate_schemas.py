#!/usr/bin/env python3
"""
Generate JSON Schema files from Pydantic models.

This script exports all API-facing Pydantic models to JSON Schema format
for TypeScript type generation.
"""

import json
import sys
from dataclasses import asdict, fields, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Type, get_args, get_origin

from pydantic import BaseModel, Field, create_model

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Import all models
from models.data_models import (
    DomainKnowledgeChunk,
    Message,
    Session,
    TherapyPlan,
    Topic,
    UserProfile,
    UserStatus,
)
from models.api_models import (
    WorkflowDisplayAction,
    WorkflowNextActionRequest,
    WorkflowNextActionResponse,
)
from models.briefing_models import (
    BriefingStatus,
    EmotionalSummary,
    KeyTheme,
    RecommendedApproach,
    SessionBriefing,
)
from orchestration.models import (
    AgentResponse,
    SessionInfo,
    TherapyStyleRecommendation,
    WorkflowEvent,
    WorkflowState,
)

OUTPUT_DIR = Path(__file__).parent.parent / "schemas"


def dataclass_to_pydantic(dataclass_type: Type) -> Type[BaseModel]:
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
        default = field.default if field.default is not field.default_factory else ...

        # Handle default_factory
        if field.default_factory is not field.default_factory:  # type: ignore
            default = None
            # Make the field optional if it has a default_factory
            if get_origin(field_type) is not type(None | int):  # Not already Optional
                field_type = field_type | None

        field_definitions[field.name] = (field_type, default)

    # Create Pydantic model
    model_name = f"{dataclass_type.__name__}Model"
    pydantic_model = create_model(
        model_name, __doc__=dataclass_type.__doc__, **field_definitions
    )

    return pydantic_model


def enhance_schema_for_typescript(schema: dict, model: Type[BaseModel]) -> dict:
    """
    Enhance schema with TypeScript-friendly metadata.

    Args:
        schema: Generated JSON schema
        model: Pydantic model type

    Returns:
        Enhanced schema dictionary
    """
    # Add metadata for better TypeScript generation
    if "properties" in schema:
        for field_name, field_info in model.model_fields.items():
            if field_name in schema["properties"]:
                field_type = field_info.annotation

                # Check if field is an Enum
                if isinstance(field_type, type) and issubclass(field_type, Enum):
                    schema["properties"][field_name]["tsType"] = "enum"
                    schema["properties"][field_name]["enumValues"] = [
                        e.value for e in field_type
                    ]

    return schema


def generate_schema(
    model: Type[BaseModel], output_dir: Path, schema_name: str | None = None
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

    # Enhance for TypeScript
    schema = enhance_schema_for_typescript(schema, model)

    # Write to file
    output_file = output_dir / f"{name}.json"
    with open(output_file, "w") as f:
        json.dump(schema, f, indent=2)

    print(f"✓ Generated schema: {output_file.name}")


def generate_enum_schema(enum_type: Type[Enum], output_dir: Path) -> None:
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


def generate_all_schemas() -> None:
    """Generate JSON Schemas for all API models."""
    OUTPUT_DIR.mkdir(exist_ok=True)

    print(f"Generating schemas in {OUTPUT_DIR.absolute()}...\n")

    # Pydantic models (direct generation)
    pydantic_models: list[Type[BaseModel]] = [
        UserProfile,
        Message,
        Topic,
        Session,
        TherapyPlan,
        DomainKnowledgeChunk,
        WorkflowNextActionRequest,
        WorkflowDisplayAction,
        WorkflowNextActionResponse,
        EmotionalSummary,
        KeyTheme,
        RecommendedApproach,
        SessionBriefing,
    ]

    # Enums
    enums: list[Type[Enum]] = [
        UserStatus,
        WorkflowState,
        WorkflowEvent,
        BriefingStatus,
    ]

    # Dataclasses (need conversion)
    dataclasses_to_convert = [
        (AgentResponse, "AgentResponse"),
        (SessionInfo, "SessionInfo"),
        (TherapyStyleRecommendation, "TherapyStyleRecommendation"),
    ]

    print("Generating Pydantic model schemas...")
    for model in pydantic_models:
        try:
            generate_schema(model, OUTPUT_DIR)
        except Exception as e:
            print(f"✗ Failed to generate schema for {model.__name__}: {e}")

    print("\nGenerating enum schemas...")
    for enum_type in enums:
        try:
            generate_enum_schema(enum_type, OUTPUT_DIR)
        except Exception as e:
            print(f"✗ Failed to generate enum schema for {enum_type.__name__}: {e}")

    print("\nGenerating dataclass schemas...")
    for dataclass_type, name in dataclasses_to_convert:
        try:
            # Convert dataclass to Pydantic model
            pydantic_model = dataclass_to_pydantic(dataclass_type)
            generate_schema(pydantic_model, OUTPUT_DIR, schema_name=name)
        except Exception as e:
            print(f"✗ Failed to generate schema for {name}: {e}")

    # Generate index file
    all_models = (
        [m.__name__ for m in pydantic_models]
        + [e.__name__ for e in enums]
        + [name for _, name in dataclasses_to_convert]
    )

    index = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "Psychoanalyst API Schema Index",
        "description": "Index of all API data models",
        "version": "1.0.0",
        "generated_at": datetime.now().isoformat(),
        "models": sorted(all_models),
    }

    with open(OUTPUT_DIR / "index.json", "w") as f:
        json.dump(index, f, indent=2)

    print(f"\n{'='*60}")
    print(f"✓ Successfully generated {len(all_models)} schemas")
    print(f"  Output directory: {OUTPUT_DIR.absolute()}")
    print(f"  Index file: index.json")
    print(f"{'='*60}")


if __name__ == "__main__":
    try:
        generate_all_schemas()
    except Exception as e:
        print(f"\n✗ Schema generation failed: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)
