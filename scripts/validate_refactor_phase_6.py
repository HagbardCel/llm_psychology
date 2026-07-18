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

OWNERS = frozenset({"6A", "6B", "6C", "6D"})
KIND_ACTIONS: dict[str, frozenset[str]] = {
    "filesystem": frozenset(
        {"delete", "port_then_delete", "reimplement_then_delete", "retain", "edit"}
    ),
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
TARGET_ENTRY_POINTS = {
    "jung-api": "jung.api.app:cli",
    "jung-console": "jung.client.terminal:cli",
    "jung-db": "jung.tools.db_backup:main",
}
TARGET_ENTRY_CUTOVER = frozenset({"jung-api", "jung-console"})
TARGET_ENTRY_FINAL = frozenset(TARGET_ENTRY_POINTS)
MAKE_TARGET_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


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

    @field_validator("path", mode="before")
    @classmethod
    def normalize_path(cls, value: Any, info: Any) -> Any:
        if not isinstance(value, str):
            return value
        kind = info.data.get("kind")
        if kind == "make_target":
            return value.strip()
        return _norm_fs_path(value.strip())

    @field_validator("replacements", "evidence", mode="before")
    @classmethod
    def normalize_path_list(cls, value: Any) -> Any:
        if value is None:
            return ()
        if not isinstance(value, list):
            return value
        return value

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
            if self.kind in {"workflow", "workflow_edit"}:
                if not self.path.startswith(".github/workflows/"):
                    raise ValueError(
                        "workflow path must be under .github/workflows/"
                    )
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
class ParsedValue:
    present: bool
    value: str | None = None
    error: str | None = None


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

    unknown_top = set(data) - {"schema_version", "status", "items"}
    if unknown_top:
        return None, [
            "manifest has unknown top-level field(s): "
            + ", ".join(sorted(unknown_top))
        ]

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


def _direct_child_indent(parent_block: str) -> int | None:
    parent_indent = None
    for line in parent_block.splitlines():
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if parent_indent is None:
            parent_indent = indent
            continue
        if indent > parent_indent:
            return indent
    return None


def _direct_children(parent_block: str) -> dict[str, str]:
    lines = parent_block.splitlines()
    if not lines:
        return {}
    child_indent = _direct_child_indent(parent_block)
    if child_indent is None:
        return {}
    children: dict[str, list[str]] = {}
    current_name: str | None = None
    for line in lines[1:]:
        if not line.strip():
            if current_name is not None:
                children[current_name].append(line)
            continue
        indent = len(line) - len(line.lstrip())
        if indent < child_indent:
            break
        if indent == child_indent:
            match = re.match(r"(\S+):\s*(.*)$", line.strip())
            if match:
                current_name = match.group(1)
                children[current_name] = [line]
            else:
                current_name = None
        elif current_name is not None and indent > child_indent:
            children[current_name].append(line)
    return {name: "\n".join(block) for name, block in children.items()}


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
    api_blocks = [name for name in children if name == "api"]
    if not api_blocks:
        return None, "docker-compose.yml missing services.api block"
    if len(api_blocks) > 1:
        return None, "docker-compose.yml has multiple services.api blocks"
    return children["api"], None


def _merge_aliases(service_block: str) -> tuple[list[str], str | None]:
    aliases = re.findall(r"<<:\s*\*(\S+)", service_block)
    if len(aliases) > 1:
        return aliases, "docker-compose api has multiple merge aliases"
    return aliases, None


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
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent != child_indent:
            continue
        match = re.match(rf"{re.escape(key)}:\s*(.*)$", line.strip())
        if match:
            matches.append((index, match.group(1).strip()))
    return matches


def _parse_inline_command_list(raw: str) -> tuple[str | None, str | None]:
    if not raw.startswith("["):
        return None, "command inline list must start with ["
    try:
        parsed = ast.literal_eval(raw)
    except (SyntaxError, ValueError):
        return None, "command inline list is malformed"
    if not isinstance(parsed, list) or not parsed:
        return None, "command inline list must be a non-empty list of strings"
    if not all(isinstance(item, str) and item for item in parsed):
        return None, "command inline list must contain only non-empty strings"
    return " ".join(parsed), None


def _parse_block_command_list(
    block: str, key_line_index: int
) -> tuple[str | None, str | None]:
    lines = block.splitlines()
    child_indent = _direct_child_indent(block)
    if child_indent is None:
        return None, "command block is malformed"
    list_indent = child_indent + 2
    items: list[str] = []
    for line in lines[key_line_index + 1 :]:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent < list_indent:
            break
        if indent != list_indent:
            return None, "command block contains unsupported child syntax"
        match = re.match(r"-\s*(.+)$", line.strip())
        if not match:
            return None, "command block contains unsupported child syntax"
        value = match.group(1).strip().strip("'\"")
        if not value:
            return None, "command block list items must be non-empty strings"
        items.append(value)
    if not items:
        return None, "command block list must be non-empty"
    return " ".join(items), None


def _extract_yaml_command(block: str) -> ParsedValue:
    matches = _extract_direct_scalar(block, "command")
    if not matches:
        return ParsedValue(present=False)
    if len(matches) > 1:
        return ParsedValue(
            present=True,
            error="docker-compose api has multiple command keys",
        )
    _, raw = matches[0]
    if not raw:
        key_index = next(
            i
            for i, line in enumerate(block.splitlines())
            if line.strip().startswith("command:")
        )
        value, err = _parse_block_command_list(block, key_index)
        if err:
            return ParsedValue(present=True, error=err)
        return ParsedValue(present=True, value=value)
    if raw.startswith("["):
        value, err = _parse_inline_command_list(raw)
        if err:
            return ParsedValue(present=True, error=err)
        return ParsedValue(present=True, value=value)
    return ParsedValue(present=True, value=raw.strip().strip("'\""))


def _extract_build_target(block: str) -> ParsedValue:
    build_children = _direct_children(block)
    build_blocks = [name for name in build_children if name == "build"]
    if not build_blocks:
        return ParsedValue(present=False)
    if len(build_blocks) > 1:
        return ParsedValue(
            present=True,
            error="docker-compose api has multiple build blocks",
        )
    build_block = build_children["build"]
    targets = _extract_direct_scalar(build_block, "target")
    if not targets:
        return ParsedValue(present=False)
    if len(targets) > 1:
        return ParsedValue(
            present=True,
            error="docker-compose api build has multiple target keys",
        )
    _, raw = targets[0]
    if not raw:
        return ParsedValue(present=True, error="docker-compose build target is empty")
    return ParsedValue(present=True, value=raw.strip().strip("'\""))


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


def _pick_parsed(local: ParsedValue, inherited: ParsedValue) -> ParsedValue | str:
    if local.error:
        return local.error
    if local.present:
        return local if local.value is not None else "present but invalid"
    if inherited.error:
        return inherited.error
    if inherited.present and inherited.value is not None:
        return inherited
    return ParsedValue(present=False)


def _resolve_api_build_target(compose: str) -> tuple[str | None, bool, str | None]:
    api_block, inherited_block, err = _api_service_layers(compose)
    if err:
        return None, False, err
    assert api_block is not None
    local = _extract_build_target(api_block)
    inherited = (
        _extract_build_target(inherited_block)
        if inherited_block is not None
        else ParsedValue(present=False)
    )
    picked = _pick_parsed(local, inherited)
    if isinstance(picked, str):
        return None, True, picked
    if picked.present and picked.value is not None:
        return picked.value, True, None
    return None, False, None


def _extract_compose_api_command(compose: str) -> tuple[str | None, str | None]:
    api_block, inherited_block, err = _api_service_layers(compose)
    if err:
        return None, err
    assert api_block is not None
    local = _extract_yaml_command(api_block)
    inherited = (
        _extract_yaml_command(inherited_block)
        if inherited_block is not None
        else ParsedValue(present=False)
    )
    picked = _pick_parsed(local, inherited)
    if isinstance(picked, str):
        return None, picked
    if picked.present and picked.value is not None:
        return picked.value, None
    return None, None


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

    compose_cmd, compose_err = _extract_compose_api_command(ctx.compose)
    if compose_err:
        errors.append(compose_err)
        return errors

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


def _split_job_steps(job_block: str) -> list[str]:
    lines = job_block.splitlines()
    steps_start = next(
        (
            index
            for index, line in enumerate(lines)
            if re.match(r"^\s*steps:\s*$", line)
        ),
        None,
    )
    if steps_start is None:
        return []
    steps: list[str] = []
    current: list[str] = []
    for line in lines[steps_start + 1 :]:
        if re.match(r"^\s*-\s", line):
            if current:
                steps.append("\n".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        steps.append("\n".join(current))
    return steps


def _extract_step_run_commands(step_block: str) -> list[str]:
    commands: list[str] = []
    lines = step_block.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        match = re.match(r"^\s*-\s*run:\s*(.*)$", line)
        if not match:
            index += 1
            continue
        remainder = match.group(1)
        if remainder in {"|", "|-", "|+", ">", ">-", ">+"}:
            folded = remainder.startswith(">")
            block_lines: list[str] = []
            index += 1
            while index < len(lines):
                next_line = lines[index]
                if re.match(r"^\s*-\s*\S", next_line):
                    break
                if next_line.strip():
                    block_lines.append(next_line.strip())
                index += 1
            if folded:
                folded_text = " ".join(block_lines).strip()
                if folded_text:
                    commands.append(folded_text)
            else:
                commands.extend(block_lines)
            continue
        if remainder:
            commands.append(remainder.strip())
        index += 1
    return commands


def _step_has_continue_on_error(step_block: str) -> bool:
    return bool(re.search(r"continue-on-error:\s*true\b", step_block))


def _is_exact_canonical_gate(command: str) -> bool:
    text = command.split("#", 1)[0].strip()
    if not text:
        return False
    if ";" in text or "||" in text or "&&" in text or "|" in text:
        return False
    tokens = _tokenize_command(text)
    return (
        len(tokens) == 2
        and tokens[0] in {"make", "$(MAKE)", "${MAKE}"}
        and tokens[1] == "finalization-check"
    )


def _job_run_commands(job_block: str) -> list[RecipeCommand]:
    commands: list[RecipeCommand] = []
    for step in _split_job_steps(job_block):
        ignored = _step_has_continue_on_error(step)
        for run_cmd in _extract_step_run_commands(step):
            commands.append(RecipeCommand(text=run_cmd, ignored_failure=ignored))
    return commands


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
        gate_jobs: list[str] = []
        for name, block in jobs.items():
            for step in _split_job_steps(block):
                ignored = _step_has_continue_on_error(step)
                run_commands = [
                    RecipeCommand(text=run_cmd, ignored_failure=ignored)
                    for run_cmd in _extract_step_run_commands(step)
                ]
                if any(
                    _is_exact_canonical_gate(cmd.text) and not cmd.ignored_failure
                    for cmd in run_commands
                ):
                    gate_jobs.append(name)
                if any(
                    _is_exact_canonical_gate(cmd.text) for cmd in run_commands
                ) and ignored:
                    errors.append(
                        f"workflow job {name} must not use continue-on-error "
                        "for finalization-check"
                    )
        if len(gate_jobs) != 1:
            errors.append(
                "workflow edit must have exactly one job invoking "
                "make finalization-check"
            )
        for name, block in jobs.items():
            run_commands = _job_run_commands(block)
            invoked = _invoked_make_targets(run_commands)
            if "finalization-check-target" in invoked:
                errors.append(
                    f"workflow job {name} must not invoke "
                    "make finalization-check-target"
                )
            for legacy in LEGACY_ONLY_STEPS:
                if legacy in invoked:
                    errors.append(
                        f"workflow job {name} must not invoke legacy target {legacy}"
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
