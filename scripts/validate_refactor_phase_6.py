#!/usr/bin/env python3
"""Semantic cutover checks for Phase 6 legacy deletion (architectural guardrail)."""
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
DOCKER_COMPOSE_RUN = (
    "docker", "compose", "-f", "docker-compose.yml",
    "--profile", "test", "run", "--rm", "--no-deps",
)
DOCKER_TEST_PREFIX = DOCKER_COMPOSE_RUN + ("test",)
DOCKER_PYTHON_PREFIX = DOCKER_COMPOSE_RUN + (
    "--entrypoint", "/usr/local/bin/python",
    "--volume", "$(CURDIR):/workspace:ro",
    "--workdir", "/workspace", "--env", "PYTHONPATH=/workspace/src", "test",
)
MAKE_TOKENS = frozenset({"make", "$(MAKE)", "${MAKE}"})
FORBIDDEN_MAKE_CONTROLS = frozenset({
    "MAKEFLAGS", "MFLAGS", "GNUMAKEFLAGS", "MAKEFILES", "SHELL",
    ".SHELLFLAGS", ".ONESHELL", ".RECIPEPREFIX",
    "COMPOSE_FILE", "MAKE", "PATH", "CURDIR",
    "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG",
})
TARGET_SUPPORT_TESTS_VAR = "$(TARGET_SUPPORT_TESTS)"
FORBIDDEN_IMPORT_ROOTS = (
    "psychoanalyst_app", "trio", "pytest_trio", "quart", "quart_trio",
    "quart_cors", "trio_websocket", "hypercorn",
)
FORBIDDEN_DEP_PREFIXES = FORBIDDEN_IMPORT_ROOTS + ("langchain",)
LEGACY_RUNTIME_ARGV = ("python", "-m", "psychoanalyst_app.server")
TARGET_RUNTIME_ARGV = ("jung-api",)
ENTRY_POINT_TARGETS = {
    "psychoanalyst-server": "psychoanalyst_app.server:cli",
    "jung-api": "jung.api.app:cli",
    "jung-console": "jung.client.terminal:cli",
}
PRE_CUTOVER_REQUIRED_ENTRY_POINTS = frozenset(
    {"psychoanalyst-server", "jung-api", "jung-console"}
)
TARGET_REQUIRED_ENTRY_POINTS = frozenset({"jung-api", "jung-console"})
PRE_CUTOVER_FORBIDDEN_ENTRY_POINTS = frozenset({"psychoanalyst-db", "jung-db"})
POST_CUTOVER_FORBIDDEN_ENTRY_POINTS = frozenset(
    {"psychoanalyst-server", "psychoanalyst-db", "jung-db"}
)
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
FORBIDDEN_API_LOCAL_KEYS = FORBIDDEN_API_BASE_KEYS | frozenset({"command", "build"})
FORBIDDEN_API_USERTEST_LOCAL_KEYS = (
    FORBIDDEN_API_BASE_KEYS - frozenset({"profiles"})
) | frozenset({"command", "build"})
FORBIDDEN_TEST_SERVICE_KEYS = frozenset({"entrypoint", "image", "extends"})
SELECTED_DOCKER_STAGE = "development"
REQUIRED_BUILD_VALUES = {
    "context": ".",
    "dockerfile": "Dockerfile",
    "target": SELECTED_DOCKER_STAGE,
}
REQUIRED_JUNG_ENVIRONMENT = {
    "JUNG_API_HOST": "0.0.0.0",
    "JUNG_API_PORT": '"8000"',
    "JUNG_API_ALLOW_REMOTE_BIND": '"true"',
}
FORBIDDEN_LEGACY_ENVIRONMENT_KEYS = frozenset(
    {"SERVER_HOST", "SERVER_PORT", "APP_ENV"}
)
REQUIRED_HEALTHCHECK_ARGV = (
    "CMD",
    "wget",
    "--no-verbose",
    "--tries=1",
    "-O",
    "/dev/null",
    "http://localhost:8000/api/v1/health",
)
YAML_SIMPLE_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
EVAL_RE = re.compile(r"\$\(\s*eval\b|\$\{\s*eval\b")
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

LEGACY_GATE = GateContract(
    prerequisites=(PREPARE_RUNTIME_DIRS,),
    recipes=(
        ("make", "lint"), ("make", "validate-docs"), ("make", "validate-schemas"),
        ("make", "validate-generated-contracts"), ("make", "validate-architecture"),
        ("make", "test-validate"), ("docker-python", PHASE_5_SCRIPT),
        ("make", "characterization-smoke"), ("make", "probe-console-deterministic"),
    ),
)

def _target_gate(stage: str) -> GateContract:
    return GateContract(
        prerequisites=(PREPARE_RUNTIME_DIRS,),
        recipes=(
            ("make", "lint"), ("make", "validate-docs"), ("make", "test-target"),
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
    required_complete_owner_prs: frozenset[str]

STAGES: dict[str, StageRules] = {
    "pre-cutover": StageRules(
        manifest_status="active",
        expected_runtime_argv=LEGACY_RUNTIME_ARGV,
        gates=(
            ("finalization-check", LEGACY_GATE),
            ("finalization-check-target", _target_gate("pre-cutover")),
        ),
        watched_targets=WATCHED_PRE_CUTOVER,
        forbidden_targets=frozenset(),
        required_entry_points=PRE_CUTOVER_REQUIRED_ENTRY_POINTS,
        forbidden_entry_points=PRE_CUTOVER_FORBIDDEN_ENTRY_POINTS,
        required_complete_owner_prs=frozenset({"6A", "6B"}),
    ),
    "cutover": StageRules(
        manifest_status="active",
        expected_runtime_argv=TARGET_RUNTIME_ARGV,
        gates=(("finalization-check", _target_gate("cutover")),),
        watched_targets=WATCHED_CUTOVER,
        forbidden_targets=frozenset({"finalization-check-target"}),
        required_entry_points=TARGET_REQUIRED_ENTRY_POINTS,
        forbidden_entry_points=POST_CUTOVER_FORBIDDEN_ENTRY_POINTS,
        required_complete_owner_prs=frozenset({"6A", "6B", "6C"}),
    ),
    "final": StageRules(
        manifest_status="completed",
        expected_runtime_argv=TARGET_RUNTIME_ARGV,
        gates=(("finalization-check", _target_gate("final")),),
        watched_targets=WATCHED_CUTOVER,
        forbidden_targets=frozenset({"finalization-check-target"}),
        required_entry_points=TARGET_REQUIRED_ENTRY_POINTS,
        forbidden_entry_points=POST_CUTOVER_FORBIDDEN_ENTRY_POINTS,
        required_complete_owner_prs=frozenset({"6A", "6B", "6C", "6D"}),
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
    docker_prefix = DOCKER_PYTHON_PREFIX
    prefix_len = len(docker_prefix)
    if len(argv) >= prefix_len and argv[:prefix_len] == docker_prefix:
        return ("docker-python", *argv[prefix_len:]), None
    return None, f"unsupported recipe: {command.text!r}"

def _validate_makefile_contracts(
    makefile: ParsedMakefile, rules: StageRules
) -> list[str]:
    errors = list(makefile.errors)
    for name in rules.watched_targets - rules.forbidden_targets:
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
        recipes: list[tuple[str, ...]] = []
        for command in gate.recipes:
            normalized, err = _normalize_gate_recipe(command)
            if err:
                errors.append(f"{target_name}: {err}")
                break
            assert normalized is not None
            recipes.append(normalized)
        else:
            actual = tuple(recipes)
            if actual != expected.recipes:
                errors.append(
                    f"{target_name} recipe contract mismatch: "
                    f"expected {expected.recipes!r}, got {actual!r}"
                )
    return errors

def _plain_compose_scalar(value: str) -> bool:
    return (
        bool(value) and value not in {"|", "|-", "|+", ">", ">-", ">+"}
        and value[0] not in "\"'" and not value.startswith(("{", "["))
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
        if not line.strip() or line.lstrip().startswith("#"):
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
            if raw_key == "<<" and not allow_merge:
                return (), f"{label} contains unsupported mapping syntax"
            if raw_key != "<<" and not YAML_SIMPLE_KEY_RE.fullmatch(raw_key):
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


def _list_item_scalars(
    block: tuple[str, ...], label: str
) -> tuple[tuple[str, ...], str | None]:
    indent = len(block[0]) - len(block[0].lstrip())
    item_indent: int | None = None
    values: list[str] = []
    for line in block[1:]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        line_indent = len(line) - len(line.lstrip())
        if line_indent <= indent:
            break
        if item_indent is None:
            item_indent = line_indent
        if line_indent != item_indent:
            return (), f"{label} contains unsupported list syntax"
        stripped = line.strip()
        if not stripped.startswith("- "):
            return (), f"{label} contains unsupported list syntax"
        value = stripped[2:].strip()
        if not value:
            return (), f"{label} contains empty list item"
        values.append(value)
    if item_indent is None:
        return (), f"{label} must contain a list item"
    return tuple(values), None


def _validate_environment_mapping(
    entry: MappingEntry,
    *,
    label: str,
    required_values: dict[str, str] | None = None,
    require_merge: bool = False,
    data_dir: str | None = None,
) -> list[str]:
    entries, error = _child_entries(entry.block, label, allow_merge=require_merge)
    if error:
        return [error]
    errors: list[str] = []
    for key in FORBIDDEN_LEGACY_ENVIRONMENT_KEYS:
        if _named(entries, key):
            errors.append(f"{label} must not declare {key}")
    if required_values is not None:
        for key, expected in required_values.items():
            matches = _named(entries, key)
            if len(matches) != 1:
                errors.append(f"{label} must have exactly one {key}")
            elif matches[0].value != expected:
                errors.append(
                    f"{label}.{key} must be {expected!r}, got {matches[0].value!r}"
                )
    if require_merge:
        merges = _named(entries, "<<")
        if len(merges) != 1 or merges[0].value != "*api-environment":
            errors.append(f"{label} must have exactly one <<: *api-environment")
        for key in REQUIRED_JUNG_ENVIRONMENT:
            if _named(entries, key):
                errors.append(f"{label} must not redeclare {key}")
    if data_dir is not None:
        matches = _named(entries, "JUNG_DATA_DIR")
        if len(matches) != 1:
            errors.append(f"{label} must have exactly one JUNG_DATA_DIR")
        elif matches[0].value != data_dir:
            errors.append(
                f"{label}.JUNG_DATA_DIR must be {data_dir!r}, got {matches[0].value!r}"
            )
    return errors


def _validate_list_value(
    entries: tuple[MappingEntry, ...], *, key: str, expected: str, label: str
) -> list[str]:
    matches = _named(entries, key)
    if len(matches) != 1:
        return [f"{label} must have exactly one {key}"]
    if matches[0].value:
        try:
            parsed = json.loads(matches[0].value)
        except json.JSONDecodeError:
            return [f"{label}.{key} must use a supported list syntax"]
        if not isinstance(parsed, list) or not all(
            isinstance(item, str) for item in parsed
        ):
            return [f"{label}.{key} must use a string list"]
        values = tuple(f'"{item}"' for item in parsed)
    else:
        values, error = _list_item_scalars(matches[0].block, f"{label}.{key}")
        if error:
            return [error]
    if expected not in values:
        return [f"{label}.{key} must include {expected!r}"]
    return []


def _validate_target_compose_structure(
    anchor_children: tuple[MappingEntry, ...],
    service_children: tuple[MappingEntry, ...],
) -> list[str]:
    errors: list[str] = []
    environment = _named(anchor_children, "environment")
    if len(environment) != 1:
        errors.append("x-api-base must have exactly one environment mapping")
    else:
        if environment[0].block[0].strip() != "environment: &api-environment":
            errors.append("x-api-base environment must be anchored as &api-environment")
        errors.extend(
            _validate_environment_mapping(
                environment[0],
                label="x-api-base environment",
                required_values=REQUIRED_JUNG_ENVIRONMENT,
            )
        )
    healthchecks = _named(anchor_children, "healthcheck")
    if len(healthchecks) != 1:
        errors.append("x-api-base must have exactly one healthcheck")
    else:
        health_entries, health_error = _child_entries(
            healthchecks[0].block, "x-api-base healthcheck"
        )
        if health_error:
            errors.append(health_error)
        else:
            tests = _named(health_entries, "test")
            if len(tests) != 1:
                errors.append("x-api-base healthcheck must have exactly one test")
            else:
                try:
                    parsed = json.loads(tests[0].value)
                except json.JSONDecodeError:
                    errors.append(
                        "x-api-base healthcheck.test must be a JSON argv array"
                    )
                else:
                    if tuple(parsed) != REQUIRED_HEALTHCHECK_ARGV:
                        errors.append(
                            "x-api-base healthcheck.test must be "
                            f"{REQUIRED_HEALTHCHECK_ARGV!r}"
                        )
    for name, data_dir, env_file, forbidden_keys, expected_port in (
        (
            "api",
            "/app/data/local",
            "${ENV_FILE:-.env}",
            FORBIDDEN_API_LOCAL_KEYS,
            '"127.0.0.1:8000:8000"',
        ),
        (
            "api-usertest",
            "/app/data/usertest",
            ".env.usertest",
            FORBIDDEN_API_USERTEST_LOCAL_KEYS,
            '"127.0.0.1:8001:8000"',
        ),
    ):
        matches = _named(service_children, name)
        if len(matches) != 1:
            errors.append(
                f"docker-compose.yml must have exactly one services.{name} block"
            )
            continue
        entries, entry_error = _child_entries(
            matches[0].block, f"services.{name}", allow_merge=True
        )
        if entry_error:
            errors.append(entry_error)
            continue
        for entry in entries:
            if entry.key in forbidden_keys:
                errors.append(f"services.{name} must not declare local {entry.key!r}")
        environments = _named(entries, "environment")
        if len(environments) != 1:
            errors.append(f"services.{name} must have exactly one environment mapping")
        else:
            errors.extend(
                _validate_environment_mapping(
                    environments[0],
                    label=f"services.{name} environment",
                    require_merge=True,
                    data_dir=data_dir,
                )
            )
        errors.extend(
            _validate_list_value(
                entries, key="env_file", expected=env_file, label=f"services.{name}"
            )
        )
        errors.extend(
            _validate_list_value(
                entries, key="ports", expected=expected_port, label=f"services.{name}"
            )
        )
        if name == "api-usertest":
            errors.extend(
                _validate_list_value(
                    entries,
                    key="profiles",
                    expected='"usertest-console"',
                    label="services.api-usertest",
                )
            )
    db_viewers = _named(service_children, "db-viewer")
    if len(db_viewers) != 1:
        errors.append(
            "docker-compose.yml must have exactly one services.db-viewer block"
        )
    else:
        entries, entry_error = _child_entries(
            db_viewers[0].block, "services.db-viewer"
        )
        if entry_error:
            errors.append(entry_error)
        else:
            errors.extend(
                _validate_list_value(
                    entries,
                    key="ports",
                    expected='"127.0.0.1:8080:8080"',
                    label="services.db-viewer",
                )
            )
    return errors

def _scalar_to_argv(raw: str) -> tuple[tuple[str, ...] | None, str | None]:
    if not _plain_compose_scalar(raw):
        return None, "unsupported scalar syntax"
    argv, err = _parse_shell_command(raw)
    if err:
        return None, err
    if argv is None:
        return None, "command must not be empty"
    return argv, None

def _validate_build_contract(
    entries: tuple[MappingEntry, ...],
    *,
    label: str,
) -> list[str]:
    builds = _named(entries, "build")
    if len(builds) != 1:
        return [f"{label} must have exactly one build key"]
    build_entries, error = _child_entries(builds[0].block, f"{label} build")
    if error:
        return [error]
    errors: list[str] = []
    for key, expected in REQUIRED_BUILD_VALUES.items():
        matches = _named(build_entries, key)
        if len(matches) != 1:
            errors.append(f"{label} build must have exactly one {key}")
        elif not _plain_compose_scalar(matches[0].value):
            errors.append(f"{label} build.{key} uses unsupported scalar syntax")
        elif matches[0].value != expected:
            errors.append(
                f"{label} build.{key} must be {expected!r}, got {matches[0].value!r}"
            )
    return errors

def _validate_compose_runtime(
    compose: str, expected_argv: tuple[str, ...]
) -> list[str]:
    errors: list[str] = []
    root_entries, root_err = _mapping_entries(
        tuple(compose.splitlines()), parent_indent=-1, label="docker-compose root"
    )
    if root_err:
        return [root_err]
    if _named(root_entries, "include"):
        return ["docker-compose.yml must not declare top-level include"]
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
    errors.extend(_validate_build_contract(anchor_children, label="x-api-base"))
    commands = _named(anchor_children, "command")
    if len(commands) != 1:
        errors.append("x-api-base must have exactly one command key")
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
    test_entries = _named(service_children, "test")
    if len(test_entries) != 1:
        return errors + ["docker-compose.yml must have exactly one services.test block"]
    test_children, test_err = _child_entries(test_entries[0].block, "services.test")
    if test_err:
        return errors + [test_err]
    for entry in test_children:
        if entry.key in FORBIDDEN_TEST_SERVICE_KEYS:
            errors.append(f"services.test must not declare {entry.key!r}")
    errors.extend(_validate_build_contract(test_children, label="services.test"))
    if expected_argv == TARGET_RUNTIME_ARGV:
        errors.extend(
            _validate_target_compose_structure(anchor_children, service_children)
        )
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
        line.rstrip() for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )

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
        path = ctx.root / WORKFLOW_EDIT_PATH
        if not path.is_file():
            errors.append(f"missing workflow edit file: {WORKFLOW_EDIT_PATH}")
        elif _normalize_workflow_text(path.read_text(encoding="utf-8")) != (
            _normalize_workflow_text(EXPECTED_COMPLETED_WORKFLOW)
        ):
            errors.append(
                "completed release workflow does not match canonical contract"
            )
    return errors
def _validate_entry_points(ctx: RepoContext, rules: StageRules) -> list[str]:
    scripts = ctx.pyproject.get("project", {}).get("scripts", {})
    if not isinstance(scripts, dict):
        return ["pyproject.toml missing project.scripts"]
    errors: list[str] = []
    names = set(scripts)
    for entry in rules.required_entry_points - names:
        errors.append(f"missing required entry point: {entry}")
    for forbidden in rules.forbidden_entry_points & names:
        errors.append(f"forbidden entry point still present: {forbidden}")
    for name, value in scripts.items():
        if not isinstance(value, str):
            errors.append(f"entry point {name!r} must be a string")
            continue
        if name in rules.forbidden_entry_points:
            continue
        if name in rules.required_entry_points:
            expected = ENTRY_POINT_TARGETS[name]
            if value != expected:
                errors.append(
                    f"entry point {name!r} must be {expected!r}, got {value!r}"
                )
            continue
        module = value.split(":", 1)[0].strip()
        if module == "psychoanalyst_app" or module.startswith("psychoanalyst_app."):
            errors.append(f"forbidden legacy entry point value: {name}")
    return errors


def _validate_required_owner_closure(
    manifest: Manifest,
    rules: StageRules,
) -> list[str]:
    return [
        (
            f"manifest item owned by {item.owner_pr} must be complete "
            f"for this stage: {item.path}"
        )
        for item in manifest.items
        if (
            item.owner_pr in rules.required_complete_owner_prs
            and item.status != "complete"
        )
    ]


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
def _validate_final_confidence_closure(manifest: Manifest) -> list[str]:
    return [
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
    errors.extend(_validate_required_owner_closure(manifest, rules))
    for item in manifest.items:
        if item.status == "complete":
            errors.extend(_validate_item_complete(ctx, item))
    if stage != "pre-cutover":
        workflow_item = next(
            (
                item for item in manifest.items
                if item.kind == "workflow_edit" and item.path == WORKFLOW_EDIT_PATH
            ),
            None,
        )
        if workflow_item is None:
            errors.append(
                f"required manifest item missing: {WORKFLOW_EDIT_PATH}"
            )
    if stage == "final":
        errors.extend(_validate_final_confidence_closure(manifest))
        errors.extend(_validate_import_closure(resolved))
        errors.extend(_validate_dependency_closure(ctx))
    return errors
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=tuple(STAGES), required=True)
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
