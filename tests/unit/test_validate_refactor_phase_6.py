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
PREPARE_RUNTIME_RECIPES = _MOD.PREPARE_RUNTIME_RECIPES

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
_PREPARE = (
    "prepare-runtime-dirs:\n"
    f"\t{PREPARE_RUNTIME_RECIPES[0]}\n"
    f"\t{PREPARE_RUNTIME_RECIPES[1]}\n"
)
_STUBS = """\
lint:\n\t@true
validate-docs:\n\t@true
validate-schemas:\n\t@true
validate-generated-contracts:\n\t@true
validate-architecture:\n\t@true
test-validate:\n\t@true
characterization-smoke:\n\t@true
probe-console-deterministic:\n\t@true
probe-console-v1-deterministic:\n\t@true
test-target:\n\tpytest tests/
"""
_PHONY = (
    ".PHONY: prepare-runtime-dirs lint validate-docs validate-schemas "
    "validate-generated-contracts validate-architecture test-validate "
    "test-target characterization-smoke probe-console-deterministic "
    "probe-console-v1-deterministic finalization-check finalization-check-target\n"
)
_DOCKER_PY = (
    "docker compose --profile test run --rm test python {script}{args}\n"
)
_LEGACY_GATE = (
    "finalization-check: prepare-runtime-dirs\n"
    "\t$(MAKE) lint\n"
    "\t$(MAKE) validate-docs\n"
    "\t$(MAKE) validate-schemas\n"
    "\t$(MAKE) validate-generated-contracts\n"
    "\t$(MAKE) validate-architecture\n"
    "\t$(MAKE) test-validate\n"
    "\t"
    + _DOCKER_PY.format(script="scripts/validate_refactor_phase_5.py", args="")
    + "\t$(MAKE) characterization-smoke\n"
    + "\t$(MAKE) probe-console-deterministic\n"
)


def _target_gate(stage: str) -> str:
    return (
        "finalization-check-target: prepare-runtime-dirs\n"
        "\t$(MAKE) lint\n"
        "\t$(MAKE) validate-docs\n"
        "\t$(MAKE) test-target\n"
        "\t" + _DOCKER_PY.format(
            script="scripts/validate_refactor_phase_6.py",
            args=f" --stage {stage}",
        )
        + "\t" + _DOCKER_PY.format(script="scripts/validate_refactor_phase_5.py", args="")
        + "\t$(MAKE) probe-console-v1-deterministic\n"
    )


def _cutover_gate(stage: str) -> str:
    return (
        "finalization-check: prepare-runtime-dirs\n"
        "\t$(MAKE) lint\n"
        "\t$(MAKE) validate-docs\n"
        "\t$(MAKE) test-target\n"
        "\t" + _DOCKER_PY.format(
            script="scripts/validate_refactor_phase_6.py",
            args=f" --stage {stage}",
        )
        + "\t" + _DOCKER_PY.format(script="scripts/validate_refactor_phase_5.py", args="")
        + "\t$(MAKE) probe-console-v1-deterministic\n"
    )


_DF_LEGACY = (
    "FROM python:3.11-slim AS base\nFROM base AS development\n"
    'CMD ["python", "-m", "psychoanalyst_app.server"]\n'
)
_DF_TARGET = (
    "FROM python:3.11-slim AS base\nFROM base AS development\n"
    'CMD ["jung-api"]\n'
)
_CP_LEGACY = (
    "x-api-base: &api-base\n  build:\n    context: .\n    dockerfile: Dockerfile\n"
    "    target: development\n  command: python -m psychoanalyst_app.server\n"
    "services:\n  api:\n    <<: *api-base\n"
)
_CP_TARGET = (
    "x-api-base: &api-base\n  build:\n    context: .\n    dockerfile: Dockerfile\n"
    "    target: development\n  command: jung-api\nservices:\n  api:\n    <<: *api-base\n"
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
    "name: x\non:\n  push:\n    branches:\n      - main\njobs:\n"
    "  finalization-check:\n    steps:\n      - run: make finalization-check\n"
)
_WF_CUTOVER = (
    "name: Release Candidate Validation\n"
    "on:\n"
    "  push:\n    branches:\n      - master\n      - main\n      - develop\n"
    "  pull_request:\n    branches:\n      - master\n      - main\n      - develop\n"
    "jobs:\n"
    "  finalization-check:\n"
    "    name: Docker Finalization Check\n"
    "    runs-on: ubuntu-latest\n"
    "    timeout-minutes: 60\n"
    "    env:\n"
    "      ENV_FILE: .env.example\n"
    "    steps:\n"
    "      - name: Checkout code\n"
    "        uses: actions/checkout@v4\n"
    "      - name: Run Docker release-candidate gate\n"
    "        run: make finalization-check\n"
    "      - name: Check whitespace and stale generated diffs\n"
    "        run: git diff --check && git diff --exit-code\n"
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
        if gates is None:
            gates = (
                _cutover_gate("cutover")
                if target
                else _LEGACY_GATE + _target_gate("pre-cutover")
            )
        (self.root / "Makefile").write_text(
            _PHONY + _PREPARE + _STUBS + gates, encoding="utf-8"
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

    def replace_target_recipe(self, target: str, old: str, new: str) -> None:
        path = self.root / "Makefile"
        text = path.read_text(encoding="utf-8")
        header = f"{target}:"
        start = text.find(header)
        assert start != -1, f"target {target!r} not found"
        next_header = re.search(r"^[A-Za-z0-9_.-]+:", text[start + len(header) :], re.M)
        end = start + len(header) + next_header.start() if next_header else len(text)
        block = text[start:end]
        count = block.count(old)
        assert count == 1, f"old recipe must appear once in {target}, got {count}"
        path.write_text(text[:start] + block.replace(old, new) + text[end:], encoding="utf-8")

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
    [("pre-cutover", "pre"), ("cutover", "cutover"), ("final", "final")],
)
def test_valid_stage_passes(tmp_path, stage, seed):
    r = RepoFixture(tmp_path)
    {"pre": r.seed_pre, "cutover": lambda: r.seed_cutover(complete=True), "final": r.seed_final}[seed]()
    assert validate(tmp_path, stage=stage) == []


@pytest.mark.parametrize(
    "stage,status",
    [("pre-cutover", "completed"), ("cutover", "completed"), ("final", "active")],
)
def test_manifest_status_rejected(tmp_path, stage, status):
    r = RepoFixture(tmp_path)
    r.seed_pre()
    r.write_manifest(status=status, items=_MANIFEST_TAIL.format(wf="in_progress"))
    assert any("manifest status" in e for e in validate(tmp_path, stage=stage))


@pytest.mark.parametrize(
    "mutation,frag",
    [
        ("wrong stage", "recipe contract mismatch"),
        ("missing recipe", "recipe contract mismatch"),
        ("extra recipe", "unsupported recipe"),
        ("ignored failure", "unsupported recipe"),
        ("wrong prerequisite", "prerequisite contract mismatch"),
        ("duplicate definition", "exactly one definition"),
        ("not phony", "must be phony"),
        ("multi-target header", "unsupported multi-target header"),
        ("double-colon", "unsupported double-colon definition"),
        ("inline recipe header", "unsupported inline recipe header"),
        ("plus prefix", "unsupported recipe"),
        ("ignore directive", ".IGNORE"),
        ("oneshell", "forbidden control"),
        ("recipeprefix", "forbidden control"),
        ("gnuflags", "forbidden control"),
    ],
    ids=lambda v: v,
)
def test_gate_mutations(tmp_path, mutation, frag):
    r = RepoFixture(tmp_path)
    r.seed_cutover(complete=True)
    makefile = (tmp_path / "Makefile").read_text(encoding="utf-8")
    if mutation == "wrong stage":
        makefile = makefile.replace("--stage cutover", "--stage pre-cutover")
    elif mutation == "missing recipe":
        makefile = makefile.replace("\t$(MAKE) probe-console-v1-deterministic\n", "")
    elif mutation == "extra recipe":
        makefile = makefile.replace(
            "\t$(MAKE) probe-console-v1-deterministic\n",
            "\t$(MAKE) probe-console-v1-deterministic\n\tbash -c 'make characterization-smoke'\n",
        )
    elif mutation == "ignored failure":
        makefile = makefile.replace("\t$(MAKE) test-target\n", "\t-$(MAKE) test-target\n")
    elif mutation == "wrong prerequisite":
        makefile = makefile.replace(
            "finalization-check: prepare-runtime-dirs",
            "finalization-check: characterization-smoke",
        )
    elif mutation == "duplicate definition":
        makefile += "\nfinalization-check: prepare-runtime-dirs\n\t@true\n"
    elif mutation == "not phony":
        makefile = makefile.replace(" finalization-check", "")
    elif mutation == "multi-target header":
        makefile = makefile.replace(
            "finalization-check: prepare-runtime-dirs",
            "finalization-check helper: prepare-runtime-dirs",
        )
    elif mutation == "double-colon":
        makefile = makefile.replace(
            "finalization-check: prepare-runtime-dirs",
            "finalization-check:: prepare-runtime-dirs",
        )
    elif mutation == "inline recipe header":
        makefile = makefile.replace(
            "finalization-check: prepare-runtime-dirs",
            "finalization-check: prepare-runtime-dirs ; $(MAKE) lint",
        )
    elif mutation == "plus prefix":
        makefile = makefile.replace("\t$(MAKE) lint\n", "\t+$(MAKE) lint\n")
    elif mutation == "ignore directive":
        makefile = ".IGNORE:\n" + makefile
    elif mutation == "oneshell":
        makefile = ".ONESHELL:\n" + makefile
    elif mutation == "recipeprefix":
        makefile = ".RECIPEPREFIX := >\n" + makefile
    elif mutation == "gnuflags":
        makefile = "GNUMAKEFLAGS += -i\n" + makefile
    else:
        raise AssertionError(mutation)
    (tmp_path / "Makefile").write_text(makefile, encoding="utf-8")
    assert any(frag in e for e in validate(tmp_path, stage="cutover"))


def test_cutover_rejects_target_gate_present(tmp_path):
    r = RepoFixture(tmp_path)
    r.seed_cutover(complete=True)
    makefile = (tmp_path / "Makefile").read_text(encoding="utf-8")
    makefile += _target_gate("cutover")
    (tmp_path / "Makefile").write_text(makefile, encoding="utf-8")
    assert any("finalization-check-target must be absent" in e for e in validate(tmp_path, stage="cutover"))


def test_cutover_rejects_in_progress_workflow_edit(tmp_path):
    RepoFixture(tmp_path).seed_cutover(complete=False)
    assert any("required item must be complete" in e for e in validate(tmp_path, stage="cutover"))


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
    "body,frag",
    [
        ('schema_version = true\nstatus = "active"\n\n[[items]]\n' + _ITEM.format(path="x", kind="filesystem", action="delete", status="planned", confidence="confirmed"), "schema_version"),
        ('schema_version = 1\nstatus = "active"\nextra = true\n\n[[items]]\n' + _ITEM.format(path="x", kind="filesystem", action="delete", status="planned", confidence="confirmed"), "extra"),
        ('schema_version = 1\nstatus = "active"\n\n[[items]]\n' + _ITEM.format(path="x", kind="filesystem", action="edit", status="planned", confidence="confirmed"), "action"),
        ('schema_version = 1\nstatus = "active"\n\n[[items]]\n' + _ITEM.format(path="x", kind="filesystem", action="retain", status="planned", confidence="confirmed") + "requires_explicit_test_target_reference = false\n", "requires_explicit_test_target_reference"),
    ],
)
def test_malformed_manifest_inputs_fail(tmp_path, body, frag):
    p = tmp_path / "docs/refactor"
    p.mkdir(parents=True)
    (p / "deletion-manifest.toml").write_text(body, encoding="utf-8")
    manifest, errors = parse_manifest(tmp_path)
    assert manifest is None
    assert any(frag in error for error in errors)


@pytest.mark.parametrize(
    "stage,compose,dockerfile,ok,err",
    [
        ("pre-cutover", "services:\n  api:\n    build:\n      context: .\n      dockerfile: Dockerfile\n      target: development\n    command: python -m psychoanalyst_app.server\n", _DF_LEGACY, True, ""),
        ("cutover", "services:\n  api:\n    build:\n      context: .\n      dockerfile: Dockerfile\n      target: development\n    command: python -m psychoanalyst_app.server\n", _DF_TARGET, False, "docker-compose api command must select"),
        ("cutover", "services:\n  api:\n    build:\n      context: .\n      dockerfile: Dockerfile\n      target: development\n    command: [not-a-valid-list\n", _DF_TARGET, False, "command inline list is malformed"),
    ],
    ids=["legacy_ok", "override_fail", "malformed_list"],
)
def test_compose_runtime(tmp_path, stage, compose, dockerfile, ok, err):
    r = RepoFixture(tmp_path)
    (r.seed_cutover(complete=True) if stage == "cutover" else r.seed_pre())
    r.write_runtime(target=stage != "pre-cutover", dockerfile=dockerfile, compose=compose)
    errors = validate(tmp_path, stage=stage)
    assert (errors == []) if ok else any(err in e for e in errors)


@pytest.mark.parametrize(
    "workflow,frag",
    [
        ("on:\n  workflow_dispatch:\njobs:\n  finalization-check:\n    name: x\n    runs-on: ubuntu-latest\n    timeout-minutes: 60\n    env:\n      ENV_FILE: .env.example\n    steps:\n      - name: Checkout\n        uses: actions/checkout@v4\n      - name: Gate\n        run: make finalization-check\n      - name: Diff\n        run: git diff --check && git diff --exit-code\n", "on missing push"),
        ("on:\n  push:\n    branches:\n      - master\n      - main\n      - develop\n  pull_request:\n    branches:\n      - master\n      - main\n      - develop\njobs:\n  finalization-check:\n    name: x\n    runs-on: ubuntu-latest\n    timeout-minutes: 60\n    env:\n      ENV_FILE: .env.example\n    steps:\n      - name: Checkout\n        uses: actions/checkout@v4\n      - name: Gate\n        run: |\n          make finalization-check\n      - name: Diff\n        run: git diff --check && git diff --exit-code\n", "unsupported block scalar"),
        ("on:\n  push:\n    branches:\n      - master\n      - main\n      - develop\n  pull_request:\n    branches:\n      - master\n      - main\n      - develop\njobs:\n  finalization-check:\n    name: x\n    runs-on: ubuntu-latest\n    timeout-minutes: 60\n    env:\n      ENV_FILE: .env.example\n      MAKEFLAGS: -i\n    steps:\n      - name: Checkout\n        uses: actions/checkout@v4\n      - name: Gate\n        run: make finalization-check\n      - name: Diff\n        run: git diff --check && git diff --exit-code\n", "workflow env contract mismatch"),
        ("on:\n  push:\n    branches:\n      - master\n      - main\n      - develop\n  pull_request:\n    branches:\n      - master\n      - main\n      - develop\njobs:\n  finalization-check:\n    name: x\n    runs-on: ubuntu-latest\n    timeout-minutes: 60\n    env:\n      ENV_FILE: .env.example\n    steps:\n      - name: Checkout\n        uses: actions/checkout@v4\n      - if: false\n        name: Gate\n        run: make finalization-check\n      - name: Diff\n        run: git diff --check && git diff --exit-code\n", "workflow step 1 keys contract mismatch"),
    ],
    ids=["dispatch", "block_scalar", "extra_env", "step_if"],
)
def test_workflow_contract(tmp_path, workflow, frag):
    r = RepoFixture(tmp_path)
    r.seed_cutover(complete=True)
    r.write_workflow("name: Release Candidate Validation\n" + workflow)
    assert any(frag in e for e in validate(tmp_path, stage="cutover"))


def test_forbidden_import_and_dependency(tmp_path):
    r = RepoFixture(tmp_path)
    r.seed_final()
    p = tmp_path / "src/legacy.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("import psychoanalyst_app\n", encoding="utf-8")
    assert any("imports forbidden module" in e for e in validate(tmp_path, stage="final"))
    r.write_pyproject(_PP_TARGET.replace('dependencies = ["fastapi"]', 'dependencies = ["fastapi", "trio"]'))
    assert any("forbidden dependency" in e for e in validate(tmp_path, stage="final"))


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
        ("TARGET_SUPPORT_TESTS := tests/unit/test_validate_refactor_phase_6.py\n" "test-target:\n\tpytest tests/unit/jung/\n", False),
        ("test-target:\n\techo $(TARGET_SUPPORT_TESTS)\n", False),
        ("test-target:\n\techo pytest tests/unit/test_validate_refactor_phase_6.py\n", False),
        ("test-target:\n\tpytest tests/unit/test_validate_refactor_phase_6.py\n", True),
        ("test-target:\n\tdocker compose --profile test run --rm test pytest tests/unit/test_validate_refactor_phase_6.py\n", True),
        ("TARGET_SUPPORT_TESTS := tests/unit/test_validate_refactor_phase_6.py\n" "test-target:\n\tdocker compose --profile test run --rm test pytest $(TARGET_SUPPORT_TESTS)\n", True),
    ],
    ids=["unused_var", "echo_var", "echo_pytest", "direct_pytest", "docker_pytest", "var_expansion"],
)
def test_retained_test_reference_rules(tmp_path, makefile_patch, should_pass):
    r = RepoFixture(tmp_path)
    r.write_manifest(items=_retained_test_manifest())
    r.write_runtime(target=True)
    r.write_workflow(_WF_CUTOVER)
    base = (tmp_path / "Makefile").read_text(encoding="utf-8")
    base = re.sub(r"test-target:\n\tpytest tests/\n", makefile_patch, base)
    (tmp_path / "Makefile").write_text(base, encoding="utf-8")
    (tmp_path / _RETAINED_TEST).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / _RETAINED_TEST).write_text("#\n", encoding="utf-8")
    errors = validate(tmp_path, stage="cutover")
    if should_pass:
        assert not any("retained test not referenced" in e for e in errors)
    else:
        assert any("retained test not referenced" in e for e in errors)
