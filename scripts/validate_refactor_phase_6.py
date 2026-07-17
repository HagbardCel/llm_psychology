#!/usr/bin/env python3
"""Semantic cutover checks for Phase 6 legacy deletion.

Transitional validator: deleted after Phase 6 final cleanup and Phase 7 tooling
finalization. See docs/refactor/deletion-inventory.md for sunset notes.
"""

from __future__ import annotations

import argparse
import ast
import re
import shlex
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path("docs/refactor/deletion-manifest.toml")
WORKFLOW_EDIT_PATH = ".github/workflows/release-candidate-validation.yml"

TOP_LEVEL_ALLOWED = frozenset({"schema_version", "status", "items"})
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
        "scripts/validate_refactor_phase_5.py",
        "characterization-smoke",
        "probe-console-deterministic",
    }
)
TARGET_GATE_STEPS = frozenset(
    {
        "lint",
        "validate-docs",
        "test-target",
        "scripts/validate_refactor_phase_6.py",
        "scripts/validate_refactor_phase_5.py",
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


@dataclass(frozen=True, slots=True)
class GateRules:
    target: str
    required: frozenset[str]
    forbidden: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class StageRules:
    manifest_status: str
    expected_runtime: str
    gates: tuple[GateRules, ...]
    required_entry_points: frozenset[str]
    forbidden_entry_points: frozenset[str]
    final_closure: bool
    required_complete_items: frozenset[tuple[str, str]] = frozenset()


@dataclass(frozen=True, slots=True)
class RepoContext:
    root: Path
    recipes: dict[str, list[RecipeCommand]]
    makefile_text: str
    pyproject: dict[str, Any]
    compose: str
    dockerfile: str


STAGES: dict[str, StageRules] = {
    "pre-cutover": StageRules(
        manifest_status="active",
        expected_runtime=LEGACY_RUNTIME,
        gates=(
            GateRules("finalization-check", LEGACY_GATE_STEPS),
            GateRules("finalization-check-target", TARGET_GATE_STEPS),
        ),
        required_entry_points=frozenset(),
        forbidden_entry_points=frozenset(),
        final_closure=False,
    ),
    "cutover": StageRules(
        manifest_status="active",
        expected_runtime=TARGET_RUNTIME,
        gates=(
            GateRules(
                "finalization-check",
                TARGET_GATE_STEPS,
                LEGACY_ONLY_STEPS,
            ),
        ),
        required_entry_points=TARGET_ENTRY_CUTOVER,
        forbidden_entry_points=LEGACY_ENTRY_POINTS,
        final_closure=False,
        required_complete_items=frozenset(
            {("workflow_edit", WORKFLOW_EDIT_PATH)}
        ),
    ),
    "final": StageRules(
        manifest_status="completed",
        expected_runtime=TARGET_RUNTIME,
        gates=(
            GateRules(
                "finalization-check",
                TARGET_GATE_STEPS,
                LEGACY_ONLY_STEPS,
            ),
        ),
        required_entry_points=TARGET_ENTRY_FINAL,
        forbidden_entry_points=LEGACY_ENTRY_POINTS,
        final_closure=True,
    ),
}


def _norm_pkg_name(name: str) -> str:
    return name.lower().replace("-", "_").replace(".", "_")


def _norm_fs_path(path: str) -> str:
    cleaned = path.strip().replace("\\", "/")
    while "//" in cleaned:
        cleaned = cleaned.replace("//", "/")
    had_trailing = path.endswith("/") or path.endswith("\\")
    cleaned = cleaned.rstrip("/")
    if had_trailing and cleaned:
        return f"{cleaned}/"
    return cleaned


def _is_absolute_repo_path(path: str) -> bool:
    if PurePosixPath(path).is_absolute():
        return True
    if PureWindowsPath(path).is_absolute():
        return True
    if len(path) >= 2 and path[0].isalpha() and path[1] == ":":
        return True
    if path.startswith("\\\\"):
        return True
    return False


def _validate_repo_relative_path(
    path: str, label: str, index: int, *, item_index: int | None = None
) -> tuple[str | None, list[str]]:
    prefix = f"item {item_index}: " if item_index is not None else ""
    errors: list[str] = []
    if not isinstance(path, str) or not path.strip():
        return None, [f"{prefix}{label} entries must be non-empty strings"]
    normalized = _norm_fs_path(path.strip())
    if not normalized or normalized in {".", "./"}:
        errors.append(f"{prefix}{label} path must not be empty: {path!r}")
        return None, errors
    if _is_absolute_repo_path(normalized):
        errors.append(f"{prefix}{label} path must be repository-relative: {path!r}")
        return None, errors
    if ".." in normalized.split("/"):
        errors.append(f"{prefix}{label} path must not contain ..: {path!r}")
        return None, errors
    return normalized, errors


def _non_empty_string(
    value: Any, label: str, index: int
) -> tuple[str | None, str | None]:
    if not isinstance(value, str):
        return None, f"item {index}: {label} must be a string"
    stripped = value.strip()
    if not stripped:
        return None, f"item {index}: {label} must be non-empty"
    return stripped, None


def _parse_path_list(
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
        normalized, entry_errors = _validate_repo_relative_path(
            entry, label, index, item_index=index
        )
        errors.extend(entry_errors)
        if normalized is None:
            continue
        if normalized in seen:
            errors.append(f"item {index}: duplicate {label} entry {normalized!r}")
        seen.add(normalized)
        items.append(normalized)
    return tuple(items), errors


def _validate_item_path(path: str, kind: str, index: int) -> list[str]:
    errors: list[str] = []
    if kind == "make_target":
        if not MAKE_TARGET_RE.match(path):
            errors.append(f"item {index}: invalid make target name: {path!r}")
        return errors
    normalized, path_errors = _validate_repo_relative_path(path, "path", index)
    if path_errors:
        return path_errors
    assert normalized is not None
    if kind in {"workflow", "workflow_edit"}:
        if not normalized.startswith(".github/workflows/"):
            errors.append(
                f"item {index}: workflow path must be under "
                f".github/workflows/: {path!r}"
            )
    return errors


def _parse_manifest_item(
    raw: dict[str, Any],
    index: int,
    seen_keys: set[tuple[str, str]],
) -> tuple[ManifestItem | None, list[str]]:
    errors: list[str] = []
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
        return None, errors

    path, err = _non_empty_string(raw["path"], "path", index)
    if err:
        return None, [err]
    kind = raw["kind"]
    action = raw["action"]
    owner_pr = raw["owner_pr"]
    item_status = raw["status"]
    confidence = raw["confidence"]
    responsibility, resp_err = _non_empty_string(
        raw["responsibility"], "responsibility", index
    )
    if resp_err:
        return None, [resp_err]

    if not isinstance(kind, str):
        errors.append(f"item {index}: kind must be a string")
    elif kind not in KINDS:
        errors.append(f"item {index}: invalid kind {kind!r}")
    if not isinstance(action, str):
        errors.append(f"item {index}: action must be a string")
    elif action not in ACTIONS:
        errors.append(f"item {index}: invalid action {action!r}")
    if not isinstance(owner_pr, str):
        errors.append(f"item {index}: owner_pr must be a string")
    elif owner_pr not in OWNERS:
        errors.append(f"item {index}: owner_pr must be one of 6A-6D")
    if not isinstance(item_status, str):
        errors.append(f"item {index}: status must be a string")
    elif item_status not in ITEM_STATUSES:
        errors.append(f"item {index}: invalid status {item_status!r}")
    if not isinstance(confidence, str):
        errors.append(f"item {index}: confidence must be a string")
    elif confidence not in CONFIDENCES:
        errors.append(f"item {index}: invalid confidence {confidence!r}")
    if (
        isinstance(kind, str)
        and isinstance(action, str)
        and kind in KIND_ACTIONS
        and action not in KIND_ACTIONS[kind]
    ):
        errors.append(f"item {index}: action {action!r} invalid for kind {kind!r}")

    blocker = None
    if "blocker" in raw:
        blocker, b_err = _non_empty_string(raw["blocker"], "blocker", index)
        if b_err:
            errors.append(b_err)

    replacements, rep_errors = _parse_path_list(
        raw.get("replacements"), "replacements", index
    )
    errors.extend(rep_errors)
    evidence, ev_errors = _parse_path_list(raw.get("evidence"), "evidence", index)
    errors.extend(ev_errors)

    aggregate = False
    if "aggregate" in raw:
        if raw["aggregate"] is not True:
            errors.append(f"item {index}: aggregate must be omitted or true")
        else:
            aggregate = True
            if kind != "filesystem" or action != "delete":
                errors.append(f"item {index}: aggregate rows require filesystem delete")

    requires_ref = False
    if "requires_explicit_test_target_reference" in raw:
        if raw["requires_explicit_test_target_reference"] is not True:
            errors.append(
                f"item {index}: requires_explicit_test_target_reference "
                "must be omitted or true"
            )
        else:
            if action != "retain":
                errors.append(
                    f"item {index}: requires_explicit_test_target_reference "
                    "only valid for retain"
                )
            requires_ref = True

    replacement_optional = (
        isinstance(action, str)
        and action in {"port_then_delete", "reimplement_then_delete"}
        and isinstance(item_status, str)
        and item_status == "planned"
        and isinstance(confidence, str)
        and confidence == "discovery-needed"
    )
    if (
        isinstance(action, str)
        and action in {"port_then_delete", "reimplement_then_delete"}
        and not replacement_optional
        and not replacements
    ):
        errors.append(f"item {index}: {action} requires replacements")

    if kind == "workflow_edit" and path != WORKFLOW_EDIT_PATH:
        errors.append(
            f"item {index}: workflow_edit path must be {WORKFLOW_EDIT_PATH!r}"
        )

    if item_status == "complete" and confidence != "confirmed":
        errors.append(f"item {index}: complete items must have confidence = confirmed")

    norm_path = path if kind != "filesystem" else _norm_fs_path(path)
    key = (kind, norm_path)
    if key in seen_keys:
        errors.append(f"item {index}: duplicate kind/path {kind} {path!r}")
    seen_keys.add(key)
    errors.extend(_validate_item_path(norm_path, kind, index))

    if errors:
        return None, errors
    return (
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
        ),
        [],
    )


def parse_manifest(root: Path) -> tuple[Manifest | None, list[str]]:
    path = root / MANIFEST_PATH
    if not path.is_file():
        return None, [f"missing manifest: {MANIFEST_PATH}"]
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        return None, [f"invalid manifest TOML: {exc}"]

    errors: list[str] = []
    unknown_top = set(data) - TOP_LEVEL_ALLOWED
    if unknown_top:
        errors.append(
            f"manifest has unknown top-level field(s): {', '.join(sorted(unknown_top))}"
        )
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
        item, item_errors = _parse_manifest_item(raw, index, seen_keys)
        errors.extend(item_errors)
        if item is not None:
            items.append(item)

    if errors:
        return None, errors
    return Manifest(status=status, items=tuple(items)), []


def _load_repo_context(root: Path) -> RepoContext:
    makefile_text = (root / "Makefile").read_text(encoding="utf-8")
    return RepoContext(
        root=root,
        recipes=_parse_makefile_text(makefile_text),
        makefile_text=makefile_text,
        pyproject=tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8")),
        compose=(root / "docker-compose.yml").read_text(encoding="utf-8"),
        dockerfile=(root / "Dockerfile").read_text(encoding="utf-8"),
    )


def _parse_makefile_text(text: str) -> dict[str, list[RecipeCommand]]:
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
            paths.add(_norm_fs_path(stripped))
    return paths


def _tokenize_command(text: str) -> list[str]:
    try:
        return shlex.split(text, posix=True)
    except ValueError:
        return text.split()


def _is_echo_or_printf(tokens: list[str]) -> bool:
    return bool(tokens) and tokens[0].lstrip("@") in {"echo", "printf"}


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
                    found.add(_norm_fs_path(tokens[index + 1]))
    return found


def _recipe_has_exact_path(commands: list[RecipeCommand], path: str) -> bool:
    normalized = _norm_fs_path(path)
    for command in commands:
        if command.ignored_failure:
            continue
        tokens = _tokenize_command(command.text.split("#", 1)[0].strip())
        if _is_echo_or_printf(tokens):
            continue
        if normalized in {_norm_fs_path(token) for token in tokens}:
            return True
    return False


def _gate_errors(
    recipes: dict[str, list[RecipeCommand]], gate: GateRules
) -> list[str]:
    errors: list[str] = []
    if gate.target not in recipes:
        return [f"missing Makefile target: {gate.target}"]
    commands = recipes[gate.target]
    make_targets = _invoked_make_targets(commands)
    scripts = _invoked_scripts(commands)
    searchable = make_targets | scripts
    for step in gate.required:
        if step.endswith(".py"):
            normalized = _norm_fs_path(step)
            if normalized not in scripts:
                errors.append(f"{gate.target} must invoke {step}")
        elif step not in searchable:
            errors.append(f"{gate.target} must invoke {step}")
    for step in gate.forbidden:
        if step in searchable:
            errors.append(f"{gate.target} must not invoke {step}")
    return errors


def _collect_nested_block(text: str, header_pattern: str) -> str | None:
    lines = text.splitlines()
    start = None
    pattern = re.compile(header_pattern)
    for index, line in enumerate(lines):
        if pattern.match(line):
            start = index
            break
    if start is None:
        return None
    block = [lines[start]]
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


def _extract_build_target(block: str) -> tuple[str | None, bool]:
    build_block = _collect_nested_block(block, r"^\s*build:\s*$")
    if build_block is None:
        return None, False
    target = _extract_yaml_scalar(build_block, "target")
    if target is None:
        return None, False
    return target, True


def _resolve_yaml_merge_anchor(compose: str, service_block: str) -> str | None:
    match = re.search(r"<<:\s*\*(\S+)", service_block)
    if not match:
        return None
    anchor_name = match.group(1)
    anchor_header = re.compile(
        rf"^(\S+):\s*&{re.escape(anchor_name)}\s*$", re.MULTILINE
    )
    header_match = anchor_header.search(compose)
    if header_match is None:
        return None
    return _collect_nested_block(compose, rf"^{re.escape(header_match.group(1))}:")


def _resolve_api_build_target(compose: str) -> tuple[str | None, bool, str | None]:
    api_block = _collect_nested_block(compose, r"^\s*api:\s*$")
    if api_block is None:
        return None, False, "docker-compose.yml missing services.api block"

    local_target, local_explicit = _extract_build_target(api_block)
    inherited_block = _resolve_yaml_merge_anchor(compose, api_block)
    inherited_target, inherited_explicit = (
        _extract_build_target(inherited_block)
        if inherited_block is not None
        else (None, False)
    )

    if inherited_block is None and re.search(r"<<:\s*\*", api_block):
        return None, True, "docker-compose api merge alias could not be resolved"

    if local_explicit:
        return local_target, True, None
    if inherited_explicit:
        return inherited_target, True, None
    return None, False, None


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
    api_block = _collect_nested_block(compose, r"^\s*api:\s*$")
    if api_block is not None:
        command = _extract_yaml_scalar(api_block, "command")
        if command is not None:
            return command.strip().strip("'\"")
        inherited = _resolve_yaml_merge_anchor(compose, api_block)
        if inherited is not None:
            command = _extract_yaml_scalar(inherited, "command")
            if command is not None:
                return command.strip().strip("'\"")
    return None


def _validate_runtime(ctx: RepoContext, expected_runtime: str) -> list[str]:
    errors: list[str] = []
    build_target, explicit, resolve_error = _resolve_api_build_target(ctx.compose)
    if resolve_error:
        errors.append(resolve_error)
        return errors

    stages = _dockerfile_stages(ctx.dockerfile)
    if not stages:
        return ["Dockerfile has no stages"]

    if explicit:
        stage_match = next(
            ((name, text) for name, text in stages if name == build_target),
            None,
        )
        if stage_match is None:
            errors.append(
                f"docker-compose build.target {build_target!r} does not match "
                "any Dockerfile stage"
            )
            return errors
        stage_name, stage_text = stage_match
    else:
        stage_name, stage_text = stages[-1]

    docker_cmd = _runtime_token(_dockerfile_cmd(stage_text))
    if docker_cmd is None:
        errors.append(f"Dockerfile stage {stage_name!r} must define an explicit CMD")
    elif not _runtime_matches(docker_cmd, expected_runtime):
        errors.append(
            f"Dockerfile stage {stage_name!r} CMD must select "
            f"{expected_runtime!r}, got {docker_cmd!r}"
        )

    compose_cmd = _extract_compose_api_command(ctx.compose)
    if compose_cmd is not None:
        if not _runtime_matches(_runtime_token(compose_cmd), expected_runtime):
            errors.append(
                f"docker-compose api command must select {expected_runtime!r}, "
                f"got {compose_cmd!r}"
            )
    elif docker_cmd is None or not _runtime_matches(docker_cmd, expected_runtime):
        errors.append("effective api runtime must select expected command")

    if expected_runtime == LEGACY_RUNTIME:
        if (
            LEGACY_RUNTIME not in ctx.compose
            and "psychoanalyst_app.server" not in ctx.compose
            and compose_cmd is None
            and docker_cmd is None
        ):
            errors.append("legacy runtime not configured for api service")
    return errors


def _path_exists(ctx: RepoContext, item: ManifestItem) -> bool:
    if item.kind == "make_target":
        return item.path in ctx.recipes
    path = ctx.root / item.path.rstrip("/")
    return path.exists() or path.is_symlink()


def _path_absent(ctx: RepoContext, item: ManifestItem) -> bool:
    if item.kind == "make_target":
        return item.path not in ctx.recipes
    path = ctx.root / item.path.rstrip("/")
    return not path.exists() and not path.is_symlink()


def _paths_exist(ctx: RepoContext, paths: tuple[str, ...]) -> list[str]:
    errors: list[str] = []
    for relative in paths:
        candidate = ctx.root / relative
        if not candidate.exists():
            errors.append(f"missing path: {relative}")
    return errors


def _test_target_references_path(ctx: RepoContext, path: str) -> bool:
    normalized = _norm_fs_path(path)
    if normalized in _target_support_test_paths(ctx.makefile_text):
        return True
    return _recipe_has_exact_path(ctx.recipes.get("test-target", []), normalized)


def _validate_item_complete(ctx: RepoContext, item: ManifestItem) -> list[str]:
    errors: list[str] = []
    if item.action in {"delete", "port_then_delete", "reimplement_then_delete"}:
        errors.extend(_paths_exist(ctx, item.replacements))
        errors.extend(_paths_exist(ctx, item.evidence))
        if not _path_absent(ctx, item):
            errors.append(f"complete item still present: {item.path}")
    elif item.action == "retain":
        if not _path_exists(ctx, item):
            errors.append(f"retained path missing: {item.path}")
        if item.requires_explicit_test_target_reference:
            if not _test_target_references_path(ctx, item.path):
                errors.append(
                    f"retained test not referenced in test-target recipe: {item.path}"
                )
    elif item.action == "edit":
        errors.extend(_validate_workflow_edit(ctx, complete=True))
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


def _validate_workflow_edit(ctx: RepoContext, *, complete: bool) -> list[str]:
    path = ctx.root / WORKFLOW_EDIT_PATH
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


def _validate_entry_points(ctx: RepoContext, rules: StageRules) -> list[str]:
    scripts = ctx.pyproject.get("project", {}).get("scripts", {})
    if not isinstance(scripts, dict):
        return ["pyproject.toml missing project.scripts"]
    names = set(scripts)
    errors: list[str] = []
    for entry in rules.required_entry_points:
        if entry not in names:
            errors.append(f"missing target entry point: {entry}")
    for legacy in rules.forbidden_entry_points:
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


def _validate_dependency_closure(ctx: RepoContext) -> list[str]:
    errors: list[str] = []
    names: set[str] = set()
    deps = ctx.pyproject.get("project", {}).get("dependencies", [])
    if isinstance(deps, list):
        for dep in deps:
            if isinstance(dep, str):
                names.add(_norm_pkg_name(dep.split(";")[0].strip()))
    for req_name in ("requirements.txt", "requirements-dev.txt"):
        names.update(_read_requirement_names(ctx.root / req_name))
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
        ctx.pyproject.get("tool", {}).get("setuptools", {}).get("package-data", {})
    )
    if isinstance(package_data, dict) and "psychoanalyst_app" in package_data:
        errors.append("pyproject package-data still references psychoanalyst_app")
    return errors


def _final_manifest_closure(manifest: Manifest) -> list[str]:
    errors: list[str] = []
    for item in manifest.items:
        if item.status != "complete":
            errors.append(f"manifest item not complete: {item.path}")
        if item.confidence == "discovery-needed":
            errors.append(f"discovery-needed item remains: {item.path}")
    return errors


def _find_item(manifest: Manifest, kind: str, path: str) -> ManifestItem | None:
    for item in manifest.items:
        if item.kind == kind and item.path == path:
            return item
    return None


def validate(root: Path | None = None, *, stage: str = "pre-cutover") -> list[str]:
    resolved = (root or REPO_ROOT).resolve()
    if stage not in STAGES:
        return [f"unknown stage: {stage}"]

    manifest, errors = parse_manifest(resolved)
    if manifest is None:
        return errors

    rules = STAGES[stage]
    if manifest.status != rules.manifest_status:
        errors.append(
            f"manifest status must be {rules.manifest_status!r} for stage {stage!r}, "
            f"got {manifest.status!r}"
        )

    ctx = _load_repo_context(resolved)
    for gate in rules.gates:
        errors.extend(_gate_errors(ctx.recipes, gate))
    errors.extend(_validate_runtime(ctx, rules.expected_runtime))

    if rules.required_entry_points or rules.forbidden_entry_points:
        errors.extend(_validate_entry_points(ctx, rules))

    for item in manifest.items:
        if item.status == "complete":
            errors.extend(_validate_item_complete(ctx, item))

    for kind, path in rules.required_complete_items:
        item = _find_item(manifest, kind, path)
        if item is None:
            errors.append(f"required complete item missing from manifest: {path}")
            continue
        if item.status != "complete":
            errors.append(
                f"required item must be complete for stage {stage!r}: {path}"
            )
            continue
        errors.extend(_validate_item_complete(ctx, item))

    if rules.final_closure:
        errors.extend(_final_manifest_closure(manifest))
        errors.extend(_validate_import_closure(resolved))
        errors.extend(_validate_dependency_closure(ctx))

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        choices=tuple(STAGES),
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
