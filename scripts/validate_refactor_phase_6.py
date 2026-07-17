#!/usr/bin/env python3
"""Static cutover checks for Phase 6 legacy deletion.

Module organization (five narrow groups):
    1. inventory parsing
    2. gate lifecycle
    3. supported-runtime checks
    4. final deletion checks
    5. CLI
"""

from __future__ import annotations

import argparse
import ast
import configparser
import re
import shlex
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

INVENTORY_PATH = Path("docs/refactor/deletion-inventory.md")

EXCEPTION_COLUMNS = ("Path", "Treatment", "Owner PR", "Status", "Evidence")

ALLOWED_TREATMENTS = frozenset(
    {
        "reimplement_minimal",
        "port_then_delete",
        "retain_outside_root",
        "retain_test",
    }
)
ALLOWED_STATUSES = frozenset({"planned", "in_progress", "complete"})

RELEASE_CANDIDATE_WORKFLOW = ".github/workflows/release-candidate-validation.yml"


# ============================================================
# 1. Inventory parsing
# ============================================================

_FILESYSTEM_ROOTS_HEADING = "## Filesystem deletion roots"
_MAKE_TARGETS_HEADING = "## Legacy Make targets"
_WORKFLOW_DELETE_HEADING = "## Legacy CI workflows"
_WORKFLOW_EDIT_HEADING = "## Legacy CI workflow edits"
_EXCEPTIONS_HEADING = "## Exceptions"

_DOCUMENT_STATUS_RE = re.compile(
    r"^status:\s*(active|completed)\s*$",
    re.MULTILINE,
)

_BULLET_RE = re.compile(r"^- `([^`]+)`\s*$")

EXPECTED_WORKFLOW_EDIT_ITEMS = frozenset({RELEASE_CANDIDATE_WORKFLOW})

_MAKE_TARGET_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True, slots=True)
class ExceptionRow:
    path: str
    treatment: str
    owner_pr: str
    status: str
    evidence: str


@dataclass(frozen=True, slots=True)
class Inventory:
    document_status: str
    filesystem_roots: tuple[str, ...]
    make_targets: tuple[str, ...]
    workflow_delete_items: tuple[str, ...]
    workflow_edit_items: tuple[str, ...]
    exceptions: tuple[ExceptionRow, ...]


def _valid_repository_relative_path(
    value: str,
    *,
    allow_trailing_slash: bool = False,
) -> bool:
    normalized = value.rstrip("/") if allow_trailing_slash else value
    path = Path(normalized)

    return (
        bool(normalized)
        and normalized != "."
        and not path.is_absolute()
        and ".." not in path.parts
        and "\\" not in value
    )


def _valid_workflow_inventory_path(item: str) -> bool:
    if not _valid_repository_relative_path(item):
        return False

    path = Path(item)

    return (
        path.parts[:2] == (".github", "workflows")
        and len(path.parts) >= 3
        and path.name not in {".yml", ".yaml"}
        and path.suffix in {".yml", ".yaml"}
    )


def _parse_bullet_section(
    text: str,
    *,
    heading: str,
) -> tuple[tuple[str, ...], list[str]]:
    items: list[str] = []
    errors: list[str] = []
    in_section = False
    found = False

    for line in text.splitlines():
        if line.strip() == heading:
            in_section = True
            found = True
            continue
        if not in_section:
            continue
        if line.startswith("#"):
            break
        if not line.strip():
            continue

        match = _BULLET_RE.match(line)
        if not match:
            errors.append(f"malformed inventory bullet in {heading!r}: {line}")
            continue

        identifier = match.group(1).strip()
        if not identifier:
            errors.append(f"empty inventory bullet in {heading!r}: {line}")
            continue

        items.append(identifier)

    if not found:
        errors.append(f"missing inventory section: {heading}")

    return tuple(items), errors


def _parse_document_status(text: str) -> tuple[str | None, list[str]]:
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None, ["inventory missing frontmatter block"]

    frontmatter = parts[1]
    matches = _DOCUMENT_STATUS_RE.findall(frontmatter)
    if len(matches) != 1:
        return None, [
            "inventory frontmatter must declare exactly one status: active|completed"
        ]

    return matches[0], []


def _parse_exceptions_table(text: str) -> tuple[tuple[ExceptionRow, ...], list[str]]:
    errors: list[str] = []
    rows: list[ExceptionRow] = []
    in_section = False
    found_section = False
    found_header = False
    seen_paths: set[str] = set()

    for line in text.splitlines():
        if line.strip() == _EXCEPTIONS_HEADING:
            in_section = True
            found_section = True
            continue
        if not in_section:
            continue
        if line.startswith("#"):
            break

        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("|"):
            errors.append(f"unexpected exceptions section content: {line}")
            continue
        if stripped.startswith("|---"):
            continue

        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if cells == list(EXCEPTION_COLUMNS):
            found_header = True
            continue
        if len(cells) != len(EXCEPTION_COLUMNS):
            errors.append(f"inventory exception row has wrong column count: {line}")
            continue

        path_value, treatment, owner_pr, status, evidence = cells
        path_value = path_value.strip("`")

        fields = (path_value, treatment, owner_pr, status, evidence)
        if not all(fields):
            errors.append(f"inventory exception row has empty field: {line}")
            continue

        if path_value in seen_paths:
            errors.append(f"duplicate inventory exception path: {path_value}")
        seen_paths.add(path_value)

        if treatment not in ALLOWED_TREATMENTS:
            errors.append(f"invalid treatment {treatment!r} for {path_value}")
        if status not in ALLOWED_STATUSES:
            errors.append(f"invalid status {status!r} for {path_value}")

        rows.append(
            ExceptionRow(
                path=path_value,
                treatment=treatment,
                owner_pr=owner_pr,
                status=status,
                evidence=evidence,
            )
        )

    if not found_section:
        errors.append(f"missing inventory section: {_EXCEPTIONS_HEADING}")
    elif not found_header:
        errors.append("inventory exceptions table missing header row")

    return tuple(rows), errors


def _duplicate_errors(items: tuple[str, ...], label: str) -> list[str]:
    seen: set[str] = set()
    errors: list[str] = []
    for item in items:
        if item in seen:
            errors.append(f"duplicate {label}: {item}")
        seen.add(item)
    return errors


def _parse_inventory(root: Path) -> tuple[Inventory, list[str]]:
    path = root / INVENTORY_PATH

    if not path.is_file():
        empty = Inventory(
            document_status="",
            filesystem_roots=(),
            make_targets=(),
            workflow_delete_items=(),
            workflow_edit_items=(),
            exceptions=(),
        )
        return empty, [f"missing inventory: {INVENTORY_PATH}"]

    text = path.read_text(encoding="utf-8")
    errors: list[str] = []

    document_status, section_errors = _parse_document_status(text)
    errors.extend(section_errors)

    filesystem_roots, section_errors = _parse_bullet_section(
        text, heading=_FILESYSTEM_ROOTS_HEADING
    )
    errors.extend(section_errors)

    make_targets, section_errors = _parse_bullet_section(
        text, heading=_MAKE_TARGETS_HEADING
    )
    errors.extend(section_errors)

    workflow_delete_items, section_errors = _parse_bullet_section(
        text, heading=_WORKFLOW_DELETE_HEADING
    )
    errors.extend(section_errors)

    workflow_edit_items, section_errors = _parse_bullet_section(
        text, heading=_WORKFLOW_EDIT_HEADING
    )
    errors.extend(section_errors)

    exceptions, section_errors = _parse_exceptions_table(text)
    errors.extend(section_errors)

    inventory = Inventory(
        document_status=document_status or "",
        filesystem_roots=filesystem_roots,
        make_targets=make_targets,
        workflow_delete_items=workflow_delete_items,
        workflow_edit_items=workflow_edit_items,
        exceptions=exceptions,
    )

    return inventory, errors


def _require_document_status(inventory: Inventory, expected: str) -> list[str]:
    if inventory.document_status != expected:
        return [
            f"inventory frontmatter status must be {expected!r}, "
            f"got {inventory.document_status!r}"
        ]
    return []


def _inventory_structure_checks(inventory: Inventory) -> list[str]:
    errors: list[str] = []

    if set(inventory.workflow_edit_items) != EXPECTED_WORKFLOW_EDIT_ITEMS:
        errors.append(
            "Legacy CI workflow edits must contain exactly "
            f"{RELEASE_CANDIDATE_WORKFLOW}"
        )

    if not inventory.filesystem_roots:
        errors.append("inventory filesystem deletion roots must be non-empty")
    if not inventory.make_targets:
        errors.append("inventory legacy make targets must be non-empty")
    if not inventory.workflow_delete_items:
        errors.append("inventory legacy CI workflows must be non-empty")
    if not inventory.workflow_edit_items:
        errors.append("inventory legacy CI workflow edits must be non-empty")

    for item in inventory.filesystem_roots:
        if not _valid_repository_relative_path(item, allow_trailing_slash=True):
            errors.append(f"invalid filesystem root path: {item}")

    for row in inventory.exceptions:
        if not _valid_repository_relative_path(row.path):
            errors.append(f"invalid exception path: {row.path}")

    for target in inventory.make_targets:
        if not _MAKE_TARGET_NAME_RE.fullmatch(target):
            errors.append(f"invalid inventory make target: {target}")

    for item in (*inventory.workflow_delete_items, *inventory.workflow_edit_items):
        if not _valid_workflow_inventory_path(item):
            errors.append(f"invalid workflow inventory path: {item}")

    errors.extend(
        _duplicate_errors(inventory.filesystem_roots, "filesystem deletion root")
    )
    errors.extend(_duplicate_errors(inventory.make_targets, "legacy make target"))
    errors.extend(
        _duplicate_errors(inventory.workflow_delete_items, "legacy CI workflow")
    )
    errors.extend(
        _duplicate_errors(inventory.workflow_edit_items, "legacy CI workflow edit")
    )

    duplicate_across = set(inventory.workflow_delete_items) & set(
        inventory.workflow_edit_items
    )
    for item in sorted(duplicate_across):
        errors.append(f"workflow item listed in both delete and edit sections: {item}")

    return errors


def _read_pyproject_scripts(root: Path) -> dict[str, str]:
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data.get("project", {}).get("scripts", {})
    if not isinstance(scripts, dict):
        return {}
    return {str(key): str(value) for key, value in scripts.items()}


def _legacy_runtime_selected(root: Path) -> list[str]:
    errors: list[str] = []

    compose_path = root / "docker-compose.yml"
    if compose_path.is_file():
        compose = compose_path.read_text(encoding="utf-8")
        if "psychoanalyst_app.server" not in compose:
            errors.append(
                "docker-compose.yml must still select the legacy api command "
                "pre-cutover"
            )

    dockerfile_path = root / "Dockerfile"
    if dockerfile_path.is_file():
        dockerfile = dockerfile_path.read_text(encoding="utf-8")
        if "psychoanalyst_app.server" not in dockerfile:
            errors.append(
                "Dockerfile CMD must still reference the legacy server pre-cutover"
            )

    return errors


# ============================================================
# 2. Gate lifecycle
# ============================================================

SHARED_GATE_INVOCATIONS = (
    "$(MAKE) lint",
    "$(MAKE) validate-docs",
    "scripts/validate_refactor_phase_5.py",
)

TARGET_ONLY_GATE_INVOCATIONS = (
    "$(MAKE) test-target",
    "scripts/validate_refactor_phase_6.py",
    "$(MAKE) probe-console-v1-deterministic",
)

LEGACY_GATE_INVOCATIONS = (
    "$(MAKE) validate-schemas",
    "$(MAKE) validate-generated-contracts",
    "$(MAKE) validate-architecture",
    "$(MAKE) characterization-smoke",
    "$(MAKE) probe-console-deterministic",
    "$(MAKE) test-validate",
)

_LEGACY_GATE_MAKE_TARGETS = tuple(
    item.split(" ", 1)[1] for item in LEGACY_GATE_INVOCATIONS
)

_PHASE6_STAGE_ARGUMENTS = {
    "pre-cutover": ("--stage", "pre-cutover"),
    "cutover": ("--stage", "cutover"),
    "final": ("--final",),
}

_NON_EXECUTING_COMMAND_RE = re.compile(
    r"^(?:env(?:\s+[A-Za-z_][A-Za-z0-9_]*=\S+)*\s+)?"
    r"(?:echo|printf)\b"
)


@dataclass(frozen=True)
class RecipeCommand:
    text: str
    ignore_errors: bool


def _logical_recipe_commands(recipe: str) -> tuple[RecipeCommand, ...]:
    physical_lines = recipe.splitlines()[1:]
    commands: list[RecipeCommand] = []
    current: list[str] = []
    ignore_errors = False

    for line in physical_lines:
        if not line.startswith("\t"):
            continue

        part = line.lstrip("\t").strip()

        if not current:
            prefix = part[: len(part) - len(part.lstrip("@+-"))]
            ignore_errors = "-" in prefix
            part = part[len(prefix) :].lstrip()

        if not part or part.startswith("#"):
            continue

        continued = part.endswith("\\")
        if continued:
            part = part[:-1].rstrip()

        current.append(part)

        if not continued:
            command = " ".join(segment for segment in current if segment)
            if command:
                commands.append(
                    RecipeCommand(text=command, ignore_errors=ignore_errors)
                )
            current = []
            ignore_errors = False

    if current:
        commands.append(
            RecipeCommand(
                text=" ".join(current),
                ignore_errors=ignore_errors,
            )
        )

    return tuple(commands)


def _executable_recipe_commands(recipe: str) -> tuple[RecipeCommand, ...]:
    commands: list[RecipeCommand] = []
    for command in _logical_recipe_commands(recipe):
        _, tokens = _split_command(command.text)
        core = " ".join(tokens)
        if _NON_EXECUTING_COMMAND_RE.match(core):
            continue
        commands.append(command)
    return tuple(commands)


def _split_command(command: str) -> tuple[dict[str, str], tuple[str, ...]]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return {}, ()

    environment: dict[str, str] = {}
    index = 0

    while index < len(tokens):
        token = tokens[index]
        if "=" not in token:
            break

        name, value = token.split("=", 1)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            break
        if name in environment:
            return {}, ()

        environment[name] = value
        index += 1

    return environment, tuple(tokens[index:])


def _environment_matches(
    actual: dict[str, str],
    expected: dict[str, str] | None,
) -> bool:
    return actual == (expected or {})


def _matches_make_gate_command(command: RecipeCommand, *, target: str) -> bool:
    if command.ignore_errors:
        return False

    environment, tokens = _split_command(command.text)

    return environment == {} and tokens == ("$(MAKE)", target)


def _matches_validator_gate_command(
    command: RecipeCommand,
    *,
    script: str,
    arguments: tuple[str, ...],
) -> bool:
    if command.ignore_errors:
        return False

    environment, tokens = _split_command(command.text)

    return environment == {} and tokens == (
        "docker",
        "compose",
        "--profile",
        "test",
        "run",
        "--rm",
        "test",
        "python",
        script,
        *arguments,
    )


def _contains_make_invocation(tokens: tuple[str, ...], *, target: str) -> bool:
    for index, token in enumerate(tokens):
        if token not in {"$(MAKE)", "make"}:
            continue
        if index + 1 < len(tokens) and tokens[index + 1] == target:
            return True
    return False


def _gate_forbids_make_target(recipe: str, *, target: str) -> list[str]:
    errors: list[str] = []

    for command in _executable_recipe_commands(recipe):
        _, tokens = _split_command(command.text)
        if _contains_make_invocation(tokens, target=target):
            errors.append(f"gate must not invoke legacy target: {target}")

    return errors


@dataclass(frozen=True)
class ValidatorInvocation:
    command: RecipeCommand
    environment: dict[str, str]
    arguments: tuple[str, ...]


_VALIDATOR_GATE_PREFIX = (
    "docker",
    "compose",
    "--profile",
    "test",
    "run",
    "--rm",
    "test",
    "python",
)


def _validator_gate_invocations(
    recipe: str,
    *,
    script: str,
) -> tuple[ValidatorInvocation, ...]:
    invocations: list[ValidatorInvocation] = []
    expected_prefix = (*_VALIDATOR_GATE_PREFIX, script)
    script_token = script.rsplit("/", 1)[-1]

    for command in _logical_recipe_commands(recipe):
        environment, tokens = _split_command(command.text)

        if tokens[: len(expected_prefix)] == expected_prefix:
            invocations.append(
                ValidatorInvocation(
                    command=command,
                    environment=environment,
                    arguments=tokens[len(expected_prefix) :],
                )
            )
            continue

        if (
            len(tokens) >= 2
            and tokens[0] == "python"
            and tokens[1] in {script, script_token}
        ):
            invocations.append(
                ValidatorInvocation(
                    command=command,
                    environment=environment,
                    arguments=tokens[2:],
                )
            )

    return tuple(invocations)


def _require_validator_invocation(
    recipe: str,
    *,
    script: str,
    expected_arguments: tuple[str, ...],
) -> list[str]:
    invocations = _validator_gate_invocations(recipe, script=script)

    if len(invocations) != 1:
        return [f"gate must invoke {script} exactly once"]

    invocation = invocations[0]
    errors: list[str] = []

    if invocation.command.ignore_errors:
        errors.append(f"{script} invocation must not ignore failures")

    if invocation.environment != {}:
        errors.append(
            f"{script} invocation must not use environment-prefixed execution"
        )

    if invocation.arguments != expected_arguments:
        errors.append(
            f"{script} invocation must use exactly {' '.join(expected_arguments)}"
        )

    return errors


_PURE_GATE_ALIAS_RE = re.compile(
    r"^finalization-check-target:\s*finalization-check\s*$"
)


def _is_pure_gate_alias(recipe: str) -> bool:
    lines = recipe.splitlines()
    if not lines:
        return False
    return (
        _PURE_GATE_ALIAS_RE.fullmatch(lines[0].strip()) is not None
        and not _logical_recipe_commands(recipe)
    )


def _is_dependency_only_alias(
    recipe: str,
    *,
    target: str,
    dependency: str,
) -> bool:
    lines = recipe.splitlines()
    if not lines:
        return False
    header = re.compile(rf"^{re.escape(target)}:\s*{re.escape(dependency)}\s*$")
    return (
        header.fullmatch(lines[0].strip()) is not None
        and not _logical_recipe_commands(recipe)
    )


@dataclass(frozen=True)
class MakeRecipes:
    recipes: dict[str, str]
    duplicate_targets: frozenset[str]


VALIDATED_MAKE_TARGETS = frozenset(
    {
        "finalization-check",
        "finalization-check-target",
        "test-target",
        "validate-refactor-phase-6",
        "probe-console-v1-deterministic",
        "run-server",
        "ui-console",
        "ui-console-test",
        "dev-install",
        "docker-db-view",
        "docker-db-backup",
        "docker-db-backup-verify",
        "docker-db-restore",
        "reset-jung-db",
        "reset-manual-test",
        "smoke-target-local-llm",
        "smoke-refactor-phase-3-local-llm",
        "help",
    }
)

_TARGET_HEADER_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)\s*:(?!=)")


def _all_recipes(root: Path) -> MakeRecipes:
    text = (root / "Makefile").read_text(encoding="utf-8")
    lines = text.splitlines()
    recipes: dict[str, str] = {}
    duplicates: set[str] = set()
    index = 0

    while index < len(lines):
        line = lines[index]

        if line.startswith("\t"):
            index += 1
            continue

        stripped = line.strip()
        if (
            not stripped
            or stripped.startswith("#")
            or stripped.startswith(".")
            or any(token in line for token in (":=", "+=", "?="))
            or ":" not in line
        ):
            index += 1
            continue

        match = _TARGET_HEADER_RE.match(line)
        if not match:
            index += 1
            continue

        target = match.group(1)
        body = [line]
        index += 1
        while index < len(lines) and (
            lines[index].startswith("\t") or not lines[index].strip()
        ):
            body.append(lines[index])
            index += 1

        while body and not body[-1].strip():
            body.pop()

        recipe_text = "\n".join(body)
        if target in recipes:
            duplicates.add(target)
        recipes[target] = recipe_text

    return MakeRecipes(recipes=recipes, duplicate_targets=frozenset(duplicates))


def _require_authoritative_recipes(make_recipes: MakeRecipes) -> list[str]:
    errors: list[str] = []

    for target in sorted(make_recipes.duplicate_targets):
        if target in VALIDATED_MAKE_TARGETS:
            errors.append(f"duplicate Makefile target definition: {target}")

    return errors


def _recipe_text(make_recipes: MakeRecipes, target: str) -> str | None:
    if target in make_recipes.duplicate_targets:
        return None
    return make_recipes.recipes.get(target)


def _require_recipe_text(
    make_recipes: MakeRecipes,
    target: str,
) -> tuple[str | None, list[str]]:
    if target in make_recipes.duplicate_targets:
        return None, [f"duplicate Makefile target definition: {target}"]
    recipe = make_recipes.recipes.get(target)
    if recipe is None:
        return None, [f"Makefile missing required target: {target}"]
    return recipe, []


def _phony_targets(root: Path) -> set[str]:
    makefile = root / "Makefile"
    if not makefile.is_file():
        return set()

    lines = makefile.read_text(encoding="utf-8").splitlines()
    targets: set[str] = set()
    index = 0

    while index < len(lines):
        stripped = lines[index].strip()
        if stripped.startswith(".PHONY"):
            _, _, remainder = stripped.partition(":")
            collected: list[str] = []
            current = remainder.strip()
            while current.endswith("\\"):
                collected.append(current[:-1])
                index += 1
                if index >= len(lines):
                    current = ""
                    break
                current = lines[index].strip()
            collected.append(current)
            for part in collected:
                targets.update(part.split())
        index += 1

    return targets


def _makefile_targets(root: Path) -> set[str]:
    makefile = root / "Makefile"
    if not makefile.is_file():
        return set()
    targets: set[str] = set()
    for line in makefile.read_text(encoding="utf-8").splitlines():
        if line.startswith("\t"):
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if any(token in line for token in (":=", "+=", "?=")):
            continue
        if ":" not in line:
            continue
        target = line.split(":", 1)[0].strip()
        if target and not target.startswith("."):
            targets.add(target)
    return targets


EXPECTED_TEST_TARGET_TOKENS = (
    "docker",
    "compose",
    "--profile",
    "test",
    "run",
    "--rm",
    "test",
    "pytest",
    "$(PHASE_6_PYTEST_OPTIONS)",
    "-m",
    "not real_llm",
    "tests/unit/jung/",
    "tests/integration/jung/",
    "$(TARGET_SUPPORT_TESTS)",
)


def _matches_test_target(command: RecipeCommand) -> bool:
    if command.ignore_errors:
        return False

    environment, tokens = _split_command(command.text)

    return environment == {} and tokens == EXPECTED_TEST_TARGET_TOKENS


EXPECTED_TARGET_SUPPORT_TESTS = (
    "tests/unit/test_validate_refactor_phase_5.py",
    "tests/unit/test_validate_refactor_phase_6.py",
    "tests/unit/test_recording_fake_llm.py",
    "tests/unit/test_measure_codebase.py",
)

EXPECTED_PHASE6_OPTIONS = {
    "pre-cutover": (
        "-o",
        "trio_mode=false",
        "-o",
        "asyncio_mode=auto",
    ),
    "cutover": (
        "-o",
        "trio_mode=false",
        "-o",
        "asyncio_mode=auto",
    ),
    "final": (
        "-o",
        "asyncio_mode=auto",
    ),
}

EXPECTED_PYTEST_ADDOPTS = (
    "-v",
    "--tb=short",
    "--strict-markers",
    "--strict-config",
)

_FORBIDDEN_PYTEST_SELECTION_OPTIONS = frozenset(
    {
        "--collect-only",
        "--co",
        "--ignore",
        "--ignore-glob",
        "--deselect",
        "-k",
        "--last-failed",
        "--lf",
        "--stepwise",
    }
)


def _make_variable_tokens(
    makefile_text: str,
    variable: str,
) -> tuple[str, ...] | None:
    lines = makefile_text.splitlines()

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not re.match(rf"^{re.escape(variable)}\s*:=", stripped):
            continue

        _, _, remainder = stripped.partition(":=")
        parts: list[str] = []
        current = remainder.strip()
        cursor = index

        while current.endswith("\\"):
            parts.append(current[:-1].strip())
            cursor += 1
            if cursor >= len(lines):
                current = ""
                break
            current = lines[cursor].strip()
        parts.append(current)

        joined = " ".join(part for part in parts if part)
        try:
            return tuple(shlex.split(joined))
        except ValueError:
            return None

    return None


def _tokenize_pytest_addopts(raw: str) -> tuple[str, ...]:
    return tuple(raw.split())


def _pytest_addopts_closure_checks(root: Path) -> list[str]:
    path = root / "pytest.ini"
    if not path.is_file():
        return ["pytest.ini is required for frozen addopts contract"]

    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")

    if not parser.has_section("pytest"):
        return ["pytest.ini missing [pytest] section"]

    errors: list[str] = []
    addopts = _tokenize_pytest_addopts(parser["pytest"].get("addopts", ""))

    if addopts != EXPECTED_PYTEST_ADDOPTS:
        errors.append("pytest.ini addopts must match frozen non-selective options")

    for token in addopts:
        if token in _FORBIDDEN_PYTEST_SELECTION_OPTIONS:
            errors.append(f"forbidden pytest selection option in pytest.ini: {token}")

    pyproject_path = root / "pyproject.toml"
    if pyproject_path.is_file():
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        ini_options = pyproject.get("tool", {}).get("pytest", {}).get("ini_options", {})
        if isinstance(ini_options, dict) and "addopts" in ini_options:
            errors.append(
                "pyproject [tool.pytest.ini_options] must not define a second "
                "addopts source while pytest.ini is authoritative"
            )

    return errors


def _test_target_option_closure_checks(root: Path, *, stage: str) -> list[str]:
    errors: list[str] = []
    makefile_text = (root / "Makefile").read_text(encoding="utf-8")

    support = _make_variable_tokens(makefile_text, "TARGET_SUPPORT_TESTS")
    if support != EXPECTED_TARGET_SUPPORT_TESTS:
        errors.append("TARGET_SUPPORT_TESTS must match frozen support-test list")

    options = _make_variable_tokens(makefile_text, "PHASE_6_PYTEST_OPTIONS")
    expected_options = EXPECTED_PHASE6_OPTIONS[stage]
    if options != expected_options:
        errors.append("PHASE_6_PYTEST_OPTIONS must match frozen stage options")

    for token in (support or ()) + (options or ()):
        if token in _FORBIDDEN_PYTEST_SELECTION_OPTIONS:
            errors.append(
                f"forbidden pytest selection option in Make variables: {token}"
            )

    errors.extend(_pytest_addopts_closure_checks(root))

    return errors


def _test_target_checks(
    root: Path,
    make_recipes: MakeRecipes,
    *,
    stage: str,
) -> list[str]:
    errors: list[str] = []

    recipe, recipe_errors = _require_recipe_text(make_recipes, "test-target")
    errors.extend(recipe_errors)
    if recipe is not None:
        commands = _executable_recipe_commands(recipe)
        if len(commands) != 1 or not _matches_test_target(commands[0]):
            errors.append(
                "test-target must use the frozen deterministic pytest command"
            )

    errors.extend(_test_target_option_closure_checks(root, stage=stage))

    return errors


def _require_shared_gate_steps(recipe: str) -> list[str]:
    errors: list[str] = []
    commands = _executable_recipe_commands(recipe)

    if not any(
        _matches_make_gate_command(command, target="lint") for command in commands
    ):
        errors.append("gate must invoke $(MAKE) lint")
    if not any(
        _matches_make_gate_command(command, target="validate-docs")
        for command in commands
    ):
        errors.append("gate must invoke $(MAKE) validate-docs")

    errors.extend(
        _require_validator_invocation(
            recipe,
            script="scripts/validate_refactor_phase_5.py",
            expected_arguments=(),
        )
    )

    return errors


def _require_legacy_gate_steps(recipe: str) -> list[str]:
    errors: list[str] = []
    commands = _executable_recipe_commands(recipe)

    for target in _LEGACY_GATE_MAKE_TARGETS:
        if not any(
            _matches_make_gate_command(command, target=target) for command in commands
        ):
            errors.append(f"gate must invoke $(MAKE) {target}")

    return errors


def _forbid_legacy_gate_steps(recipe: str) -> list[str]:
    errors: list[str] = []
    for target in _LEGACY_GATE_MAKE_TARGETS:
        errors.extend(_gate_forbids_make_target(recipe, target=target))
    return errors


def _require_target_only_gate_steps(recipe: str, *, stage: str) -> list[str]:
    errors: list[str] = []
    commands = _executable_recipe_commands(recipe)

    if not any(
        _matches_make_gate_command(command, target="test-target")
        for command in commands
    ):
        errors.append("gate must invoke $(MAKE) test-target")
    if not any(
        _matches_make_gate_command(command, target="probe-console-v1-deterministic")
        for command in commands
    ):
        errors.append("gate must invoke $(MAKE) probe-console-v1-deterministic")

    errors.extend(
        _require_validator_invocation(
            recipe,
            script="scripts/validate_refactor_phase_6.py",
            expected_arguments=_PHASE6_STAGE_ARGUMENTS[stage],
        )
    )

    return errors


def _forbid_target_only_gate_steps(recipe: str) -> list[str]:
    errors: list[str] = []
    errors.extend(_gate_forbids_make_target(recipe, target="test-target"))
    errors.extend(
        _gate_forbids_make_target(recipe, target="probe-console-v1-deterministic")
    )
    if _validator_gate_invocations(
        recipe, script="scripts/validate_refactor_phase_6.py"
    ):
        errors.append("gate must not invoke scripts/validate_refactor_phase_6.py")
    return errors


_GATE_CRITICAL_PHONY_TARGETS = (
    "finalization-check",
    "test-target",
    "probe-console-v1-deterministic",
    "validate-refactor-phase-6",
)


def _gate_critical_phony_checks(
    root: Path,
    *,
    require_candidate: bool,
) -> list[str]:
    phony = _phony_targets(root)
    targets = _GATE_CRITICAL_PHONY_TARGETS
    if require_candidate:
        targets = (*targets, "finalization-check-target")
    return [
        f".PHONY missing gate-critical target: {target}"
        for target in targets
        if target not in phony
    ]


def _validate_pre_cutover_gate(root: Path) -> list[str]:
    make_recipes = _all_recipes(root)
    recipe_errors = _require_authoritative_recipes(make_recipes)
    if recipe_errors:
        return recipe_errors

    errors: list[str] = []

    canonical, canonical_errors = _require_recipe_text(
        make_recipes, "finalization-check"
    )
    errors.extend(canonical_errors)
    if canonical is not None:
        errors.extend(_require_shared_gate_steps(canonical))
        errors.extend(_require_legacy_gate_steps(canonical))
        errors.extend(_forbid_target_only_gate_steps(canonical))

    candidate, candidate_errors = _require_recipe_text(
        make_recipes, "finalization-check-target"
    )
    errors.extend(candidate_errors)
    if candidate is not None:
        errors.extend(_require_shared_gate_steps(candidate))
        errors.extend(_require_target_only_gate_steps(candidate, stage="pre-cutover"))
        errors.extend(_forbid_legacy_gate_steps(candidate))

    errors.extend(_test_target_checks(root, make_recipes, stage="pre-cutover"))
    errors.extend(_gate_critical_phony_checks(root, require_candidate=True))

    return errors


def _validate_cutover_gate(root: Path) -> list[str]:
    make_recipes = _all_recipes(root)
    recipe_errors = _require_authoritative_recipes(make_recipes)
    if recipe_errors:
        return recipe_errors

    errors: list[str] = []

    canonical, canonical_errors = _require_recipe_text(
        make_recipes, "finalization-check"
    )
    errors.extend(canonical_errors)
    if canonical is not None:
        errors.extend(_require_shared_gate_steps(canonical))
        errors.extend(_require_target_only_gate_steps(canonical, stage="cutover"))
        errors.extend(_forbid_legacy_gate_steps(canonical))

    if "finalization-check-target" in make_recipes.duplicate_targets:
        errors.append("duplicate Makefile target definition: finalization-check-target")
    else:
        candidate = make_recipes.recipes.get("finalization-check-target")
        if candidate is not None and not _is_pure_gate_alias(candidate):
            errors.extend(_require_shared_gate_steps(candidate))
            errors.extend(_require_target_only_gate_steps(candidate, stage="cutover"))
            errors.extend(_forbid_legacy_gate_steps(candidate))

    errors.extend(_test_target_checks(root, make_recipes, stage="cutover"))
    errors.extend(
        _gate_critical_phony_checks(
            root,
            require_candidate="finalization-check-target" in make_recipes.recipes,
        )
    )

    return errors


def _validate_final_gate(root: Path) -> list[str]:
    make_recipes = _all_recipes(root)
    recipe_errors = _require_authoritative_recipes(make_recipes)
    if recipe_errors:
        return recipe_errors

    errors: list[str] = []

    canonical, canonical_errors = _require_recipe_text(
        make_recipes, "finalization-check"
    )
    errors.extend(canonical_errors)
    if canonical is not None:
        errors.extend(_require_shared_gate_steps(canonical))
        errors.extend(_require_target_only_gate_steps(canonical, stage="final"))
        errors.extend(_forbid_legacy_gate_steps(canonical))

    if "finalization-check-target" in make_recipes.duplicate_targets:
        errors.append("duplicate Makefile target definition: finalization-check-target")
    else:
        candidate = make_recipes.recipes.get("finalization-check-target")
        if candidate is not None and not _is_pure_gate_alias(candidate):
            errors.extend(_require_shared_gate_steps(candidate))
            errors.extend(_require_target_only_gate_steps(candidate, stage="final"))
            errors.extend(_forbid_legacy_gate_steps(candidate))

    errors.extend(_test_target_checks(root, make_recipes, stage="final"))
    errors.extend(
        _gate_critical_phony_checks(
            root,
            require_candidate="finalization-check-target" in make_recipes.recipes,
        )
    )

    return errors


# ============================================================
# 3. Supported-runtime checks (persistent: cutover AND final)
# ============================================================

def _dockerfile_stage_blocks(text: str, *, stage: str) -> list[str]:
    lines = text.splitlines()
    header_pattern = re.compile(
        rf"^FROM\s+\S+\s+AS\s+{re.escape(stage)}\s*$", re.IGNORECASE
    )
    from_pattern = re.compile(r"^FROM\s+", re.IGNORECASE)

    blocks: list[str] = []
    index = 0
    while index < len(lines):
        if header_pattern.match(lines[index].strip()):
            block = [lines[index]]
            cursor = index + 1
            while cursor < len(lines) and not from_pattern.match(lines[cursor].strip()):
                block.append(lines[cursor])
                cursor += 1
            blocks.append("\n".join(block))
            index = cursor
        else:
            index += 1

    return blocks


_DOCKERFILE_CMD_RE = re.compile(r'^CMD\s*\[\s*"jung-api"\s*\]\s*$')


def _dockerfile_cutover_checks(root: Path) -> list[str]:
    path = root / "Dockerfile"
    if not path.is_file():
        return ["missing Dockerfile"]

    text = path.read_text(encoding="utf-8")
    blocks = _dockerfile_stage_blocks(text, stage="development")

    if len(blocks) != 1:
        return ["Dockerfile must define exactly one FROM ... AS development stage"]

    active_cmd: str | None = None
    for line in blocks[0].splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("CMD"):
            active_cmd = stripped

    if active_cmd is None or not _DOCKERFILE_CMD_RE.match(active_cmd):
        return ['Dockerfile development stage must end with CMD ["jung-api"]']

    return []


_EXPECTED_ENTRY_POINTS = {
    "jung-api": "jung.api.app:cli",
    "jung-console": "jung.client.terminal:cli",
    "jung-db": "jung.tools.db_backup:main",
}


def _entry_point_checks(root: Path) -> list[str]:
    errors: list[str] = []
    scripts = _read_pyproject_scripts(root)

    if set(scripts) != set(_EXPECTED_ENTRY_POINTS):
        errors.append(
            "pyproject [project.scripts] must define exactly "
            f"{sorted(_EXPECTED_ENTRY_POINTS)}, got {sorted(scripts)}"
        )

    for entry, target in _EXPECTED_ENTRY_POINTS.items():
        if entry in scripts and scripts[entry] != target:
            errors.append(f"pyproject script {entry!r} must map to {target!r}")

    return errors


def _compose_services_block(text: str) -> str:
    lines = text.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        if line == "services:":
            start = index + 1
            break
    if start is None:
        return ""
    block: list[str] = []
    for line in lines[start:]:
        if line.strip() and not line.startswith((" ", "\t")):
            break
        block.append(line)
    return "\n".join(block)


_SERVICE_HEADER_RE = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")


def _compose_service_block(text: str, service: str) -> str:
    lines = text.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        match = _SERVICE_HEADER_RE.match(line)
        if match and match.group(1) == service:
            start = index
            break
    if start is None:
        return ""
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if line.strip():
            indentation = len(line) - len(line.lstrip())
            if indentation <= 2:
                break
        block.append(line)
    return "\n".join(block)


def _service_header_counts(services: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in services.splitlines():
        match = _SERVICE_HEADER_RE.match(line)
        if match:
            counts[match.group(1)] = counts.get(match.group(1), 0) + 1
    return counts


_FORBIDDEN_COMPOSE_SERVICES = ("api-usertest", "console-ui", "console-ui-usertest")

_API_IMAGE_RE = re.compile(r"^\s{4}image:\s*jung-local:dev\s*$", re.MULTILINE)
_API_BUILD_RE = re.compile(
    r"^\s{4}build:\s*\n\s{6}context:\s*\.\s*\n\s{6}dockerfile:\s*Dockerfile\s*\n"
    r"\s{6}target:\s*development\s*$",
    re.MULTILINE,
)
_API_COMMAND_RE = re.compile(
    r"^\s{4}command:\s*(?:jung-api|\[\s*[\"']jung-api[\"']\s*\])\s*$",
    re.MULTILINE,
)
_API_USER_RE = re.compile(
    r'^\s{4}user:\s*"\$\{HOST_UID:-1000\}:\$\{HOST_GID:-1000\}"\s*$', re.MULTILINE
)
_API_PORT_RE = re.compile(r'^\s*-\s*"127\.0\.0\.1:8000:8000"\s*$', re.MULTILINE)
_API_HEALTHCHECK_RE = re.compile(
    r'test:\s*\[\s*"CMD",\s*"wget",\s*"-qO-",\s*'
    r'"http://127\.0\.0\.1:8000/api/v1/health"\s*\]'
)
_APP_NETWORK_MEMBERSHIP_RE = re.compile(r"^\s*-\s*app-network\s*$", re.MULTILINE)
_API_VOLUME_RE = re.compile(r"^\s*-\s*\./data:/app/data\s*$", re.MULTILINE)
_API_HOST_ENV_RE = re.compile(
    r'^\s+JUNG_API_HOST:\s*"?0\.0\.0\.0"?\s*$', re.MULTILINE
)
_API_REMOTE_BIND_ENV_RE = re.compile(
    r'^\s+JUNG_API_ALLOW_REMOTE_BIND:\s*"?true"?\s*$', re.MULTILINE
)
_API_DATA_DIR_ENV_RE = re.compile(
    r'^\s+JUNG_DATA_DIR:\s*"\$\{JUNG_DATA_DIR:-/app/data/default\}"\s*$',
    re.MULTILINE,
)

_CONSOLE_IMAGE_RE = _API_IMAGE_RE
_CONSOLE_COMMAND_RE = re.compile(
    r"^\s{4}command:\s*\n\s{6}-\s*jung-console\s*\n\s{6}-\s*--api-url\s*\n"
    r"\s{6}-\s*http://api:8000\s*$",
    re.MULTILINE,
)
_CONSOLE_STDIN_RE = re.compile(r"^\s{4}stdin_open:\s*true\s*$", re.MULTILINE)
_CONSOLE_TTY_RE = re.compile(r"^\s{4}tty:\s*true\s*$", re.MULTILINE)
_CONSOLE_PROFILES_RE = re.compile(
    r'^\s{4}profiles:\s*\[\s*"console"\s*\]\s*$', re.MULTILINE
)

_DB_VIEWER_IMAGE_RE = re.compile(
    r"^\s{4}image:\s*coleifer/sqlite-web\s*$", re.MULTILINE
)
_DB_VIEWER_PROFILES_RE = re.compile(
    r'^\s{4}profiles:\s*\[\s*"debug"\s*\]\s*$', re.MULTILINE
)
_DB_VIEWER_VOLUME_RE = re.compile(r"^\s*-\s*\./data:/data:ro\s*$", re.MULTILINE)
_DB_VIEWER_PORT_RE = re.compile(r'^\s*-\s*"127\.0\.0\.1:8080:8080"\s*$', re.MULTILINE)
_DB_VIEWER_COMMAND_RE = re.compile(r"/data/\$\{DB_FILE:-default/jung\.db\}")


def _compose_api_checks(block: str) -> list[str]:
    checks = (
        (_API_IMAGE_RE, "api service must set image: jung-local:dev"),
        (
            _API_BUILD_RE,
            "api service must define explicit build: context/dockerfile/target",
        ),
        (_API_COMMAND_RE, "api service must run command: jung-api"),
        (_API_USER_RE, "api service must run as non-root HOST_UID:HOST_GID user"),
        (_API_PORT_RE, "api service must publish loopback-only 127.0.0.1:8000:8000"),
        (_API_HEALTHCHECK_RE, "api service must use the frozen wget health check"),
        (_APP_NETWORK_MEMBERSHIP_RE, "api service must join app-network explicitly"),
        (_API_VOLUME_RE, "api service must mount ./data:/app/data"),
        (_API_HOST_ENV_RE, "api service must set JUNG_API_HOST=0.0.0.0"),
        (
            _API_REMOTE_BIND_ENV_RE,
            "api service must set JUNG_API_ALLOW_REMOTE_BIND=true",
        ),
        (
            _API_DATA_DIR_ENV_RE,
            "api service must set the JUNG_DATA_DIR default mapping",
        ),
    )
    return [message for pattern, message in checks if not pattern.search(block)]


def _compose_console_checks(block: str) -> list[str]:
    checks = (
        (_CONSOLE_IMAGE_RE, "console service must set image: jung-local:dev"),
        (
            _CONSOLE_COMMAND_RE,
            "console service must run jung-console --api-url http://api:8000",
        ),
        (_CONSOLE_STDIN_RE, "console service must set stdin_open: true"),
        (_CONSOLE_TTY_RE, "console service must set tty: true"),
        (_CONSOLE_PROFILES_RE, 'console service must declare profiles: ["console"]'),
        (
            _APP_NETWORK_MEMBERSHIP_RE,
            "console service must join app-network explicitly",
        ),
    )
    errors = [message for pattern, message in checks if not pattern.search(block)]
    if re.search(r"^\s{4}build:\s*$", block, re.MULTILINE):
        errors.append(
            "console service must not define its own build: (reuse api image)"
        )
    return errors


def _compose_db_viewer_checks(block: str) -> list[str]:
    checks = (
        (_DB_VIEWER_IMAGE_RE, "db-viewer service must use image: coleifer/sqlite-web"),
        (_DB_VIEWER_PROFILES_RE, 'db-viewer service must declare profiles: ["debug"]'),
        (_DB_VIEWER_VOLUME_RE, "db-viewer service must mount ./data:/data:ro"),
        (
            _DB_VIEWER_PORT_RE,
            "db-viewer service must publish loopback-only 127.0.0.1:8080:8080",
        ),
        (
            _DB_VIEWER_COMMAND_RE,
            "db-viewer command must use /data/${DB_FILE:-default/jung.db}",
        ),
    )
    return [message for pattern, message in checks if not pattern.search(block)]


def _compose_cutover_checks(root: Path) -> list[str]:
    path = root / "docker-compose.yml"
    if not path.is_file():
        return ["missing docker-compose.yml"]

    text = path.read_text(encoding="utf-8")
    errors: list[str] = []

    top_level_blocks, _ = _workflow_top_level_block(text, key="services")
    services_count = len(re.findall(r"^services:\s*$", text, re.MULTILINE))
    if services_count != 1:
        errors.append(
            "docker-compose.yml must define exactly one top-level services: block"
        )

    services = _compose_services_block(text)
    if not services:
        errors.append("docker-compose.yml missing services: block")
        return errors

    header_counts = _service_header_counts(services)
    for header, count in header_counts.items():
        if count > 1:
            errors.append(
                f"docker-compose.yml duplicate service definition: {header}"
            )
    for forbidden in _FORBIDDEN_COMPOSE_SERVICES:
        if forbidden in header_counts:
            errors.append(
                f"docker-compose.yml must not define forbidden service: {forbidden}"
            )

    network_block, network_count = _workflow_top_level_block(text, key="networks")
    if (
        network_count != 1
        or "app-network:" not in network_block
        or "driver: bridge" not in network_block
    ):
        errors.append(
            "docker-compose.yml missing top-level app-network network definition"
        )

    api_block = _compose_service_block(services, "api")
    console_block = _compose_service_block(services, "console")
    db_viewer_block = _compose_service_block(services, "db-viewer")

    if not api_block:
        errors.append("docker-compose.yml missing api service")
    else:
        errors.extend(_compose_api_checks(api_block))

    if not console_block:
        errors.append("docker-compose.yml missing console service")
    else:
        errors.extend(_compose_console_checks(console_block))

    if not db_viewer_block:
        errors.append("docker-compose.yml missing db-viewer service")
    else:
        errors.extend(_compose_db_viewer_checks(db_viewer_block))

    _ = top_level_blocks
    return errors


REQUIRED_CUTOVER_MAKE_TARGETS = (
    "run-server",
    "ui-console",
    "ui-console-test",
    "docker-db-view",
    "docker-db-backup",
    "docker-db-backup-verify",
    "docker-db-restore",
    "reset-jung-db",
    "reset-manual-test",
    "dev-install",
    "smoke-target-local-llm",
)

FORBIDDEN_CUTOVER_MAKE_TARGETS = (
    "test-real-llm",
    "test-validate-no-mocks",
    "reset-usertest",
    "reset-foundation-db",
    "finalization-check-full",
)

FORBIDDEN_USER_TARGET_TOKENS = (
    "psychoanalyst_app.server",
    "psychoanalyst_app.tools",
    "console-ui",
)

_PUBLIC_PHONY_REQUIRED_TARGETS = (
    "run-server",
    "ui-console",
    "ui-console-test",
    "docker-db-view",
    "docker-db-backup",
    "docker-db-backup-verify",
    "docker-db-restore",
    "reset-jung-db",
    "reset-manual-test",
    "smoke-target-local-llm",
)

_HELP_DOCUMENTED_TARGETS = (
    "ui-console",
    "ui-console-test",
    "docker-db-view",
    "reset-jung-db",
    "reset-manual-test",
    "smoke-target-local-llm",
)

RESET_TARGET_PATHS = {
    "reset-jung-db": "data/default",
    "reset-manual-test": "data/manual-test",
}

_DB_TARGET_OPERATIONS = {
    "docker-db-backup": "backup",
    "docker-db-backup-verify": "verify",
    "docker-db-restore": "restore",
}


def _make_target_reference_pattern(target: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?<![A-Za-z0-9_.-]){re.escape(target)}(?![A-Za-z0-9_.-])"
    )


def _make_invocation_pattern(target: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?:^|(?:&&|;|\|\|)\s*)"
        rf"(?:\$\(MAKE\)|make)\s+{re.escape(target)}(?=\s|$|[;&])"
    )


_JUNG_DB_PROFILE_DEFAULT_RE = re.compile(
    r"^JUNG_DB_PROFILE\s*\?=\s*default\s*$", re.MULTILINE
)
_JUNG_DB_PROFILE_FILTER_RE = re.compile(r"\$\(filter\b")


def _db_profile_mechanism_checks(makefile_text: str) -> list[str]:
    errors: list[str] = []

    if not _JUNG_DB_PROFILE_DEFAULT_RE.search(makefile_text):
        errors.append("Makefile missing JUNG_DB_PROFILE ?= default")

    if _JUNG_DB_PROFILE_FILTER_RE.search(makefile_text):
        errors.append("JUNG_DB_PROFILE allow-list must not use $(filter ...)")

    if not re.search(
        r"ifneq\s*\(\s*\$\(JUNG_DB_PROFILE\)\s*,\s*default\s*\)", makefile_text
    ) or not re.search(
        r"ifneq\s*\(\s*\$\(JUNG_DB_PROFILE\)\s*,\s*manual-test\s*\)", makefile_text
    ):
        errors.append(
            "JUNG_DB_PROFILE allow-list must use exact-equality ifneq guards"
        )

    if not re.search(r"^JUNG_DB_DATA_DIR\s*:=", makefile_text, re.MULTILINE):
        errors.append("Makefile missing JUNG_DB_DATA_DIR derived from profile")

    if not re.search(r"^JUNG_DB_RELATIVE_FILE\s*:=", makefile_text, re.MULTILINE):
        errors.append("Makefile missing JUNG_DB_RELATIVE_FILE derived from profile")

    if re.search(r"^JUNG_DB_HOST_DIR\s*[:?]?=", makefile_text, re.MULTILINE):
        errors.append("Makefile must not define unused JUNG_DB_HOST_DIR")
    if re.search(r"^JUNG_DB_HOST_FILE\s*[:?]?=", makefile_text, re.MULTILINE):
        errors.append("Makefile must not define unused JUNG_DB_HOST_FILE")

    return errors


def _matches_api_up(
    command: str,
    *,
    expected_options: tuple[str, ...],
    expected_env: dict[str, str] | None = None,
) -> bool:
    environment, tokens = _split_command(command)
    if not _environment_matches(environment, expected_env):
        return False

    return tokens == ("docker", "compose", "up", *expected_options, "api")


def _matches_console_run(
    command: str,
    *,
    expected_env: dict[str, str] | None = None,
) -> bool:
    environment, tokens = _split_command(command)
    if not _environment_matches(environment, expected_env):
        return False

    return tokens in {
        (
            "docker", "compose", "--profile", "console", "run", "--rm",
            "-it", "--no-deps", "console",
        ),
        (
            "docker", "compose", "--profile", "console", "run", "--rm",
            "-i", "-t", "--no-deps", "console",
        ),
    }


def _matches_run_server(command: str) -> bool:
    return _matches_api_up(
        command,
        expected_options=("--build", "--remove-orphans"),
        expected_env={},
    )


def _matches_dev_install_build(command: str) -> bool:
    environment, tokens = _split_command(command)
    return _environment_matches(environment, {}) and tokens == (
        "docker", "compose", "build", "api",
    )


def _matches_stop_api(command: str) -> bool:
    environment, tokens = _split_command(command)
    return _environment_matches(environment, {}) and tokens == (
        "docker", "compose", "stop", "api",
    )


def _matches_compose_down(command: str) -> bool:
    environment, tokens = _split_command(command)
    return _environment_matches(environment, {}) and tokens == (
        "docker", "compose", "down", "--remove-orphans",
    )


def _matches_db_view(command: str) -> bool:
    environment, tokens = _split_command(command)
    return environment == {"DB_FILE": "$(JUNG_DB_RELATIVE_FILE)"} and tokens == (
        "docker", "compose", "--profile", "debug", "up",
        "--remove-orphans", "db-viewer",
    )


def _matches_reset_rm(command: str, *, directory: str) -> bool:
    environment, tokens = _split_command(command)
    return _environment_matches(environment, {}) and tokens == (
        "rm", "-f",
        f"{directory}/jung.db",
        f"{directory}/jung.db-wal",
        f"{directory}/jung.db-shm",
    )


def _matches_db_command(
    command: str,
    *,
    operation: str,
    expected_env: dict[str, str] | None = None,
) -> bool:
    environment, tokens = _split_command(command)

    if not _environment_matches(environment, expected_env):
        return False

    try:
        service_index = tokens.index("api")
    except ValueError:
        return False

    compose_prefix = tokens[:service_index]
    tool_tokens = tokens[service_index + 1 :]

    if compose_prefix != ("docker", "compose", "run", "--rm", "--no-deps"):
        return False

    expected_tools = {
        "backup": ("jung-db", "backup"),
        "verify": ("jung-db", "verify", "$(BACKUP)"),
        "restore": ("jung-db", "restore", "$(BACKUP)", "--replace"),
    }

    return tool_tokens == expected_tools[operation]


_BACKUP_GUARD_RE = re.compile(
    r'test\s+-n\s+"\$\(BACKUP\)"\s*\|\|\s*\{.*exit\s+\d+\s*;?\s*\}'
)


def _require_backup_guard(recipe: str) -> list[str]:
    guard_index: int | None = None
    invocation_index: int | None = None

    for index, command in enumerate(_logical_recipe_commands(recipe)):
        if command.ignore_errors:
            continue
        if _BACKUP_GUARD_RE.search(command.text):
            guard_index = index
        _, tokens = _split_command(command.text)
        if "jung-db" in tokens and ("verify" in tokens or "restore" in tokens):
            invocation_index = index

    if guard_index is None:
        return ['BACKUP guard is missing (test -n "$(BACKUP)" || exit)']
    if invocation_index is not None and guard_index > invocation_index:
        return ["BACKUP guard must appear before the DB invocation"]
    return []


def _db_operation_checks(make_recipes: MakeRecipes) -> list[str]:
    errors: list[str] = []

    for target, operation in _DB_TARGET_OPERATIONS.items():
        recipe, recipe_errors = _require_recipe_text(make_recipes, target)
        errors.extend(recipe_errors)
        if recipe is None:
            continue

        expected_env = (
            {"JUNG_DATA_DIR": "$(JUNG_DB_DATA_DIR)"}
            if operation in {"backup", "restore"}
            else {}
        )
        commands = _executable_recipe_commands(recipe)
        if not any(
            not command.ignore_errors
            and _matches_db_command(
                command.text, operation=operation, expected_env=expected_env
            )
            for command in commands
        ):
            errors.append(
                f"{target} must match the frozen docker compose run contract"
            )

        if operation in {"verify", "restore"}:
            errors.extend(_require_backup_guard(recipe))

        if operation == "restore" and not any(
            not command.ignore_errors and _matches_stop_api(command.text)
            for command in commands
        ):
            errors.append("docker-db-restore must stop api before restoring")

    return errors


def _reset_command_checks(make_recipes: MakeRecipes) -> list[str]:
    errors: list[str] = []

    for target, directory in RESET_TARGET_PATHS.items():
        recipe, recipe_errors = _require_recipe_text(make_recipes, target)
        errors.extend(recipe_errors)
        if recipe is None:
            continue

        commands = _executable_recipe_commands(recipe)
        has_stop = any(
            not command.ignore_errors and _matches_stop_api(command.text)
            for command in commands
        )
        has_rm = any(
            not command.ignore_errors
            and _matches_reset_rm(command.text, directory=directory)
            for command in commands
        )

        if not has_stop:
            errors.append(f"{target} must stop api before deleting database files")
        if not has_rm:
            errors.append(
                f"{target} must remove exactly the {directory} database files"
            )

    return errors


def _ui_profile_checks(
    recipe: str,
    *,
    target: str,
    data_dir: str,
    other_dir: str,
    requires_down_first: bool,
) -> list[str]:
    errors: list[str] = []
    commands = [
        command
        for command in _executable_recipe_commands(recipe)
        if not command.ignore_errors
    ]

    api_matches = [
        command
        for command in commands
        if _matches_api_up(
            command.text,
            expected_options=("-d", "--wait"),
            expected_env={"JUNG_DATA_DIR": data_dir},
        )
    ]
    console_matches = [
        command
        for command in commands
        if _matches_console_run(command.text, expected_env={"JUNG_DATA_DIR": data_dir})
    ]

    if len(api_matches) != 1:
        errors.append(
            f"{target} must start api exactly once with JUNG_DATA_DIR={data_dir}"
        )
    if len(console_matches) != 1:
        errors.append(
            f"{target} must run console exactly once with JUNG_DATA_DIR={data_dir}"
        )

    if requires_down_first and (
        not commands or not _matches_compose_down(commands[0].text)
    ):
        errors.append(f"{target} must run docker compose down --remove-orphans first")

    for command in commands:
        if other_dir in command.text:
            errors.append(f"{target} must not reference {other_dir}")

    return errors


def _ui_and_runtime_command_checks(make_recipes: MakeRecipes) -> list[str]:
    errors: list[str] = []

    run_server, run_server_errors = _require_recipe_text(make_recipes, "run-server")
    errors.extend(run_server_errors)
    if run_server is not None:
        commands = _executable_recipe_commands(run_server)
        if not any(
            not command.ignore_errors and _matches_run_server(command.text)
            for command in commands
        ):
            errors.append(
                "run-server must use docker compose up --build --remove-orphans api"
            )

    dev_install, dev_install_errors = _require_recipe_text(make_recipes, "dev-install")
    errors.extend(dev_install_errors)
    if dev_install is not None:
        commands = _executable_recipe_commands(dev_install)
        if not any(
            not command.ignore_errors and _matches_dev_install_build(command.text)
            for command in commands
        ):
            errors.append("dev-install must run docker compose build api only")

    ui_console, ui_console_errors = _require_recipe_text(make_recipes, "ui-console")
    errors.extend(ui_console_errors)
    if ui_console is not None:
        errors.extend(
            _ui_profile_checks(
                ui_console,
                target="ui-console",
                data_dir="/app/data/default",
                other_dir="/app/data/manual-test",
                requires_down_first=False,
            )
        )

    ui_console_test, ui_console_test_errors = _require_recipe_text(
        make_recipes, "ui-console-test"
    )
    errors.extend(ui_console_test_errors)
    if ui_console_test is not None:
        errors.extend(
            _ui_profile_checks(
                ui_console_test,
                target="ui-console-test",
                data_dir="/app/data/manual-test",
                other_dir="/app/data/default",
                requires_down_first=True,
            )
        )

    docker_db_view, docker_db_view_errors = _require_recipe_text(
        make_recipes, "docker-db-view"
    )
    errors.extend(docker_db_view_errors)
    if docker_db_view is not None:
        commands = _executable_recipe_commands(docker_db_view)
        if not any(
            not command.ignore_errors and _matches_db_view(command.text)
            for command in commands
        ):
            errors.append(
                "docker-db-view must run DB_FILE=$(JUNG_DB_RELATIVE_FILE) docker "
                "compose --profile debug up --remove-orphans db-viewer"
            )

    return errors


def _makefile_cutover_checks(root: Path) -> list[str]:
    make_recipes = _all_recipes(root)
    recipe_errors = _require_authoritative_recipes(make_recipes)
    if recipe_errors:
        return recipe_errors

    errors: list[str] = []
    defined_targets = _makefile_targets(root)
    phony_targets = _phony_targets(root)
    makefile_text = (root / "Makefile").read_text(encoding="utf-8")

    for target in REQUIRED_CUTOVER_MAKE_TARGETS:
        if target not in defined_targets:
            errors.append(f"Makefile missing required cutover target: {target}")

    for target in FORBIDDEN_CUTOVER_MAKE_TARGETS:
        if target in defined_targets:
            errors.append(f"Makefile must not define forbidden target: {target}")
        if target in phony_targets:
            errors.append(f".PHONY must not declare forbidden target: {target}")

    for target in _PUBLIC_PHONY_REQUIRED_TARGETS:
        if target not in phony_targets:
            errors.append(f".PHONY missing public replacement target: {target}")

    help_recipe, help_errors = _require_recipe_text(make_recipes, "help")
    errors.extend(help_errors)
    if help_recipe is not None:
        for target in FORBIDDEN_CUTOVER_MAKE_TARGETS:
            if _make_target_reference_pattern(target).search(help_recipe):
                errors.append(f"help still documents forbidden target: {target}")
        for target in _HELP_DOCUMENTED_TARGETS:
            if not _make_target_reference_pattern(target).search(help_recipe):
                errors.append(f"help missing documentation for target: {target}")

    for recipe_target, recipe in make_recipes.recipes.items():
        if recipe_target in make_recipes.duplicate_targets:
            continue
        for command in _executable_recipe_commands(recipe):
            for token in FORBIDDEN_USER_TARGET_TOKENS:
                if token in command.text:
                    errors.append(
                        f"{recipe_target} still references forbidden token: {token}"
                    )

    smoke_recipe, smoke_errors = _require_recipe_text(
        make_recipes, "smoke-target-local-llm"
    )
    errors.extend(smoke_errors)
    if smoke_recipe is not None and not _is_dependency_only_alias(
        smoke_recipe,
        target="smoke-target-local-llm",
        dependency="smoke-refactor-phase-3-local-llm",
    ):
        errors.append(
            "smoke-target-local-llm must delegate to smoke-refactor-phase-3-local-llm"
        )
    if "smoke-refactor-phase-3-local-llm" not in defined_targets:
        errors.append(
            "Makefile missing smoke delegate: smoke-refactor-phase-3-local-llm"
        )

    errors.extend(_db_profile_mechanism_checks(makefile_text))
    errors.extend(_db_operation_checks(make_recipes))
    errors.extend(_reset_command_checks(make_recipes))
    errors.extend(_ui_and_runtime_command_checks(make_recipes))

    return errors


_FORBIDDEN_ENV_ASSIGNMENT_RE = re.compile(
    r"^\s*(?:#\s*)?(?:-\s*)?(USER_ID|AUTH_TOKEN)\s*(?:=|:)",
    re.MULTILINE,
)
_JUNG_DATA_DIR_DOCUMENTED_RE = re.compile(
    r'^\s*#?\s*JUNG_DATA_DIR\s*=\s*["\']?/app/data/default["\']?\s*$',
    re.MULTILINE,
)


def _env_example_cutover_checks(root: Path) -> list[str]:
    path = root / ".env.example"
    if not path.is_file():
        return ["missing .env.example"]

    text = path.read_text(encoding="utf-8")
    errors: list[str] = []

    if _FORBIDDEN_ENV_ASSIGNMENT_RE.search(text):
        errors.append(".env.example must not assign USER_ID or AUTH_TOKEN")
    if not _JUNG_DATA_DIR_DOCUMENTED_RE.search(text):
        errors.append(".env.example must document JUNG_DATA_DIR=/app/data/default")

    return errors


def _supported_runtime_checks(root: Path) -> list[str]:
    errors: list[str] = []
    errors.extend(_compose_cutover_checks(root))
    errors.extend(_dockerfile_cutover_checks(root))
    errors.extend(_entry_point_checks(root))
    errors.extend(_makefile_cutover_checks(root))
    errors.extend(_env_example_cutover_checks(root))
    return errors


# ============================================================
# 4. Final deletion checks
# ============================================================

def _workflow_top_level_block(text: str, *, key: str) -> tuple[str, int]:
    lines = text.splitlines()
    count = 0
    start: int | None = None

    for index, line in enumerate(lines):
        if line == f"{key}:":
            count += 1
            if start is None:
                start = index

    if start is None:
        return "", count

    block = [lines[start]]
    for line in lines[start + 1 :]:
        if line.strip() and not line.startswith((" ", "\t")):
            break
        block.append(line)

    return "\n".join(block), count


def _workflow_jobs_block(text: str) -> tuple[str, int]:
    return _workflow_top_level_block(text, key="jobs")


def _workflow_job_block(text: str, job: str) -> tuple[str, int]:
    jobs_block, jobs_count = _workflow_jobs_block(text)
    if jobs_count != 1:
        return "", jobs_count

    lines = jobs_block.splitlines()
    matches = 0
    start: int | None = None

    for index, line in enumerate(lines):
        if line == f"  {job}:":
            matches += 1
            if start is None:
                start = index

    if start is None:
        return "", 0

    block = [lines[start]]
    for line in lines[start + 1 :]:
        if line.strip():
            indentation = len(line) - len(line.lstrip())
            if indentation <= 2:
                break
        block.append(line)

    return "\n".join(block), matches


def _release_workflow_trigger_checks(text: str) -> list[str]:
    on_block, on_count = _workflow_top_level_block(text, key="on")
    errors: list[str] = []

    if on_count != 1 or not on_block:
        errors.append("release-candidate workflow must define exactly one on: block")
        return errors

    if "pull_request" not in on_block:
        errors.append("release-candidate workflow must trigger on pull_request")
    else:
        pull_request_section = on_block.split("pull_request", 1)[1]
        next_trigger_index = len(pull_request_section)
        for marker in ("push:", "workflow_dispatch:", "schedule:"):
            marker_index = pull_request_section.find(f"\n  {marker}")
            if marker_index != -1:
                next_trigger_index = min(next_trigger_index, marker_index)
        pull_request_body = pull_request_section[:next_trigger_index]

        if "main" not in pull_request_body:
            errors.append("release-candidate pull_request trigger must include main")
        if "paths" in pull_request_body:
            errors.append(
                "release-candidate pull_request trigger must not restrict paths"
            )

    if "push" not in on_block:
        errors.append("release-candidate workflow must retain a push trigger for main")

    return errors


FORBIDDEN_RELEASE_GATE_ENV_KEYS = frozenset(
    {
        "MAKEFLAGS",
        "MFLAGS",
        "MAKE",
        "COMPOSE_FILE",
        "DOCKER_HOST",
        "COMPOSE_PROFILES",
    }
)


def _release_workflow_env_checks(text: str) -> list[str]:
    errors: list[str] = []

    for key in FORBIDDEN_RELEASE_GATE_ENV_KEYS:
        if re.search(rf"^\s*{re.escape(key)}\s*:", text, re.MULTILINE):
            errors.append(f"release-candidate workflow must not set env key: {key}")

    top_level_env, _ = _workflow_top_level_block(text, key="env")
    if top_level_env:
        errors.append(
            "release-candidate workflow must not define a top-level env: block"
        )

    return errors


_FORBIDDEN_GATE_JOB_KEYS = (
    re.compile(r"^\s+if\s*:", re.MULTILINE),
    re.compile(r"^\s+continue-on-error\s*:", re.MULTILINE),
)

_WORKFLOW_STEP_RE = re.compile(r"(?:^|\n)(\s+-\s+.*?)(?=\n\s+-\s+|\Z)", re.DOTALL)


def _release_workflow_job_shape_checks(job_block: str) -> list[str]:
    errors: list[str] = []

    for pattern in _FORBIDDEN_GATE_JOB_KEYS:
        if pattern.search(job_block):
            errors.append(
                "release-candidate finalization-check job must not use if: or "
                "continue-on-error:"
            )
            break

    if not re.search(r"^\s+runs-on:\s*ubuntu-latest\s*$", job_block, re.MULTILINE):
        errors.append(
            "release-candidate finalization-check job must run on ubuntu-latest"
        )

    if re.search(r"^\s+container\s*:", job_block, re.MULTILINE):
        errors.append(
            "release-candidate finalization-check job must not define container:"
        )

    if re.search(r"defaults\s*:\s*\n\s+run\s*:\s*\n\s+shell\s*:", job_block):
        errors.append(
            "release-candidate finalization-check job must not override "
            "defaults.run.shell"
        )

    env_match = re.search(
        r"^\s+env\s*:\s*\n((?:\s{4,}.+\n?)*)", job_block, re.MULTILINE
    )
    if env_match:
        env_lines = [
            line.strip() for line in env_match.group(1).splitlines() if line.strip()
        ]
        if env_lines != ["ENV_FILE: .env.example"]:
            errors.append(
                "release-candidate finalization-check job env: must contain only "
                "ENV_FILE: .env.example"
            )

    steps_match = re.search(r"^\s+steps\s*:\s*\n((?:.*\n?)*)", job_block, re.MULTILINE)
    steps_body = steps_match.group(1) if steps_match else ""
    steps = [match.group(1) for match in _WORKFLOW_STEP_RE.finditer(steps_body)]

    if len(steps) != 3:
        errors.append(
            "release-candidate finalization-check job must define exactly three steps"
        )
        return errors

    checkout, gate, diff = steps

    if "uses: actions/checkout@v4" not in checkout:
        errors.append("first step must be uses: actions/checkout@v4")
    if "with:" in checkout:
        errors.append("checkout step must not define a with: block")

    if "run: make finalization-check" not in gate:
        errors.append("second step must run: make finalization-check")
    forbidden_step_keys = (
        "shell:",
        "working-directory:",
        "env:",
        "if:",
        "continue-on-error:",
    )
    for forbidden_key in forbidden_step_keys:
        if forbidden_key in gate:
            errors.append(f"gate step must not define {forbidden_key.rstrip(':')}")

    if "run: git diff --check && git diff --exit-code" not in diff:
        errors.append("third step must run: git diff --check && git diff --exit-code")

    return errors


_FORBIDDEN_RELEASE_WORKFLOW_PATTERNS: tuple[re.Pattern[str], ...] = ()


def _release_candidate_workflow_clean(root: Path) -> list[str]:
    errors: list[str] = []
    workflow_text = (root / RELEASE_CANDIDATE_WORKFLOW).read_text(encoding="utf-8")

    errors.extend(_release_workflow_trigger_checks(workflow_text))
    errors.extend(_release_workflow_env_checks(workflow_text))

    job_block, job_count = _workflow_job_block(workflow_text, "finalization-check")

    if job_count != 1:
        errors.append(
            "release-candidate workflow must define exactly one finalization-check "
            "job under jobs:"
        )
    elif not job_block:
        errors.append("release-candidate workflow missing finalization-check job")
    else:
        errors.extend(_release_workflow_job_shape_checks(job_block))

    for pattern in _FORBIDDEN_RELEASE_WORKFLOW_PATTERNS:
        if pattern.search(workflow_text):
            errors.append("release-candidate workflow contains a forbidden pattern")

    return errors


def _workflow_deletion_checks(root: Path, inventory: Inventory) -> list[str]:
    errors: list[str] = []

    for item in inventory.workflow_delete_items:
        path = root / item
        if path.exists() or path.is_symlink():
            errors.append(f"legacy workflow still exists: {item}")

    release_path = root / RELEASE_CANDIDATE_WORKFLOW
    if not release_path.is_file():
        errors.append(
            f"workflow scheduled for editing is missing: {RELEASE_CANDIDATE_WORKFLOW}"
        )
    else:
        errors.extend(_release_candidate_workflow_clean(root))

    return errors


def _remaining_makefile_checks(
    root: Path,
    inventory: Inventory,
    make_recipes: MakeRecipes,
) -> list[str]:
    errors: list[str] = []
    recipe_errors = _require_authoritative_recipes(make_recipes)
    if recipe_errors:
        return recipe_errors

    defined_targets = _makefile_targets(root)
    phony_targets = _phony_targets(root)
    help_recipe, help_errors = _require_recipe_text(make_recipes, "help")
    errors.extend(help_errors)
    reference_pattern_cache: dict[str, re.Pattern[str]] = {}

    for target in inventory.make_targets:
        if target in defined_targets:
            errors.append(f"Makefile still defines legacy target: {target}")
        if target in phony_targets:
            errors.append(f".PHONY still declares legacy target: {target}")

        reference_pattern = reference_pattern_cache.setdefault(
            target, _make_target_reference_pattern(target)
        )

        for recipe_target, recipe in make_recipes.recipes.items():
            if recipe_target in make_recipes.duplicate_targets:
                continue
            lines = recipe.splitlines()
            if not lines:
                continue
            _, _, prerequisites = lines[0].partition(":")
            if reference_pattern.search(prerequisites):
                errors.append(
                    f"{recipe_target} still lists legacy prerequisite: {target}"
                )

        invocation_pattern = _make_invocation_pattern(target)
        for recipe_target, recipe in make_recipes.recipes.items():
            if recipe_target in make_recipes.duplicate_targets:
                continue
            for command in _executable_recipe_commands(recipe):
                _, tokens = _split_command(command.text)
                command_for_match = " ".join(tokens)
                if invocation_pattern.search(command_for_match):
                    errors.append(
                        f"{recipe_target} still invokes legacy target: {target}"
                    )

        if help_recipe is not None and reference_pattern.search(help_recipe):
            errors.append(f"help still documents legacy target: {target}")

    return errors


def _remaining_workflow_checks(root: Path, inventory: Inventory) -> list[str]:
    errors: list[str] = []
    workflow_root = root / ".github/workflows"

    if not workflow_root.is_dir():
        return ["missing .github/workflows directory"]

    workflow_paths = sorted(
        {*workflow_root.glob("*.yml"), *workflow_root.glob("*.yaml")}
    )

    patterns = {
        target: re.compile(rf"\bmake\s+{re.escape(target)}(?=\s|$|[;&])")
        for target in inventory.make_targets
    }

    for path in workflow_paths:
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(root)

        if "psychoanalyst_app" in text:
            errors.append(f"{relative} still references psychoanalyst_app")

        for target, pattern in patterns.items():
            if pattern.search(text):
                errors.append(f"{relative} still invokes legacy command: make {target}")

        for item in inventory.filesystem_roots:
            normalized = item.rstrip("/")
            if normalized and normalized in text:
                errors.append(
                    f"{relative} still references deleted filesystem item: {item}"
                )

    return errors


FORBIDDEN_FINAL_DEPENDENCIES = frozenset(
    {
        "trio",
        "pytest-trio",
        "quart",
        "quart-trio",
        "quart-cors",
        "trio-websocket",
        "hypercorn",
    }
)


def _is_forbidden_final_dependency(name: str) -> bool:
    return (
        name in FORBIDDEN_FINAL_DEPENDENCIES
        or name == "langchain"
        or name.startswith("langchain-")
    )


FORBIDDEN_FINAL_MODULE_ROOTS = frozenset(
    {
        "psychoanalyst_app",
        "trio",
        "pytest_trio",
        "quart",
        "quart_trio",
        "quart_cors",
        "trio_websocket",
        "hypercorn",
    }
)


def _is_forbidden_final_module(module: str) -> bool:
    root = module.split(".", 1)[0]

    return (
        root in FORBIDDEN_FINAL_MODULE_ROOTS
        or module == "langchain"
        or module.startswith("langchain.")
        or module.startswith("langchain_")
    )


_PIP_DIRECTIVE_PREFIXES = (
    "-r",
    "--requirement",
    "-c",
    "--constraint",
    "--index-url",
    "--extra-index-url",
    "--trusted-host",
    "--hash",
)


def _canonical_dependency_name(line: str) -> str | None:
    stripped = line.split("#", 1)[0].strip().rstrip("\\").strip()
    if not stripped:
        return None
    first_token = stripped.split()[0]
    if stripped.startswith(_PIP_DIRECTIVE_PREFIXES) or first_token.startswith("-"):
        return None
    name = re.split(r"[<>=!~\[;]", stripped, maxsplit=1)[0].strip().lower()
    return name or None


def _dependency_closure_checks(root: Path) -> list[str]:
    errors: list[str] = []

    for relative in (
        "requirements.in",
        "requirements.txt",
        "requirements-dev.in",
        "requirements-dev.txt",
    ):
        path = root / relative
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            name = _canonical_dependency_name(raw_line)
            if name and _is_forbidden_final_dependency(name):
                errors.append(f"{relative} still lists forbidden dependency: {name}")

    pyproject_path = root / "pyproject.toml"
    if pyproject_path.is_file():
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        project = pyproject.get("project", {})

        dependencies = project.get("dependencies", [])
        if isinstance(dependencies, list):
            for entry in dependencies:
                if isinstance(entry, str):
                    name = _canonical_dependency_name(entry)
                    if name and _is_forbidden_final_dependency(name):
                        errors.append(
                            "pyproject dependencies still lists forbidden "
                            f"dependency: {name}"
                        )

        optional_dependencies = project.get("optional-dependencies", {})
        if isinstance(optional_dependencies, dict):
            for group, entries in optional_dependencies.items():
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if isinstance(entry, str):
                        name = _canonical_dependency_name(entry)
                        if name and _is_forbidden_final_dependency(name):
                            errors.append(
                                f"pyproject optional-dependencies[{group}] still "
                                f"lists forbidden dependency: {name}"
                            )

    return errors


def _pytest_ini_checks(root: Path) -> list[str]:
    path = root / "pytest.ini"
    if not path.is_file():
        return ["pytest.ini is required for frozen addopts contract"]

    text = path.read_text(encoding="utf-8")
    errors: list[str] = []

    if re.search(r"^\s*trio_mode\s*=", text, re.MULTILINE):
        errors.append("pytest.ini must not set trio_mode in final closure")
    if re.search(r"^\s*trio\s*:", text, re.MULTILINE):
        errors.append("pytest.ini must not declare a trio marker in final closure")

    return errors


_TRIO_MODE_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_-])trio_mode(?![A-Za-z0-9_-])")


def _makefile_final_tooling_checks(root: Path) -> list[str]:
    text = (root / "Makefile").read_text(encoding="utf-8")
    normalized = "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#")
    )
    if _TRIO_MODE_TOKEN_RE.search(normalized):
        return [
            "Makefile must not retain trio_mode pytest configuration in "
            "final closure"
        ]
    return []


def _tooling_config_checks(root: Path, inventory: Inventory) -> list[str]:
    errors: list[str] = []

    pyproject_path = root / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    per_file_ignores = (
        pyproject.get("tool", {})
        .get("ruff", {})
        .get("lint", {})
        .get("per-file-ignores", {})
    )
    if isinstance(per_file_ignores, dict):
        for pattern in per_file_ignores:
            for root_item in inventory.filesystem_roots:
                normalized = root_item.rstrip("/")
                if normalized and normalized in pattern:
                    errors.append(
                        "Ruff per-file-ignores still references a deleted "
                        f"root: {pattern}"
                    )

    overrides = pyproject.get("tool", {}).get("mypy", {}).get("overrides", [])
    if not isinstance(overrides, list):
        errors.append("[[tool.mypy.overrides]] must be a list")
    else:
        for override in overrides:
            if not isinstance(override, dict):
                errors.append("tool.mypy.overrides entries must be tables")
                continue
            module = override.get("module")
            modules = module if isinstance(module, list) else [module]
            for entry in modules:
                if not isinstance(entry, str):
                    errors.append(
                        "tool.mypy.overrides module must be a string or list of strings"
                    )
                    continue
                if _is_forbidden_final_module(entry.rstrip(".*")):
                    errors.append(
                        f"MyPy override still references forbidden module: {entry}"
                    )

    pytest_ini_options = (
        pyproject.get("tool", {}).get("pytest", {}).get("ini_options", {})
    )
    if isinstance(pytest_ini_options, dict):
        if "trio_mode" in pytest_ini_options:
            errors.append(
                "pyproject [tool.pytest.ini_options] must not set trio_mode"
            )
        markers = pytest_ini_options.get("markers", [])
        has_trio_marker = isinstance(markers, list) and any(
            "trio" in str(marker) for marker in markers
        )
        if has_trio_marker:
            errors.append(
                "pyproject [tool.pytest.ini_options] must not declare a "
                "trio marker"
            )
        if "addopts" in pytest_ini_options:
            errors.append(
                "pyproject [tool.pytest.ini_options] must not define a second "
                "addopts source while pytest.ini is authoritative"
            )

    errors.extend(_pytest_ini_checks(root))
    errors.extend(_makefile_final_tooling_checks(root))

    return errors


def _attribute_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _python_final_checks(root: Path) -> list[str]:
    errors: list[str] = []

    for relative_root in ("src", "scripts", "tests"):
        scan_root = root / relative_root
        if not scan_root.is_dir():
            continue

        for path in scan_root.rglob("*.py"):
            relative = path.relative_to(root)

            if relative.parts[:2] == ("src", "psychoanalyst_app"):
                continue

            try:
                tree = ast.parse(
                    path.read_text(encoding="utf-8"),
                    filename=str(relative),
                )
            except SyntaxError as exc:
                errors.append(
                    f"{relative}:{exc.lineno or 0} cannot be parsed: {exc.msg}"
                )
                continue

            pytest_aliases = {
                alias.asname or "pytest"
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
                if alias.name == "pytest"
            }

            nodes = tuple(ast.walk(tree))

            for node in nodes:
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if _is_forbidden_final_module(alias.name):
                            errors.append(
                                f"{relative}:{node.lineno} imports forbidden module: "
                                f"{alias.name}"
                            )

                elif isinstance(node, ast.ImportFrom) and node.module:
                    if _is_forbidden_final_module(node.module):
                        errors.append(
                            f"{relative}:{node.lineno} imports forbidden module: "
                            f"{node.module}"
                        )

                if relative.parts[0] != "tests" or not isinstance(node, ast.Attribute):
                    continue

                name = _attribute_name(node)
                is_trio_mark = name and any(
                    name == f"{alias}.mark.trio" for alias in pytest_aliases
                )
                if is_trio_mark:
                    errors.append(f"{relative}:{node.lineno} still uses {name}")

    return errors


def _final_deletion_checks(root: Path, inventory: Inventory) -> list[str]:
    errors: list[str] = []

    for row in inventory.exceptions:
        if row.status != "complete":
            errors.append(f"inventory exception not complete: {row.path}")

    for item in inventory.filesystem_roots:
        path = root / item.rstrip("/")
        if path.exists() or path.is_symlink():
            errors.append(f"deletion root still present: {item}")

    make_recipes = _all_recipes(root)
    recipe_errors = _require_authoritative_recipes(make_recipes)
    if recipe_errors:
        errors.extend(recipe_errors)
    else:
        errors.extend(_remaining_makefile_checks(root, inventory, make_recipes))

    errors.extend(_workflow_deletion_checks(root, inventory))
    errors.extend(_remaining_workflow_checks(root, inventory))
    errors.extend(_python_final_checks(root))
    errors.extend(_tooling_config_checks(root, inventory))
    errors.extend(_dependency_closure_checks(root))

    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    setuptools_tool = pyproject.get("tool", {}).get("setuptools", {})
    package_data = setuptools_tool.get("package-data", {})
    if isinstance(package_data, dict) and "psychoanalyst_app" in package_data:
        errors.append("pyproject package-data still references psychoanalyst_app")

    if (root / "src/psychoanalyst_app").exists():
        errors.append("src/psychoanalyst_app still exists")

    return errors


# ============================================================
# 5. CLI
# ============================================================

def validate_pre_cutover(root: Path) -> list[str]:
    errors: list[str] = []
    inventory, inventory_errors = _parse_inventory(root)
    errors.extend(inventory_errors)
    errors.extend(_inventory_structure_checks(inventory))
    errors.extend(_require_document_status(inventory, "active"))

    errors.extend(_validate_pre_cutover_gate(root))
    errors.extend(_legacy_runtime_selected(root))

    return errors


def validate_cutover(root: Path) -> list[str]:
    errors: list[str] = []
    inventory, inventory_errors = _parse_inventory(root)
    errors.extend(inventory_errors)
    errors.extend(_inventory_structure_checks(inventory))
    errors.extend(_require_document_status(inventory, "active"))

    errors.extend(_validate_cutover_gate(root))
    errors.extend(_supported_runtime_checks(root))

    return errors


def validate_final(root: Path) -> list[str]:
    errors: list[str] = []
    inventory, inventory_errors = _parse_inventory(root)
    errors.extend(inventory_errors)
    errors.extend(_inventory_structure_checks(inventory))
    errors.extend(_require_document_status(inventory, "completed"))

    errors.extend(_validate_final_gate(root))
    errors.extend(_supported_runtime_checks(root))
    errors.extend(_final_deletion_checks(root, inventory))

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
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--stage", choices=("pre-cutover", "cutover"))
    group.add_argument("--final", action="store_true")
    args = parser.parse_args()
    stage = "final" if args.final else args.stage

    errors = validate(stage=stage)
    if errors:
        print(f"Phase 6 refactor validation failed ({stage}):")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print(f"Phase 6 refactor validation passed ({stage}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
