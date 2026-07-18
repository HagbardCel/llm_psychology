#!/usr/bin/env python3
"""Semantic cutover checks for Phase 6 legacy deletion.

Transitional validator: deleted after Phase 6 final cleanup and Phase 7 tooling
finalization. See docs/refactor/deletion-inventory.md for sunset notes.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shlex
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path("docs/refactor/deletion-manifest.toml")
WORKFLOW_EDIT_PATH = ".github/workflows/release-candidate-validation.yml"

KIND_ACTIONS: dict[str, frozenset[str]] = {
    "filesystem": frozenset(
        {"delete", "port_then_delete", "reimplement_then_delete", "retain"}
    ),
    "make_target": frozenset({"delete", "retain"}),
    "workflow": frozenset({"delete", "retain"}),
    "workflow_edit": frozenset({"edit"}),
}

LEGACY_GATE_TARGETS = frozenset(
    {
        "lint",
        "validate-docs",
        "validate-schemas",
        "validate-generated-contracts",
        "validate-architecture",
        "test-validate",
        "characterization-smoke",
        "probe-console-deterministic",
    }
)
TARGET_GATE_TARGETS = frozenset(
    {
        "lint",
        "validate-docs",
        "test-target",
        "probe-console-v1-deterministic",
    }
)
LEGACY_ONLY_STEPS = frozenset(
    {
        "test-validate",
        "characterization-smoke",
        "characterization-full",
        "finalization-check-full",
        "probe-console-deterministic",
        "probe-console-intake-notes",
        "validate-schemas",
        "validate-generated-contracts",
        "validate-architecture",
    }
)
PHASE_5_SCRIPT = "scripts/validate_refactor_phase_5.py"
PHASE_6_SCRIPT = "scripts/validate_refactor_phase_6.py"
GOVERNED_GATES = frozenset({"finalization-check", "finalization-check-target"})
PERMITTED_STRUCTURAL_PREREQS = frozenset({"prepare-runtime-dirs"})
DOCKER_TEST_PREFIX = (
    "docker",
    "compose",
    "--profile",
    "test",
    "run",
    "--rm",
    "test",
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

LEGACY_RUNTIME_ARGV = ("python", "-m", "psychoanalyst_app.server")
TARGET_RUNTIME_ARGV = ("jung-api",)
LEGACY_ENTRY_POINTS = frozenset({"psychoanalyst-server", "psychoanalyst-db"})
TARGET_ENTRY_POINTS = {
    "jung-api": "jung.api.app:cli",
    "jung-console": "jung.client.terminal:cli",
    "jung-db": "jung.tools.db_backup:main",
}
TARGET_ENTRY_CUTOVER = frozenset({"jung-api", "jung-console"})
TARGET_ENTRY_FINAL = frozenset(TARGET_ENTRY_POINTS)
MAKE_TARGET_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
MAKE_TOKENS = frozenset({"make", "$(MAKE)", "${MAKE}"})
PYTHON_INTERPRETERS = frozenset({"python", "python3"})
TARGET_SUPPORT_TESTS_VAR = "$(TARGET_SUPPORT_TESTS)"


def _strip_nonempty(value: Any, field_name: str) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must be non-empty")
    return stripped


class ManifestItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["filesystem", "make_target", "workflow", "workflow_edit"]
    path: StrictStr
    action: Literal[
        "delete", "port_then_delete", "reimplement_then_delete", "retain", "edit"
    ]
    owner_pr: Literal["6A", "6B", "6C", "6D"]
    status: Literal["planned", "in_progress", "complete"]
    confidence: Literal["confirmed", "likely", "discovery-needed"]
    responsibility: StrictStr
    blocker: StrictStr | None = None
    replacements: tuple[StrictStr, ...] = ()
    evidence: tuple[StrictStr, ...] = ()
    aggregate: StrictBool | None = None
    requires_explicit_test_target_reference: StrictBool | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_item_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        for field in ("path", "responsibility", "blocker"):
            if field in normalized and normalized[field] is not None:
                normalized[field] = _strip_nonempty(normalized[field], field)
        kind = normalized.get("kind")
        if isinstance(normalized.get("path"), str) and kind != "make_target":
            normalized["path"] = _norm_fs_path(normalized["path"])
        return normalized

    @field_validator("replacements", "evidence")
    @classmethod
    def validate_path_entries(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        seen: set[str] = set()
        normalized: list[str] = []
        for entry in value:
            norm, err = _validate_repo_relative_path(entry, "path")
            if err:
                raise ValueError(err)
            assert norm is not None
            if norm in seen:
                raise ValueError(f"duplicate path entry {norm!r}")
            seen.add(norm)
            normalized.append(norm)
        return tuple(normalized)

    @model_validator(mode="after")
    def validate_item_rules(self) -> Self:
        if self.action not in KIND_ACTIONS[self.kind]:
            raise ValueError(
                f"action {self.action!r} invalid for kind {self.kind!r}"
            )
        if self.aggregate is not None:
            if self.aggregate is not True:
                raise ValueError("aggregate must be omitted or true")
            if self.kind != "filesystem" or self.action != "delete":
                raise ValueError("aggregate rows require filesystem delete")
        if self.requires_explicit_test_target_reference is not None:
            if self.requires_explicit_test_target_reference is not True:
                raise ValueError(
                    "requires_explicit_test_target_reference must be omitted or true"
                )
            if self.action != "retain":
                raise ValueError(
                    "requires_explicit_test_target_reference only valid for retain"
                )
        replacement_optional = (
            self.action in {"port_then_delete", "reimplement_then_delete"}
            and self.status == "planned"
            and self.confidence == "discovery-needed"
        )
        if (
            self.action in {"port_then_delete", "reimplement_then_delete"}
            and not replacement_optional
            and not self.replacements
        ):
            raise ValueError(f"{self.action} requires replacements")
        if self.kind == "workflow_edit" and self.path != WORKFLOW_EDIT_PATH:
            raise ValueError(
                f"workflow_edit path must be {WORKFLOW_EDIT_PATH!r}"
            )
        if self.status == "complete" and self.confidence != "confirmed":
            raise ValueError("complete items must have confidence = confirmed")
        if self.kind == "make_target":
            if not MAKE_TARGET_RE.match(self.path):
                raise ValueError(f"invalid make target name: {self.path!r}")
        else:
            _, err = _validate_repo_relative_path(self.path, "path")
            if err:
                raise ValueError(err)
            if self.kind in {"workflow", "workflow_edit"} and not self.path.startswith(
                ".github/workflows/"
            ):
                raise ValueError("workflow path must be under .github/workflows/")
        return self


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: StrictInt
    status: Literal["active", "completed"]
    items: tuple[ManifestItem, ...]

    @field_validator("schema_version")
    @classmethod
    def require_schema_version_one(cls, value: int) -> int:
        if value != 1:
            raise ValueError("must be 1")
        return value

    @model_validator(mode="after")
    def reject_duplicate_items(self) -> Self:
        seen: set[tuple[str, str]] = set()
        for index, item in enumerate(self.items):
            key = (item.kind, item.path)
            if key in seen:
                raise ValueError(
                    f"item {index}: duplicate kind/path {item.kind} {item.path!r}"
                )
            seen.add(key)
        return self


@dataclass(frozen=True, slots=True)
class RecipeCommand:
    text: str
    ignored_failure: bool


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    tokens: tuple[str, ...]
    segments: tuple[tuple[str, ...], ...]
    has_shell_control: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedArgv:
    present: bool
    argv: tuple[str, ...] | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ScriptRequirement:
    path: str
    required_args: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ParsedMakeTarget:
    recipes: tuple[RecipeCommand, ...]
    prerequisites: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GateRules:
    target: str
    required_targets: frozenset[str]
    required_scripts: tuple[ScriptRequirement, ...]
    forbidden_targets: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class StageRules:
    manifest_status: str
    expected_runtime_argv: tuple[str, ...]
    gates: tuple[GateRules, ...]
    required_entry_points: frozenset[str]
    forbidden_entry_points: frozenset[str]
    final_closure: bool
    required_complete_items: frozenset[tuple[str, str]] = frozenset()


@dataclass(frozen=True, slots=True)
class RepoContext:
    root: Path
    targets: dict[str, ParsedMakeTarget]
    makefile_text: str
    pyproject: dict[str, Any]
    compose: str
    dockerfile: str


def _target_gate(
    stage: str, *, forbidden: frozenset[str] = LEGACY_ONLY_STEPS
) -> GateRules:
    return GateRules(
        "finalization-check",
        TARGET_GATE_TARGETS,
        (
            ScriptRequirement(PHASE_6_SCRIPT, ("--stage", stage)),
            ScriptRequirement(PHASE_5_SCRIPT),
        ),
        forbidden,
    )


STAGES: dict[str, StageRules] = {
    "pre-cutover": StageRules(
        manifest_status="active",
        expected_runtime_argv=LEGACY_RUNTIME_ARGV,
        gates=(
            GateRules(
                "finalization-check",
                LEGACY_GATE_TARGETS,
                (ScriptRequirement(PHASE_5_SCRIPT),),
            ),
            GateRules(
                "finalization-check-target",
                TARGET_GATE_TARGETS,
                (
                    ScriptRequirement(PHASE_6_SCRIPT, ("--stage", "pre-cutover")),
                    ScriptRequirement(PHASE_5_SCRIPT),
                ),
            ),
        ),
        required_entry_points=frozenset(),
        forbidden_entry_points=frozenset(),
        final_closure=False,
    ),
    "cutover": StageRules(
        manifest_status="active",
        expected_runtime_argv=TARGET_RUNTIME_ARGV,
        gates=(_target_gate("cutover"),),
        required_entry_points=TARGET_ENTRY_CUTOVER,
        forbidden_entry_points=LEGACY_ENTRY_POINTS,
        final_closure=False,
        required_complete_items=frozenset(
            {("workflow_edit", WORKFLOW_EDIT_PATH)}
        ),
    ),
    "final": StageRules(
        manifest_status="completed",
        expected_runtime_argv=TARGET_RUNTIME_ARGV,
        gates=(_target_gate("final"),),
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
    return path.startswith("\\\\")


def _validate_repo_relative_path(
    path: str, label: str
) -> tuple[str | None, str | None]:
    if not isinstance(path, str) or not path.strip():
        return None, f"{label} entries must be non-empty strings"
    normalized = _norm_fs_path(path.strip())
    if not normalized or normalized in {".", "./"}:
        return None, f"{label} path must not be empty: {path!r}"
    if _is_absolute_repo_path(normalized):
        return None, f"{label} path must be repository-relative: {path!r}"
    if ".." in normalized.split("/"):
        return None, f"{label} path must not contain ..: {path!r}"
    return normalized, None


def _format_validation_errors(exc: ValidationError) -> list[str]:
    errors: list[str] = []
    for err in exc.errors():
        loc = err["loc"]
        msg = err["msg"]
        if loc and loc[0] == "items" and isinstance(loc[1], int):
            prefix = f"item {loc[1]}"
            if len(loc) > 2:
                field = loc[2]
                errors.append(f"{prefix}: {field}: {msg}")
            else:
                errors.append(f"{prefix}: {msg}")
        elif loc:
            errors.append(f"{'.'.join(str(part) for part in loc)}: {msg}")
        else:
            errors.append(msg)
    return errors


def parse_manifest(root: Path) -> tuple[Manifest | None, list[str]]:
    path = root / MANIFEST_PATH
    if not path.is_file():
        return None, [f"missing manifest: {MANIFEST_PATH}"]
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        return None, [f"invalid manifest TOML: {exc}"]

    raw_items = data.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        return None, ["manifest must define at least one item"]

    try:
        manifest = Manifest.model_validate(data)
    except ValidationError as exc:
        return None, _format_validation_errors(exc)
    return manifest, []


def _load_repo_context(root: Path) -> RepoContext:
    makefile_text = (root / "Makefile").read_text(encoding="utf-8")
    return RepoContext(
        root=root,
        targets=_parse_makefile_text(makefile_text),
        makefile_text=makefile_text,
        pyproject=tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8")),
        compose=(root / "docker-compose.yml").read_text(encoding="utf-8"),
        dockerfile=(root / "Dockerfile").read_text(encoding="utf-8"),
    )


def _parse_prerequisite_tokens(prereq_part: str) -> tuple[str, ...]:
    return tuple(token for token in prereq_part.split() if token)


def _parse_makefile_text(text: str) -> dict[str, ParsedMakeTarget]:
    targets: dict[str, ParsedMakeTarget] = {}
    current: str | None = None
    current_prereqs: tuple[str, ...] = ()
    pending: str | None = None
    pending_ignored = False
    current_recipes: list[RecipeCommand] = []

    for line in text.splitlines():
        if line.startswith("#"):
            continue
        if line and not line.startswith("\t") and ":" in line:
            if current is not None:
                targets[current] = ParsedMakeTarget(
                    tuple(current_recipes), current_prereqs
                )
            target_part, prereq_part = line.split(":", 1)
            current = target_part.strip()
            if not current or current.startswith("."):
                current = None
                pending = None
                continue
            current_prereqs = _parse_prerequisite_tokens(prereq_part)
            current_recipes = []
            pending = None
            continue
        if not line.startswith("\t") or current is None:
            continue
        body = line[1:].strip()
        if not body or body.startswith("#"):
            continue
        if pending is None:
            pending_ignored = body.startswith("-")
            pending = body[1:].strip() if pending_ignored else body
        else:
            pending = f"{pending} {body}"
        if body.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        current_recipes.append(
            RecipeCommand(text=pending, ignored_failure=pending_ignored)
        )
        pending = None

    if current is not None:
        targets[current] = ParsedMakeTarget(tuple(current_recipes), current_prereqs)
    return targets


def _parse_shell_command(text: str) -> ParsedCommand:
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = "#"
        tokens = tuple(lexer)
    except ValueError as exc:
        return ParsedCommand((), (), False, str(exc))

    segments: list[list[str]] = []
    current: list[str] = []
    has_control = False
    for token in tokens:
        if token and all(char in ";&|" for char in token):
            has_control = True
            if current:
                segments.append(current)
                current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    return ParsedCommand(tokens, tuple(tuple(part) for part in segments), has_control)


def _segment_invokes_make_target(
    segment: tuple[str, ...], target: str, *, allow_leading_dash: bool
) -> bool:
    if not segment:
        return False
    offset = 1 if allow_leading_dash and segment[0] == "-" else 0
    if len(segment) < offset + 2:
        return False
    return (
        segment[offset] in MAKE_TOKENS and segment[offset + 1] == target
    )


def _command_invokes_required_make(
    command: ParsedCommand, target: str
) -> bool:
    if command.error or command.has_shell_control or len(command.segments) != 1:
        return False
    segment = command.segments[0]
    if segment and segment[0] == "-":
        return False
    return (
        len(segment) == 2
        and segment[0] in MAKE_TOKENS
        and segment[1] == target
    )


def _script_argv_offset(segment: tuple[str, ...]) -> int | None:
    if not segment:
        return None
    if segment[0] in PYTHON_INTERPRETERS:
        return 1
    docker_prefix = DOCKER_TEST_PREFIX + ("python",)
    prefix_len = len(docker_prefix)
    if len(segment) >= prefix_len and segment[:prefix_len] == docker_prefix:
        return prefix_len
    return None


def _command_invokes_script(
    command: ParsedCommand, requirement: ScriptRequirement
) -> bool:
    if command.error or command.has_shell_control or len(command.segments) != 1:
        return False
    segment = command.segments[0]
    if segment and segment[0] == "-":
        return False
    offset = _script_argv_offset(segment)
    if offset is None:
        return False
    argv = segment[offset:]
    expected_len = 1 + len(requirement.required_args)
    if len(argv) != expected_len:
        return False
    if _norm_fs_path(argv[0]) != _norm_fs_path(requirement.path):
        return False
    return argv[1:] == requirement.required_args


def _pytest_argv_offset(segment: tuple[str, ...]) -> int | None:
    if not segment:
        return None
    if segment[0] == "pytest":
        return 0
    if len(segment) >= 3 and segment[:3] == ("python", "-m", "pytest"):
        return 3
    docker_prefix = DOCKER_TEST_PREFIX + ("pytest",)
    prefix_len = len(docker_prefix)
    if len(segment) >= prefix_len and segment[:prefix_len] == docker_prefix:
        return prefix_len
    return None


def _command_invokes_pytest_with_path(
    command: ParsedCommand, path: str
) -> bool:
    if command.error or command.has_shell_control or len(command.segments) != 1:
        return False
    segment = command.segments[0]
    if segment and segment[0] == "-":
        return False
    offset = _pytest_argv_offset(segment)
    if offset is None:
        return False
    normalized = _norm_fs_path(path)
    return normalized in {_norm_fs_path(token) for token in segment[offset:]}


def _is_canonical_gate(command: ParsedCommand) -> bool:
    return _command_invokes_required_make(command, "finalization-check")


def _command_has_forbidden_make(
    command: ParsedCommand, target: str
) -> bool:
    if command.error:
        return False
    return any(
        _segment_invokes_make_target(segment, target, allow_leading_dash=True)
        for segment in command.segments
    )


def _reachable_prerequisites(
    targets: dict[str, ParsedMakeTarget], start: str
) -> set[str]:
    if start not in targets:
        return set()
    visited: set[str] = set()
    reachable: set[str] = set()
    stack = list(targets[start].prerequisites)
    while stack:
        name = stack.pop()
        if name in PERMITTED_STRUCTURAL_PREREQS or name in visited:
            continue
        visited.add(name)
        reachable.add(name)
        if name in targets:
            stack.extend(targets[name].prerequisites)
    return reachable


def _gate_errors(
    targets: dict[str, ParsedMakeTarget], gate: GateRules
) -> list[str]:
    errors: list[str] = []
    if gate.target not in targets:
        return [f"missing Makefile target: {gate.target}"]
    if gate.target in GOVERNED_GATES:
        for token in targets[gate.target].prerequisites:
            if token in PERMITTED_STRUCTURAL_PREREQS:
                continue
            if MAKE_TARGET_RE.match(token):
                continue
            errors.append(f"{gate.target} has unsupported prerequisite: {token}")
        for legacy in LEGACY_ONLY_STEPS:
            if legacy in _reachable_prerequisites(targets, gate.target):
                errors.append(f"{gate.target} must not depend on {legacy}")
    recipes = targets[gate.target].recipes
    for step in gate.required_targets:
        found = False
        for command in recipes:
            if command.ignored_failure:
                continue
            parsed = _parse_shell_command(command.text)
            if _command_invokes_required_make(parsed, step):
                found = True
                break
        if not found:
            errors.append(f"{gate.target} must invoke {step}")
    for script in gate.required_scripts:
        found = False
        for command in recipes:
            if command.ignored_failure:
                continue
            parsed = _parse_shell_command(command.text)
            if _command_invokes_script(parsed, script):
                found = True
                break
        if not found:
            label = script.path
            if script.required_args:
                label = f"{script.path} {' '.join(script.required_args)}"
            errors.append(f"{gate.target} must invoke {label}")
    for step in gate.forbidden_targets:
        for command in recipes:
            parsed = _parse_shell_command(command.text)
            if _command_has_forbidden_make(parsed, step):
                errors.append(f"{gate.target} must not invoke {step}")
                break
    return errors


def _yaml_block(text: str, header_pattern: str) -> str | None:
    match = re.search(header_pattern, text, re.MULTILINE)
    if not match:
        return None
    start = text[: match.start()].count("\n")
    lines = text.splitlines()
    block = [lines[start]]
    base_indent = len(lines[start]) - len(lines[start].lstrip())
    for line in lines[start + 1 :]:
        if not line.strip():
            block.append(line)
            continue
        if len(line) - len(line.lstrip()) <= base_indent:
            break
        block.append(line)
    return "\n".join(block)


def _is_comment_or_blank(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _direct_child_indent(parent_block: str) -> int | None:
    parent_indent: int | None = None
    for line in parent_block.splitlines():
        if _is_comment_or_blank(line):
            continue
        indent = len(line) - len(line.lstrip())
        if parent_indent is None:
            parent_indent = indent
            continue
        if indent > parent_indent:
            return indent
    return None


def _direct_children(parent_block: str) -> list[tuple[str, str]]:
    lines = parent_block.splitlines()
    if not lines:
        return []
    child_indent = _direct_child_indent(parent_block)
    if child_indent is None:
        return []
    children: list[tuple[str, list[str]]] = []
    current_name: str | None = None
    for line in lines[1:]:
        if _is_comment_or_blank(line):
            if current_name is not None:
                children[-1][1].append(line)
            continue
        indent = len(line) - len(line.lstrip())
        if indent < child_indent:
            break
        if indent == child_indent:
            match = re.match(r"(\S+):\s*(.*)$", line.strip())
            if match:
                current_name = match.group(1)
                children.append((current_name, [line]))
            else:
                current_name = None
        elif current_name is not None and indent > child_indent:
            children[-1][1].append(line)
    return [(name, "\n".join(block)) for name, block in children]


def _children_named(
    children: list[tuple[str, str]], name: str
) -> list[str]:
    return [block for child_name, block in children if child_name == name]


def _is_inline_mapping(block: str) -> bool:
    first = block.splitlines()[0].strip() if block else ""
    return "{" in first


def _services_block(compose: str) -> tuple[str | None, str | None]:
    if len(re.findall(r"^services:\s*$", compose, re.MULTILINE)) > 1:
        return None, "docker-compose.yml has multiple services blocks"
    block = _yaml_block(compose, r"^services:\s*$")
    if block is None:
        return None, "docker-compose.yml missing services block"
    return block, None


def _api_service_block(compose: str) -> tuple[str | None, str | None]:
    services, err = _services_block(compose)
    if err:
        return None, err
    assert services is not None
    children = _direct_children(services)
    api_blocks = _children_named(children, "api")
    if not api_blocks:
        return None, "docker-compose.yml missing services.api block"
    if len(api_blocks) > 1:
        return None, "docker-compose.yml has multiple services.api blocks"
    api_block = api_blocks[0]
    if _is_inline_mapping(api_block):
        return None, "docker-compose api inline mapping is unsupported"
    return api_block, None


def _merge_aliases(service_block: str) -> tuple[list[str], str | None]:
    children = _direct_children(service_block)
    merge_blocks = _children_named(children, "<<")
    if len(merge_blocks) > 1:
        return [], "docker-compose api has multiple merge keys"
    if not merge_blocks:
        return [], None
    block = merge_blocks[0]
    first_line = block.splitlines()[0].strip()
    match = re.match(r"<<:\s*(.*)$", first_line)
    if not match:
        return [], "docker-compose api has unsupported merge syntax"
    value = match.group(1).strip()
    if not value:
        if len(block.splitlines()) > 1:
            return [], "docker-compose api has unsupported merge list syntax"
        return [], "docker-compose api has unsupported merge syntax"
    if value.startswith("*") and not value.startswith("[") and " " not in value:
        return [value[1:]], None
    return [], "docker-compose api has unsupported merge syntax"


def _resolve_merge_anchor(compose: str, alias: str) -> tuple[str | None, str | None]:
    headers = list(
        re.finditer(
            rf"^(\S+):\s*&{re.escape(alias)}\s*$", compose, re.MULTILINE
        )
    )
    if not headers:
        return None, f"docker-compose merge alias *{alias} could not be resolved"
    if len(headers) > 1:
        return None, f"docker-compose merge alias *{alias} is ambiguous"
    anchor_name = headers[0].group(1)
    block = _yaml_block(compose, rf"^{re.escape(anchor_name)}:\s*")
    if block is None:
        return None, f"docker-compose merge alias *{alias} could not be resolved"
    return block, None


def _extract_direct_scalar(block: str, key: str) -> list[tuple[int, str]]:
    child_indent = _direct_child_indent(block)
    if child_indent is None:
        return []
    matches: list[tuple[int, str]] = []
    for index, line in enumerate(block.splitlines()):
        if _is_comment_or_blank(line):
            continue
        indent = len(line) - len(line.lstrip())
        if indent != child_indent:
            continue
        match = re.match(rf"{re.escape(key)}:\s*(.*)$", line.strip())
        if match:
            matches.append((index, match.group(1).strip()))
    return matches


def _parse_inline_command_list(raw: str) -> ParsedArgv:
    if not raw.startswith("["):
        return ParsedArgv(True, error="command inline list must start with [")
    try:
        parsed = ast.literal_eval(raw)
    except (SyntaxError, ValueError):
        return ParsedArgv(True, error="command inline list is malformed")
    if not isinstance(parsed, list) or not parsed:
        return ParsedArgv(
            True, error="command inline list must be a non-empty list of strings"
        )
    if not all(isinstance(item, str) and item for item in parsed):
        return ParsedArgv(
            True,
            error="command inline list must contain only non-empty strings",
        )
    return ParsedArgv(True, argv=tuple(parsed))


def _parse_block_command_list(
    block: str, key_line_index: int
) -> ParsedArgv:
    child_indent = _direct_child_indent(block)
    if child_indent is None:
        return ParsedArgv(True, error="command block is malformed")
    list_indent = child_indent + 2
    items: list[str] = []
    for line in block.splitlines()[key_line_index + 1 :]:
        if _is_comment_or_blank(line):
            continue
        indent = len(line) - len(line.lstrip())
        if indent < list_indent:
            break
        if indent != list_indent:
            return ParsedArgv(
                True, error="command block contains unsupported child syntax"
            )
        match = re.match(r"-\s*(.+)$", line.strip())
        if not match:
            return ParsedArgv(
                True, error="command block contains unsupported child syntax"
            )
        value = match.group(1).strip().strip("'\"")
        if not value:
            return ParsedArgv(
                True, error="command block list items must be non-empty strings"
            )
        items.append(value)
    if not items:
        return ParsedArgv(True, error="command block list must be non-empty")
    return ParsedArgv(True, argv=tuple(items))


def _scalar_to_argv(raw: str) -> ParsedArgv:
    value = raw.strip().strip("'\"")
    if not value:
        return ParsedArgv(True, error="command must not be empty")
    parsed = _parse_shell_command(value)
    if parsed.error:
        return ParsedArgv(True, error=parsed.error)
    if parsed.has_shell_control:
        return ParsedArgv(True, error="command contains unsupported shell control")
    if len(parsed.segments) != 1:
        return ParsedArgv(True, error="command contains unsupported shell control")
    return ParsedArgv(True, argv=parsed.segments[0])


def _extract_yaml_command(block: str) -> ParsedArgv:
    matches = _extract_direct_scalar(block, "command")
    if not matches:
        return ParsedArgv(False)
    if len(matches) > 1:
        return ParsedArgv(True, error="docker-compose api has multiple command keys")
    key_index, raw = matches[0]
    if not raw:
        return _parse_block_command_list(block, key_index)
    if raw.startswith("["):
        return _parse_inline_command_list(raw)
    return _scalar_to_argv(raw)


def _extract_build_target(block: str) -> ParsedArgv:
    children = _direct_children(block)
    build_blocks = _children_named(children, "build")
    if not build_blocks:
        return ParsedArgv(False)
    if len(build_blocks) > 1:
        return ParsedArgv(True, error="docker-compose api has multiple build blocks")
    build_block = build_blocks[0]
    if _is_inline_mapping(build_block):
        return ParsedArgv(True, error="docker-compose api inline build is unsupported")
    first_line = build_block.splitlines()[0].strip()
    if re.match(r"build:\s*\S+", first_line) and "{" not in first_line:
        remainder = first_line.split(":", 1)[1].strip()
        if remainder and not remainder.startswith("{"):
            return ParsedArgv(
                True, error="docker-compose scalar build syntax is unsupported"
            )
    targets = _extract_direct_scalar(build_block, "target")
    if not targets:
        return ParsedArgv(False)
    if len(targets) > 1:
        return ParsedArgv(
            True, error="docker-compose api build has multiple target keys"
        )
    _, raw = targets[0]
    if not raw:
        return ParsedArgv(True, error="docker-compose build target is empty")
    return ParsedArgv(True, argv=(raw.strip().strip("'\""),))


def _api_service_layers(
    compose: str,
) -> tuple[str | None, str | None, str | None]:
    api_block, err = _api_service_block(compose)
    if err:
        return None, None, err
    assert api_block is not None
    aliases, alias_err = _merge_aliases(api_block)
    if alias_err:
        return api_block, None, alias_err
    if not aliases:
        return api_block, None, None
    inherited, resolve_err = _resolve_merge_anchor(compose, aliases[0])
    if resolve_err:
        return api_block, None, resolve_err
    return api_block, inherited, None


def _pick_argv(local: ParsedArgv, inherited: ParsedArgv) -> ParsedArgv | str:
    if local.present and local.error:
        return local.error
    if local.present and local.argv is not None:
        return local
    if inherited.present and inherited.error:
        return inherited.error
    if inherited.present and inherited.argv is not None:
        return inherited
    return ParsedArgv(False)


def _layered_argv(
    compose: str,
    extractor: Callable[[str], ParsedArgv],
) -> tuple[ParsedArgv | None, str | None]:
    api_block, inherited_block, err = _api_service_layers(compose)
    if err:
        return None, err
    assert api_block is not None
    local = extractor(api_block)
    inherited = (
        extractor(inherited_block) if inherited_block else ParsedArgv(False)
    )
    picked = _pick_argv(local, inherited)
    if isinstance(picked, str):
        return None, picked
    return picked, None


def _resolve_api_build_target(compose: str) -> tuple[str | None, bool, str | None]:
    picked, err = _layered_argv(compose, _extract_build_target)
    if err:
        return None, False, err
    assert picked is not None
    if picked.present and picked.argv is not None:
        return picked.argv[0], True, None
    return None, False, None


def _extract_compose_api_command(compose: str) -> tuple[ParsedArgv | None, str | None]:
    return _layered_argv(compose, _extract_yaml_command)


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


def _dockerfile_cmd(stage_text: str) -> ParsedArgv:
    matches = list(
        re.finditer(r"^\s*CMD\s+(\[[^\]]*\]|.+?)\s*$", stage_text, re.MULTILINE)
    )
    if not matches:
        return ParsedArgv(False)
    raw = matches[-1].group(1).strip()
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return ParsedArgv(True, error="Dockerfile CMD exec form is malformed")
        if not isinstance(parsed, list) or not parsed:
            return ParsedArgv(
                True,
                error="Dockerfile CMD exec form must be a non-empty list",
            )
        if not all(isinstance(item, str) and item for item in parsed):
            return ParsedArgv(
                True,
                error="Dockerfile CMD exec form must contain only non-empty strings",
            )
        return ParsedArgv(True, argv=tuple(parsed))
    return _scalar_to_argv(raw)


def _validate_runtime(
    ctx: RepoContext, expected_argv: tuple[str, ...]
) -> list[str]:
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

    docker_parsed = _dockerfile_cmd(stage_text)
    if docker_parsed.present and docker_parsed.error:
        errors.append(
            f"Dockerfile stage {stage_name!r} CMD is invalid: {docker_parsed.error}"
        )
    elif not docker_parsed.present:
        errors.append(f"Dockerfile stage {stage_name!r} must define an explicit CMD")
    elif docker_parsed.argv != expected_argv:
        errors.append(
            f"Dockerfile stage {stage_name!r} CMD must select "
            f"{expected_argv!r}, got {docker_parsed.argv!r}"
        )

    compose_parsed, compose_err = _extract_compose_api_command(ctx.compose)
    if compose_err:
        errors.append(compose_err)
        return errors
    assert compose_parsed is not None

    if compose_parsed.present:
        if compose_parsed.error:
            errors.append(
                f"docker-compose api command is invalid: {compose_parsed.error}"
            )
        elif compose_parsed.argv != expected_argv:
            errors.append(
                f"docker-compose api command must select {expected_argv!r}, "
                f"got {compose_parsed.argv!r}"
            )
    elif not docker_parsed.present or (
        docker_parsed.argv is not None and docker_parsed.argv != expected_argv
    ):
        errors.append("effective api runtime must select expected command")

    return errors


def _path_exists(ctx: RepoContext, item: ManifestItem) -> bool:
    if item.kind == "make_target":
        return item.path in ctx.targets
    path = ctx.root / item.path.rstrip("/")
    return path.exists() or path.is_symlink()


def _path_absent(ctx: RepoContext, item: ManifestItem) -> bool:
    if item.kind == "make_target":
        return item.path not in ctx.targets
    path = ctx.root / item.path.rstrip("/")
    return not path.exists() and not path.is_symlink()


def _paths_exist(ctx: RepoContext, paths: tuple[str, ...]) -> list[str]:
    errors: list[str] = []
    for relative in paths:
        candidate = ctx.root / relative
        if not candidate.exists():
            errors.append(f"missing path: {relative}")
    return errors


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


def _test_target_expands_support_tests(ctx: RepoContext) -> bool:
    target = ctx.targets.get("test-target")
    if target is None:
        return False
    for command in target.recipes:
        if command.ignored_failure:
            continue
        parsed = _parse_shell_command(command.text)
        if parsed.error or parsed.has_shell_control or len(parsed.segments) != 1:
            continue
        if TARGET_SUPPORT_TESTS_VAR in parsed.segments[0]:
            return True
    return False


def _test_target_references_path(ctx: RepoContext, path: str) -> bool:
    normalized = _norm_fs_path(path)
    if (
        normalized in _target_support_test_paths(ctx.makefile_text)
        and _test_target_expands_support_tests(ctx)
    ):
        return True
    target = ctx.targets.get("test-target")
    if target is None:
        return False
    for command in target.recipes:
        if command.ignored_failure:
            continue
        parsed = _parse_shell_command(command.text)
        if _command_invokes_pytest_with_path(parsed, normalized):
            return True
    return False


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
    elif item.action == "edit" and item.kind == "workflow_edit":
        errors.extend(_validate_workflow_edit(ctx, complete=True))
    return errors


def _workflow_jobs(workflow: str) -> tuple[list[tuple[str, str]], list[str]]:
    matches = list(re.finditer(r"^jobs:\s*$", workflow, re.MULTILINE))
    if not matches:
        return [], ["workflow missing jobs block"]
    if len(matches) > 1:
        return [], ["workflow has multiple jobs blocks"]
    jobs_block = _yaml_block(workflow, r"^jobs:\s*$")
    if jobs_block is None:
        return [], ["workflow missing jobs block"]
    children = _direct_children(jobs_block)
    names = [name for name, _ in children]
    if len(names) != len(set(names)):
        return [], ["workflow has duplicate job names"]
    return children, []


def _split_step_list(steps_block: str) -> list[str]:
    lines = steps_block.splitlines()
    step_indent: int | None = None
    start_index = 0
    for index, line in enumerate(lines):
        if re.match(r"^\s*steps:\s*$", line):
            start_index = index + 1
            continue
        if _is_comment_or_blank(line):
            continue
        if re.match(r"^\s*-\s", line):
            step_indent = len(line) - len(line.lstrip())
            break
    if step_indent is None:
        return []
    steps: list[str] = []
    current: list[str] = []
    for line in lines[start_index:]:
        if _is_comment_or_blank(line):
            if current:
                current.append(line)
            continue
        indent = len(line) - len(line.lstrip())
        if indent < step_indent:
            break
        if indent == step_indent and re.match(r"^\s*-\s", line):
            if current:
                steps.append("\n".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        steps.append("\n".join(current))
    return steps


def _job_steps(job_block: str) -> tuple[list[str], list[str]]:
    children = _direct_children(job_block)
    steps_blocks = _children_named(children, "steps")
    if not steps_blocks:
        return [], ["job missing steps block"]
    if len(steps_blocks) > 1:
        return [], ["job has duplicate steps keys"]
    return _split_step_list(steps_blocks[0]), []


def _read_yaml_scalar_value(
    remainder: str, block: str, key_line_index: int
) -> tuple[list[str], str | None]:
    if remainder in {"|", "|-", "|+", ">", ">-", ">+"}:
        folded = remainder.startswith(">")
        block_lines: list[str] = []
        for line in block.splitlines()[key_line_index + 1 :]:
            if re.match(r"^\s*-\s*\S", line):
                break
            if line.rstrip().endswith("\\"):
                msg = "workflow block scalar contains unsupported shell continuation"
                return [], msg
            if line.strip():
                block_lines.append(line.strip())
        if folded:
            text = " ".join(block_lines).strip()
            return ([text] if text else []), None
        return [line for line in block_lines if line], None
    if remainder:
        return [remainder.strip()], None
    return [], None


def _scalar_property_values(
    block: str, key: str
) -> tuple[list[str], str | None]:
    values: list[str] = []
    first_line = block.splitlines()[0] if block else ""
    shorthand = re.match(rf"^\s*-\s*{re.escape(key)}:\s*(.*)$", first_line)
    if shorthand:
        read_values, err = _read_yaml_scalar_value(shorthand.group(1), block, 0)
        if err:
            return [], err
        values.extend(read_values)
        return values, None
    children = _direct_children(block)
    for child_name, child_block in children:
        if child_name != key:
            continue
        first = child_block.splitlines()[0]
        match = re.match(rf"^{re.escape(key)}:\s*(.*)$", first.strip())
        if match:
            read_values, err = _read_yaml_scalar_value(
                match.group(1), child_block, 0
            )
            if err:
                return [], err
            values.extend(read_values)
    return values, None


def _parse_continue_on_error(step_block: str) -> tuple[str, str | None]:
    values, err = _scalar_property_values(step_block, "continue-on-error")
    if err:
        return "unsupported", err
    if not values:
        return "absent", None
    if len(values) > 1:
        return "unsupported", "step has multiple continue-on-error values"
    value = values[0].strip()
    if value in {"false", "False"}:
        return "false", None
    if value in {"true", "True"}:
        return "true", None
    return "unsupported", None


def _count_run_keys(step_block: str) -> int:
    count = 0
    for line in step_block.splitlines():
        stripped = line.strip()
        if re.match(r"^-\s*run:", stripped) or re.match(r"^run:", stripped):
            count += 1
    return count


def _step_run_commands(step_block: str) -> tuple[list[str], str | None]:
    if _count_run_keys(step_block) > 1:
        return [], "step has multiple run values"
    first_line = step_block.splitlines()[0] if step_block else ""
    shorthand = re.match(r"^\s*-\s*run:\s*(.*)$", first_line)
    if shorthand:
        read_values, err = _read_yaml_scalar_value(shorthand.group(1), step_block, 0)
        if err:
            return [], err
        return read_values, None
    values, err = _scalar_property_values(step_block, "run")
    if err:
        return [], err
    if len(values) > 1:
        return [], "step has multiple run values"
    return values, None


def _analyze_workflow_step(
    step_block: str,
) -> tuple[list[str], str, str | None]:
    run_cmds, run_err = _step_run_commands(step_block)
    if run_err:
        return [], "unsupported", run_err
    coe_status, coe_err = _parse_continue_on_error(step_block)
    if coe_err:
        return run_cmds, "unsupported", coe_err
    return run_cmds, coe_status, None


def _validate_workflow_edit(ctx: RepoContext, *, complete: bool) -> list[str]:
    path = ctx.root / WORKFLOW_EDIT_PATH
    if not path.is_file():
        return [f"missing workflow edit file: {WORKFLOW_EDIT_PATH}"]
    if not complete:
        return []
    workflow = path.read_text(encoding="utf-8")
    jobs, job_errors = _workflow_jobs(workflow)
    errors: list[str] = list(job_errors)
    if any(name == "phase-1-evidence" for name, _ in jobs):
        errors.append("workflow edit must remove phase-1-evidence job")
    gate_jobs: list[str] = []
    for name, block in jobs:
        steps, step_errors = _job_steps(block)
        errors.extend(f"workflow job {name}: {err}" for err in step_errors)
        for step in steps:
            run_cmds, coe_status, step_err = _analyze_workflow_step(step)
            if step_err:
                errors.append(f"workflow job {name}: {step_err}")
                continue
            for run_cmd in run_cmds:
                parsed = _parse_shell_command(run_cmd)
                if _is_canonical_gate(parsed):
                    if coe_status in {"true", "unsupported"}:
                        errors.append(
                            f"workflow job {name} must not use continue-on-error "
                            "for finalization-check"
                        )
                    elif coe_status in {"absent", "false"}:
                        gate_jobs.append(name)
                for legacy in LEGACY_ONLY_STEPS:
                    if _command_has_forbidden_make(parsed, legacy):
                        errors.append(
                            f"workflow job {name} must not invoke "
                            f"legacy target {legacy}"
                        )
                if _command_has_forbidden_make(
                    parsed, "finalization-check-target"
                ):
                    errors.append(
                        f"workflow job {name} must not invoke "
                        "make finalization-check-target"
                    )
    if len(gate_jobs) != 1:
        errors.append(
            "workflow edit must have exactly one job invoking "
            "make finalization-check"
        )
    return errors


def _validate_entry_points(ctx: RepoContext, rules: StageRules) -> list[str]:
    scripts = ctx.pyproject.get("project", {}).get("scripts", {})
    if not isinstance(scripts, dict):
        return ["pyproject.toml missing project.scripts"]
    errors: list[str] = []
    names = set(scripts)
    for entry in rules.required_entry_points:
        if entry not in names:
            errors.append(f"missing target entry point: {entry}")
    for legacy in rules.forbidden_entry_points:
        if legacy in names:
            errors.append(f"legacy entry point still present: {legacy}")
    for name, value in scripts.items():
        if not isinstance(value, str):
            errors.append(f"entry point {name!r} must be a string")
            continue
        module = value.split(":", 1)[0].strip()
        if module == "psychoanalyst_app" or module.startswith("psychoanalyst_app."):
            errors.append(f"legacy entry point value still present: {name}")
    for entry in rules.required_entry_points:
        if entry in scripts and isinstance(scripts[entry], str):
            expected = TARGET_ENTRY_POINTS[entry]
            if scripts[entry] != expected:
                errors.append(
                    f"entry point {entry!r} must be {expected!r}, "
                    f"got {scripts[entry]!r}"
                )
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
        errors.extend(_gate_errors(ctx.targets, gate))
    errors.extend(_validate_runtime(ctx, rules.expected_runtime_argv))

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
