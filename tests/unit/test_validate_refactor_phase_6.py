import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "validate_refactor_phase_6.py"
_SPEC = importlib.util.spec_from_file_location("validate_refactor_phase_6", _SCRIPT)
assert _SPEC and _SPEC.loader
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules["validate_refactor_phase_6"] = _MOD
_SPEC.loader.exec_module(_MOD)
validate, parse_manifest = _MOD.validate, _MOD.parse_manifest
_parse_shell_command = _MOD._parse_shell_command
_parse_makefile_text = _MOD._parse_makefile_text
_command_invokes_script = _MOD._command_invokes_script
_ScriptRequirement = _MOD.ScriptRequirement

_ITEM = (
    'path = "{path}"\nkind = "{kind}"\naction = "{action}"\nowner_pr = "6C"\n'
    'status = "{status}"\nconfidence = "{confidence}"\nresponsibility = "x"\n'
)
_MANIFEST_TAIL = """
[[items]]
path = "probe-console-v1-deterministic"
kind = "make_target"
action = "retain"
owner_pr = "6A"
status = "complete"
confidence = "confirmed"
responsibility = "Target probe"

[[items]]
path = ".github/workflows/release-candidate-validation.yml"
kind = "workflow_edit"
action = "edit"
owner_pr = "6C"
status = "{wf}"
confidence = "confirmed"
responsibility = "Workflow cutover"
"""
_MAKE = """\
.PHONY: prepare-runtime-dirs lint validate-docs test-target test-validate \\
\tvalidate-schemas validate-generated-contracts validate-architecture \\
\tcharacterization-smoke characterization-full probe-console-deterministic \\
\tprobe-console-intake-notes probe-console-v1-deterministic \\
\tfinalization-check finalization-check-target finalization-check-full
prepare-runtime-dirs:
\t@true
lint:
\t@true
validate-docs:
\t@true
test-target:
\tpytest tests/
test-validate:
\t@true
validate-schemas:
\t@true
validate-generated-contracts:
\t@true
validate-architecture:
\t@true
characterization-smoke:
\t@true
characterization-full:
\t@true
probe-console-deterministic:
\t@true
probe-console-intake-notes:
\t@true
probe-console-v1-deterministic:
\t@true
finalization-check-full:
\t@true
helper-gate:
\t@true
"""
_LEGACY_GATE = (
    "finalization-check:\n"
    "\t$(MAKE) lint\n"
    "\t$(MAKE) validate-docs\n"
    "\t$(MAKE) validate-schemas\n"
    "\t$(MAKE) validate-generated-contracts\n"
    "\t$(MAKE) validate-architecture\n"
    "\t$(MAKE) test-validate\n"
    "\tpython scripts/validate_refactor_phase_5.py\n"
    "\t$(MAKE) characterization-smoke\n"
    "\t$(MAKE) probe-console-deterministic\n"
)
_TARGET_GATE = (
    "finalization-check-target:\n"
    "\t$(MAKE) lint\n"
    "\t$(MAKE) validate-docs\n"
    "\t$(MAKE) test-target\n"
    "\tdocker compose --profile test run --rm \\\n"
    "\t    test python scripts/validate_refactor_phase_6.py --stage pre-cutover\n"
    "\tpython scripts/validate_refactor_phase_5.py\n"
    "\t$(MAKE) probe-console-v1-deterministic\n"
)


def _cutover_gate(stage: str) -> str:
    return (
        "finalization-check:\n"
        "\t$(MAKE) lint\n"
        "\t$(MAKE) validate-docs\n"
        "\t$(MAKE) test-target\n"
        f"\tpython scripts/validate_refactor_phase_6.py --stage {stage}\n"
        "\tpython scripts/validate_refactor_phase_5.py\n"
        "\t$(MAKE) probe-console-v1-deterministic\n"
    )


_DF_LEGACY = (
    "FROM python:3.11-slim AS base\n"
    "FROM base AS development\n"
    'CMD ["python", "-m", "psychoanalyst_app.server"]\n'
)
_DF_TARGET = (
    "FROM python:3.11-slim AS base\n"
    "FROM base AS development\n"
    'CMD ["jung-api"]\n'
)
_CP_LEGACY = (
    "x-api-base: &api-base\n"
    "  build:\n"
    "    context: .\n"
    "    dockerfile: Dockerfile\n"
    "    target: development\n"
    "  command: python -m psychoanalyst_app.server\n"
    "services:\n"
    "  api:\n"
    "    <<: *api-base\n"
)
_CP_TARGET = (
    "x-api-base: &api-base\n"
    "  build:\n"
    "    context: .\n"
    "    dockerfile: Dockerfile\n"
    "    target: development\n"
    "  command: jung-api\n"
    "services:\n"
    "  api:\n"
    "    <<: *api-base\n"
)
_PP_LEGACY = (
    '[project]\nname = "x"\nversion = "0.0.0"\ndependencies = ["fastapi"]\n'
    '[project.scripts]\npsychoanalyst-server = "psychoanalyst_app.server:cli"\n'
)
_PP_TARGET = (
    '[project]\nname = "x"\nversion = "0.0.0"\ndependencies = ["fastapi"]\n'
    "[project.scripts]\n"
    'jung-api = "jung.api.app:cli"\n'
    'jung-console = "jung.client.terminal:cli"\n'
    'jung-db = "jung.tools.db_backup:main"\n'
)
_WF_COEXIST = (
    "name: x\non: {pull_request: null}\njobs:\n"
    "  finalization-check:\n    steps:\n"
    "      - run: make finalization-check\n"
    "  target-finalization-check:\n    steps:\n"
    "      - run: make finalization-check-target\n"
)
_WF_CUTOVER = (
    "name: x\non: {pull_request: null}\njobs:\n"
    "  finalization-check:\n"
    "    name: Docker Finalization Check\n"
    "    steps:\n"
    "      - name: Checkout\n"
    "        uses: actions/checkout@v4\n"
    "      - name: Run Docker release-candidate gate\n"
    "        run: make finalization-check\n"
)


@dataclass
class RepoFixture:
    root: Path

    def write_manifest(self, *, status="active", items: str) -> None:
        p = self.root / "docs/refactor"
        p.mkdir(parents=True, exist_ok=True)
        (p / "deletion-manifest.toml").write_text(
            f'schema_version = 1\nstatus = "{status}"\n\n{items}', encoding="utf-8"
        )

    def write_runtime(
        self, *, target: bool, dockerfile=None, compose=None, pyproject=None, gates=None
    ) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "Makefile").write_text(
            _MAKE + (gates or (_cutover_gate("cutover") if target else _LEGACY_GATE + _TARGET_GATE)),
            encoding="utf-8",
        )
        (self.root / "Dockerfile").write_text(
            dockerfile or (_DF_TARGET if target else _DF_LEGACY), encoding="utf-8"
        )
        (self.root / "docker-compose.yml").write_text(
            compose or (_CP_TARGET if target else _CP_LEGACY), encoding="utf-8"
        )
        (self.root / "pyproject.toml").write_text(
            pyproject or (_PP_TARGET if target else _PP_LEGACY), encoding="utf-8"
        )
        (self.root / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
        (self.root / "scripts").mkdir(exist_ok=True)
        (self.root / "scripts/validate_refactor_phase_5.py").write_text("#\n", encoding="utf-8")
        (self.root / "scripts/validate_refactor_phase_6.py").write_text("#\n", encoding="utf-8")
        (self.root / "tests").mkdir(exist_ok=True)

    def mutate_gate(self, target: str, old: str, new: str) -> None:
        path = self.root / "Makefile"
        path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")

    def write_workflow(self, text: str) -> None:
        d = self.root / ".github/workflows"
        d.mkdir(parents=True, exist_ok=True)
        (d / "release-candidate-validation.yml").write_text(text, encoding="utf-8")

    def write_pyproject(self, text: str) -> None:
        (self.root / "pyproject.toml").write_text(text, encoding="utf-8")

    def seed_pre(self) -> None:
        self.write_manifest(items=_MANIFEST_TAIL.format(wf="in_progress"))
        self.write_runtime(target=False)
        self.write_workflow(_WF_COEXIST)

    def seed_cutover(self, *, complete=False) -> None:
        self.write_manifest(items=_MANIFEST_TAIL.format(wf="complete" if complete else "in_progress"))
        self.write_runtime(target=True)
        self.write_workflow(_WF_CUTOVER if complete else _WF_COEXIST)

    def seed_final(self) -> None:
        self.write_manifest(
            status="completed",
            items=(
                '[[items]]\npath = "gone/"\nkind = "filesystem"\naction = "delete"\n'
                "aggregate = true\nowner_pr = \"6D\"\nstatus = \"complete\"\n"
                'confidence = "confirmed"\nresponsibility = "x"\n\n'
                "[[items]]\npath = \".github/workflows/release-candidate-validation.yml\"\n"
                'kind = "workflow_edit"\naction = "edit"\nowner_pr = "6C"\n'
                'status = "complete"\nconfidence = "confirmed"\nresponsibility = "x"\n'
            ),
        )
        self.write_runtime(target=True, gates=_cutover_gate("final"))
        self.write_workflow(_WF_CUTOVER)
        (self.root / "src").mkdir(exist_ok=True)


@pytest.mark.parametrize(
    "stage,seed",
    [
        ("pre-cutover", "pre"),
        ("cutover", "cutover"),
        ("final", "final"),
    ],
)
def test_valid_stage_passes(tmp_path, stage, seed):
    r = RepoFixture(tmp_path)
    {"pre": r.seed_pre, "cutover": lambda: r.seed_cutover(complete=True), "final": r.seed_final}[seed]()
    assert validate(tmp_path, stage=stage) == []


@pytest.mark.parametrize(
    "stage,status",
    [("pre-cutover", "completed"), ("cutover", "completed"), ("final", "active")],
)
def test_manifest_status_rejected_for_stage(tmp_path, stage, status):
    r = RepoFixture(tmp_path)
    r.seed_pre()
    r.write_manifest(status=status, items=_MANIFEST_TAIL.format(wf="in_progress"))
    assert any("manifest status" in e for e in validate(tmp_path, stage=stage))


@pytest.mark.parametrize(
    "stage,wrong_stage",
    [
        ("cutover", "pre-cutover"),
        ("final", "cutover"),
    ],
)
def test_wrong_phase6_stage_rejected(tmp_path, stage, wrong_stage):
    r = RepoFixture(tmp_path)
    r.seed_cutover(complete=True) if stage == "cutover" else r.seed_final()
    r.mutate_gate(
        "finalization-check",
        f"--stage {stage if stage == 'cutover' else 'final'}",
        f"--stage {wrong_stage}",
    )
    assert any("must invoke scripts/validate_refactor_phase_6.py" in e for e in validate(tmp_path, stage=stage))


@pytest.mark.parametrize(
    "recipe",
    [
        "echo python scripts/validate_refactor_phase_6.py --stage cutover",
        "! python scripts/validate_refactor_phase_6.py --stage cutover",
        "$(MAKE) test-target || true",
        "-python scripts/validate_refactor_phase_6.py --stage cutover",
    ],
)
def test_suppressed_gate_commands_fail_e2e(tmp_path, recipe):
    r = RepoFixture(tmp_path)
    r.seed_cutover(complete=True)
    makefile = (tmp_path / "Makefile").read_text(encoding="utf-8")
    makefile = makefile.replace(
        "\tpython scripts/validate_refactor_phase_6.py --stage cutover\n",
        f"\t{recipe}\n",
    )
    (tmp_path / "Makefile").write_text(makefile, encoding="utf-8")
    assert validate(tmp_path, stage="cutover")


@pytest.mark.parametrize(
    "header,body,remove_recipe,frag",
    [
        ("finalization-check: characterization-smoke", "", "", "must not depend on characterization-smoke"),
        ("finalization-check: finalization-check-full", "", "", "must not depend on finalization-check-full"),
        (
            "finalization-check: helper-gate",
            "helper-gate: characterization-smoke",
            "",
            "must not depend on characterization-smoke",
        ),
        ("finalization-check: $(LEGACY_RELEASE_TARGETS)", "", "", "unsupported prerequisite"),
        ("finalization-check: test-target", "", "\t$(MAKE) test-target\n", "must invoke test-target"),
    ],
)
def test_gate_prerequisite_rules(tmp_path, header, body, remove_recipe, frag):
    r = RepoFixture(tmp_path)
    r.seed_cutover(complete=True)
    makefile = (tmp_path / "Makefile").read_text(encoding="utf-8")
    makefile = makefile.replace(
        "finalization-check:\n",
        f"{header}\n{body}\n" if body else f"{header}\n",
    )
    if remove_recipe:
        makefile = makefile.replace(remove_recipe, "")
    (tmp_path / "Makefile").write_text(makefile, encoding="utf-8")
    assert any(frag in e for e in validate(tmp_path, stage="cutover"))


def test_cutover_rejects_in_progress_workflow_edit(tmp_path):
    RepoFixture(tmp_path).seed_cutover(complete=False)
    assert any("required item must be complete" in e for e in validate(tmp_path, stage="cutover"))


def test_cutover_rejects_workflow_with_phase1_job(tmp_path):
    r = RepoFixture(tmp_path)
    r.seed_cutover(complete=True)
    r.write_workflow(_WF_CUTOVER + "\n  phase-1-evidence:\n    steps:\n      - run: make x\n")
    assert any("phase-1-evidence" in e for e in validate(tmp_path, stage="cutover"))


def _manifest_item(**kwargs) -> str:
    defaults = {"status": "complete", "confidence": "confirmed"}
    defaults.update(kwargs)
    return "[[items]]\n" + _ITEM.format(**defaults)


@pytest.mark.parametrize(
    "extra,setup,frag",
    [
        ({"path": "legacy.txt", "kind": "filesystem", "action": "delete"}, "touch", "still present"),
        ({"path": "legacy.py", "kind": "filesystem", "action": "port_then_delete"}, "replacements", "missing path"),
        ({"path": "missing-target", "kind": "make_target", "action": "retain"}, None, "retained path missing"),
    ],
)
def test_manifest_item_failures(tmp_path, extra, setup, frag):
    r = RepoFixture(tmp_path)
    r.seed_pre()
    item = _manifest_item(**extra)
    if setup == "touch":
        (tmp_path / extra["path"]).write_text("x", encoding="utf-8")
    elif setup == "replacements":
        item += 'replacements = ["missing/replacement.py"]\n'
    r.write_manifest(items=_MANIFEST_TAIL.format(wf="in_progress") + item)
    assert any(frag in e for e in validate(tmp_path, stage="pre-cutover"))


@pytest.mark.parametrize(
    "dep_source,content",
    [
        ("pyproject", _PP_TARGET.replace('dependencies = ["fastapi"]', 'dependencies = ["fastapi", "trio"]')),
        ("requirements", None),
    ],
)
def test_forbidden_dependency_fails(tmp_path, dep_source, content):
    r = RepoFixture(tmp_path)
    r.seed_final()
    if dep_source == "pyproject":
        r.write_pyproject(content)
    else:
        (tmp_path / "requirements.txt").write_text("quart\n", encoding="utf-8")
    assert any("forbidden dependency" in e for e in validate(tmp_path, stage="final"))


def test_forbidden_import_fails(tmp_path):
    RepoFixture(tmp_path).seed_final()
    p = tmp_path / "src/legacy.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("import psychoanalyst_app\n", encoding="utf-8")
    assert any("imports forbidden module" in e for e in validate(tmp_path, stage="final"))


@pytest.mark.parametrize(
    "stage,compose,dockerfile,ok,err",
    [
        (
            "pre-cutover",
            "services:\n  console:\n    depends_on:\n      api:\n        condition: service_healthy\n"
            "  api:\n    build:\n      context: .\n      dockerfile: Dockerfile\n      target: development\n"
            "    command: python -m psychoanalyst_app.server\n",
            _DF_LEGACY,
            True,
            "",
        ),
        (
            "cutover",
            "x-api-base: &api-base\n  build:\n    context: .\n    dockerfile: Dockerfile\n"
            "    target: development\n  command: jung-api\nservices:\n  api:\n    <<: *api-base\n"
            "    command: python -m psychoanalyst_app.server\n",
            _DF_TARGET,
            False,
            "docker-compose api command must select",
        ),
        (
            "cutover",
            "services:\n  api:\n    build:\n      context: .\n      dockerfile: Dockerfile\n"
            '      target: development\n    command: ["python", "-m", "psychoanalyst_app.server"]\n',
            _DF_TARGET,
            False,
            "docker-compose api command must select",
        ),
        (
            "cutover",
            "services:\n  api:\n    build:\n      context: .\n      dockerfile: Dockerfile\n"
            "      target: development\n    command:\n      - python\n      - -m\n"
            "      - psychoanalyst_app.server\n",
            _DF_TARGET,
            False,
            "docker-compose api command must select",
        ),
        (
            "cutover",
            "services:\n  api:\n    build:\n      context: .\n      dockerfile: Dockerfile\n"
            "      target: development\n    command: [not-a-valid-list\n",
            _DF_TARGET,
            False,
            "command inline list is malformed",
        ),
        (
            "cutover",
            "services:\n  api:\n    command: jung-api\n    build:\n"
            "      context: .\n      dockerfile: Dockerfile\n      target: development\n"
            "    build:\n      context: .\n      dockerfile: Dockerfile\n      target: development\n",
            _DF_TARGET,
            False,
            "multiple build blocks",
        ),
    ],
    ids=["depends_on", "local_override", "inline_list", "block_list", "malformed", "duplicate_build"],
)
def test_compose_runtime_overrides(tmp_path, stage, compose, dockerfile, ok, err):
    r = RepoFixture(tmp_path)
    (r.seed_cutover(complete=True) if stage == "cutover" else r.seed_pre())
    r.write_runtime(target=stage != "pre-cutover", dockerfile=dockerfile, compose=compose)
    errors = validate(tmp_path, stage=stage)
    assert (errors == []) if ok else any(err in e for e in errors)


def test_non_final_selected_stage_fails_when_only_final_correct(tmp_path):
    r = RepoFixture(tmp_path)
    r.seed_pre()
    r.write_runtime(
        target=False,
        dockerfile=(
            "FROM python:3.11-slim AS base\n"
            "FROM base AS development\n"
            'CMD ["jung-api"]\n'
            "FROM base AS runtime\n"
            'CMD ["python", "-m", "psychoanalyst_app.server"]\n'
        ),
        compose=(
            "services:\n  api:\n    build:\n      context: .\n"
            "      dockerfile: Dockerfile\n      target: development\n"
            "    command: python -m psychoanalyst_app.server\n"
        ),
    )
    assert any("CMD must select" in e for e in validate(tmp_path, stage="pre-cutover"))


def test_unknown_explicit_build_target_fails(tmp_path):
    r = RepoFixture(tmp_path)
    r.seed_pre()
    r.write_runtime(
        target=False,
        compose=(
            "services:\n  api:\n    build:\n      context: .\n"
            "      dockerfile: Dockerfile\n      target: missing-stage\n"
            "    command: python -m psychoanalyst_app.server\n"
        ),
    )
    assert any("does not match any Dockerfile stage" in e for e in validate(tmp_path, stage="pre-cutover"))


def test_missing_target_gate_step_fails(tmp_path):
    r = RepoFixture(tmp_path)
    r.seed_pre()
    r.mutate_gate("finalization-check-target", "\t$(MAKE) test-target\n", "")
    assert any("finalization-check-target must invoke test-target" in e for e in validate(tmp_path, stage="pre-cutover"))


def test_make_recipe_continuation_joins_python_gate():
    recipes = _parse_makefile_text(_TARGET_GATE)
    req = _ScriptRequirement(
        "scripts/validate_refactor_phase_6.py", ("--stage", "pre-cutover")
    )
    commands = recipes["finalization-check-target"].recipes
    assert any(
        _command_invokes_script(_parse_shell_command(cmd.text), req) for cmd in commands
    )


@pytest.mark.parametrize(
    "body,frag",
    [
        ('schema_version = true\nstatus = "active"\n\n[[items]]\n' + _ITEM.format(path="x", kind="filesystem", action="delete", status="planned", confidence="confirmed"), "schema_version"),
        ('schema_version = 1\nstatus = "active"\nextra = true\n\n[[items]]\n' + _ITEM.format(path="x", kind="filesystem", action="delete", status="planned", confidence="confirmed"), "extra"),
        ('schema_version = 1\nstatus = "active"\n\n[[items]]\n' + _ITEM.format(path="x", kind="filesystem", action="edit", status="planned", confidence="confirmed"), "action"),
        ('schema_version = 1\nstatus = "active"\n\n[[items]]\n' + _ITEM.format(path="x", kind="filesystem", action="retain", status="planned", confidence="confirmed") + "requires_explicit_test_target_reference = false\n", "requires_explicit_test_target_reference"),
    ],
    ids=["schema_true", "unknown_top", "filesystem_edit", "requires_false"],
)
def test_malformed_manifest_inputs_fail(tmp_path, body, frag):
    p = tmp_path / "docs/refactor"
    p.mkdir(parents=True)
    (p / "deletion-manifest.toml").write_text(body, encoding="utf-8")
    manifest, errors = parse_manifest(tmp_path)
    assert manifest is None and errors


def test_absolute_manifest_path_fails(tmp_path):
    RepoFixture(tmp_path).write_manifest(
        items="[[items]]\n"
        + _ITEM.format(
            path="/etc/passwd",
            kind="filesystem",
            action="delete",
            status="planned",
            confidence="confirmed",
        )
    )
    manifest, errors = parse_manifest(tmp_path)
    assert manifest is None and any("repository-relative" in e for e in errors)


def test_workflow_path_traversal_fails(tmp_path):
    RepoFixture(tmp_path).write_manifest(
        items="[[items]]\n"
        + _ITEM.format(
            path=".github/workflows/../../Makefile",
            kind="workflow",
            action="delete",
            status="planned",
            confidence="confirmed",
        )
    )
    manifest, errors = parse_manifest(tmp_path)
    assert manifest is None and any("must not contain .." in e for e in errors)


def test_workflow_path_duplicate_slash_variants_fail(tmp_path):
    item = "[[items]]\n" + _ITEM.format(
        path=".github/workflows/legacy.yml",
        kind="workflow",
        action="delete",
        status="planned",
        confidence="confirmed",
    )
    dup = (
        "[[items]]\npath = '.github\\workflows\\legacy.yml'\n"
        'kind = "workflow"\naction = "delete"\nowner_pr = "6C"\n'
        'status = "planned"\nconfidence = "confirmed"\nresponsibility = "x"\n'
    )
    RepoFixture(tmp_path).write_manifest(items=item + dup)
    manifest, errors = parse_manifest(tmp_path)
    assert manifest is None and any("duplicate kind/path" in e for e in errors)


def test_planned_discovery_needed_port_without_replacement_passes(tmp_path):
    RepoFixture(tmp_path).write_manifest(
        items="[[items]]\n"
        + _ITEM.format(
            path="tests/unit/test_planning_analysis.py",
            kind="filesystem",
            action="port_then_delete",
            status="planned",
            confidence="discovery-needed",
        )
    )
    manifest, errors = parse_manifest(tmp_path)
    assert manifest is not None and errors == []


@pytest.mark.parametrize(
    "status,confidence",
    [("planned", "confirmed"), ("complete", "confirmed"), ("in_progress", "confirmed")],
)
def test_port_without_replacement_fails_unless_discovery_needed(tmp_path, status, confidence):
    RepoFixture(tmp_path).write_manifest(
        items="[[items]]\n"
        + _ITEM.format(
            path="tests/unit/test_planning_analysis.py",
            kind="filesystem",
            action="port_then_delete",
            status=status,
            confidence=confidence,
        )
    )
    manifest, errors = parse_manifest(tmp_path)
    assert manifest is None and any("requires replacements" in e for e in errors)


@pytest.mark.parametrize(
    "workflow,frag",
    [
        ("jobs:\n  finalization-check:\n    steps:\n      - run: echo finalization-check\n", "exactly one job invoking"),
        ("jobs:\n  finalization-check:\n    steps:\n      - run: make finalization-check || true\n", "exactly one job invoking"),
        (
            "jobs:\n  finalization-check:\n    steps:\n      - run: make finalization-check\n"
            "  legacy:\n    steps:\n      - run: |\n          cd /workspace\n"
            "          make characterization-full\n",
            "legacy target characterization-full",
        ),
        (
            "jobs:\n  finalization-check:\n    steps:\n      - run: |\n          make \\\n"
            "            characterization-full\n",
            "unsupported shell continuation",
        ),
        (
            "jobs:\n  finalization-check:\n    steps:\n      - run: >\n          make \\\n"
            "          finalization-check\n",
            "unsupported shell continuation",
        ),
        ("jobs:\n  finalization-check:\n    steps:\n      - run: make finalization-check-target\n", "finalization-check-target"),
        ("jobs:\n  finalization-check:\n    steps:\n      - run: make finalization-check\n        continue-on-error: true\n", "continue-on-error"),
        ("jobs:\n  finalization-check:\n    steps:\n      - run: echo make characterization-full\n", "exactly one job invoking"),
        ("jobs:\n  finalization-check:\n    steps:\n      - run: echo preparing && make characterization-full\n", "legacy target characterization-full"),
        (
            "jobs:\n  finalization-check:\n    steps:\n      - run: make finalization-check\n"
            "  finalization-check:\n    steps:\n      - run: echo gate disabled\n",
            "duplicate job names",
        ),
        (
            "jobs:\n  finalization-check:\n    steps:\n      - run: make finalization-check\n"
            "        run: echo gate disabled\n",
            "multiple run values",
        ),
        (
            "jobs:\n  finalization-check:\n    steps:\n      - name: Step\n        env:\n          ITEMS: |\n            - one\n            - two\n"
            "      - run: make finalization-check\n",
            "__pass__",
        ),
        (
            "jobs:\n  legacy:\n    steps:\n      - run: make characterization-full\n"
            "        continue-on-error: true\n"
            "  finalization-check:\n    steps:\n      - run: make finalization-check\n"
            "        continue-on-error: false\n",
            "legacy target characterization-full",
        ),
    ],
    ids=[
        "echo",
        "suppressed",
        "literal_legacy",
        "literal_continuation",
        "folded_continuation",
        "target_gate",
        "continue_on_error_true",
        "echo_not_legacy",
        "segment_legacy",
        "duplicate_job",
        "duplicate_run",
        "nested_env",
        "continue_on_error_false_positive",
    ],
)
def test_workflow_completion_rules(tmp_path, workflow, frag):
    r = RepoFixture(tmp_path)
    r.seed_cutover(complete=True)
    r.write_workflow("name: x\non: {pull_request: null}\n" + workflow)
    errors = validate(tmp_path, stage="cutover")
    if frag == "__pass__":
        assert not any("exactly one job invoking" in e for e in errors)
    else:
        assert any(frag in e for e in errors)


def test_renamed_legacy_entry_point_fails(tmp_path):
    r = RepoFixture(tmp_path)
    r.seed_cutover(complete=True)
    r.write_pyproject(_PP_TARGET + 'old-debug-server = "psychoanalyst_app.server:cli"\n')
    assert any("legacy entry point value" in e for e in validate(tmp_path, stage="cutover"))


def test_wrong_target_entry_point_value_fails(tmp_path):
    r = RepoFixture(tmp_path)
    r.seed_cutover(complete=True)
    r.write_pyproject(
        _PP_TARGET.replace(
            'jung-api = "jung.api.app:cli"', 'jung-api = "some_other_package.app:main"'
        )
    )
    assert any("entry point 'jung-api' must be" in e for e in validate(tmp_path, stage="cutover"))


@pytest.mark.parametrize(
    "dockerfile,compose,frag",
    [
        (
            "FROM python:3.11-slim AS base\nFROM base AS development\nCMD [\"echo\", \"jung-api\"]\n",
            None,
            "CMD must select",
        ),
        (
            "FROM python:3.11-slim AS base\nFROM base AS development\nCMD [\"jung-api\",\n",
            None,
            "CMD is invalid",
        ),
        (
            None,
            "services:\n  api:\n    build:\n      context: .\n"
            "      dockerfile: Dockerfile\n      target: development\n"
            "    command: echo jung.api.app:cli\n",
            "docker-compose api command must select",
        ),
        (
            None,
            "x-api-base: &api-base\n  command: jung-api\nservices:\n  api:\n    <<: [*api-base]\n"
            "    build:\n      context: .\n      dockerfile: Dockerfile\n      target: development\n",
            "unsupported merge",
        ),
        (
            None,
            "services:\n  api:\n    command: jung-api\n    build:\n"
            "      context: .\n      dockerfile: Dockerfile\n      target: development\n"
            "  api:\n    command: jung-api\n    build:\n"
            "      context: .\n      dockerfile: Dockerfile\n      target: development\n",
            "multiple services.api blocks",
        ),
        (
            None,
            "services:\n  api:\n    build: .\n    command: jung-api\n",
            "scalar build syntax is unsupported",
        ),
    ],
    ids=["docker_echo", "docker_malformed", "compose_echo", "merge_list", "duplicate_api", "scalar_build"],
)
def test_invalid_runtime_shapes(tmp_path, dockerfile, compose, frag):
    r = RepoFixture(tmp_path)
    r.seed_cutover(complete=True)
    r.write_runtime(
        target=True,
        dockerfile=dockerfile or _DF_TARGET,
        compose=compose or _CP_TARGET,
    )
    assert any(frag in e for e in validate(tmp_path, stage="cutover"))


_RETAINED_TEST = "tests/unit/test_validate_refactor_phase_6.py"


def _retained_test_manifest() -> str:
    return (
        _MANIFEST_TAIL.format(wf="complete")
        + "[[items]]\n"
        + _ITEM.format(
            path=_RETAINED_TEST,
            kind="filesystem",
            action="retain",
            status="complete",
            confidence="confirmed",
        )
        + "requires_explicit_test_target_reference = true\n"
    )


@pytest.mark.parametrize(
    "makefile_patch,should_pass",
    [
        (
            "TARGET_SUPPORT_TESTS := tests/unit/test_validate_refactor_phase_6.py\n"
            "test-target:\n\tpytest tests/unit/jung/\n",
            False,
        ),
        (
            "test-target:\n\techo pytest tests/unit/test_validate_refactor_phase_6.py\n",
            False,
        ),
        (
            "test-target:\n\tpytest tests/unit/test_validate_refactor_phase_6.py\n",
            True,
        ),
        (
            "test-target:\n\tdocker compose --profile test run --rm test pytest "
            "tests/unit/test_validate_refactor_phase_6.py\n",
            True,
        ),
        (
            "TARGET_SUPPORT_TESTS := tests/unit/test_validate_refactor_phase_6.py\n"
            "test-target:\n\tdocker compose --profile test run --rm test pytest "
            "$(TARGET_SUPPORT_TESTS)\n",
            True,
        ),
    ],
    ids=["unused_var", "echo_pytest", "direct_pytest", "docker_pytest", "var_expansion"],
)
def test_retained_test_reference_rules(tmp_path, makefile_patch, should_pass):
    r = RepoFixture(tmp_path)
    r.write_manifest(items=_retained_test_manifest())
    r.write_runtime(target=True)
    r.write_workflow(_WF_CUTOVER)
    base = (tmp_path / "Makefile").read_text(encoding="utf-8")
    base = re.sub(
        r"test-target:\n\tpytest tests/\n",
        makefile_patch,
        base,
    )
    (tmp_path / "Makefile").write_text(base, encoding="utf-8")
    (tmp_path / _RETAINED_TEST).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / _RETAINED_TEST).write_text("#\n", encoding="utf-8")
    errors = validate(tmp_path, stage="cutover")
    if should_pass:
        assert not any("retained test not referenced" in e for e in errors)
    else:
        assert any("retained test not referenced" in e for e in errors)
