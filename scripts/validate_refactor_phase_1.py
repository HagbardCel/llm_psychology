#!/usr/bin/env python3
"""Validate the discoverable Phase 1 planning artifacts."""

from pathlib import Path

REQUIRED = [
    "docs/refactor/api-v1-contract.md", "docs/refactor/workflow-specification.md",
    "docs/refactor/deletion-inventory.md", "docs/refactor/baseline-metrics.md",
    *[
        f"docs/adr/000{i}-{name}.md"
        for i, name in [
            (1, "single-user-api-modular-monolith"),
            (2, "asyncio-fastapi-runtime"),
            (3, "workflow-stage-command-operation-model"),
            (4, "single-sqlite-store-and-schema-reset"),
            (5, "phase-processors-and-llm-gateway"),
        ]
    ],
]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    missing = [item for item in REQUIRED if not (root / item).is_file()]
    invalid = [
        item
        for item in REQUIRED
        if (root / item).is_file()
        and not (root / item).read_text(encoding="utf-8").startswith("---\n")
    ]
    if missing or invalid:
        for item in missing:
            print(f"missing: {item}")
        for item in invalid:
            print(f"missing front matter: {item}")
        return 1
    print("Phase 1 refactor artifacts validated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
