import importlib.util
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
_invoked_make_targets, _invoked_scripts = _MOD._invoked_make_targets, _MOD._invoked_scripts
_RC = _MOD.RecipeCommand

_ITEM = """path = "{path}"\nkind = "{kind}"\naction = "{action}"\nowner_pr = "6C"\nstatus = "{status}"\nconfidence = "{confidence}"\nresponsibility = "x"\n"""
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
\tfinalization-check finalization-check-target
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
"""
_LEGACY_GATE = "finalization-check:\n\t$(MAKE) lint\n\t$(MAKE) validate-docs\n\t$(MAKE) validate-schemas\n\t$(MAKE) validate-generated-contracts\n\t$(MAKE) validate-architecture\n\t$(MAKE) test-validate\n\tpython scripts/validate_refactor_phase_5.py\n\t$(MAKE) characterization-smoke\n\t$(MAKE) probe-console-deterministic\n"
_TARGET_GATE = "finalization-check-target:\n\t$(MAKE) lint\n\t$(MAKE) validate-docs\n\t$(MAKE) test-target\n\tpython scripts/validate_refactor_phase_6.py\n\tpython scripts/validate_refactor_phase_5.py\n\t$(MAKE) probe-console-v1-deterministic\n"
_CUTOVER_GATE = "finalization-check:\n\t$(MAKE) lint\n\t$(MAKE) validate-docs\n\t$(MAKE) test-target\n\tpython scripts/validate_refactor_phase_6.py\n\tpython scripts/validate_refactor_phase_5.py\n\t$(MAKE) probe-console-v1-deterministic\n"
_DF_LEGACY = "FROM python:3.11-slim AS base\nFROM base AS development\nCMD [\"python\", \"-m\", \"psychoanalyst_app.server\"]\n"
_DF_TARGET = "FROM python:3.11-slim AS base\nFROM base AS development\nCMD [\"jung-api\"]\n"
_CP_LEGACY = "x-api-base: &api-base\n  build:\n    context: .\n    dockerfile: Dockerfile\n    target: development\n  command: python -m psychoanalyst_app.server\nservices:\n  api:\n    <<: *api-base\n"
_CP_TARGET = "x-api-base: &api-base\n  build:\n    context: .\n    dockerfile: Dockerfile\n    target: development\n  command: jung-api\nservices:\n  api:\n    <<: *api-base\n"
_PP_LEGACY = '[project]\nname = "x"\nversion = "0.0.0"\ndependencies = ["fastapi"]\n[project.scripts]\npsychoanalyst-server = "psychoanalyst_app.server:cli"\n'
_PP_TARGET = '[project]\nname = "x"\nversion = "0.0.0"\ndependencies = ["fastapi"]\n[project.scripts]\njung-api = "jung.api.app:cli"\njung-console = "jung.client.terminal:cli"\njung-db = "jung.tools.db_backup:main"\n'
_WF_COEXIST = "name: x\non: {pull_request: null}\njobs:\n  finalization-check:\n    steps:\n      - run: make finalization-check\n  target-finalization-check:\n    steps:\n      - run: make finalization-check-target\n"
_WF_CUTOVER = "name: x\non: {pull_request: null}\njobs:\n  finalization-check:\n    steps:\n      - run: make finalization-check\n"


@dataclass
class RepoFixture:
    root: Path

    def write_manifest(self, *, status="active", items: str) -> None:
        p = self.root / "docs/refactor"
        p.mkdir(parents=True, exist_ok=True)
        (p / "deletion-manifest.toml").write_text(
            f'schema_version = 1\nstatus = "{status}"\n\n{items}', encoding="utf-8"
        )

    def write_runtime(self, *, target: bool, dockerfile=None, compose=None, pyproject=None, gates=None) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "Makefile").write_text(
            _MAKE + (gates or (_CUTOVER_GATE if target else _LEGACY_GATE + _TARGET_GATE)),
            encoding="utf-8",
        )
        (self.root / "Dockerfile").write_text(dockerfile or (_DF_TARGET if target else _DF_LEGACY), encoding="utf-8")
        (self.root / "docker-compose.yml").write_text(compose or (_CP_TARGET if target else _CP_LEGACY), encoding="utf-8")
        (self.root / "pyproject.toml").write_text(pyproject or (_PP_TARGET if target else _PP_LEGACY), encoding="utf-8")
        (self.root / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
        (self.root / "scripts").mkdir(exist_ok=True)
        (self.root / "scripts/validate_refactor_phase_5.py").write_text("#\n", encoding="utf-8")
        (self.root / "scripts/validate_refactor_phase_6.py").write_text("#\n", encoding="utf-8")
        (self.root / "tests").mkdir(exist_ok=True)

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
            items='[[items]]\npath = "gone/"\nkind = "filesystem"\naction = "delete"\naggregate = true\nowner_pr = "6D"\nstatus = "complete"\nconfidence = "confirmed"\nresponsibility = "x"\n\n[[items]]\npath = ".github/workflows/release-candidate-validation.yml"\nkind = "workflow_edit"\naction = "edit"\nowner_pr = "6C"\nstatus = "complete"\nconfidence = "confirmed"\nresponsibility = "x"\n',
        )
        self.write_runtime(target=True)
        self.write_workflow(_WF_CUTOVER)
        (self.root / "src").mkdir(exist_ok=True)


def test_valid_pre_cutover_passes(tmp_path):
    RepoFixture(tmp_path).seed_pre()
    assert validate(tmp_path, stage="pre-cutover") == []


def test_valid_cutover_passes_when_workflow_complete(tmp_path):
    RepoFixture(tmp_path).seed_cutover(complete=True)
    assert validate(tmp_path, stage="cutover") == []


def test_valid_final_passes(tmp_path):
    RepoFixture(tmp_path).seed_final()
    assert validate(tmp_path, stage="final") == []


@pytest.mark.parametrize("stage,status", [("pre-cutover", "completed"), ("cutover", "completed"), ("final", "active")])
def test_manifest_status_rejected_for_stage(tmp_path, stage, status):
    r = RepoFixture(tmp_path)
    r.seed_pre()
    r.write_manifest(status=status, items=_MANIFEST_TAIL.format(wf="in_progress"))
    assert any("manifest status" in e for e in validate(tmp_path, stage=stage))


def test_cutover_rejects_in_progress_workflow_edit(tmp_path):
    RepoFixture(tmp_path).seed_cutover(complete=False)
    assert any("required item must be complete" in e for e in validate(tmp_path, stage="cutover"))


def test_cutover_rejects_workflow_with_phase1_job(tmp_path):
    r = RepoFixture(tmp_path)
    r.seed_cutover(complete=True)
    r.write_workflow(_WF_CUTOVER + "\n  phase-1-evidence:\n    steps:\n      - run: make x\n")
    assert any("phase-1-evidence" in e for e in validate(tmp_path, stage="cutover"))


def test_completed_deletion_still_present_fails(tmp_path):
    r = RepoFixture(tmp_path)
    r.seed_pre()
    r.write_manifest(items=_MANIFEST_TAIL.format(wf="in_progress") + "[[items]]\n" + _ITEM.format(path="legacy.txt", kind="filesystem", action="delete", status="complete", confidence="confirmed"))
    (tmp_path / "legacy.txt").write_text("x", encoding="utf-8")
    assert any("still present" in e for e in validate(tmp_path, stage="pre-cutover"))


def test_missing_concrete_replacement_fails(tmp_path):
    r = RepoFixture(tmp_path)
    r.seed_pre()
    r.write_manifest(items=_MANIFEST_TAIL.format(wf="in_progress") + "[[items]]\n" + _ITEM.format(path="legacy.py", kind="filesystem", action="port_then_delete", status="complete", confidence="confirmed") + 'replacements = ["missing/replacement.py"]\n')
    assert any("missing path" in e for e in validate(tmp_path, stage="pre-cutover"))


def test_retained_make_target_absent_fails(tmp_path):
    r = RepoFixture(tmp_path)
    r.seed_pre()
    r.write_manifest(items=_MANIFEST_TAIL.format(wf="in_progress") + "[[items]]\n" + _ITEM.format(path="missing-target", kind="make_target", action="retain", status="complete", confidence="confirmed"))
    assert any("retained path missing" in e for e in validate(tmp_path, stage="pre-cutover"))


def test_forbidden_dependency_in_pyproject_fails(tmp_path):
    r = RepoFixture(tmp_path)
    r.seed_final()
    r.write_pyproject(_PP_TARGET.replace('dependencies = ["fastapi"]', 'dependencies = ["fastapi", "trio"]'))
    assert any("forbidden dependency" in e for e in validate(tmp_path, stage="final"))


def test_forbidden_dependency_in_requirements_fails(tmp_path):
    RepoFixture(tmp_path).seed_final()
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
        ("pre-cutover", "services:\n  console:\n    depends_on:\n      api:\n        condition: service_healthy\n  api:\n    build:\n      context: .\n      dockerfile: Dockerfile\n      target: development\n    command: python -m psychoanalyst_app.server\n", _DF_LEGACY, True, ""),
        ("cutover", "x-api-base: &api-base\n  build:\n    context: .\n    dockerfile: Dockerfile\n    target: development\n  command: jung-api\nservices:\n  api:\n    <<: *api-base\n    command: python -m psychoanalyst_app.server\n", _DF_TARGET, False, "docker-compose api command must select"),
        ("cutover", "services:\n  api:\n    build:\n      context: .\n      dockerfile: Dockerfile\n      target: development\n    command: [\"python\", \"-m\", \"psychoanalyst_app.server\"]\n", _DF_TARGET, False, "docker-compose api command must select"),
        ("cutover", "services:\n  api:\n    build:\n      context: .\n      dockerfile: Dockerfile\n      target: development\n    command:\n      - python\n      - -m\n      - psychoanalyst_app.server\n", _DF_TARGET, False, "docker-compose api command must select"),
        ("cutover", "services:\n  api:\n    build:\n      context: .\n      dockerfile: Dockerfile\n      target: development\n    command: [not-a-valid-list\n", _DF_TARGET, False, "command inline list is malformed"),
    ],
    ids=["depends_on", "local_override", "inline_list", "block_list", "malformed"],
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
    r.write_runtime(target=False, dockerfile="FROM python:3.11-slim AS base\nFROM base AS development\nCMD [\"jung-api\"]\nFROM base AS runtime\nCMD [\"python\", \"-m\", \"psychoanalyst_app.server\"]\n", compose="services:\n  api:\n    build:\n      context: .\n      dockerfile: Dockerfile\n      target: development\n    command: python -m psychoanalyst_app.server\n")
    assert any("CMD must select" in e for e in validate(tmp_path, stage="pre-cutover"))


def test_unknown_explicit_build_target_fails(tmp_path):
    r = RepoFixture(tmp_path)
    r.seed_pre()
    r.write_runtime(target=False, compose="services:\n  api:\n    build:\n      context: .\n      dockerfile: Dockerfile\n      target: missing-stage\n    command: python -m psychoanalyst_app.server\n")
    assert any("does not match any Dockerfile stage" in e for e in validate(tmp_path, stage="pre-cutover"))


def test_missing_target_gate_step_fails(tmp_path):
    r = RepoFixture(tmp_path)
    r.seed_pre()
    (tmp_path / "Makefile").write_text((tmp_path / "Makefile").read_text(encoding="utf-8").replace("$(MAKE) test-target\n", ""), encoding="utf-8")
    assert any("finalization-check-target must invoke test-target" in e for e in validate(tmp_path, stage="pre-cutover"))


@pytest.mark.parametrize("recipe,target,expected", [("@echo probe-console-deterministic", "probe-console-deterministic", False), ("@echo test-target", "test-target", False), ("-$(MAKE) test-target", "test-target", False), ("$(MAKE) probe-console-v1-deterministic", "probe-console-deterministic", False), ("$(MAKE) probe-console-deterministic", "probe-console-deterministic", True)])
def test_gate_make_target_false_positives(recipe, target, expected):
    assert (target in _invoked_make_targets([_RC(recipe, recipe.startswith("-"))])) is expected


@pytest.mark.parametrize("recipe,script,expected", [("python scripts/validate_refactor_phase_6.py", "scripts/validate_refactor_phase_6.py", True), ("python scripts/validate_refactor_phase_6.py.old", "scripts/validate_refactor_phase_6.py", False), ("echo scripts/validate_refactor_phase_6.py", "scripts/validate_refactor_phase_6.py", False)])
def test_gate_script_exact_match(recipe, script, expected):
    assert (script in _invoked_scripts([_RC(recipe, False)])) is expected


@pytest.mark.parametrize(
    "body",
    [
        'schema_version = true\nstatus = "active"\n\n[[items]]\n' + _ITEM.format(path="x", kind="filesystem", action="delete", status="planned", confidence="confirmed"),
        'schema_version = 1.0\nstatus = "active"\n\n[[items]]\n' + _ITEM.format(path="x", kind="filesystem", action="delete", status="planned", confidence="confirmed"),
        'schema_version = 1\nstatus = ["active"]\n\n[[items]]\n' + _ITEM.format(path="x", kind="filesystem", action="delete", status="planned", confidence="confirmed"),
        'schema_version = 1\nstatus = "active"\n\n[[items]]\npath = "x"\nkind = ["filesystem"]\naction = "delete"\nowner_pr = "6C"\nstatus = "planned"\nconfidence = "confirmed"\nresponsibility = "x"\n',
        'schema_version = 1\nstatus = "active"\n\n[[items]]\n' + _ITEM.format(path="x", kind="filesystem", action="delete", status="planned", confidence="confirmed") + "aggregate = 1\n",
        'schema_version = 1\nstatus = "active"\n\n[[items]]\n' + _ITEM.format(path="x", kind="filesystem", action="retain", status="planned", confidence="confirmed") + "requires_explicit_test_target_reference = 1\n",
        'schema_version = 1\nstatus = "active"\nextra = true\n\n[[items]]\n' + _ITEM.format(path="x", kind="filesystem", action="delete", status="planned", confidence="confirmed"),
    ],
    ids=["schema_true", "schema_float", "status_list", "kind_list", "aggregate_int", "requires_int", "unknown_top"],
)
def test_malformed_manifest_inputs_fail(tmp_path, body):
    p = tmp_path / "docs/refactor"
    p.mkdir(parents=True)
    (p / "deletion-manifest.toml").write_text(body, encoding="utf-8")
    manifest, errors = parse_manifest(tmp_path)
    assert manifest is None and errors


def test_absolute_manifest_path_fails(tmp_path):
    RepoFixture(tmp_path).write_manifest(items="[[items]]\n" + _ITEM.format(path="/etc/passwd", kind="filesystem", action="delete", status="planned", confidence="confirmed"))
    manifest, errors = parse_manifest(tmp_path)
    assert manifest is None and any("repository-relative" in e for e in errors)


def test_workflow_path_duplicate_slash_variants_fail(tmp_path):
    item = "[[items]]\n" + _ITEM.format(
        path=".github/workflows/legacy.yml",
        kind="workflow",
        action="delete",
        status="planned",
        confidence="confirmed",
    )
    dup = "[[items]]\npath = '.github\\workflows\\legacy.yml'\nkind = \"workflow\"\naction = \"delete\"\nowner_pr = \"6C\"\nstatus = \"planned\"\nconfidence = \"confirmed\"\nresponsibility = \"x\"\n"
    RepoFixture(tmp_path).write_manifest(items=item + dup)
    manifest, errors = parse_manifest(tmp_path)
    assert manifest is None and any("duplicate kind/path" in e for e in errors)


def test_planned_discovery_needed_port_without_replacement_passes(tmp_path):
    RepoFixture(tmp_path).write_manifest(items="[[items]]\n" + _ITEM.format(path="tests/unit/test_planning_analysis.py", kind="filesystem", action="port_then_delete", status="planned", confidence="discovery-needed"))
    manifest, errors = parse_manifest(tmp_path)
    assert manifest is not None and errors == []


@pytest.mark.parametrize("status,confidence", [("planned", "confirmed"), ("complete", "confirmed"), ("in_progress", "confirmed")])
def test_port_without_replacement_fails_unless_discovery_needed(tmp_path, status, confidence):
    RepoFixture(tmp_path).write_manifest(items="[[items]]\n" + _ITEM.format(path="tests/unit/test_planning_analysis.py", kind="filesystem", action="port_then_delete", status=status, confidence=confidence))
    manifest, errors = parse_manifest(tmp_path)
    assert manifest is None and any("requires replacements" in e for e in errors)


@pytest.mark.parametrize(
    "workflow,frag",
    [
        ("jobs:\n  finalization-check:\n    steps:\n      - run: echo finalization-check\n", "exactly one job invoking"),
        ("jobs:\n  finalization-check:\n    steps:\n      - run: make finalization-check || true\n", "exactly one job invoking"),
        ("jobs:\n  finalization-check:\n    steps:\n      - run: make finalization-check\n  legacy:\n    steps:\n      - run: |\n          cd /workspace\n          make characterization-full\n", "legacy target characterization-full"),
        ("jobs:\n  finalization-check:\n    steps:\n      - run: >\n          echo\n          make finalization-check\n", "exactly one job invoking"),
        ("jobs:\n  finalization-check:\n    steps:\n      - run: make finalization-check-target\n", "finalization-check-target"),
        ("jobs:\n  finalization-check:\n    steps:\n      - run: make finalization-check\n        continue-on-error: true\n", "continue-on-error"),
    ],
    ids=["echo", "suppressed", "literal_legacy", "folded_echo", "target_gate", "continue_on_error"],
)
def test_workflow_completion_rules(tmp_path, workflow, frag):
    r = RepoFixture(tmp_path)
    r.seed_cutover(complete=True)
    r.write_workflow("name: x\non: {pull_request: null}\n" + workflow)
    assert any(frag in e for e in validate(tmp_path, stage="cutover"))


def test_renamed_legacy_entry_point_fails(tmp_path):
    r = RepoFixture(tmp_path)
    r.seed_cutover(complete=True)
    r.write_pyproject(_PP_TARGET + 'old-debug-server = "psychoanalyst_app.server:cli"\n')
    assert any("legacy entry point value" in e for e in validate(tmp_path, stage="cutover"))


def test_wrong_target_entry_point_value_fails(tmp_path):
    r = RepoFixture(tmp_path)
    r.seed_cutover(complete=True)
    r.write_pyproject(_PP_TARGET.replace('jung-api = "jung.api.app:cli"', 'jung-api = "some_other_package.app:main"'))
    assert any("entry point 'jung-api' must be" in e for e in validate(tmp_path, stage="cutover"))
