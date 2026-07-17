#!/usr/bin/env python3
"""Semantic cutover checks for Phase 6 legacy deletion.

Transitional validator: deleted after Phase 6 final cleanup and Phase 7 tooling
finalization. See docs/refactor/deletion-inventory.md for sunset notes.
"""

from __future__ import annotations

import argparse
import ast
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path("docs/refactor/deletion-manifest.toml")
WORKFLOW_EDIT_PATH = ".github/workflows/release-candidate-validation.yml"

STAGE_MANIFEST_STATUS = {
    "pre-cutover": "active",
    "cutover": "active",
    "final": "completed",
}

OWNERS = frozenset({"6A", "6B", "6C", "6D"})
KINDS = frozenset({"filesystem", "make_target", "workflow", "workflow_edit"})
ACTIONS = frozenset(
    {"delete", "port_then_delete", "reimplement_then_delete", "retain", "edit"}
)
ITEM_STATUSES = frozenset({"planned", "in_progress", "complete"})
CONFIDENCES = frozenset({"confirmed", "likely", "discovery-needed"})

ITEM_REQUIRED = frozenset(
    {
        "path",
        "kind",
        "action",
        "owner_pr",
        "status",
        "confidence",
        "responsibility",
    }
)
ITEM_OPTIONAL = frozenset(
    {
        "blocker",
        "replacements",
        "evidence",
        "aggregate",
        "requires_explicit_test_target_reference",
    }
)
ITEM_ALLOWED = ITEM_REQUIRED | ITEM_OPTIONAL

KIND_ACTIONS: dict[str, frozenset[str]] = {
    "filesystem": ACTIONS,
    "make_target": frozenset({"delete", "retain"}),
    "workflow": frozenset({"delete", "retain"}),
    "workflow_edit": frozenset({"edit"}),
}

LEGACY_GATE_STEPS = frozenset(
    {
        "lint",
        "validate-docs",
        "validate-schemas",
        "validate-generated-contracts",
        "validate-architecture",
        "test-validate",
        "validate_refactor_phase_5.py",
        "characterization-smoke",
        "probe-console-deterministic",
    }
)
TARGET_GATE_STEPS = frozenset(
    {
        "lint",
        "validate-docs",
        "test-target",
        "validate_refactor_phase_6.py",
        "validate_refactor_phase_5.py",
        "probe-console-v1-deterministic",
    }
)
LEGACY_ONLY_STEPS = frozenset(
    {
        "test-validate",
        "characterization-smoke",
        "characterization-full",
        "probe-console-deterministic",
        "probe-console-intake-notes",
        "validate-schemas",
        "validate-generated-contracts",
        "validate-architecture",
    }
)
WORKFLOW_LEGACY_TARGETS = frozenset(
    {
        "characterization-smoke",
        "probe-console-deterministic",
        "test-validate",
        "validate-schemas",
        "validate-generated-contracts",
        "validate-architecture",
    }
)

FORBIDDEN_IMPORT_ROOTS = (
    "psychoanalyst_app",
    "trio",
    "pytest_trio",
    "quart",
    "quart_trio",
    "quart_cors",
    "trio_websocket",
    "hypercorn",
)
FORBIDDEN_DEP_PREFIXES = FORBIDDEN_IMPORT_ROOTS + ("langchain",)

LEGACY_RUNTIME = "psychoanalyst_app.server"
TARGET_RUNTIME = "jung-api"
LEGACY_ENTRY_POINTS = frozenset({"psychoanalyst-server", "psychoanalyst-db"})
TARGET_ENTRY_CUTOVER = frozenset({"jung-api", "jung-console"})
TARGET_ENTRY_FINAL = TARGET_ENTRY_CUTOVER | frozenset({"jung-db"})

MAKE_TARGET_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True, slots=True)
class ManifestItem:
    path: str
    kind: str
    action: str
    owner_pr: str
    status: str
    confidence: str
    responsibility: str
    blocker: str | None = None
    replacements: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    aggregate: bool = False
    requires_explicit_test_target_reference: bool = False


@dataclass(frozen=True, slots=True)
class Manifest:
    status: str
    items: tuple[ManifestItem, ...]


@dataclass(frozen=True, slots=True)
class RecipeCommand:
    text: str
    ignored_failure: bool


def _norm_fs_path(path: str) -> str:
    cleaned = path.strip().replace("\\", "/").replace("//", "/")
    had_trailing = path.endswith("/") or path.endswith("\\")
    cleaned = cleaned.rstrip("/")
    if had_trailing and cleaned:
        return f"{cleaned}/"
    return cleaned


def _norm_pkg_name(name: str) -> str:
    return name.lower().replace("-", "_").replace(".", "_")


def _non_empty_string(
    value: Any, label: str, index: int
) -> tuple[str | None, str | None]:
    if not isinstance(value, str):
        return None, f"item {index}: {label} must be a string"
    stripped = value.strip()
    if not stripped:
        return None, f"item {index}: {label} must be non-empty"
    return stripped, None


def _parse_string_list(
    value: Any, label: str, index: int
) -> tuple[tuple[str, ...] | None, list[str]]:
    if value is None:
        return (), []
    if not isinstance(value, list):
        return None, [f"item {index}: {label} must be a list"]
    errors: list[str] = []
    items: list[str] = []
    seen: set[str] = set()
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            errors.append(f"item {index}: {label} entries must be non-empty strings")
            continue
        normalized = entry.strip()
        if normalized in seen:
            errors.append(f"item {index}: duplicate {label} entry {normalized!r}")
        seen.add(normalized)
        items.append(normalized)
    return tuple(items), errors


def _validate_repo_path(path: str, kind: str, index: int) -> list[str]:
    errors: list[str] = []
    if ".." in path.split("/"):
        errors.append(f"item {index}: path must not contain ..: {path!r}")
    if kind in {"workflow", "workflow_edit"}:
        if not path.startswith(".github/workflows/"):
            errors.append(
                f"item {index}: workflow path must be under "
                f".github/workflows/: {path!r}"
            )
    elif kind == "make_target":
        if not MAKE_TARGET_RE.match(path):
            errors.append(f"item {index}: invalid make target name: {path!r}")
    return errors


def parse_manifest(root: Path) -> tuple[Manifest | None, list[str]]:
    path = root / MANIFEST_PATH
    if not path.is_file():
        return None, [f"missing manifest: {MANIFEST_PATH}"]
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        return None, [f"invalid manifest TOML: {exc}"]

    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("manifest schema_version must be 1")
    status = data.get("status")
    if status not in {"active", "completed"}:
        errors.append("manifest status must be active or completed")

    raw_items = data.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        errors.append("manifest must define at least one item")
        return None, errors

    items: list[ManifestItem] = []
    seen_keys: set[tuple[str, str]] = set()
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            errors.append(f"item {index}: must be a table")
            continue
        unknown = set(raw) - ITEM_ALLOWED
        if unknown:
            errors.append(
                f"item {index}: unknown field(s): {', '.join(sorted(unknown))}"
            )
        missing = ITEM_REQUIRED - set(raw)
        if missing:
            errors.append(
                f"item {index}: missing required field(s): {', '.join(sorted(missing))}"
            )
            continue

        path, err = _non_empty_string(raw["path"], "path", index)
        if err:
            errors.append(err)
            continue
        kind = raw["kind"]
        action = raw["action"]
        owner_pr = raw["owner_pr"]
        item_status = raw["status"]
        confidence = raw["confidence"]
        responsibility, resp_err = _non_empty_string(
            raw["responsibility"], "responsibility", index
        )
        if resp_err:
            errors.append(resp_err)
            continue

        if kind not in KINDS:
            errors.append(f"item {index}: invalid kind {kind!r}")
        if action not in ACTIONS:
            errors.append(f"item {index}: invalid action {action!r}")
        if owner_pr not in OWNERS:
            errors.append(f"item {index}: owner_pr must be one of 6A-6D")
        if item_status not in ITEM_STATUSES:
            errors.append(f"item {index}: invalid status {item_status!r}")
        if confidence not in CONFIDENCES:
            errors.append(f"item {index}: invalid confidence {confidence!r}")
        if kind in KIND_ACTIONS and action not in KIND_ACTIONS[kind]:
            errors.append(f"item {index}: action {action!r} invalid for kind {kind!r}")

        blocker = None
        if "blocker" in raw:
            blocker, b_err = _non_empty_string(raw["blocker"], "blocker", index)
            if b_err:
                errors.append(b_err)

        replacements, rep_errors = _parse_string_list(
            raw.get("replacements"), "replacements", index
        )
        errors.extend(rep_errors)
        evidence, ev_errors = _parse_string_list(raw.get("evidence"), "evidence", index)
        errors.extend(ev_errors)

        aggregate = False
        if "aggregate" in raw:
            if raw["aggregate"] is not True:
                errors.append(f"item {index}: aggregate must be omitted or true")
            else:
                aggregate = True
                if kind != "filesystem" or action != "delete":
                    errors.append(
                        f"item {index}: aggregate rows require filesystem delete"
                    )

        requires_ref = False
        if raw.get("requires_explicit_test_target_reference"):
            if action != "retain":
                errors.append(
                    f"item {index}: requires_explicit_test_target_reference "
                    "only valid for retain"
                )
            requires_ref = True

        if action in {"port_then_delete", "reimplement_then_delete"}:
            if not replacements:
                errors.append(f"item {index}: {action} requires replacements")

        if kind == "workflow_edit":
            if path != WORKFLOW_EDIT_PATH:
                errors.append(
                    f"item {index}: workflow_edit path must be {WORKFLOW_EDIT_PATH!r}"
                )

        if item_status == "complete" and confidence != "confirmed":
            errors.append(
                f"item {index}: complete items must have confidence = confirmed"
            )

        norm_path = path if kind != "filesystem" else _norm_fs_path(path)
        key = (kind, norm_path)
        if key in seen_keys:
            errors.append(f"item {index}: duplicate kind/path {kind} {path!r}")
        seen_keys.add(key)
        errors.extend(_validate_repo_path(norm_path, kind, index))

        items.append(
            ManifestItem(
                path=norm_path,
                kind=kind,
                action=action,
                owner_pr=owner_pr,
                status=item_status,
                confidence=confidence,
                responsibility=responsibility,
                blocker=blocker,
                replacements=replacements or (),
                evidence=evidence or (),
                aggregate=aggregate,
                requires_explicit_test_target_reference=requires_ref,
            )
        )

    if errors:
        return None, errors
    return Manifest(status=status, items=tuple(items)), []


def _manifest_status_for_stage(stage: str, manifest: Manifest) -> list[str]:
    expected = STAGE_MANIFEST_STATUS[stage]
    if manifest.status != expected:
        return [
            f"manifest status must be {expected!r} for stage {stage!r}, "
            f"got {manifest.status!r}"
        ]
    return []


def _final_manifest_closure(manifest: Manifest) -> list[str]:
    errors: list[str] = []
    for item in manifest.items:
        if item.status != "complete":
            errors.append(f"manifest item not complete: {item.path}")
        if item.confidence == "discovery-needed":
            errors.append(f"discovery-needed item remains: {item.path}")
    return errors


def _parse_makefile(root: Path) -> dict[str, list[RecipeCommand]]:
    text = (root / "Makefile").read_text(encoding="utf-8")
    recipes: dict[str, list[RecipeCommand]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        if line and not line.startswith("\t") and ":" in line:
            target = line.split(":", 1)[0].strip()
            if target and not target.startswith("."):
                current = target
                recipes.setdefault(current, [])
            continue
        if line.startswith("\t") and current is not None:
            body = line[1:].strip()
            if not body or body.startswith("#"):
                continue
            if body.endswith("\\"):
                body = body[:-1].strip()
            ignored = body.startswith("-")
            if ignored:
                body = body[1:].strip()
            recipes[current].append(
                RecipeCommand(text=body, ignored_failure=ignored)
            )
    return recipes


def _target_support_test_paths(makefile_text: str) -> set[str]:
    match = re.search(
        r"^TARGET_SUPPORT_TESTS\s*:=\s*(.*?)(?=^\S|\Z)",
        makefile_text,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        return set()
    paths: set[str] = set()
    for line in match.group(1).splitlines():
        stripped = line.strip().rstrip("\\").strip()
        if stripped and not stripped.startswith("#"):
            paths.add(stripped)
    return paths


def _test_target_references_path(root: Path, path: str) -> bool:
    makefile_text = (root / "Makefile").read_text(encoding="utf-8")
    if path in _target_support_test_paths(makefile_text):
        return True
    recipes = _parse_makefile(root)
    return _recipe_has_exact_path(recipes.get("test-target", []), path)


def _tokenize_command(text: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    for char in text:
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char.isspace() and not in_single and not in_double:
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(char)
    if current:
        tokens.append("".join(current))
    return tokens


def _is_echo_or_printf(tokens: list[str]) -> bool:
    return bool(tokens) and tokens[0] in {"echo", "printf", "@echo", "@printf"}


def _invoked_make_targets(commands: list[RecipeCommand]) -> set[str]:
    found: set[str] = set()
    for command in commands:
        if command.ignored_failure:
            continue
        tokens = _tokenize_command(command.text.split("#", 1)[0].strip())
        if _is_echo_or_printf(tokens):
            continue
        for index, token in enumerate(tokens):
            if token in {"$(MAKE)", "make", "${MAKE}"} and index + 1 < len(tokens):
                found.add(tokens[index + 1])
    return found


def _invoked_scripts(commands: list[RecipeCommand]) -> set[str]:
    found: set[str] = set()
    for command in commands:
        if command.ignored_failure:
            continue
        tokens = _tokenize_command(command.text.split("#", 1)[0].strip())
        if _is_echo_or_printf(tokens):
            continue
        for index, token in enumerate(tokens):
            if token.endswith("python") or token.endswith("python3"):
                if index + 1 < len(tokens):
                    found.add(tokens[index + 1])
    return found


def _recipe_has_exact_path(commands: list[RecipeCommand], path: str) -> bool:
    for command in commands:
        if command.ignored_failure:
            continue
        tokens = _tokenize_command(command.text.split("#", 1)[0].strip())
        if _is_echo_or_printf(tokens):
            continue
        if path in tokens:
            return True
    return False


def _gate_errors(
    recipes: dict[str, list[RecipeCommand]],
    target: str,
    required: frozenset[str],
    forbidden: frozenset[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    if target not in recipes:
        return [f"missing Makefile target: {target}"]
    commands = recipes[target]
    make_targets = _invoked_make_targets(commands)
    scripts = _invoked_scripts(commands)
    searchable = make_targets | scripts
    for step in required:
        if step.endswith(".py"):
            if not any(step in script for script in scripts):
                errors.append(f"{target} must invoke {step}")
        elif step not in searchable:
            errors.append(f"{target} must invoke {step}")
    if forbidden:
        for step in forbidden:
            if step in searchable:
                errors.append(f"{target} must not invoke {step}")
    return errors


def _validate_gates(root: Path, stage: str) -> list[str]:
    recipes = _parse_makefile(root)
    errors: list[str] = []
    if stage == "pre-cutover":
        errors.extend(
            _gate_errors(recipes, "finalization-check", LEGACY_GATE_STEPS)
        )
        errors.extend(
            _gate_errors(recipes, "finalization-check-target", TARGET_GATE_STEPS)
        )
    else:
        errors.extend(
            _gate_errors(
                recipes,
                "finalization-check",
                TARGET_GATE_STEPS,
                LEGACY_ONLY_STEPS,
            )
        )
    return errors


def _extract_yaml_scalar(block: str, key: str) -> str | None:
    pattern = re.compile(
        rf"^\s*{re.escape(key)}:\s*(.+?)\s*$",
        re.MULTILINE,
    )
    match = pattern.search(block)
    if not match:
        return None
    value = match.group(1).strip()
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    return value


def _extract_compose_service_block(compose: str, service: str) -> str | None:
    lines = compose.splitlines()
    start = None
    for index, line in enumerate(lines):
        if re.match(rf"^\s*{re.escape(service)}:\s*$", line):
            start = index
            break
    if start is None:
        return None
    block: list[str] = [lines[start]]
    base_indent = len(lines[start]) - len(lines[start].lstrip())
    for line in lines[start + 1 :]:
        if not line.strip():
            block.append(line)
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= base_indent:
            break
        block.append(line)
    return "\n".join(block)


def _extract_compose_command(block: str) -> str | None:
    if re.search(r"^\s*command:\s*$", block, re.MULTILINE):
        values = re.findall(r"^\s*-\s+(.+?)\s*$", block, re.MULTILINE)
        if not values:
            return None
        return values[-1].strip().strip("'\"")
    scalar = _extract_yaml_scalar(block, "command")
    if scalar is None:
        return None
    return scalar.strip().strip("'\"")


def _extract_compose_build_target(block: str) -> str | None:
    build_block_match = re.search(
        r"^\s*build:\s*$([\s\S]*?)(?=^\s*\w|\Z)",
        block,
        re.MULTILINE,
    )
    if not build_block_match:
        return None
    return _extract_yaml_scalar(build_block_match.group(1), "target")


def _dockerfile_stages(dockerfile: str) -> list[tuple[str, str]]:
    stages: list[tuple[str, str]] = []
    current_name = "final"
    current_lines: list[str] = []
    for line in dockerfile.splitlines():
        stage_match = re.match(r"^FROM\b.*\sAS\s+(\S+)", line, re.IGNORECASE)
        if stage_match:
            if current_lines:
                stages.append((current_name, "\n".join(current_lines)))
            current_name = stage_match.group(1)
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_lines:
        stages.append((current_name, "\n".join(current_lines)))
    return stages


def _dockerfile_cmd(stage_text: str) -> str | None:
    matches = list(
        re.finditer(r'^\s*CMD\s+(\[[^\]]+\]|.+?)\s*$', stage_text, re.MULTILINE)
    )
    if not matches:
        return None
    raw = matches[-1].group(1).strip()
    if raw.startswith("["):
        parts = re.findall(r'"([^"]+)"', raw)
        return parts[-1] if parts else None
    return raw.strip().strip("'\"")


def _runtime_token(command: str | None) -> str | None:
    if command is None:
        return None
    if command.startswith("python -m "):
        return command.split("python -m ", 1)[1].strip()
    if command.startswith("python3 -m "):
        return command.split("python3 -m ", 1)[1].strip()
    return command.strip()


def _expected_runtime(stage: str) -> str:
    return LEGACY_RUNTIME if stage == "pre-cutover" else TARGET_RUNTIME


def _runtime_matches(token: str | None, expected: str) -> bool:
    if token is None:
        return False
    if expected == LEGACY_RUNTIME:
        return token == LEGACY_RUNTIME or token.endswith("psychoanalyst_app.server")
    return (
        token == TARGET_RUNTIME
        or token.endswith("jung.api.app:cli")
        or token == "jung-api"
    )


def _extract_compose_api_command(compose: str) -> str | None:
    api_block = _extract_compose_service_block(compose, "api")
    if api_block is not None:
        command = _extract_compose_command(api_block)
        if command is not None:
            return command
    anchor_match = re.search(
        r"^x-api-base:.*?(?=^x-|\nservices:)",
        compose,
        re.MULTILINE | re.DOTALL,
    )
    if anchor_match is not None:
        return _extract_compose_command(anchor_match.group(0))
    return None


def _validate_runtime(root: Path, stage: str) -> list[str]:
    errors: list[str] = []
    expected = _expected_runtime(stage)
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    api_block = _extract_compose_service_block(compose, "api")
    if api_block is None:
        return ["docker-compose.yml missing services.api block"]

    build_target = _extract_compose_build_target(api_block)
    if build_target is None:
        anchor_match = re.search(
            r"^x-api-base:.*?(?=^x-|\nservices:)",
            compose,
            re.MULTILINE | re.DOTALL,
        )
        if anchor_match is not None:
            build_target = _extract_compose_build_target(anchor_match.group(0))
    stages = _dockerfile_stages(dockerfile)
    stage_name = build_target or (stages[-1][0] if stages else None)
    stage_text = next(
        (text for name, text in stages if name == stage_name),
        stages[-1][1],
    )
    docker_cmd = _runtime_token(_dockerfile_cmd(stage_text))
    if not _runtime_matches(docker_cmd, expected):
        errors.append(
            f"Dockerfile stage {stage_name!r} CMD must select "
            f"{expected!r}, got {docker_cmd!r}"
        )

    compose_cmd = _extract_compose_api_command(compose)
    if compose_cmd is not None:
        if not _runtime_matches(_runtime_token(compose_cmd), expected):
            errors.append(
                f"docker-compose api command must select {expected!r}, "
                f"got {compose_cmd!r}"
            )
    elif not _runtime_matches(docker_cmd, expected):
        errors.append("effective api runtime must select expected command")

    if stage == "pre-cutover":
        if LEGACY_RUNTIME not in compose and "psychoanalyst_app.server" not in compose:
            if compose_cmd is None and docker_cmd is None:
                errors.append("legacy runtime not configured for api service")
    return errors


def _path_exists(root: Path, item: ManifestItem) -> bool:
    if item.kind == "make_target":
        recipes = _parse_makefile(root)
        return item.path in recipes
    return (root / item.path).exists() or (root / item.path.rstrip("/")).is_symlink()


def _path_absent(root: Path, item: ManifestItem) -> bool:
    if item.kind == "make_target":
        return item.path not in _parse_makefile(root)
    path = root / item.path.rstrip("/")
    return not path.exists() and not path.is_symlink()


def _paths_exist(root: Path, paths: tuple[str, ...]) -> list[str]:
    errors: list[str] = []
    for relative in paths:
        candidate = root / relative
        if not candidate.exists():
            errors.append(f"missing path: {relative}")
    return errors


def _validate_item_complete(root: Path, item: ManifestItem) -> list[str]:
    errors: list[str] = []
    if item.action in {"delete", "port_then_delete", "reimplement_then_delete"}:
        errors.extend(_paths_exist(root, item.replacements))
        errors.extend(_paths_exist(root, item.evidence))
        if not _path_absent(root, item):
            errors.append(f"complete item still present: {item.path}")
    elif item.action == "retain":
        if not _path_exists(root, item):
            errors.append(f"retained path missing: {item.path}")
        if item.requires_explicit_test_target_reference:
            if not _test_target_references_path(root, item.path):
                errors.append(
                    f"retained test not referenced in test-target recipe: {item.path}"
                )
    elif item.action == "edit":
        errors.extend(_validate_workflow_edit(root, complete=True))
    return errors


def _extract_workflow_job_blocks(workflow: str) -> dict[str, str]:
    jobs: dict[str, str] = {}
    match = re.search(r"^\s*jobs:\s*$", workflow, re.MULTILINE)
    if not match:
        return jobs
    lines = workflow.splitlines()
    start = workflow[: match.start()].count("\n")
    index = start + 1
    while index < len(lines):
        line = lines[index]
        job_match = re.match(r"^  (\S+):\s*$", line)
        if not job_match:
            index += 1
            continue
        name = job_match.group(1)
        block = [line]
        index += 1
        while index < len(lines):
            next_line = lines[index]
            if re.match(r"^  \S+:\s*$", next_line):
                break
            block.append(next_line)
            index += 1
        jobs[name] = "\n".join(block)
    return jobs


def _job_invokes_make_target(job_block: str, make_target: str) -> bool:
    for line in job_block.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "run:" in stripped and make_target in stripped:
            tokens = _tokenize_command(stripped.split("run:", 1)[1].strip())
            if make_target in tokens:
                return True
    return False


def _validate_workflow_edit(root: Path, *, complete: bool) -> list[str]:
    path = root / WORKFLOW_EDIT_PATH
    if not path.is_file():
        return [f"missing workflow edit file: {WORKFLOW_EDIT_PATH}"]
    workflow = path.read_text(encoding="utf-8")
    jobs = _extract_workflow_job_blocks(workflow)
    errors: list[str] = []
    if complete:
        if "phase-1-evidence" in jobs:
            errors.append("workflow edit must remove phase-1-evidence job")
        finalization_jobs = [
            name
            for name, block in jobs.items()
            if _job_invokes_make_target(block, "finalization-check")
        ]
        if len(finalization_jobs) != 1:
            errors.append(
                "workflow edit must have exactly one job invoking "
                "make finalization-check"
            )
        for name, block in jobs.items():
            if _job_invokes_make_target(block, "finalization-check-target"):
                errors.append(
                    f"workflow job {name} must not invoke "
                    "make finalization-check-target"
                )
            for legacy in WORKFLOW_LEGACY_TARGETS:
                if _job_invokes_make_target(block, legacy):
                    errors.append(
                        f"workflow job {name} must not invoke legacy target {legacy}"
                    )
    return errors


def _validate_complete_items(root: Path, manifest: Manifest) -> list[str]:
    errors: list[str] = []
    for item in manifest.items:
        if item.status == "complete":
            errors.extend(_validate_item_complete(root, item))
    return errors


def _validate_entry_points(root: Path, stage: str) -> list[str]:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = pyproject.get("project", {}).get("scripts", {})
    if not isinstance(scripts, dict):
        return ["pyproject.toml missing project.scripts"]
    names = set(scripts)
    errors: list[str] = []
    if stage in {"cutover", "final"}:
        required = TARGET_ENTRY_CUTOVER if stage == "cutover" else TARGET_ENTRY_FINAL
        for entry in required:
            if entry not in names:
                errors.append(f"missing target entry point: {entry}")
        for legacy in LEGACY_ENTRY_POINTS:
            if legacy in names:
                errors.append(f"legacy entry point still present: {legacy}")
    return errors


def _collect_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def _forbidden_import(module: str) -> str | None:
    root = module.split(".")[0]
    if root in FORBIDDEN_IMPORT_ROOTS:
        return root
    if root.startswith("langchain"):
        return root
    return None


def _validate_import_closure(root: Path) -> list[str]:
    errors: list[str] = []
    for base in (root / "src", root / "scripts", root / "tests"):
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            for module in _collect_imports(path):
                forbidden = _forbidden_import(module)
                if forbidden:
                    rel = path.relative_to(root)
                    errors.append(f"{rel} imports forbidden module {module}")
    return errors


def _read_requirement_names(requirements_path: Path) -> list[str]:
    names: list[str] = []
    if not requirements_path.is_file():
        return names
    for line in requirements_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        token = re.split(r"[<>=!~\[]", stripped, maxsplit=1)[0].strip()
        if token:
            names.append(_norm_pkg_name(token))
    return names


def _validate_dependency_closure(root: Path) -> list[str]:
    errors: list[str] = []
    names: set[str] = set()
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    for section in ("dependencies",):
        deps = pyproject.get("project", {}).get(section, [])
        if isinstance(deps, list):
            for dep in deps:
                if isinstance(dep, str):
                    names.add(_norm_pkg_name(dep.split(";")[0].strip()))
    for req_name in ("requirements.txt", "requirements-dev.txt"):
        names.update(_read_requirement_names(root / req_name))
    for forbidden in FORBIDDEN_DEP_PREFIXES:
        normalized = _norm_pkg_name(forbidden)
        matches = [
            name
            for name in names
            if name == normalized or name.startswith(normalized)
        ]
        if matches:
            errors.append(f"forbidden dependency remains: {forbidden}")
    package_data = (
        pyproject.get("tool", {}).get("setuptools", {}).get("package-data", {})
    )
    if isinstance(package_data, dict) and "psychoanalyst_app" in package_data:
        errors.append("pyproject package-data still references psychoanalyst_app")
    return errors


def validate_pre_cutover(root: Path) -> list[str]:
    manifest, errors = parse_manifest(root)
    if manifest is None:
        return errors
    errors.extend(_manifest_status_for_stage("pre-cutover", manifest))
    errors.extend(_validate_gates(root, "pre-cutover"))
    errors.extend(_validate_runtime(root, "pre-cutover"))
    errors.extend(_validate_complete_items(root, manifest))
    return errors


def validate_cutover(root: Path) -> list[str]:
    manifest, errors = parse_manifest(root)
    if manifest is None:
        return errors
    errors.extend(_manifest_status_for_stage("cutover", manifest))
    errors.extend(_validate_gates(root, "cutover"))
    errors.extend(_validate_runtime(root, "cutover"))
    errors.extend(_validate_entry_points(root, "cutover"))
    errors.extend(_validate_complete_items(root, manifest))
    return errors


def validate_final(root: Path) -> list[str]:
    manifest, errors = parse_manifest(root)
    if manifest is None:
        return errors
    errors.extend(_manifest_status_for_stage("final", manifest))
    errors.extend(_final_manifest_closure(manifest))
    errors.extend(_validate_gates(root, "final"))
    errors.extend(_validate_runtime(root, "final"))
    errors.extend(_validate_entry_points(root, "final"))
    errors.extend(_validate_complete_items(root, manifest))
    for item in manifest.items:
        if (
            item.action != "edit"
            and item.status == "complete"
            and not _path_absent(root, item)
        ):
            if item.action in {"delete", "port_then_delete", "reimplement_then_delete"}:
                errors.append(f"deletion item still present: {item.path}")
            elif item.kind in {"make_target", "workflow"} and item.action == "delete":
                errors.append(f"deletion item still present: {item.path}")
    errors.extend(_validate_import_closure(root))
    errors.extend(_validate_dependency_closure(root))
    return errors


def validate(root: Path | None = None, *, stage: str = "pre-cutover") -> list[str]:
    resolved = (root or REPO_ROOT).resolve()
    if stage == "pre-cutover":
        return validate_pre_cutover(resolved)
    if stage == "cutover":
        return validate_cutover(resolved)
    if stage == "final":
        return validate_final(resolved)
    return [f"unknown stage: {stage}"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        choices=("pre-cutover", "cutover", "final"),
        required=True,
    )
    args = parser.parse_args()
    errors = validate(stage=args.stage)
    if errors:
        print(f"Phase 6 refactor validation failed ({args.stage}):")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print(f"Phase 6 refactor validation passed ({args.stage}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
