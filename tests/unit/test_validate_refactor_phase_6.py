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
    "\t@mkdir -p data logs logs/workflow-probes\n"
    '\t@if [ "$${CI:-}" = "true" ]; then chmod -R a+rwX data logs; '
    "else chmod -R u+rwX,g+rwX data logs; fi\n"
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
_DOCKER_TEST_RUN = (
    "docker compose -f docker-compose.yml --profile test run --rm --no-deps test"
)
_DOCKER_PY = (
    "docker compose -f docker-compose.yml --profile test run --rm --no-deps "
    "--entrypoint /usr/local/bin/python "
    '--volume "$(CURDIR):/workspace:ro" '
    "--workdir /workspace "
    "--env PYTHONPATH=/workspace/src "
    "test {script}{args}\n"
)
_CANONICAL_VALIDATOR_RECIPE = _DOCKER_PY.format(
    script="scripts/validate_refactor_phase_6.py", args=" --stage cutover"
)
_LEGACY_GATE = (
    "finalization-check: prepare-runtime-dirs\n"
    "\t$(MAKE) lint\n"
    "\t$(MAKE) validate-docs\n"
    "\t$(MAKE) validate-schemas\n"
    "\t$(MAKE) validate-generated-contracts\n"
    "\t$(MAKE) validate-architecture\n"
    "\t$(MAKE) test-validate\n"
    "\t" + _DOCKER_PY.format(script="scripts/validate_refactor_phase_5.py", args="")
    + "\t$(MAKE) characterization-smoke\n"
    + "\t$(MAKE) probe-console-deterministic\n"
)
_WF_CANONICAL = (
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
_WF_COEXIST = (
    "name: x\non:\n  push:\n    branches:\n      - main\njobs:\n"
    "  finalization-check:\n    steps:\n      - run: make finalization-check\n"
)
_CANONICAL_MISMATCH = "completed release workflow does not match canonical contract"
_PHASE6_DOCKER = "\t" + _CANONICAL_VALIDATOR_RECIPE

def _target_gate(stage: str, *, name: str = "finalization-check-target") -> str:
    return (
        f"{name}: prepare-runtime-dirs\n"
        "\t$(MAKE) lint\n"
        "\t$(MAKE) validate-docs\n"
        "\t$(MAKE) test-target\n"
        "\t" + _DOCKER_PY.format(
            script="scripts/validate_refactor_phase_6.py", args=f" --stage {stage}"
        )
        + "\t" + _DOCKER_PY.format(script="scripts/validate_refactor_phase_5.py", args="")
        + "\t$(MAKE) probe-console-v1-deterministic\n"
    )

def replace_target_block(makefile: str, target: str, replacement: str) -> str:
    pattern = re.compile(
        rf"^{re.escape(target)}:.*?(?=^[A-Za-z0-9_.-]+:|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    matches = list(pattern.finditer(makefile))
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one {target!r} block, got {len(matches)}")
    start, end = matches[0].span()
    return makefile[:start] + replacement + makefile[end:]

def _compose_fixture(
    command: str, *, api_extra: str = "", base_extra: str = "", test_extra: str = ""
) -> str:
    return (
        "x-api-base: &api-base\n"
        "  build:\n"
        "    context: .\n"
        "    dockerfile: Dockerfile\n"
        "    target: development\n"
        f"{base_extra}"
        '  user: "${HOST_UID:-1000}:${HOST_GID:-1000}"\n'
        "  volumes:\n"
        "    - ./src:/app/src:delegated\n"
        "  environment:\n"
        "    - APP_ENV=development\n"
        "  networks:\n"
        "    - app-network\n"
        f"  command: {command}\n"
        "  logging:\n"
        '    driver: "json-file"\n'
        "    options:\n"
        '      max-size: "10m"\n'
        "  healthcheck:\n"
        '    test: ["CMD", "wget"]\n'
        "    interval: 30s\n"
        "services:\n"
        "  api:\n"
        "    <<: *api-base\n"
        "    container_name: psychoanalyst_api\n"
        "    env_file:\n"
        "      - ${ENV_FILE:-.env}\n"
        f"{api_extra}"
        "  test:\n"
        "    profiles: [\"test\"]\n"
        "    build:\n"
        "      context: .\n"
        "      dockerfile: Dockerfile\n"
        "      target: development\n"
        f"{test_extra}"
        "    command: pytest\n"
    )

_DF_LEGACY = "FROM python:3.11-slim AS base\nFROM base AS development\nCMD [\"python\", \"-m\", \"psychoanalyst_app.server\"]\n"
_DF_TARGET = "FROM python:3.11-slim AS base\nFROM base AS development\nCMD [\"jung-api\"]\n"
_DF_WRONG_CMD = "FROM python:3.11-slim AS base\nFROM base AS development\nCMD [\"echo\", \"jung-api\"]\n"
_DF_MALFORMED_CMD = "FROM python:3.11-slim AS base\nFROM base AS development\nCMD [not-valid\n"
_DF_SHELL_CMD = "FROM python:3.11-slim AS base\nFROM base AS development\nCMD jung-api\n"
_DF_ENTRYPOINT = (
    "FROM python:3.11-slim AS base\nENTRYPOINT [\"echo\"]\n"
    "FROM base AS development\nCMD [\"jung-api\"]\n"
)
_DF_NONSELECTED = (
    "FROM python:3.11-slim AS base\nCMD [\"wrong\"]\n"
    "FROM base AS development\nCMD [\"jung-api\"]\n"
)
_DF_DUP_STAGE = (
    "FROM python:3.11-slim AS base\nFROM base AS development\nCMD [\"jung-api\"]\n"
    "FROM other AS development\nCMD [\"other\"]\n"
)
_CP_LEGACY = _compose_fixture("python -m psychoanalyst_app.server")
_CP_TARGET = _compose_fixture("jung-api")
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
_RETAINED_TEST = "tests/unit/test_validate_refactor_phase_6.py"

def _manifest_item(**kwargs) -> str:
    defaults = {"status": "complete", "confidence": "confirmed"}
    defaults.update(kwargs)
    return "[[items]]\n" + _ITEM.format(**defaults)

def _retained_test_manifest() -> str:
    return (
        _MANIFEST_TAIL.format(wf="complete")
        + _manifest_item(
            path=_RETAINED_TEST,
            kind="filesystem",
            action="retain",
        )
        + "requires_explicit_test_target_reference = true\n"
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
                _target_gate("cutover", name="finalization-check")
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
        for name in ("validate_refactor_phase_5.py", "validate_refactor_phase_6.py"):
            (self.root / "scripts" / name).write_text("#\n", encoding="utf-8")
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
        self.write_workflow(_WF_CANONICAL if complete else _WF_COEXIST)

    def seed_final(self) -> None:
        self.write_manifest(
            status="completed",
            items=(
                _manifest_item(
                    path="gone/",
                    kind="filesystem",
                    action="delete",
                    owner_pr="6D",
                    responsibility="x",
                )
                + "aggregate = true\n"
                + _manifest_item(
                    path=".github/workflows/release-candidate-validation.yml",
                    kind="workflow_edit",
                    action="edit",
                    owner_pr="6C",
                    responsibility="x",
                )
            ),
        )
        self.write_runtime(target=True, gates=_target_gate("final", name="finalization-check"))
        self.write_workflow(_WF_CANONICAL)
        (self.root / "src").mkdir(exist_ok=True)

@pytest.fixture
def repo(tmp_path: Path) -> RepoFixture:
    return RepoFixture(tmp_path)

@pytest.mark.parametrize(
    "stage,seed",
    [("pre-cutover", "pre"), ("cutover", "cutover"), ("final", "final")],
)
def test_valid_stage_passes(repo, stage, seed):
    {"pre": repo.seed_pre, "cutover": lambda: repo.seed_cutover(complete=True), "final": repo.seed_final}[seed]()
    assert validate(repo.root, stage=stage) == []

@pytest.mark.parametrize(
    "stage,status",
    [("pre-cutover", "completed"), ("cutover", "completed"), ("final", "active")],
)
def test_manifest_status_rejected(repo, stage, status):
    repo.seed_pre()
    repo.write_manifest(status=status, items=_MANIFEST_TAIL.format(wf="in_progress"))
    assert any("manifest status" in e for e in validate(repo.root, stage=stage))

@pytest.mark.parametrize(
    "old,new,frag",
    [
        pytest.param("--stage cutover", "--stage pre-cutover", "recipe contract mismatch", id="wrong_stage"),
        pytest.param("\t$(MAKE) probe-console-v1-deterministic\n", "", "recipe contract mismatch", id="missing_recipe"),
        pytest.param(
            "\t$(MAKE) probe-console-v1-deterministic\n",
            "\t$(MAKE) probe-console-v1-deterministic\n\tbash -c 'make characterization-smoke'\n",
            "unsupported recipe",
            id="extra_recipe",
        ),
        pytest.param("\t$(MAKE) test-target\n", "\t-$(MAKE) test-target\n", "unsupported recipe prefix", id="ignored_failure"),
        pytest.param("\t$(MAKE) lint\n", "\t@-$(MAKE) lint\n", "unsupported recipe prefix", id="at_prefix_make"),
        pytest.param(_PHASE6_DOCKER, "\t@-" + _PHASE6_DOCKER.lstrip(), "unsupported recipe prefix", id="at_prefix_docker"),
        pytest.param(
            "finalization-check: prepare-runtime-dirs",
            "finalization-check: characterization-smoke",
            "prerequisite contract mismatch",
            id="wrong_prerequisite",
        ),
        pytest.param(
            " finalization-check finalization-check-target",
            " finalization-check-target",
            "must be phony",
            id="not_phony",
        ),
        pytest.param("\t$(MAKE) lint\n", "\t+$(MAKE) lint\n", "unsupported recipe prefix", id="plus_prefix"),
    ],
)
def test_gate_replacements(repo, old, new, frag):
    repo.seed_cutover(complete=True)
    makefile = (repo.root / "Makefile").read_text(encoding="utf-8")
    assert makefile.count(old) == 1
    (repo.root / "Makefile").write_text(makefile.replace(old, new, 1), encoding="utf-8")
    assert any(frag in e for e in validate(repo.root, stage="cutover"))

@pytest.mark.parametrize(
    "old,new",
    [
        pytest.param("-f docker-compose.yml ", "", id="missing_compose_file"),
        pytest.param("--no-deps ", "", id="missing_no_deps"),
        pytest.param("$(CURDIR):/workspace:ro", "$(CURDIR):/other:ro", id="wrong_workspace_mount"),
        pytest.param("--workdir /workspace", "--workdir /app", id="wrong_workdir"),
    ],
)
def test_validator_bootstrap_recipe_mutations(repo, old, new):
    repo.seed_cutover(complete=True)
    makefile = (repo.root / "Makefile").read_text(encoding="utf-8")
    assert makefile.count(_CANONICAL_VALIDATOR_RECIPE) == 1
    assert _CANONICAL_VALIDATOR_RECIPE.count(old) == 1
    mutated = _CANONICAL_VALIDATOR_RECIPE.replace(old, new, 1)
    (repo.root / "Makefile").write_text(
        makefile.replace(_CANONICAL_VALIDATOR_RECIPE, mutated, 1),
        encoding="utf-8",
    )
    assert any(
        "recipe contract mismatch" in e or "unsupported recipe" in e
        for e in validate(repo.root, stage="cutover")
    )

@pytest.mark.parametrize(
    "prefix,suffix,frag",
    [
        pytest.param('', '\nfinalization-check: prepare-runtime-dirs\n\t@true\n', 'exactly one definition', id='duplicate_definition'),
        pytest.param('', '\nfinalization-check helper: prepare-runtime-dirs\n\t@true\n', 'unsupported multi-target header', id='forbidden_multi_target'),
        pytest.param('.IGNORE:\n', '', '.IGNORE', id='ignore_directive'),
        pytest.param('.ONESHELL:\n', '', 'forbidden control', id='oneshell'),
        pytest.param('.RECIPEPREFIX := >\n', '', 'forbidden control', id='recipeprefix'),
        pytest.param('GNUMAKEFLAGS += -i\n', '', 'forbidden control', id='gnuflags'),
        pytest.param('MAKEFILES := extra.mk\n', '', 'forbidden control MAKEFILES', id='makefiles'),
        pytest.param('include extra.mk\n', '', 'include directives are unsupported', id='include'),
        pytest.param('GATE := finalization-check\n$(GATE): characterization-smoke\n', '', 'variable-expanded target headers are unsupported', id='expanded_target'),
        pytest.param('HIDDEN := $(eval finalization-check: characterization-smoke)\n', '', 'eval expressions are unsupported', id='eval_assignment'),
        pytest.param('export COMPOSE_FILE := alternate.yml\n', '', 'forbidden control COMPOSE_FILE', id='compose_file'),
        pytest.param('MAKE := true\n', '', 'forbidden control MAKE', id='make_override'),
        pytest.param('export PATH := ./fake-bin:$(PATH)\n', '', 'forbidden control PATH', id='path_override'),
        pytest.param('CURDIR := /tmp/alternate-checkout\n', '', 'forbidden control CURDIR', id='curdir_override'),
        pytest.param('export DOCKER_HOST := tcp://evil:2375\n', '', 'forbidden control DOCKER_HOST', id='docker_host'),
        pytest.param('DOCKER_CONTEXT := evil\n', '', 'forbidden control DOCKER_CONTEXT', id='docker_context'),
        pytest.param('export DOCKER_CONFIG := ./fake-docker\n', '', 'forbidden control DOCKER_CONFIG', id='docker_config'),
    ],
)
def test_gate_additions(repo, prefix, suffix, frag):
    repo.seed_cutover(complete=True)
    makefile = (repo.root / "Makefile").read_text(encoding="utf-8")
    (repo.root / "Makefile").write_text(prefix + makefile + suffix, encoding="utf-8")
    assert any(frag in e for e in validate(repo.root, stage="cutover"))

def test_empty_gate_body_fails(repo):
    repo.seed_cutover(complete=True)
    (repo.root / "Makefile").write_text(
        replace_target_block(
            (repo.root / "Makefile").read_text(encoding="utf-8"),
            "finalization-check",
            "finalization-check: prepare-runtime-dirs\n",
        ),
        encoding="utf-8",
    )
    assert any("recipe contract mismatch" in e for e in validate(repo.root, stage="cutover"))

def test_cutover_rejects_target_gate_present(repo):
    repo.seed_cutover(complete=True)
    (repo.root / "Makefile").write_text(
        (repo.root / "Makefile").read_text(encoding="utf-8") + _target_gate("cutover"),
        encoding="utf-8",
    )
    assert any("finalization-check-target must be absent" in e for e in validate(repo.root, stage="cutover"))

@pytest.mark.parametrize(
    "stage,setup,frag",
    [
        pytest.param("cutover", "incomplete", "required workflow item must be complete", id="cutover_incomplete"),
        pytest.param("final", "absent", "required complete item missing", id="final_absent"),
    ],
)
def test_workflow_lifecycle_requirements(repo, stage, setup, frag):
    if stage == "cutover":
        repo.seed_cutover(complete=False)
    else:
        repo.seed_final()
        repo.write_manifest(
            status="completed",
            items=_manifest_item(
                path="gone/",
                kind="filesystem",
                action="delete",
                owner_pr="6D",
                responsibility="x",
            )
            + "aggregate = true\n",
        )
    assert any(frag in e for e in validate(repo.root, stage=stage))

@pytest.mark.parametrize(
    "extra,setup,frag",
    [
        ({"path": "legacy.txt", "kind": "filesystem", "action": "delete"}, "touch", "still present"),
        ({"path": "legacy.py", "kind": "filesystem", "action": "port_then_delete"}, "replacements", "missing path"),
        ({"path": "missing-target", "kind": "make_target", "action": "retain"}, None, "retained path missing"),
    ],
)
def test_manifest_item_failures(repo, extra, setup, frag):
    repo.seed_pre()
    item = _manifest_item(**extra)
    if setup == "touch":
        (repo.root / extra["path"]).write_text("x", encoding="utf-8")
    elif setup == "replacements":
        item += 'replacements = ["missing/replacement.py"]\n'
    repo.write_manifest(items=_MANIFEST_TAIL.format(wf="in_progress") + item)
    assert any(frag in e for e in validate(repo.root, stage="pre-cutover"))

def _planned_manifest(**item_overrides) -> str:
    defaults = {
        "path": "x", "kind": "filesystem", "action": "delete",
        "status": "planned", "confidence": "confirmed",
    }
    defaults.update(item_overrides)
    return f'schema_version = 1\nstatus = "active"\n\n{_manifest_item(**defaults)}'

@pytest.mark.parametrize(
    "body,frag",
    [
        pytest.param(_planned_manifest().replace("schema_version = 1", "schema_version = true", 1), "schema_version", id="bad_schema_version"),
        pytest.param(_planned_manifest().replace('status = "active"\n', 'status = "active"\nextra = true\n', 1), "extra", id="extra_top_level"),
        pytest.param(_planned_manifest(action="edit"), "action", id="bad_action"),
        pytest.param(_planned_manifest(action="retain") + "requires_explicit_test_target_reference = false\n", "requires_explicit_test_target_reference", id="retain_flag"),
        pytest.param(_planned_manifest(path="/abs/path"), "repository-relative", id="abs_path"),
        pytest.param(_planned_manifest(path="a/../b"), "must not contain", id="dotdot_path"),
        pytest.param(_planned_manifest(path="dup") + 'replacements = ["dup", "dup"]\n', "duplicate path entry", id="dup_replacements"),
        pytest.param(_planned_manifest(action="port_then_delete") + 'evidence = ["e", "e"]\n', "duplicate path entry", id="dup_evidence"),
    ],
)
def test_malformed_manifest_inputs_fail(tmp_path, body, frag):
    p = tmp_path / "docs/refactor"
    p.mkdir(parents=True)
    (p / "deletion-manifest.toml").write_text(body, encoding="utf-8")
    manifest, errors = parse_manifest(tmp_path)
    assert manifest is None
    assert any(frag in error for error in errors)

def test_manifest_duplicate_normalized_paths_fail(tmp_path):
    body = (
        'schema_version = 1\nstatus = "active"\n\n'
        + _manifest_item(path="a//b", kind="filesystem", action="delete", status="planned", confidence="confirmed")
        + _manifest_item(path="a/b", kind="filesystem", action="delete", status="planned", confidence="confirmed")
    )
    (tmp_path / "docs/refactor").mkdir(parents=True)
    (tmp_path / "docs/refactor/deletion-manifest.toml").write_text(body, encoding="utf-8")
    manifest, errors = parse_manifest(tmp_path)
    assert manifest is None
    assert any("duplicate kind/path" in error for error in errors)

@pytest.mark.parametrize(
    "stage,dockerfile,compose,ok,err",
    [
        pytest.param("pre-cutover", _DF_LEGACY, _CP_LEGACY, True, "", id="legacy_ok"),
        pytest.param("cutover", _DF_TARGET, _compose_fixture("python -m psychoanalyst_app.server"), False, "docker-compose api command must select", id="compose_wrong_command"),
        pytest.param("cutover", _DF_WRONG_CMD, _CP_TARGET, False, "CMD must select", id="docker_wrong_cmd"),
        pytest.param("cutover", _DF_MALFORMED_CMD, _CP_TARGET, False, "malformed", id="docker_malformed_cmd"),
        pytest.param("cutover", _DF_SHELL_CMD, _CP_TARGET, False, "Dockerfile CMD must use JSON exec form", id="docker_shell_cmd"),
        pytest.param("cutover", _DF_ENTRYPOINT, _CP_TARGET, False, "ENTRYPOINT is unsupported", id="docker_entrypoint"),
        pytest.param("cutover", _DF_TARGET, _compose_fixture("jung-api", api_extra="    command: jung-api\n"), False, "must not declare local 'command'", id="api_local_override"),
        pytest.param("cutover", _DF_TARGET, _compose_fixture("jung-api").replace("target: development", "target: production"), False, "build.target", id="unknown_build_target"),
        pytest.param("cutover", _DF_TARGET, _compose_fixture("jung-api", test_extra="      target: production\n"), False, "services.test build", id="test_service_build_target"),
        pytest.param("cutover", _DF_TARGET, _compose_fixture("jung-api").replace("  command: jung-api\n", ""), False, "exactly one command", id="missing_command"),
        pytest.param("cutover", _DF_NONSELECTED, _CP_TARGET, True, "", id="nonselected_stage_ok"),
        pytest.param("cutover", _DF_TARGET, _compose_fixture("jung-api").replace("services:\n  api:", "services:\n  api:\n  api:"), False, "exactly one services.api", id="duplicate_api"),
        pytest.param("cutover", _DF_DUP_STAGE, _CP_TARGET, False, "exactly one 'development' stage", id="duplicate_docker_stage"),
    ],
)
def test_compose_runtime(repo, stage, dockerfile, compose, ok, err):
    (repo.seed_cutover(complete=True) if stage == "cutover" else repo.seed_pre())
    repo.write_runtime(target=stage != "pre-cutover", dockerfile=dockerfile, compose=compose)
    errors = validate(repo.root, stage=stage)
    assert (errors == []) if ok else any(err in e for e in errors)

@pytest.mark.parametrize(
    "compose,frag",
    [
        pytest.param(_compose_fixture("jung-api").replace("services:\n", "services: # duplicate\nservices:\n", 1), "exactly one services", id="dup_services_comment"),
        pytest.param(_compose_fixture("jung-api").replace("x-api-base:", "x-api-base: # duplicate\nx-api-base:", 1), "exactly one x-api-base", id="dup_api_base_comment"),
        pytest.param('"services":\n  api:\n    image: x\n' + _compose_fixture("jung-api").split("services:", 1)[1], "unsupported mapping syntax", id="quoted_services"),
        pytest.param(_compose_fixture("jung-api", api_extra='    "command": jung-api\n'), "unsupported mapping syntax", id="quoted_command"),
        pytest.param("? services\n" + _compose_fixture("jung-api"), "unsupported mapping syntax", id="explicit_key"),
        pytest.param(_compose_fixture("jung-api").replace("<<: *api-base", "<<: *other"), "merge must be <<: *api-base", id="wrong_merge"),
        pytest.param(_compose_fixture("jung-api", api_extra="    profiles:\n      - dev\n"), "must not declare local 'profiles'", id="profiles_local"),
        pytest.param(_compose_fixture("jung-api", api_extra="    deploy:\n      replicas: 1\n"), "must not declare local 'deploy'", id="deploy_local"),
        pytest.param(_compose_fixture("jung-api", api_extra="    scale: 2\n"), "must not declare local 'scale'", id="scale_local"),
        pytest.param(_compose_fixture("jung-api", base_extra="  entrypoint: echo\n"), "x-api-base must not declare 'entrypoint'", id="entrypoint_base"),
        pytest.param(_compose_fixture("jung-api", base_extra="  profiles:\n    - dev\n"), "x-api-base must not declare 'profiles'", id="profiles_base"),
        pytest.param("include:\n  - alternate-compose.yml\n" + _compose_fixture("jung-api"), "must not declare top-level include", id="top_level_include"),
        pytest.param(_compose_fixture("jung-api", test_extra='    entrypoint: ["true"]\n'), "services.test must not declare 'entrypoint'", id="test_entrypoint"),
    ],
)
def test_compose_syntax_categories(repo, compose, frag):
    repo.seed_cutover(complete=True)
    repo.write_runtime(target=True, compose=compose)
    assert any(frag in e for e in validate(repo.root, stage="cutover"))

@pytest.mark.parametrize(
    "workflow,expect_fail",
    [
        pytest.param(
            _WF_CANONICAL.replace("make finalization-check", "make other-gate"), True, id="altered_gate",
        ),
        pytest.param(
            _WF_CANONICAL.replace("jobs:\n", "jobs:\n  extra:\n    runs-on: ubuntu-latest\n"),
            True, id="extra_job",
        ),
        pytest.param(
            _WF_CANONICAL.replace(
                "run: make finalization-check\n",
                "  # whole-line comment\n\n        run: make finalization-check   \n",
            ),
            False, id="normalization_ok",
        ),
    ],
)
def test_workflow_contract(repo, workflow, expect_fail):
    repo.seed_cutover(complete=True)
    repo.write_workflow(workflow)
    errors = validate(repo.root, stage="cutover")
    if expect_fail:
        assert any(_CANONICAL_MISMATCH in e for e in errors)
    else:
        assert not any(_CANONICAL_MISMATCH in e for e in errors)

def test_forbidden_import_and_dependency(repo):
    repo.seed_final()
    p = repo.root / "src/legacy.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("import psychoanalyst_app\n", encoding="utf-8")
    assert any("imports forbidden module" in e for e in validate(repo.root, stage="final"))
    repo.write_pyproject(_PP_TARGET.replace('dependencies = ["fastapi"]', 'dependencies = ["fastapi", "trio"]'))
    assert any("forbidden dependency" in e for e in validate(repo.root, stage="final"))

@pytest.mark.parametrize(
    "makefile_patch,referenced",
    [
        pytest.param(
            "TARGET_SUPPORT_TESTS := tests/unit/test_validate_refactor_phase_6.py\n"
            "test-target:\n\tpytest tests/unit/jung/\n", False, id="unused_var",
        ),
        pytest.param("test-target:\n\techo $(TARGET_SUPPORT_TESTS)\n", False, id="echo_var"),
        pytest.param(
            "test-target:\n\techo pytest tests/unit/test_validate_refactor_phase_6.py\n",
            False, id="echo_pytest",
        ),
        pytest.param(
            "test-target:\n\tpytest tests/unit/test_validate_refactor_phase_6.py\n",
            True, id="direct_pytest",
        ),
        pytest.param(
            "test-target:\n\t" + _DOCKER_TEST_RUN + " pytest tests/unit/test_validate_refactor_phase_6.py\n",
            True, id="docker_pytest",
        ),
        pytest.param(
            "TARGET_SUPPORT_TESTS := tests/unit/test_validate_refactor_phase_6.py\n"
            "test-target:\n\t" + _DOCKER_TEST_RUN + " pytest $(TARGET_SUPPORT_TESTS)\n",
            True, id="var_expansion",
        ),
        pytest.param(
            "test-target:\n\t@-pytest tests/unit/test_validate_refactor_phase_6.py\n",
            False, id="at_prefix_pytest",
        ),
        pytest.param(
            "test-target:\n\tpytest -k SHELL tests/unit/test_validate_refactor_phase_6.py\n",
            True, id="shell_word_in_pytest",
        ),
    ],
)
def test_retained_test_reference_rules(repo, makefile_patch, referenced):
    repo.write_manifest(items=_retained_test_manifest())
    repo.write_runtime(target=True)
    repo.write_workflow(_WF_CANONICAL)
    base = (repo.root / "Makefile").read_text(encoding="utf-8")
    base = re.sub(r"test-target:\n\tpytest tests/\n", makefile_patch, base)
    (repo.root / "Makefile").write_text(base, encoding="utf-8")
    (repo.root / _RETAINED_TEST).parent.mkdir(parents=True, exist_ok=True)
    (repo.root / _RETAINED_TEST).write_text("#\n", encoding="utf-8")
    errors = validate(repo.root, stage="cutover")
    if referenced:
        assert not any("retained test not referenced" in e for e in errors)
    else:
        assert any("retained test not referenced" in e for e in errors)
    assert not any("forbidden control" in e for e in errors)
