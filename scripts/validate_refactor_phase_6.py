#!/usr/bin/env python3
"""Semantic cutover checks for Phase 6 legacy deletion."""
from __future__ import annotations

import argparse
import ast
import json
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
KIND_ACTIONS: dict[str, frozenset[str]] = {
    "filesystem": frozenset(
        {"delete", "port_then_delete", "reimplement_then_delete", "retain"}
    ),
    "make_target": frozenset({"delete", "retain"}),
    "workflow": frozenset({"delete", "retain"}),
    "workflow_edit": frozenset({"edit"}),
}
PHASE_5_SCRIPT = "scripts/validate_refactor_phase_5.py"
PHASE_6_SCRIPT = "scripts/validate_refactor_phase_6.py"
PREPARE_RUNTIME_DIRS = "prepare-runtime-dirs"
DOCKER_TEST_PREFIX = ("docker", "compose", "--profile", "test", "run", "--rm", "test")
MAKE_TOKENS = frozenset({"make", "$(MAKE)", "${MAKE}"})
FORBIDDEN_MAKE_CONTROLS = frozenset({
    "MAKEFLAGS", "MFLAGS", "GNUMAKEFLAGS", "MAKEFILES", "SHELL",
    ".SHELLFLAGS", ".ONESHELL", ".RECIPEPREFIX",
})
TARGET_SUPPORT_TESTS_VAR = "$(TARGET_SUPPORT_TESTS)"
FORBIDDEN_IMPORT_ROOTS = (
    "psychoanalyst_app", "trio", "pytest_trio", "quart", "quart_trio",
    "quart_cors", "trio_websocket", "hypercorn",
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
PREPARE_RUNTIME_RECIPES = (
    "@mkdir -p data logs logs/workflow-probes",
    (
        '@if [ "$${CI:-}" = "true" ]; then chmod -R a+rwX data logs; '
        "else chmod -R u+rwX,g+rwX data logs; fi"
    ),
)
FORBIDDEN_API_BASE_KEYS = frozenset({
    "entrypoint", "image", "extends", "profiles", "deploy", "scale",
})
FORBIDDEN_API_LOCAL_KEYS = (
    FORBIDDEN_API_BASE_KEYS | frozenset({"command", "build"})
)
SELECTED_DOCKER_STAGE = "development"
REQUIRED_BUILD_VALUES = {
    "context": ".",
    "dockerfile": "Dockerfile",
    "target": SELECTED_DOCKER_STAGE,
}
YAML_SIMPLE_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
EVAL_RE = re.compile(r"\$\(\s*eval\b|\$\{\s*eval\b")
REQUIRED_WORKFLOW_ITEM = frozenset({("workflow_edit", WORKFLOW_EDIT_PATH)})
EXPECTED_COMPLETED_WORKFLOW = (
    "name: Release Candidate Validation\n"
    "on:\n  push:\n    branches:\n      - master\n      - main\n      - develop\n"
    "  pull_request:\n    branches:\n      - master\n      - main\n      - develop\n"
    "jobs:\n  finalization-check:\n    name: Docker Finalization Check\n"
    "    runs-on: ubuntu-latest\n    timeout-minutes: 60\n    env:\n"
    "      ENV_FILE: .env.example\n    steps:\n"
    "      - name: Checkout code\n        uses: actions/checkout@v4\n"
    "      - name: Run Docker release-candidate gate\n"
    "        run: make finalization-check\n"
    "      - name: Check whitespace and stale generated diffs\n"
    "        run: git diff --check && git diff --exit-code"
)
WATCHED_PRE_CUTOVER = frozenset({
    PREPARE_RUNTIME_DIRS, "finalization-check", "finalization-check-target", "lint",
    "validate-docs", "validate-schemas", "validate-generated-contracts",
    "validate-architecture", "test-validate", "test-target", "characterization-smoke",
    "probe-console-deterministic", "probe-console-v1-deterministic",
})
WATCHED_CUTOVER = frozenset({
    PREPARE_RUNTIME_DIRS, "finalization-check", "finalization-check-target", "lint",
    "validate-docs", "test-target", "probe-console-v1-deterministic",
})

@dataclass(frozen=True, slots=True)
class GateContract:
    prerequisites: tuple[str, ...]
    recipes: tuple[tuple[str, ...], ...]

def _legacy_gate() -> GateContract:
    return GateContract(
        prerequisites=(PREPARE_RUNTIME_DIRS,),
        recipes=(
            ("make", "lint"),
            ("make", "validate-docs"),
            ("make", "validate-schemas"),
            ("make", "validate-generated-contracts"),
            ("make", "validate-architecture"),
            ("make", "test-validate"),
            ("docker-python", PHASE_5_SCRIPT),
            ("make", "characterization-smoke"),
            ("make", "probe-console-deterministic"),
        ),
    )
def _target_gate(stage: str) -> GateContract:
    return GateContract(
        prerequisites=(PREPARE_RUNTIME_DIRS,),
        recipes=(
            ("make", "lint"),
            ("make", "validate-docs"),
            ("make", "test-target"),
            ("docker-python", PHASE_6_SCRIPT, "--stage", stage),
            ("docker-python", PHASE_5_SCRIPT),
            ("make", "probe-console-v1-deterministic"),
        ),
    )

@dataclass(frozen=True, slots=True)
class StageRules:
    manifest_status: str
    expected_runtime_argv: tuple[str, ...]
    gates: tuple[tuple[str, GateContract], ...]
    watched_targets: frozenset[str]
    forbidden_targets: frozenset[str]
    required_entry_points: frozenset[str]
    forbidden_entry_points: frozenset[str]
    final_closure: bool
    required_complete_items: frozenset[tuple[str, str]] = frozenset()

STAGES: dict[str, StageRules] = {
    "pre-cutover": StageRules(
        manifest_status="active",
        expected_runtime_argv=LEGACY_RUNTIME_ARGV,
        gates=(
            ("finalization-check", _legacy_gate()),
            ("finalization-check-target", _target_gate("pre-cutover")),
        ),
        watched_targets=WATCHED_PRE_CUTOVER,
        forbidden_targets=frozenset(),
        required_entry_points=frozenset(),
        forbidden_entry_points=frozenset(),
        final_closure=False,
    ),
    "cutover": StageRules(
        manifest_status="active",
        expected_runtime_argv=TARGET_RUNTIME_ARGV,
        gates=(("finalization-check", _target_gate("cutover")),),
        watched_targets=WATCHED_CUTOVER,
        forbidden_targets=frozenset({"finalization-check-target"}),
        required_entry_points=TARGET_ENTRY_CUTOVER,
        forbidden_entry_points=LEGACY_ENTRY_POINTS,
        final_closure=False,
        required_complete_items=REQUIRED_WORKFLOW_ITEM,
    ),
    "final": StageRules(
        manifest_status="completed",
        expected_runtime_argv=TARGET_RUNTIME_ARGV,
        gates=(("finalization-check", _target_gate("final")),),
        watched_targets=WATCHED_CUTOVER,
        forbidden_targets=frozenset({"finalization-check-target"}),
        required_entry_points=TARGET_ENTRY_FINAL,
        forbidden_entry_points=LEGACY_ENTRY_POINTS,
        final_closure=True,
        required_complete_items=REQUIRED_WORKFLOW_ITEM,
    ),
}

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
            raise ValueError(f"action {self.action!r} invalid for kind {self.kind!r}")
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
            raise ValueError(f"workflow_edit path must be {WORKFLOW_EDIT_PATH!r}")
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
    prefix: str
@dataclass(frozen=True, slots=True)
class ParsedMakeTarget:
    recipes: tuple[RecipeCommand, ...]
    prerequisites: tuple[str, ...]
@dataclass(frozen=True, slots=True)
class ParsedMakefile:
    definitions: dict[str, tuple[ParsedMakeTarget, ...]]
    phony: frozenset[str]
    errors: tuple[str, ...]
@dataclass(frozen=True, slots=True)
class MappingEntry:
    key: str
    value: str
    block: tuple[str, ...]
@dataclass(frozen=True, slots=True)
class RepoContext:
    root: Path
    makefile: ParsedMakefile
    makefile_text: str
    pyproject: dict[str, Any]
    compose: str
    dockerfile: str
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

def _load_repo_context(root: Path, watched: frozenset[str]) -> RepoContext:
    makefile_text = (root / "Makefile").read_text(encoding="utf-8")
    return RepoContext(
        root,
        _parse_makefile(makefile_text, watched),
        makefile_text,
        tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8")),
        (root / "docker-compose.yml").read_text(encoding="utf-8"),
        (root / "Dockerfile").read_text(encoding="utf-8"),
    )

def _parse_shell_command(text: str) -> tuple[tuple[str, ...] | None, str | None]:
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        lexer.commenters = "#"
        tokens: list[str] = []
        for token in lexer:
            if token and all(char in ";&|<>" for char in token):
                return None, "unsupported shell control"
            tokens.append(token)
    except ValueError as exc:
        return None, str(exc)
    if not tokens:
        return None, "empty command"
    return tuple(tokens), None
def _recipe_prefix(body: str) -> tuple[str, str]:
    prefix = ""
    rest = body
    while rest and rest[0] in "@-+":
        prefix += rest[0]
        rest = rest[1:].strip()
    return prefix, rest
def _header_targets(lhs: str) -> tuple[list[str], bool, bool]:
    is_double = "::" in lhs
    is_grouped = "&:" in lhs
    lhs_clean = lhs.replace("::", ":").replace("&:", ":")
    targets = [part for part in lhs_clean.split() if part]
    return targets, is_double, is_grouped
def _is_invalid_watched_header(
    lhs: str, rhs: str, watched: frozenset[str], *, is_double: bool
) -> list[str]:
    targets, _, is_grouped = _header_targets(lhs)
    errors: list[str] = []
    for name in targets:
        if name not in watched:
            continue
        if "%" in lhs:
            errors.append(f"{name} uses unsupported pattern target header")
        if ";" in rhs:
            errors.append(f"{name} uses unsupported inline recipe header")
        if is_double:
            errors.append(f"{name} uses unsupported double-colon definition")
        if is_grouped:
            errors.append(f"{name} uses unsupported grouped target header")
        if len(targets) > 1:
            errors.append(f"{name} uses unsupported multi-target header")
    return errors
def _detect_make_control(line: str) -> str | None:
    if line.startswith("\t"):
        return None
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if re.match(r"^\.IGNORE\b", stripped):
        return ".IGNORE"
    for control in FORBIDDEN_MAKE_CONTROLS:
        if control.startswith("."):
            if re.match(rf"^{re.escape(control)}\b", stripped):
                return control
        elif re.search(
            rf"(?:^|\s)(?:export|override|private)?\s*{re.escape(control)}\b",
            stripped,
        ):
            return control
        elif re.search(rf"^{re.escape(control)}\s*[:+?]?=", stripped):
            return control
        elif re.search(rf":\s*{re.escape(control)}\s*=", stripped):
            return control
        elif re.match(rf"^define\s+{re.escape(control)}\b", stripped):
            return control
    return None
def _detect_make_composition(line: str) -> str | None:
    if line.startswith("\t"):
        return None
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if re.match(r"^(?:include|-include|sinclude)\s+", stripped):
        return "Makefile include directives are unsupported"
    if EVAL_RE.search(stripped):
        return "Makefile eval expressions are unsupported"
    return None
def _parse_makefile(text: str, watched: frozenset[str]) -> ParsedMakefile:
    definitions: dict[str, list[ParsedMakeTarget]] = {}
    phony: set[str] = set()
    errors: list[str] = []
    current: str | None = None
    current_prereqs: tuple[str, ...] = ()
    current_recipes: list[RecipeCommand] = []
    pending: str | None = None
    pending_prefix = ""
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        composition = _detect_make_composition(line)
        if composition:
            errors.append(composition)
        control = _detect_make_control(line)
        if control:
            if control == ".IGNORE":
                errors.append("Makefile must not declare .IGNORE")
            else:
                errors.append(f"Makefile declares forbidden control {control}")
        if line and not line.startswith("\t") and ":" in line:
            if current is not None:
                definitions.setdefault(current, []).append(
                    ParsedMakeTarget(tuple(current_recipes), current_prereqs)
                )
            lhs, rhs = line.split(":", 1)
            if lhs.strip().startswith("."):
                if lhs.strip() == ".PHONY":
                    phony.update(token for token in rhs.split() if token)
                current = None
                pending = None
                continue
            lhs_stripped = lhs.strip()
            is_double = "::" in line
            if "$" in lhs_stripped:
                errors.append("variable-expanded target headers are unsupported")
            targets, _, _ = _header_targets(lhs)
            errors.extend(
                _is_invalid_watched_header(lhs, rhs, watched, is_double=is_double)
            )
            if len(targets) != 1:
                current = None
                pending = None
                continue
            current = targets[0]
            prereq_part = rhs.split(";", 1)[0]
            current_prereqs = tuple(token for token in prereq_part.split() if token)
            current_recipes = []
            pending = None
            continue
        if not line.startswith("\t") or current is None:
            continue
        body = line[1:].strip()
        if not body or body.startswith("#"):
            continue
        if pending is None:
            pending_prefix, pending = _recipe_prefix(body)
        else:
            pending = f"{pending} {body}"
        if body.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        current_recipes.append(RecipeCommand(text=pending, prefix=pending_prefix))
        pending = None
        pending_prefix = ""
    if current is not None:
        definitions.setdefault(current, []).append(
            ParsedMakeTarget(tuple(current_recipes), current_prereqs)
        )
    return ParsedMakefile(
        definitions={name: tuple(items) for name, items in definitions.items()},
        phony=frozenset(phony),
        errors=tuple(errors),
    )

def _normalize_gate_recipe(
    command: RecipeCommand,
) -> tuple[tuple[str, ...] | None, str | None]:
    if command.prefix:
        return None, "unsupported recipe prefix"
    argv, err = _parse_shell_command(command.text)
    if err or argv is None:
        return None, err or "unsupported recipe"
    if len(argv) == 2 and argv[0] in MAKE_TOKENS:
        return ("make", argv[1]), None
    docker_prefix = DOCKER_TEST_PREFIX + ("python",)
    prefix_len = len(docker_prefix)
    if len(argv) >= prefix_len and argv[:prefix_len] == docker_prefix:
        return ("docker-python", *argv[prefix_len:]), None
    return None, f"unsupported recipe: {command.text!r}"

def _validate_makefile_contracts(
    makefile: ParsedMakefile, rules: StageRules
) -> list[str]:
    errors = list(makefile.errors)
    active_targets = rules.watched_targets - rules.forbidden_targets
    phony_required = active_targets
    for name in phony_required:
        if name not in makefile.phony:
            errors.append(f"{name} must be phony")
        if name == PREPARE_RUNTIME_DIRS:
            continue
        defs = makefile.definitions.get(name, ())
        if len(defs) != 1:
            errors.append(f"{name} must have exactly one definition, got {len(defs)}")
    defs = makefile.definitions.get(PREPARE_RUNTIME_DIRS, ())
    if len(defs) != 1:
        errors.append(
            f"{PREPARE_RUNTIME_DIRS} must have exactly one definition, got {len(defs)}"
        )
    else:
        target = defs[0]
        if target.prerequisites:
            errors.append(f"{PREPARE_RUNTIME_DIRS} must have no prerequisites")
        elif len(target.recipes) != 2:
            errors.append(f"{PREPARE_RUNTIME_DIRS} must have exactly two recipes")
        else:
            texts = tuple(f"{cmd.prefix}{cmd.text}" for cmd in target.recipes)
            if texts != PREPARE_RUNTIME_RECIPES:
                errors.append(f"{PREPARE_RUNTIME_DIRS} recipe contract mismatch")
    for forbidden in rules.forbidden_targets:
        if forbidden in makefile.definitions:
            errors.append(f"{forbidden} must be absent after cutover")
    for target_name, expected in rules.gates:
        gate_defs = makefile.definitions.get(target_name, ())
        if len(gate_defs) != 1:
            continue
        gate = gate_defs[0]
        if gate.prerequisites != expected.prerequisites:
            errors.append(
                f"{target_name} prerequisite contract mismatch: "
                f"expected {expected.prerequisites!r}, got {gate.prerequisites!r}"
            )
        normalization_failed = False
        recipes: list[tuple[str, ...]] = []
        for command in gate.recipes:
            normalized, err = _normalize_gate_recipe(command)
            if err:
                errors.append(f"{target_name}: {err}")
                normalization_failed = True
                break
            assert normalized is not None
            recipes.append(normalized)
        if not normalization_failed:
            actual = tuple(recipes)
            if actual != expected.recipes:
                errors.append(
                    f"{target_name} recipe contract mismatch: "
                    f"expected {expected.recipes!r}, got {actual!r}"
                )
    return errors

def _is_comment_or_blank(line: str) -> bool:
    return not line.strip() or line.lstrip().startswith("#")
def _valid_compose_key(key: str, *, allow_merge: bool) -> bool:
    if key == "<<":
        return allow_merge
    return YAML_SIMPLE_KEY_RE.fullmatch(key) is not None
def _plain_compose_scalar(value: str) -> bool:
    return (
        bool(value)
        and value not in {"|", "|-", "|+", ">", ">-", ">+"}
        and value[0] not in "\"'"
        and not value.startswith(("{", "["))
    )
def _mapping_entries(
    lines: tuple[str, ...],
    *,
    parent_indent: int,
    label: str,
    allow_merge: bool = False,
) -> tuple[tuple[MappingEntry, ...], str | None]:
    child_indent: int | None = None
    entries: list[MappingEntry] = []
    current_key: str | None = None
    current_value = ""
    current_block: list[str] = []
    for line in lines:
        if _is_comment_or_blank(line):
            if current_key is not None:
                current_block.append(line)
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= parent_indent:
            break
        if child_indent is None:
            child_indent = indent
        if indent == child_indent:
            if current_key is not None:
                entries.append(
                    MappingEntry(current_key, current_value, tuple(current_block))
                )
            stripped = line.strip()
            if stripped.startswith("- "):
                return (), f"{label} contains unsupported list syntax"
            if stripped.startswith("?"):
                return (), f"{label} contains unsupported mapping syntax"
            if stripped.startswith("---"):
                return (), f"{label} contains unsupported document syntax"
            match = re.match(r"([^:]+):\s*(.*)$", stripped)
            if not match:
                return (), f"{label} contains unsupported mapping syntax"
            raw_key = match.group(1).strip()
            if not _valid_compose_key(raw_key, allow_merge=allow_merge):
                return (), f"{label} contains unsupported mapping syntax"
            current_key = raw_key
            current_value = match.group(2).strip()
            current_block = [line]
        elif current_key is not None and indent > child_indent:
            current_block.append(line)
    if current_key is not None:
        entries.append(MappingEntry(current_key, current_value, tuple(current_block)))
    return tuple(entries), None
def _named(entries: tuple[MappingEntry, ...], key: str) -> list[MappingEntry]:
    return [entry for entry in entries if entry.key == key]
def _child_entries(
    block: tuple[str, ...], label: str, *, allow_merge: bool = False
) -> tuple[tuple[MappingEntry, ...], str | None]:
    indent = len(block[0]) - len(block[0].lstrip())
    return _mapping_entries(
        block[1:], parent_indent=indent, label=label, allow_merge=allow_merge
    )
def _scalar_to_argv(raw: str) -> tuple[tuple[str, ...] | None, str | None]:
    if not _plain_compose_scalar(raw):
        return None, "unsupported scalar syntax"
    argv, err = _parse_shell_command(raw)
    if err:
        return None, err
    if argv is None:
        return None, "command must not be empty"
    return argv, None

def _validate_compose_runtime(
    compose: str, expected_argv: tuple[str, ...]
) -> list[str]:
    errors: list[str] = []
    root_entries, root_err = _mapping_entries(
        tuple(compose.splitlines()), parent_indent=-1, label="docker-compose root"
    )
    if root_err:
        return [root_err]
    api_base = _named(root_entries, "x-api-base")
    services = _named(root_entries, "services")
    if len(api_base) != 1:
        errors.append("docker-compose must have exactly one x-api-base block")
    if len(services) != 1:
        errors.append("docker-compose.yml must have exactly one services block")
    if errors:
        return errors
    anchor = api_base[0]
    if anchor.block[0].strip() != "x-api-base: &api-base":
        errors.append(
            "docker-compose must have exactly one x-api-base: &api-base anchor"
        )
    anchor_children, anchor_err = _child_entries(anchor.block, "x-api-base")
    if anchor_err:
        return [anchor_err]
    for entry in anchor_children:
        if entry.key in FORBIDDEN_API_BASE_KEYS:
            errors.append(f"x-api-base must not declare {entry.key!r}")
    builds = _named(anchor_children, "build")
    commands = _named(anchor_children, "command")
    if len(builds) != 1:
        errors.append("x-api-base must have exactly one build key")
    if len(commands) != 1:
        errors.append("x-api-base must have exactly one command key")
    if builds:
        build_children, build_err = _child_entries(builds[0].block, "x-api-base build")
        if build_err:
            errors.append(build_err)
        else:
            for key, expected in REQUIRED_BUILD_VALUES.items():
                matches = _named(build_children, key)
                if len(matches) != 1:
                    errors.append(f"x-api-base build missing {key}")
                elif not _plain_compose_scalar(matches[0].value):
                    errors.append(
                        f"x-api-base build.{key} uses unsupported scalar syntax"
                    )
                elif matches[0].value != expected:
                    errors.append(
                        f"docker-compose build.{key} must be {expected!r}, "
                        f"got {matches[0].value!r}"
                    )
    if commands:
        compose_argv, argv_err = _scalar_to_argv(commands[0].value)
        if argv_err:
            errors.append(f"docker-compose api command is invalid: {argv_err}")
        elif compose_argv != expected_argv:
            errors.append(
                f"docker-compose api command must select {expected_argv!r}, "
                f"got {compose_argv!r}"
            )
    service_children, service_err = _child_entries(services[0].block, "services")
    if service_err:
        return errors + [service_err]
    api_entries = _named(service_children, "api")
    if len(api_entries) != 1:
        return errors + ["docker-compose.yml must have exactly one services.api block"]
    api_children, api_err = _child_entries(
        api_entries[0].block, "services.api", allow_merge=True
    )
    if api_err:
        return errors + [api_err]
    for entry in api_children:
        if entry.key in FORBIDDEN_API_LOCAL_KEYS:
            errors.append(f"services.api must not declare local {entry.key!r}")
    merges = _named(api_children, "<<")
    if len(merges) != 1:
        errors.append("services.api must have exactly one merge key")
    elif merges[0].value != "*api-base":
        errors.append("services.api merge must be <<: *api-base")
    return errors

def _dockerfile_stage_cmd(
    dockerfile: str, stage_name: str
) -> tuple[tuple[str, ...] | None, str | None]:
    if re.search(
        r"^[ \t]*(?:ONBUILD[ \t]+)?ENTRYPOINT\b",
        dockerfile,
        re.IGNORECASE | re.MULTILINE,
    ):
        return None, "Dockerfile ENTRYPOINT is unsupported"
    stages: list[tuple[str, list[str]]] = []
    current_name = "final"
    current_lines: list[str] = []
    for line in dockerfile.splitlines():
        stage_match = re.match(r"^FROM\b.*\sAS\s+(\S+)", line, re.IGNORECASE)
        if stage_match:
            if current_lines:
                stages.append((current_name, current_lines))
            current_name = stage_match.group(1)
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_lines:
        stages.append((current_name, current_lines))
    matches = [lines for name, lines in stages if name == stage_name]
    if len(matches) != 1:
        return None, f"Dockerfile must define exactly one {stage_name!r} stage"
    stage_text = "\n".join(matches[0])
    cmd_matches = list(
        re.finditer(r"^\s*CMD\s+(\[[^\]]*\]|.+?)\s*$", stage_text, re.MULTILINE)
    )
    if len(cmd_matches) != 1:
        return None, f"Dockerfile stage {stage_name!r} must define exactly one CMD"
    raw = cmd_matches[0].group(1).strip()
    if not raw.startswith("["):
        return None, "Dockerfile CMD must use JSON exec form"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None, "Dockerfile CMD exec form is malformed"
    if not isinstance(parsed, list) or not parsed:
        return None, "Dockerfile CMD exec form must be a non-empty list"
    if not all(isinstance(item, str) and item for item in parsed):
        return None, "Dockerfile CMD exec form must contain only non-empty strings"
    return tuple(parsed), None

def _validate_runtime(ctx: RepoContext, rules: StageRules) -> list[str]:
    errors = _validate_compose_runtime(ctx.compose, rules.expected_runtime_argv)
    if errors:
        return errors
    docker_argv, docker_err = _dockerfile_stage_cmd(
        ctx.dockerfile, SELECTED_DOCKER_STAGE
    )
    if docker_err:
        return [docker_err]
    if docker_argv != rules.expected_runtime_argv:
        return [
            f"Dockerfile stage {SELECTED_DOCKER_STAGE!r} CMD must select "
            f"{rules.expected_runtime_argv!r}, got {docker_argv!r}"
        ]
    return []
def _normalize_workflow_text(text: str) -> str:
    return "\n".join(
        line.rstrip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
def _validate_workflow_edit(ctx: RepoContext, *, complete: bool) -> list[str]:
    path = ctx.root / WORKFLOW_EDIT_PATH
    if not path.is_file():
        return [f"missing workflow edit file: {WORKFLOW_EDIT_PATH}"]
    canonical = _normalize_workflow_text(EXPECTED_COMPLETED_WORKFLOW)
    actual = _normalize_workflow_text(path.read_text(encoding="utf-8"))
    if complete and actual != canonical:
        return ["completed release workflow does not match canonical contract"]
    return []

def _manifest_path_present(ctx: RepoContext, item: ManifestItem) -> bool:
    if item.kind == "make_target":
        return item.path in ctx.makefile.definitions
    path = ctx.root / item.path.rstrip("/")
    return path.exists() or path.is_symlink()
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
def _pytest_argv_offset(argv: tuple[str, ...]) -> int | None:
    if not argv:
        return None
    if argv[0] == "pytest":
        return 0
    docker_prefix = DOCKER_TEST_PREFIX + ("pytest",)
    prefix_len = len(docker_prefix)
    if len(argv) >= prefix_len and argv[:prefix_len] == docker_prefix:
        return prefix_len
    return None
def _pytest_arguments(makefile: ParsedMakefile) -> tuple[tuple[str, ...], ...]:
    defs = makefile.definitions.get("test-target", ())
    if len(defs) != 1:
        return ()
    arguments: list[tuple[str, ...]] = []
    for command in defs[0].recipes:
        if "-" in command.prefix or "+" in command.prefix:
            continue
        argv, err = _parse_shell_command(command.text)
        if err or argv is None:
            continue
        offset = _pytest_argv_offset(argv)
        if offset is None:
            continue
        arguments.append(argv[offset:])
    return tuple(arguments)
def _test_target_references_path(ctx: RepoContext, path: str) -> bool:
    normalized = _norm_fs_path(path)
    args_list = _pytest_arguments(ctx.makefile)
    if normalized in _target_support_test_paths(ctx.makefile_text):
        if any(TARGET_SUPPORT_TESTS_VAR in args for args in args_list):
            return True
    return any(
        normalized in {_norm_fs_path(token) for token in args} for args in args_list
    )
def _validate_item_complete(ctx: RepoContext, item: ManifestItem) -> list[str]:
    errors: list[str] = []
    if item.action in {"delete", "port_then_delete", "reimplement_then_delete"}:
        for relative in item.replacements + item.evidence:
            if not (ctx.root / relative).exists():
                errors.append(f"missing path: {relative}")
        if _manifest_path_present(ctx, item):
            errors.append(f"complete item still present: {item.path}")
    elif item.action == "retain":
        if not _manifest_path_present(ctx, item):
            errors.append(f"retained path missing: {item.path}")
        if (
            item.requires_explicit_test_target_reference
            and not _test_target_references_path(ctx, item.path)
        ):
            errors.append(
                f"retained test not referenced in test-target recipe: {item.path}"
            )
    elif item.action == "edit" and item.kind == "workflow_edit":
        errors.extend(_validate_workflow_edit(ctx, complete=True))
    return errors
def _validate_entry_points(ctx: RepoContext, rules: StageRules) -> list[str]:
    scripts = ctx.pyproject.get("project", {}).get("scripts", {})
    if not isinstance(scripts, dict):
        return ["pyproject.toml missing project.scripts"]
    errors: list[str] = []
    names = set(scripts)
    for entry in rules.required_entry_points - names:
        errors.append(f"missing target entry point: {entry}")
    for legacy in rules.forbidden_entry_points & names:
        errors.append(f"legacy entry point still present: {legacy}")
    for name, value in scripts.items():
        if not isinstance(value, str):
            errors.append(f"entry point {name!r} must be a string")
            continue
        module = value.split(":", 1)[0].strip()
        if module == "psychoanalyst_app" or module.startswith("psychoanalyst_app."):
            errors.append(f"legacy entry point value still present: {name}")
        elif name in rules.required_entry_points and value != TARGET_ENTRY_POINTS[name]:
            expected = TARGET_ENTRY_POINTS[name]
            errors.append(
                f"entry point {name!r} must be {expected!r}, got {value!r}"
            )
    return errors
def _validate_import_closure(root: Path) -> list[str]:
    errors: list[str] = []
    for base in (root / "src", root / "scripts", root / "tests"):
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                modules: list[str] = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules = [node.module]
                for module in modules:
                    root_name = module.split(".")[0]
                    if root_name in FORBIDDEN_IMPORT_ROOTS or root_name.startswith(
                        "langchain"
                    ):
                        rel = path.relative_to(root)
                        errors.append(f"{rel} imports forbidden module {module}")
    return errors
def _validate_dependency_closure(ctx: RepoContext) -> list[str]:
    errors: list[str] = []
    names: set[str] = set()
    deps = ctx.pyproject.get("project", {}).get("dependencies", [])
    if isinstance(deps, list):
        for dep in deps:
            if isinstance(dep, str):
                names.add(_norm_pkg_name(dep.split(";")[0].strip()))
    for req_name in ("requirements.txt", "requirements-dev.txt"):
        req_path = ctx.root / req_name
        if req_path.is_file():
            for line in req_path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    token = re.split(r"[<>=!~\[]", stripped, maxsplit=1)[0].strip()
                    if token:
                        names.add(_norm_pkg_name(token))
    for forbidden in FORBIDDEN_DEP_PREFIXES:
        normalized = _norm_pkg_name(forbidden)
        if any(name == normalized or name.startswith(normalized) for name in names):
            errors.append(f"forbidden dependency remains: {forbidden}")
    package_data = (
        ctx.pyproject.get("tool", {}).get("setuptools", {}).get("package-data", {})
    )
    if isinstance(package_data, dict) and "psychoanalyst_app" in package_data:
        errors.append("pyproject package-data still references psychoanalyst_app")
    return errors
def _final_manifest_closure(manifest: Manifest) -> list[str]:
    return [
        f"manifest item not complete: {item.path}"
        for item in manifest.items
        if item.status != "complete"
    ] + [
        f"discovery-needed item remains: {item.path}"
        for item in manifest.items
        if item.confidence == "discovery-needed"
    ]

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
    ctx = _load_repo_context(resolved, rules.watched_targets)
    errors.extend(_validate_makefile_contracts(ctx.makefile, rules))
    errors.extend(_validate_runtime(ctx, rules))
    if rules.required_entry_points or rules.forbidden_entry_points:
        errors.extend(_validate_entry_points(ctx, rules))
    for item in manifest.items:
        if item.status == "complete":
            errors.extend(_validate_item_complete(ctx, item))
    for kind, path in rules.required_complete_items:
        item = next(
            (row for row in manifest.items if row.kind == kind and row.path == path),
            None,
        )
        if item is None:
            errors.append(f"required complete item missing from manifest: {path}")
        elif item.status != "complete":
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
