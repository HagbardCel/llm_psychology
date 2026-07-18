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
_DOCKER_PY = "docker compose --profile test run --rm test python {script}{args}\n"
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
_PHASE6_DOCKER = (
    "\tdocker compose --profile test run --rm test python "
    "scripts/validate_refactor_phase_6.py --stage cutover\n"
)


def _target_gate(stage: str) -> str:
    return (
        "finalization-check-target: prepare-runtime-dirs\n"
        "\t$(MAKE) lint\n"
        "\t$(MAKE) validate-docs\n"
        "\t$(MAKE) test-target\n"
        "\t" + _DOCKER_PY.format(
            script="scripts/validate_refactor_phase_6.py", args=f" --stage {stage}"
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
    command: str, *, api_extra: str = "", base_extra: str = ""
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
                '[[items]]\npath = "gone/"\nkind = "filesystem"\naction = "delete"\n'
                "aggregate = true\nowner_pr = \"6D\"\nstatus = \"complete\"\n"
                'confidence = "confirmed"\nresponsibility = "x"\n\n'
                "[[items]]\npath = \".github/workflows/release-candidate-validation.yml\"\n"
                'kind = "workflow_edit"\naction = "edit"\nowner_pr = "6C"\n'
                'status = "complete"\nconfidence = "confirmed"\nresponsibility = "x"\n'
            ),
        )
        self.write_runtime(target=True, gates=_cutover_gate("final"))
        self.write_workflow(_WF_CANONICAL)
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
    "old,new,frag",
    [
        ("--stage cutover", "--stage pre-cutover", "recipe contract mismatch"),
        (
            "\t$(MAKE) probe-console-v1-deterministic\n",
            "",
            "recipe contract mismatch",
        ),
        (
            "\t$(MAKE) probe-console-v1-deterministic\n",
            "\t$(MAKE) probe-console-v1-deterministic\n\tbash -c 'make characterization-smoke'\n",
            "unsupported recipe",
        ),
        ("\t$(MAKE) test-target\n", "\t-$(MAKE) test-target\n", "unsupported recipe prefix"),
        ("\t$(MAKE) lint\n", "\t@-$(MAKE) lint\n", "unsupported recipe prefix"),
        (_PHASE6_DOCKER, "\t@-" + _PHASE6_DOCKER.lstrip(), "unsupported recipe prefix"),
        (
            "finalization-check: prepare-runtime-dirs",
            "finalization-check: characterization-smoke",
            "prerequisite contract mismatch",
        ),
        (
            " finalization-check finalization-check-target",
            " finalization-check-target",
            "must be phony",
        ),
        ("\t$(MAKE) lint\n", "\t+$(MAKE) lint\n", "unsupported recipe prefix"),
    ],
    ids=[
        "wrong_stage",
        "missing_recipe",
        "extra_recipe",
        "ignored_failure",
        "at_prefix_make",
        "at_prefix_docker",
        "wrong_prerequisite",
        "not_phony",
        "plus_prefix",
    ],
)
def test_gate_replacements(tmp_path, old, new, frag):
    r = RepoFixture(tmp_path)
    r.seed_cutover(complete=True)
    makefile = (tmp_path / "Makefile").read_text(encoding="utf-8")
    assert makefile.count(old) == 1
    (tmp_path / "Makefile").write_text(makefile.replace(old, new, 1), encoding="utf-8")
    assert any(frag in e for e in validate(tmp_path, stage="cutover"))


@pytest.mark.parametrize(
    "prefix,suffix,frag",
    [
        ("", "\nfinalization-check: prepare-runtime-dirs\n\t@true\n", "exactly one definition"),
        (
            "",
            "\nfinalization-check helper: prepare-runtime-dirs\n\t@true\n",
            "unsupported multi-target header",
        ),
        (".IGNORE:\n", "", ".IGNORE"),
        (".ONESHELL:\n", "", "forbidden control"),
        (".RECIPEPREFIX := >\n", "", "forbidden control"),
        ("GNUMAKEFLAGS += -i\n", "", "forbidden control"),
        ("MAKEFILES := extra.mk\n", "", "forbidden control MAKEFILES"),
        ("include extra.mk\n", "", "include directives are unsupported"),
        (
            "GATE := finalization-check\n$(GATE): characterization-smoke\n",
            "",
            "variable-expanded target headers are unsupported",
        ),
        (
            "HIDDEN := $(eval finalization-check: characterization-smoke)\n",
            "",
            "eval expressions are unsupported",
        ),
    ],
    ids=[
        "duplicate_definition",
        "forbidden_multi_target",
        "ignore_directive",
        "oneshell",
        "recipeprefix",
        "gnuflags",
        "makefiles",
        "include",
        "expanded_target",
        "eval_assignment",
    ],
)
def test_gate_additions(tmp_path, prefix, suffix, frag):
    r = RepoFixture(tmp_path)
    r.seed_cutover(complete=True)
    makefile = (tmp_path / "Makefile").read_text(encoding="utf-8")
    (tmp_path / "Makefile").write_text(prefix + makefile + suffix, encoding="utf-8")
    assert any(frag in e for e in validate(tmp_path, stage="cutover"))


def test_empty_gate_body_fails(tmp_path):
    r = RepoFixture(tmp_path)
    r.seed_cutover(complete=True)
    (tmp_path / "Makefile").write_text(
        replace_target_block(
            (tmp_path / "Makefile").read_text(encoding="utf-8"),
            "finalization-check",
            "finalization-check: prepare-runtime-dirs\n",
        ),
        encoding="utf-8",
    )
    assert any("recipe contract mismatch" in e for e in validate(tmp_path, stage="cutover"))


def test_cutover_rejects_target_gate_present(tmp_path):
    r = RepoFixture(tmp_path)
    r.seed_cutover(complete=True)
    (tmp_path / "Makefile").write_text(
        (tmp_path / "Makefile").read_text(encoding="utf-8") + _target_gate("cutover"),
        encoding="utf-8",
    )
    assert any("finalization-check-target must be absent" in e for e in validate(tmp_path, stage="cutover"))


def test_cutover_rejects_in_progress_workflow_edit(tmp_path):
    RepoFixture(tmp_path).seed_cutover(complete=False)
    assert any("required item must be complete" in e for e in validate(tmp_path, stage="cutover"))


def test_final_requires_completed_workflow_item(tmp_path):
    r = RepoFixture(tmp_path)
    r.seed_final()
    r.write_manifest(
        status="completed",
        items=(
            '[[items]]\npath = "gone/"\nkind = "filesystem"\naction = "delete"\n'
            "aggregate = true\nowner_pr = \"6D\"\nstatus = \"complete\"\n"
            'confidence = "confirmed"\nresponsibility = "x"\n'
        ),
    )
    assert any(
        "required complete item missing" in error
        for error in validate(tmp_path, stage="final")
    )


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
        ('schema_version = 1\nstatus = "active"\n\n[[items]]\npath = "/abs/path"\nkind = "filesystem"\naction = "delete"\nowner_pr = "6C"\nstatus = "planned"\nconfidence = "confirmed"\nresponsibility = "x"\n', "repository-relative"),
        ('schema_version = 1\nstatus = "active"\n\n[[items]]\npath = "a/../b"\nkind = "filesystem"\naction = "delete"\nowner_pr = "6C"\nstatus = "planned"\nconfidence = "confirmed"\nresponsibility = "x"\n', "must not contain"),
        ('schema_version = 1\nstatus = "active"\n\n[[items]]\npath = "dup"\nkind = "filesystem"\naction = "delete"\nowner_pr = "6C"\nstatus = "planned"\nconfidence = "confirmed"\nresponsibility = "x"\nreplacements = ["dup", "dup"]\n', "duplicate path entry"),
        ('schema_version = 1\nstatus = "active"\n\n[[items]]\npath = "x"\nkind = "filesystem"\naction = "port_then_delete"\nowner_pr = "6C"\nstatus = "planned"\nconfidence = "confirmed"\nresponsibility = "x"\nevidence = ["e", "e"]\n', "duplicate path entry"),
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
        '[[items]]\npath = "a//b"\nkind = "filesystem"\naction = "delete"\n'
        'owner_pr = "6C"\nstatus = "planned"\nconfidence = "confirmed"\nresponsibility = "x"\n\n'
        '[[items]]\npath = "a/b"\nkind = "filesystem"\naction = "delete"\n'
        'owner_pr = "6C"\nstatus = "planned"\nconfidence = "confirmed"\nresponsibility = "x"\n'
    )
    (tmp_path / "docs/refactor").mkdir(parents=True)
    (tmp_path / "docs/refactor/deletion-manifest.toml").write_text(body, encoding="utf-8")
    manifest, errors = parse_manifest(tmp_path)
    assert manifest is None
    assert any("duplicate kind/path" in error for error in errors)


@pytest.mark.parametrize(
    "stage,dockerfile,compose,ok,err",
    [
        ("pre-cutover", _DF_LEGACY, _CP_LEGACY, True, ""),
        ("cutover", _DF_TARGET, _compose_fixture("python -m psychoanalyst_app.server"), False, "docker-compose api command must select"),
        ("cutover", _DF_WRONG_CMD, _CP_TARGET, False, "CMD must select"),
        ("cutover", _DF_MALFORMED_CMD, _CP_TARGET, False, "malformed"),
        ("cutover", _DF_SHELL_CMD, _CP_TARGET, False, "Dockerfile CMD must use JSON exec form"),
        ("cutover", _DF_ENTRYPOINT, _CP_TARGET, False, "ENTRYPOINT is unsupported"),
        ("cutover", _DF_TARGET, _compose_fixture("jung-api", api_extra="    command: jung-api\n"), False, "must not declare local 'command'"),
        ("cutover", _DF_TARGET, _compose_fixture("jung-api").replace("target: development", "target: production"), False, "build.target"),
        ("cutover", _DF_TARGET, _compose_fixture("jung-api").replace("  command: jung-api\n", ""), False, "exactly one command"),
        ("cutover", _DF_NONSELECTED, _CP_TARGET, True, ""),
        ("cutover", _DF_TARGET, _compose_fixture("jung-api").replace("services:\n  api:", "services:\n  api:\n  api:"), False, "exactly one services.api"),
        ("cutover", _DF_DUP_STAGE, _CP_TARGET, False, "exactly one 'development' stage"),
    ],
    ids=[
        "legacy_ok",
        "compose_wrong_command",
        "docker_wrong_cmd",
        "docker_malformed_cmd",
        "docker_shell_cmd",
        "docker_entrypoint",
        "api_local_override",
        "unknown_build_target",
        "missing_command",
        "nonselected_stage_ok",
        "duplicate_api",
        "duplicate_docker_stage",
    ],
)
def test_compose_runtime(tmp_path, stage, dockerfile, compose, ok, err):
    r = RepoFixture(tmp_path)
    (r.seed_cutover(complete=True) if stage == "cutover" else r.seed_pre())
    r.write_runtime(target=stage != "pre-cutover", dockerfile=dockerfile, compose=compose)
    errors = validate(tmp_path, stage=stage)
    assert (errors == []) if ok else any(err in e for e in errors)


@pytest.mark.parametrize(
    "compose,frag",
    [
        (_compose_fixture("jung-api").replace("services:\n", "services: # duplicate\nservices:\n", 1), "exactly one services"),
        (_compose_fixture("jung-api").replace("x-api-base:", "x-api-base: # duplicate\nx-api-base:", 1), "exactly one x-api-base"),
        ('"services":\n  api:\n    image: x\n' + _compose_fixture("jung-api").split("services:", 1)[1], "unsupported mapping syntax"),
        (_compose_fixture("jung-api", api_extra='    "command": jung-api\n'), "unsupported mapping syntax"),
        ("? services\n" + _compose_fixture("jung-api"), "unsupported mapping syntax"),
        (_compose_fixture("jung-api").replace("<<: *api-base", "<<: *other"), "merge must be <<: *api-base"),
        (_compose_fixture("jung-api", api_extra="    profiles:\n      - dev\n"), "must not declare local 'profiles'"),
        (_compose_fixture("jung-api", api_extra="    deploy:\n      replicas: 1\n"), "must not declare local 'deploy'"),
        (_compose_fixture("jung-api", api_extra="    scale: 2\n"), "must not declare local 'scale'"),
        (_compose_fixture("jung-api", base_extra="  entrypoint: echo\n"), "x-api-base must not declare 'entrypoint'"),
        (_compose_fixture("jung-api", base_extra="  profiles:\n    - dev\n"), "x-api-base must not declare 'profiles'"),
    ],
    ids=[
        "dup_services_comment",
        "dup_api_base_comment",
        "quoted_services",
        "quoted_command",
        "explicit_key",
        "wrong_merge",
        "profiles_local",
        "deploy_local",
        "scale_local",
        "entrypoint_base",
        "profiles_base",
    ],
)
def test_compose_syntax_categories(tmp_path, compose, frag):
    r = RepoFixture(tmp_path)
    r.seed_cutover(complete=True)
    r.write_runtime(target=True, compose=compose)
    assert any(frag in e for e in validate(tmp_path, stage="cutover"))


@pytest.mark.parametrize(
    "workflow,expect_fail",
    [
        (_WF_CANONICAL.replace("make finalization-check", "make other-gate"), True),
        (
            _WF_CANONICAL.replace(
                "jobs:\n",
                "jobs:\n  extra:\n    runs-on: ubuntu-latest\n",
            ),
            True,
        ),
        (
            _WF_CANONICAL.replace(
                "run: make finalization-check\n",
                "  # whole-line comment\n\n        run: make finalization-check   \n",
            ),
            False,
        ),
    ],
    ids=["altered_gate", "extra_job", "normalization_ok"],
)
def test_workflow_contract(tmp_path, workflow, expect_fail):
    r = RepoFixture(tmp_path)
    r.seed_cutover(complete=True)
    r.write_workflow(workflow)
    errors = validate(tmp_path, stage="cutover")
    if expect_fail:
        assert any(_CANONICAL_MISMATCH in e for e in errors)
    else:
        assert not any(_CANONICAL_MISMATCH in e for e in errors)


def test_recipe_shell_word_allowed_for_retained_test(tmp_path):
    r = RepoFixture(tmp_path)
    r.write_manifest(items=_retained_test_manifest())
    r.write_runtime(target=True)
    r.write_workflow(_WF_CANONICAL)
    base = (tmp_path / "Makefile").read_text(encoding="utf-8")
    base = re.sub(
        r"test-target:\n\tpytest tests/\n",
        "test-target:\n\tpytest -k SHELL tests/unit/test_validate_refactor_phase_6.py\n",
        base,
    )
    (tmp_path / "Makefile").write_text(base, encoding="utf-8")
    (tmp_path / _RETAINED_TEST).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / _RETAINED_TEST).write_text("#\n", encoding="utf-8")
    errors = validate(tmp_path, stage="cutover")
    assert not any("forbidden control" in e for e in errors)
    assert not any("retained test not referenced" in e for e in errors)


def test_forbidden_import_and_dependency(tmp_path):
    r = RepoFixture(tmp_path)
    r.seed_final()
    p = tmp_path / "src/legacy.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("import psychoanalyst_app\n", encoding="utf-8")
    assert any("imports forbidden module" in e for e in validate(tmp_path, stage="final"))
    r.write_pyproject(_PP_TARGET.replace('dependencies = ["fastapi"]', 'dependencies = ["fastapi", "trio"]'))
    assert any("forbidden dependency" in e for e in validate(tmp_path, stage="final"))


@pytest.mark.parametrize(
    "makefile_patch,should_pass",
    [
        ("TARGET_SUPPORT_TESTS := tests/unit/test_validate_refactor_phase_6.py\n" "test-target:\n\tpytest tests/unit/jung/\n", False),
        ("test-target:\n\techo $(TARGET_SUPPORT_TESTS)\n", False),
        ("test-target:\n\techo pytest tests/unit/test_validate_refactor_phase_6.py\n", False),
        ("test-target:\n\tpytest tests/unit/test_validate_refactor_phase_6.py\n", True),
        ("test-target:\n\tdocker compose --profile test run --rm test pytest tests/unit/test_validate_refactor_phase_6.py\n", True),
        ("TARGET_SUPPORT_TESTS := tests/unit/test_validate_refactor_phase_6.py\n" "test-target:\n\tdocker compose --profile test run --rm test pytest $(TARGET_SUPPORT_TESTS)\n", True),
        ("test-target:\n\t@-pytest tests/unit/test_validate_refactor_phase_6.py\n", False),
    ],
    ids=["unused_var", "echo_var", "echo_pytest", "direct_pytest", "docker_pytest", "var_expansion", "at_prefix_pytest"],
)
def test_retained_test_reference_rules(tmp_path, makefile_patch, should_pass):
    r = RepoFixture(tmp_path)
    r.write_manifest(items=_retained_test_manifest())
    r.write_runtime(target=True)
    r.write_workflow(_WF_CANONICAL)
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
