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
DOCKER_TEST_PREFIX = (
    "docker",
    "compose",
    "--profile",
    "test",
    "run",
    "--rm",
    "test",
)
MAKE_TOKENS = frozenset({"make", "$(MAKE)", "${MAKE}"})
FORBIDDEN_MAKE_CONTROLS = frozenset(
    {
        "MAKEFLAGS",
        "MFLAGS",
        "GNUMAKEFLAGS",
        "MAKEFILES",
        "SHELL",
        ".SHELLFLAGS",
        ".ONESHELL",
        ".RECIPEPREFIX",
    }
)
TARGET_SUPPORT_TESTS_VAR = "$(TARGET_SUPPORT_TESTS)"

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

PREPARE_RUNTIME_RECIPES = (
    "@mkdir -p data logs logs/workflow-probes",
    (
        '@if [ "$${CI:-}" = "true" ]; then chmod -R a+rwX data logs; '
        "else chmod -R u+rwX,g+rwX data logs; fi"
    ),
)

API_BASE_KEYS = frozenset(
    {
        "build",
        "user",
        "volumes",
        "environment",
        "networks",
        "command",
        "logging",
        "healthcheck",
    }
)
API_SERVICE_KEYS = frozenset({"<<", "container_name", "env_file"})
FORBIDDEN_API_OVERRIDE_KEYS = frozenset(
    {"command", "build", "entrypoint", "image", "extends"}
)
SELECTED_DOCKER_STAGE = "development"
REQUIRED_BUILD_VALUES = {
    "context": ".",
    "dockerfile": "Dockerfile",
    "target": SELECTED_DOCKER_STAGE,
}

WORKFLOW_TOP_KEYS = frozenset({"name", "on", "jobs"})
WORKFLOW_ON_KEYS = frozenset({"push", "pull_request"})
WORKFLOW_TRIGGER_KEYS = frozenset({"branches"})
WORKFLOW_JOB_KEYS = frozenset(
    {"name", "runs-on", "timeout-minutes", "env", "steps"}
)


@dataclass(frozen=True, slots=True)
class GateContract:
    prerequisites: tuple[str, ...]
    recipes: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class WorkflowTriggers:
    push_branches: frozenset[str]
    pull_request_branches: frozenset[str]


@dataclass(frozen=True, slots=True)
class WorkflowStepContract:
    allowed_keys: frozenset[str]
    operation: tuple[str, str]


@dataclass(frozen=True, slots=True)
class WorkflowContract:
    triggers: WorkflowTriggers
    job_name: str
    runs_on: str
    timeout_minutes: int
    env: frozenset[tuple[str, str]]
    steps: tuple[WorkflowStepContract, ...]


WORKFLOW_CONTRACT = WorkflowContract(
    triggers=WorkflowTriggers(
        push_branches=frozenset({"master", "main", "develop"}),
        pull_request_branches=frozenset({"master", "main", "develop"}),
    ),
    job_name="finalization-check",
    runs_on="ubuntu-latest",
    timeout_minutes=60,
    env=frozenset({("ENV_FILE", ".env.example")}),
    steps=(
        WorkflowStepContract(
            frozenset({"name", "uses"}), ("uses", "actions/checkout@v4")
        ),
        WorkflowStepContract(
            frozenset({"name", "run"}), ("run", "make finalization-check")
        ),
        WorkflowStepContract(
            frozenset({"name", "run"}),
            ("run", "git diff --check && git diff --exit-code"),
        ),
    ),
)


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
    expected_compose_command: str
    gates: tuple[tuple[str, GateContract], ...]
    forbidden_targets: frozenset[str]
    required_entry_points: frozenset[str]
    forbidden_entry_points: frozenset[str]
    final_closure: bool
    required_complete_items: frozenset[tuple[str, str]] = frozenset()


STAGES: dict[str, StageRules] = {
    "pre-cutover": StageRules(
        manifest_status="active",
        expected_runtime_argv=LEGACY_RUNTIME_ARGV,
        expected_compose_command="python -m psychoanalyst_app.server",
        gates=(
            ("finalization-check", _legacy_gate()),
            ("finalization-check-target", _target_gate("pre-cutover")),
        ),
        forbidden_targets=frozenset(),
        required_entry_points=frozenset(),
        forbidden_entry_points=frozenset(),
        final_closure=False,
    ),
    "cutover": StageRules(
        manifest_status="active",
        expected_runtime_argv=TARGET_RUNTIME_ARGV,
        expected_compose_command="jung-api",
        gates=(("finalization-check", _target_gate("cutover")),),
        forbidden_targets=frozenset({"finalization-check-target"}),
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
        expected_compose_command="jung-api",
        gates=(("finalization-check", _target_gate("final")),),
        forbidden_targets=frozenset({"finalization-check-target"}),
        required_entry_points=TARGET_ENTRY_FINAL,
        forbidden_entry_points=LEGACY_ENTRY_POINTS,
        final_closure=True,
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
    prefix: str


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    argv: tuple[str, ...] | None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedMakeTarget:
    recipes: tuple[RecipeCommand, ...]
    prerequisites: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ParsedMakefile:
    definitions: dict[str, tuple[ParsedMakeTarget, ...]]
    phony: frozenset[str]
    has_ignore: bool
    header_errors: tuple[str, ...]
    control_errors: tuple[str, ...]


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


def _delegated_make_targets(
    gates: tuple[tuple[str, GateContract], ...],
) -> frozenset[str]:
    names: set[str] = set()
    for _, contract in gates:
        for recipe in contract.recipes:
            if recipe[0] == "make":
                names.add(recipe[1])
    return frozenset(names)


def _contracted_targets(rules: StageRules) -> frozenset[str]:
    names = {PREPARE_RUNTIME_DIRS}
    names.update(name for name, _ in rules.gates)
    names.update(_delegated_make_targets(rules.gates))
    return frozenset(names)


def _watched_targets(rules: StageRules) -> frozenset[str]:
    return _contracted_targets(rules) | rules.forbidden_targets


def _load_repo_context(root: Path, watched: frozenset[str]) -> RepoContext:
    makefile_text = (root / "Makefile").read_text(encoding="utf-8")
    return RepoContext(
        root=root,
        makefile=_parse_makefile(makefile_text, watched),
        makefile_text=makefile_text,
        pyproject=tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8")),
        compose=(root / "docker-compose.yml").read_text(encoding="utf-8"),
        dockerfile=(root / "Dockerfile").read_text(encoding="utf-8"),
    )


def _parse_shell_command(text: str) -> ParsedCommand:
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        lexer.commenters = "#"
        tokens: list[str] = []
        for token in lexer:
            if token and all(char in ";&|<>" for char in token):
                return ParsedCommand(None, "unsupported shell control")
            tokens.append(token)
    except ValueError as exc:
        return ParsedCommand(None, str(exc))
    if not tokens:
        return ParsedCommand(None, "empty command")
    return ParsedCommand(tuple(tokens))


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
    if "%" in lhs:
        for name in targets:
            if name in watched:
                errors.append(f"{name} uses unsupported pattern target header")
    if ";" in rhs:
        for name in targets:
            if name in watched:
                errors.append(f"{name} uses unsupported inline recipe header")
    if is_double:
        for name in targets:
            if name in watched:
                errors.append(f"{name} uses unsupported double-colon definition")
    if is_grouped:
        for name in targets:
            if name in watched:
                errors.append(f"{name} uses unsupported grouped target header")
    if len(targets) > 1:
        for name in targets:
            if name in watched:
                errors.append(f"{name} uses unsupported multi-target header")
    return errors


def _detect_make_control(line: str) -> str | None:
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
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or line.startswith("\t"):
        return None
    if re.match(r"^(?:include|-include|sinclude)\s+", stripped):
        return "Makefile include directives are unsupported"
    if re.match(r"^\$\(eval\b", stripped):
        return "Makefile eval directives are unsupported"
    return None


def _parse_makefile(text: str, watched: frozenset[str] | None = None) -> ParsedMakefile:
    watched = watched or frozenset()
    definitions: dict[str, list[ParsedMakeTarget]] = {}
    phony: set[str] = set()
    has_ignore = False
    header_errors: list[str] = []
    control_errors: list[str] = []
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
            control_errors.append(composition)
        control = _detect_make_control(line)
        if control:
            if control == ".IGNORE":
                has_ignore = True
            else:
                control_errors.append(f"Makefile declares forbidden control {control}")
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
                header_errors.append(
                    "variable-expanded target headers are unsupported"
                )
            targets, _, _ = _header_targets(lhs)
            header_errors.extend(
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
        has_ignore=has_ignore,
        header_errors=tuple(header_errors),
        control_errors=tuple(control_errors),
    )


def _recipe_text(command: RecipeCommand) -> str:
    return f"{command.prefix}{command.text}"


def _normalize_gate_recipe(
    command: RecipeCommand,
) -> tuple[tuple[str, ...] | None, str | None]:
    if command.prefix:
        return None, "unsupported recipe prefix"
    parsed = _parse_shell_command(command.text)
    if parsed.error or parsed.argv is None:
        return None, parsed.error or "unsupported recipe"
    argv = parsed.argv
    if len(argv) == 2 and argv[0] in MAKE_TOKENS:
        return ("make", argv[1]), None
    docker_prefix = DOCKER_TEST_PREFIX + ("python",)
    prefix_len = len(docker_prefix)
    if len(argv) >= prefix_len and argv[:prefix_len] == docker_prefix:
        return ("docker-python", *argv[prefix_len:]), None
    return None, f"unsupported recipe: {command.text!r}"


def _compare_gate_contract(
    target: str, actual: GateContract, expected: GateContract
) -> list[str]:
    errors: list[str] = []
    if actual.prerequisites != expected.prerequisites:
        errors.append(
            f"{target} prerequisite contract mismatch: "
            f"expected {expected.prerequisites!r}, got {actual.prerequisites!r}"
        )
    if len(actual.recipes) != len(expected.recipes):
        errors.append(
            f"{target} recipe contract mismatch: expected {len(expected.recipes)} "
            f"recipes, got {len(actual.recipes)}"
        )
        return errors
    for index, (got, want) in enumerate(
        zip(actual.recipes, expected.recipes, strict=True)
    ):
        if got != want:
            errors.append(
                f"{target} recipe contract mismatch at index {index}: "
                f"expected {want!r}, got {got!r}"
            )
            break
    return errors


def _gate_contract_from_target(
    target: ParsedMakeTarget,
) -> tuple[GateContract | None, list[str]]:
    recipes: list[tuple[str, ...]] = []
    for command in target.recipes:
        normalized, err = _normalize_gate_recipe(command)
        if err:
            return None, [err]
        assert normalized is not None
        recipes.append(normalized)
    return GateContract(target.prerequisites, tuple(recipes)), []


def _validate_makefile_contracts(
    makefile: ParsedMakefile, rules: StageRules
) -> list[str]:
    errors = list(makefile.header_errors)
    errors.extend(makefile.control_errors)
    if makefile.has_ignore:
        errors.append("Makefile must not declare .IGNORE")

    contracted = _contracted_targets(rules)
    phony_required = contracted | _delegated_make_targets(rules.gates)
    for name in phony_required:
        if name not in makefile.phony:
            errors.append(f"{name} must be phony")
    for name in phony_required:
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
            texts = tuple(_recipe_text(cmd) for cmd in target.recipes)
            if texts != PREPARE_RUNTIME_RECIPES:
                errors.append(f"{PREPARE_RUNTIME_DIRS} recipe contract mismatch")

    for forbidden in rules.forbidden_targets:
        if forbidden in makefile.definitions:
            errors.append(f"{forbidden} must be absent after cutover")

    for target_name, expected in rules.gates:
        gate_defs = makefile.definitions.get(target_name, ())
        if len(gate_defs) != 1:
            errors.append(
                f"{target_name} must have exactly one definition, got {len(gate_defs)}"
            )
            continue
        actual_contract, norm_errors = _gate_contract_from_target(gate_defs[0])
        errors.extend(norm_errors)
        if actual_contract is None:
            continue
        errors.extend(_compare_gate_contract(target_name, actual_contract, expected))
    return errors


# --- YAML helpers (canonical subset) ---


def _is_comment_or_blank(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


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


def _one_child(
    children: list[tuple[str, str]],
    name: str,
    *,
    required: bool,
    label: str,
) -> tuple[str | None, str | None]:
    matches = [block for child_name, block in children if child_name == name]
    if not matches:
        return (None, f"{label} missing {name}") if required else (None, None)
    if len(matches) > 1:
        return None, f"{label} has multiple {name} keys"
    return matches[0], None


def _exact_child_keys(
    children: list[tuple[str, str]], allowed: frozenset[str], label: str
) -> str | None:
    keys = [name for name, _ in children]
    if len(keys) != len(set(keys)):
        return f"{label} has duplicate keys"
    if frozenset(keys) != allowed:
        return f"{label} keys must be {sorted(allowed)!r}"
    return None


def _scalar_value(block: str, key: str) -> tuple[str | None, str | None]:
    child, err = _one_child(_direct_children(block), key, required=True, label=key)
    if err:
        return None, err
    assert child is not None
    first = child.splitlines()[0].strip()
    match = re.match(rf"^{re.escape(key)}:\s*(.*)$", first)
    if not match:
        return None, f"invalid {key} syntax"
    value = match.group(1).strip()
    if value in {"|", "|-", "|+", ">", ">-", ">+"}:
        return None, "unsupported block scalar"
    if value.startswith("{") or value.startswith("["):
        return None, "unsupported inline mapping"
    if "&" in value or "*" in value:
        return None, "unsupported YAML anchor"
    return value.strip("'\""), None


def _top_level_children(text: str) -> list[tuple[str, str]]:
    children: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        if _is_comment_or_blank(line):
            continue
        if line.startswith((" ", "\t")):
            if children:
                children[-1][1].append(line)
            continue
        match = re.match(r"(\S+):\s*(.*)$", line.strip())
        if match:
            children.append((match.group(1), [line]))
    return [(name, "\n".join(block)) for name, block in children]


def _parse_branch_list(
    trigger_block: str, trigger_name: str, expected: frozenset[str]
) -> str | None:
    child, err = _one_child(
        _direct_children(trigger_block), "branches", required=True, label=trigger_name
    )
    if err:
        return err
    assert child is not None
    child_indent = _direct_child_indent(child)
    if child_indent is None:
        return f"{trigger_name} branches must be non-empty"
    branches: list[str] = []
    for line in child.splitlines()[1:]:
        if _is_comment_or_blank(line):
            continue
        indent = len(line) - len(line.lstrip())
        if indent != child_indent:
            return f"{trigger_name} branches contain unsupported syntax"
        match = re.match(r"^\s*-\s+(\S+)\s*$", line)
        if not match:
            return f"{trigger_name} branches contain unsupported syntax"
        branch = match.group(1)
        if branch in branches:
            return f"{trigger_name} branches contain duplicate values"
        branches.append(branch)
    if not branches:
        return f"{trigger_name} branches must be non-empty"
    if frozenset(branches) != expected:
        return f"workflow {trigger_name} branches contract mismatch"
    return None


def _env_mapping(block: str) -> tuple[frozenset[tuple[str, str]] | None, str | None]:
    child, err = _one_child(_direct_children(block), "env", required=True, label="job")
    if err:
        return None, err
    assert child is not None
    env_children = _direct_children(child)
    if frozenset(name for name, _ in env_children) != frozenset({"ENV_FILE"}):
        return None, "workflow env contract mismatch"
    value, value_err = _scalar_value(child, "ENV_FILE")
    if value_err:
        return None, value_err
    if value != ".env.example":
        return None, "workflow env contract mismatch"
    return frozenset({("ENV_FILE", ".env.example")}), None


def _workflow_steps(
    job_block: str,
) -> tuple[list[tuple[tuple[str, str], ...]] | None, str | None]:
    steps_block, err = _one_child(
        _direct_children(job_block), "steps", required=True, label="job"
    )
    if err:
        return None, err
    assert steps_block is not None
    lines = steps_block.splitlines()
    step_indent: int | None = None
    start = 0
    for index, line in enumerate(lines):
        if re.match(r"^\s*steps:\s*$", line):
            start = index + 1
            continue
        if _is_comment_or_blank(line):
            continue
        if re.match(r"^\s*-\s", line):
            step_indent = len(line) - len(line.lstrip())
            break
    if step_indent is None:
        return [], None
    steps: list[tuple[tuple[str, str], ...]] = []
    current: list[tuple[str, str]] = []
    for line in lines[start:]:
        if _is_comment_or_blank(line):
            continue
        indent = len(line) - len(line.lstrip())
        if indent < step_indent:
            break
        if indent == step_indent and re.match(r"^\s*-\s", line):
            if current:
                steps.append(tuple(current))
            current = []
            remainder = line.strip()[1:].strip()
            if remainder:
                match = re.match(r"(\S+):\s*(.*)$", remainder)
                if match:
                    current.append((match.group(1), match.group(2).strip()))
            continue
        match = re.match(r"^(\S+):\s*(.*)$", line.strip())
        if match:
            key, value = match.group(1), match.group(2).strip()
            if value in {"|", "|-", "|+", ">", ">-", ">+"}:
                return None, "unsupported block scalar"
            if value.startswith("{") or value.startswith("["):
                return None, "unsupported inline mapping"
            if any(existing_key == key for existing_key, _ in current):
                return None, f"workflow step has duplicate {key!r} key"
            current.append((key, value.strip("'\"")))
    if current:
        steps.append(tuple(current))
    return steps, None


def _validate_workflow_triggers(
    on_children: list[tuple[str, str]], contract: WorkflowContract
) -> list[str]:
    errors: list[str] = []
    on_key_err = _exact_child_keys(on_children, WORKFLOW_ON_KEYS, "on")
    if on_key_err:
        return [on_key_err]
    for trigger_name, expected_branches in (
        ("push", contract.triggers.push_branches),
        ("pull_request", contract.triggers.pull_request_branches),
    ):
        trigger_block, trigger_err = _one_child(
            on_children, trigger_name, required=True, label="on"
        )
        if trigger_err:
            errors.append(trigger_err)
            continue
        assert trigger_block is not None
        trigger_key_err = _exact_child_keys(
            _direct_children(trigger_block), WORKFLOW_TRIGGER_KEYS, trigger_name
        )
        if trigger_key_err:
            errors.append(trigger_key_err)
            continue
        branch_err = _parse_branch_list(trigger_block, trigger_name, expected_branches)
        if branch_err:
            errors.append(branch_err)
    return errors


def _validate_workflow_job(job_block: str, contract: WorkflowContract) -> list[str]:
    errors: list[str] = []
    job_key_err = _exact_child_keys(
        _direct_children(job_block), WORKFLOW_JOB_KEYS, "workflow job"
    )
    if job_key_err:
        errors.append(job_key_err)
    runs_on, err = _scalar_value(job_block, "runs-on")
    if err:
        errors.append(err)
    elif runs_on != contract.runs_on:
        errors.append("workflow runs-on contract mismatch")
    timeout_raw, err = _scalar_value(job_block, "timeout-minutes")
    if err:
        errors.append(err)
    elif timeout_raw is None:
        errors.append("workflow timeout-minutes contract mismatch")
    else:
        try:
            timeout = int(timeout_raw)
        except ValueError:
            errors.append("workflow timeout-minutes must be integer 60")
        else:
            if timeout != contract.timeout_minutes:
                errors.append("workflow timeout-minutes contract mismatch")
    env, err = _env_mapping(job_block)
    if err:
        errors.append(err)
    elif env != contract.env:
        errors.append("workflow env contract mismatch")
    name, name_err = _scalar_value(job_block, "name")
    if name_err:
        errors.append(name_err)
    elif not name:
        errors.append("workflow job name must be a non-empty string")
    steps, err = _workflow_steps(job_block)
    if err:
        errors.append(err)
        return errors
    if steps is None:
        return errors
    if len(steps) != len(contract.steps):
        errors.append("workflow step count contract mismatch")
        return errors
    for index, (actual_pairs, expected) in enumerate(
        zip(steps, contract.steps, strict=True)
    ):
        actual = dict(actual_pairs)
        if frozenset(actual) != expected.allowed_keys:
            errors.append(f"workflow step {index} keys contract mismatch")
            continue
        if not actual.get("name"):
            errors.append(f"workflow step {index} name must be a non-empty string")
        op_kind, op_value = expected.operation
        if actual.get(op_kind) != op_value:
            errors.append(f"workflow step {index} operation contract mismatch")
        extra_keys = set(actual) - {op_kind, "name"}
        if extra_keys:
            errors.append(f"workflow step {index} has unsupported keys")
    return errors


def _validate_workflow_edit(ctx: RepoContext, *, complete: bool) -> list[str]:
    path = ctx.root / WORKFLOW_EDIT_PATH
    if not path.is_file():
        return [f"missing workflow edit file: {WORKFLOW_EDIT_PATH}"]
    if not complete:
        return []
    workflow = path.read_text(encoding="utf-8")
    if re.search(r"^\s*&\w", workflow, re.MULTILINE) or "<<:" in workflow:
        return ["workflow uses unsupported YAML anchors"]
    errors: list[str] = []
    root_children = _top_level_children(workflow)
    root_err = _exact_child_keys(root_children, WORKFLOW_TOP_KEYS, "workflow")
    if root_err:
        errors.append(root_err)
    on_block, on_err = _one_child(root_children, "on", required=True, label="workflow")
    if on_err:
        return errors + [on_err]
    assert on_block is not None
    on_children = _direct_children(on_block)
    contract = WORKFLOW_CONTRACT
    errors.extend(_validate_workflow_triggers(on_children, contract))
    jobs_block, jobs_err = _one_child(
        root_children, "jobs", required=True, label="workflow"
    )
    if jobs_err:
        return errors + [jobs_err]
    assert jobs_block is not None
    jobs = _direct_children(jobs_block)
    if len(jobs) != 1 or jobs[0][0] != contract.job_name:
        errors.append(
            f"workflow must have exactly one job: {contract.job_name!r}"
        )
        return errors
    errors.extend(_validate_workflow_job(jobs[0][1], contract))
    return errors


# --- Compose / Docker runtime ---


def _scalar_to_argv(raw: str) -> tuple[tuple[str, ...] | None, str | None]:
    value = raw.strip().strip("'\"")
    if not value:
        return None, "command must not be empty"
    parsed = _parse_shell_command(value)
    if parsed.error:
        return None, parsed.error
    if parsed.argv is None:
        return None, "command must not be empty"
    return parsed.argv, None


def _validate_compose_runtime(
    compose: str, expected_command: str
) -> tuple[tuple[str, ...] | None, list[str]]:
    errors: list[str] = []
    anchor_headers = list(
        re.finditer(r"^x-api-base:\s*&api-base\s*$", compose, re.MULTILINE)
    )
    if len(anchor_headers) != 1:
        errors.append(
            "docker-compose must have exactly one x-api-base: &api-base anchor"
        )
        return None, errors
    anchor_block = _yaml_block(compose, r"^x-api-base:\s*&api-base\s*$")
    if anchor_block is None:
        errors.append("docker-compose missing x-api-base anchor block")
        return None, errors
    anchor_children = _direct_children(anchor_block)
    key_err = _exact_child_keys(anchor_children, API_BASE_KEYS, "x-api-base")
    if key_err:
        errors.append(key_err)
    command_raw, command_err = _scalar_value(anchor_block, "command")
    if command_err:
        errors.append(command_err)
    elif command_raw != expected_command:
        errors.append(
            f"docker-compose api command must select {expected_command!r}, "
            f"got {command_raw!r}"
        )
    build_block, build_err = _one_child(
        anchor_children, "build", required=True, label="x-api-base"
    )
    if build_err:
        errors.append(build_err)
    elif build_block is not None:
        build_children = _direct_children(build_block)
        build_key_err = _exact_child_keys(
            build_children, frozenset(REQUIRED_BUILD_VALUES), "x-api-base build"
        )
        if build_key_err:
            errors.append(build_key_err)
        else:
            for key, expected in REQUIRED_BUILD_VALUES.items():
                value, value_err = _scalar_value(build_block, key)
                if value_err:
                    errors.append(value_err)
                elif value != expected:
                    errors.append(
                        f"docker-compose build.{key} must be {expected!r}, "
                        f"got {value!r}"
                    )
    if len(re.findall(r"^services:\s*$", compose, re.MULTILINE)) != 1:
        errors.append("docker-compose.yml must have exactly one services block")
        return None, errors
    services_block = _yaml_block(compose, r"^services:\s*$")
    if services_block is None:
        errors.append("docker-compose.yml missing services block")
        return None, errors
    api_blocks = [
        block for name, block in _direct_children(services_block) if name == "api"
    ]
    if len(api_blocks) != 1:
        errors.append("docker-compose.yml must have exactly one services.api block")
        return None, errors
    api_children = _direct_children(api_blocks[0])
    for forbidden in FORBIDDEN_API_OVERRIDE_KEYS:
        if any(name == forbidden for name, _ in api_children):
            errors.append(f"services.api must not declare local {forbidden!r}")
    api_key_err = _exact_child_keys(api_children, API_SERVICE_KEYS, "services.api")
    if api_key_err:
        errors.append(api_key_err)
    else:
        merge_block, merge_err = _one_child(
            api_children, "<<", required=True, label="services.api"
        )
        if merge_err:
            errors.append(merge_err)
        elif merge_block is not None:
            first_line = merge_block.splitlines()[0].strip()
            if first_line != "<<: *api-base":
                errors.append("services.api merge must be <<: *api-base")
    if command_raw is None or command_err:
        return None, errors
    argv, argv_err = _scalar_to_argv(command_raw)
    if argv_err:
        errors.append(f"docker-compose api command is invalid: {argv_err}")
        return None, errors
    return argv, errors


def _dockerfile_stage_cmd(
    dockerfile: str, stage_name: str
) -> tuple[tuple[str, ...] | None, str | None]:
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
    stage_lines = next((lines for name, lines in stages if name == stage_name), None)
    if stage_lines is None:
        return None, (
            f"Dockerfile stage {stage_name!r} not found for compose build.target"
        )
    stage_text = "\n".join(stage_lines)
    matches = list(
        re.finditer(r"^\s*CMD\s+(\[[^\]]*\]|.+?)\s*$", stage_text, re.MULTILINE)
    )
    if not matches:
        return None, f"Dockerfile stage {stage_name!r} must define an explicit CMD"
    raw = matches[-1].group(1).strip()
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None, "Dockerfile CMD exec form is malformed"
        if not isinstance(parsed, list) or not parsed:
            return None, "Dockerfile CMD exec form must be a non-empty list"
        if not all(isinstance(item, str) and item for item in parsed):
            return None, (
                "Dockerfile CMD exec form must contain only non-empty strings"
            )
        return tuple(parsed), None
    return _scalar_to_argv(raw)


def _validate_runtime(ctx: RepoContext, rules: StageRules) -> list[str]:
    expected_argv = rules.expected_runtime_argv
    compose_argv, errors = _validate_compose_runtime(
        ctx.compose, rules.expected_compose_command
    )
    if errors:
        return errors
    assert compose_argv is not None
    if compose_argv != expected_argv:
        errors.append(
            f"docker-compose api command must select {expected_argv!r}, "
            f"got {compose_argv!r}"
        )
    docker_argv, docker_err = _dockerfile_stage_cmd(
        ctx.dockerfile, SELECTED_DOCKER_STAGE
    )
    if docker_err:
        errors.append(docker_err)
    elif docker_argv != expected_argv:
        errors.append(
            f"Dockerfile stage {SELECTED_DOCKER_STAGE!r} CMD must select "
            f"{expected_argv!r}, got {docker_argv!r}"
        )
    return errors


def _target_exists(ctx: RepoContext, path: str) -> bool:
    return path in ctx.makefile.definitions


def _path_exists(ctx: RepoContext, item: ManifestItem) -> bool:
    if item.kind == "make_target":
        return _target_exists(ctx, item.path)
    path = ctx.root / item.path.rstrip("/")
    return path.exists() or path.is_symlink()


def _path_absent(ctx: RepoContext, item: ManifestItem) -> bool:
    if item.kind == "make_target":
        return not _target_exists(ctx, item.path)
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


def _recipe_ignored(command: RecipeCommand) -> bool:
    return "-" in command.prefix or "+" in command.prefix


def _test_target_expands_support_tests(ctx: RepoContext) -> bool:
    defs = ctx.makefile.definitions.get("test-target", ())
    if len(defs) != 1:
        return False
    for command in defs[0].recipes:
        if _recipe_ignored(command):
            continue
        parsed = _parse_shell_command(command.text)
        if parsed.error or parsed.argv is None:
            continue
        offset = _pytest_argv_offset(parsed.argv)
        if offset is None:
            continue
        if TARGET_SUPPORT_TESTS_VAR in parsed.argv[offset:]:
            return True
    return False


def _test_target_references_path(ctx: RepoContext, path: str) -> bool:
    normalized = _norm_fs_path(path)
    if (
        normalized in _target_support_test_paths(ctx.makefile_text)
        and _test_target_expands_support_tests(ctx)
    ):
        return True
    defs = ctx.makefile.definitions.get("test-target", ())
    if len(defs) != 1:
        return False
    for command in defs[0].recipes:
        if _recipe_ignored(command):
            continue
        parsed = _parse_shell_command(command.text)
        if parsed.error or parsed.argv is None:
            continue
        offset = _pytest_argv_offset(parsed.argv)
        if offset is None:
            continue
        if normalized in {_norm_fs_path(token) for token in parsed.argv[offset:]}:
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

    watched = _watched_targets(rules)
    ctx = _load_repo_context(resolved, watched)
    errors.extend(_validate_makefile_contracts(ctx.makefile, rules))
    errors.extend(_validate_runtime(ctx, rules))

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
