#!/usr/bin/env python3
"""Produce deterministic source metrics for the refactor baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

EXCLUDED = {".git", ".venv", "__pycache__", "data", "schemas"}


def _python_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.py")
        if not set(path.relative_to(root).parts) & EXCLUDED
    )


def _lines(paths: list[Path]) -> tuple[int, int]:
    physical = code = 0
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            physical += 1
            if line.strip() and not line.lstrip().startswith("#"):
                code += 1
    return physical, code


def measure(root: Path) -> dict[str, int]:
    source = _python_files(root / "src")
    tests = _python_files(root / "tests")
    all_files = source + tests
    content = {path: path.read_text(encoding="utf-8") for path in all_files}
    source_physical, source_code = _lines(source)
    test_physical, test_code = _lines(tests)
    return {
        "production_python_files": len(source),
        "production_python_physical_loc": source_physical,
        "production_python_code_loc": source_code,
        "test_python_files": len(tests),
        "test_python_physical_loc": test_physical,
        "test_python_code_loc": test_code,
        "trio_importing_production_modules": sum(
            "import trio" in content[p] for p in source
        ),
        "service_container_importing_modules": sum(
            "service_container" in content[p] for p in source
        ),
        "pydantic_model_candidates": sum("BaseModel" in content[p] for p in source),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args()
    metrics = measure(args.root.resolve())
    if args.format == "json":
        print(json.dumps(metrics, indent=2, sort_keys=True))
    else:
        print("# Baseline Metrics\n\n| Metric | Value |\n|---|---:|")
        for key, value in metrics.items():
            print(f"| {key} | {value} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
