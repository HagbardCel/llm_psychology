# Phase 6 (Optional) — Packaging + Dev Experience Polish (Detailed Implementation Plan)

Source: `docs/assessments/project/CODEBASE_ASSESSMENT_2025-12-16.md` (Phase 6 — Packaging + Dev Experience Polish)

## Objective

Remove `sys.path` hacks and make backend execution uniform, predictable, and tool-friendly by:
- turning the backend into an installable Python package,
- standardizing entry points via `python -m ...` (and optional console scripts),
- aligning the supported Python version across Docker/CI/tooling/docs, and
- moving dev-only tooling out of production dependencies.

This phase should be a **mechanical refactor**: it should not change product behavior, workflow semantics, HTTP/WS contracts, or data persistence.

## Alignment With `docs/design-principles.md` (Why This Phase Fits)

This phase reinforces (and must not violate) the project invariants:
- **Trio-first structured concurrency** remains unchanged; we are changing import/package mechanics, not runtime architecture.
- **Clean boundaries** (gateway/orchestration/agents/services) are preserved; namespacing should make them clearer, not blur them.
- **Stable contracts** (DTOs + schemas, WS protocol) remain stable; packaging work must not “accidentally” rename fields or change payload shapes.
- **DI composition root** remains the container; packaging must not introduce new module-level singletons.

## Non-goals (Explicitly Out of Scope)

- Any change to the HTTP API contract (Phase 1).
- Any change to workflow navigation semantics (Phase 2).
- Any DI redesign beyond import/entrypoint adjustments (Phase 3).
- Any streaming or module-splitting work (Phases 4–5).
- Any “dependency modernization” larger than separating dev vs prod requirements (e.g., migrating fully to PEP 621 dependency management).

## Phase 6 Scope (What We Touch)

Backend packaging and execution surfaces:
- `src/` layout and Python module imports
- execution entry points (`src/main.py`, `src/server.py`, `src/e2e_server.py`)
- scripts that currently rely on `sys.path` injection (`scripts/generate_schemas.py`, `scripts/validate_schemas.py`, selected test runners)
- build/infra runners (`Makefile`, `Dockerfile`, CI workflows)
- requirements split (`requirements.in`, `requirements-dev.in`, and their locked `.txt` outputs)
- documentation updates where execution commands and version targets are mentioned

## Key Decisions (Lock These Early)

### D6.1 Package name and distribution name

**Decision (recommended)**:
- Distribution (pip) name: `psychoanalyst-app` (hyphenated, user-facing)
- Import package name: `psychoanalyst_app` (underscored, Pythonic)

Rationale:
- Matches the repository identity without introducing an ambiguous generic top-level namespace like `models`/`services`.
- Avoids collisions with common package names and improves stack traces/import clarity.

### D6.2 Migration strategy: incremental vs “big bang”

Choose one explicitly:

**Option A (recommended): incremental, compatibility-first**
1. Introduce the package skeleton under `src/psychoanalyst_app/`.
2. Add new `python -m` entry points that call into existing code (temporary adapters).
3. Move subpackages (`models/`, `services/`, …) into the package one domain at a time, updating imports per PR.
4. Remove adapters after the tree is fully namespaced.

Pros: smaller PRs, easier review, lower rollback risk.  
Cons: temporary duplicate paths/adapters.

**Option B: single PR “big bang”**
- Move the entire backend tree under `src/psychoanalyst_app/` and update all imports in one go.

Pros: shortest time in hybrid state.  
Cons: large blast radius; harder to review/debug.

This plan proceeds with **Option A** unless there is strong preference for Option B.

### D6.3 Supported Python version

**Decision (recommended)**: standardize on **Python 3.11**.

Rationale:
- Docker base image and CI already use 3.11.
- Reduces “it works in Docker but not locally” drift.
- Keeps typing/tooling consistent (Black/Ruff/mypy targets).

### D6.4 Runtime assets: style packs and other non-`.py` files

**Decision (recommended)**:
- Treat `psychoanalyst_app/styles/**` prompt files (`*.txt`, `knowledge.md`) as **package data**.
- Load them via `importlib.resources` by default, with an optional override path for local development.

Rationale:
- Packaging should not break style prompts/knowledge loading.
- Avoid hardcoding `src/styles` paths (previously embedded in `StyleService`).

Current status (codebase):
- Implemented via `importlib.resources`, with `STYLES_DIR` overrides supported.
- Package data includes `styles/`, `prompts/`, and `data/domain_knowledge/`.

## Implementation Plan

### P6.1 Add packaging metadata and installable package skeleton

Deliverables:
- A package root: `src/psychoanalyst_app/` with at minimum:
  - `__init__.py` (package version metadata optional)
  - `__main__.py` (dispatch entry point for `python -m psychoanalyst_app`)
- Packaging metadata in `pyproject.toml` (or `setup.cfg`) that:
  - defines the distribution name
  - sets `python_requires >= 3.11`
  - discovers packages under `src/`
  - includes package data for style packs

Acceptance:
- `python -m pip install -e .` succeeds locally.
- `python -c "import psychoanalyst_app"` succeeds without `sys.path` manipulation.

Status (codebase):
- Done. `src/psychoanalyst_app/` and `__main__.py` exist, `pyproject.toml` defines
  `psychoanalyst-app` with `requires-python >= 3.11`, and package data includes styles,
  prompts, and domain knowledge.

### P6.2 Introduce uniform module entry points (`python -m ...`)

Target behaviors:
- Standalone terminal UI: `python -m psychoanalyst_app`
- Server (HTTP + WS): `python -m psychoanalyst_app.server`
- Deterministic E2E server: `python -m psychoanalyst_app.e2e_server`

Implementation notes:
- Initially, these entry points may delegate to the existing implementations (adapters), but the *user-facing execution commands* should stabilize early.
- If useful, add console scripts (optional) as stable developer ergonomics:
  - `psychoanalyst-app` → `psychoanalyst_app.__main__:cli`
  - `psychoanalyst-server` → `psychoanalyst_app.server:cli`
  - `psychoanalyst-e2e-server` → `psychoanalyst_app.e2e_server:cli`

Acceptance:
- Running each entry point works from any working directory (after install).
- No entry point relies on `sys.path.insert(...)`.

Status (codebase):
- Done. Console scripts and `python -m ...` entry points exist.

### P6.3 Migrate backend modules under the package namespace

End-state layout (illustrative):
- `src/psychoanalyst_app/agents/`
- `src/psychoanalyst_app/api/`
- `src/psychoanalyst_app/container/`
- `src/psychoanalyst_app/models/`
- `src/psychoanalyst_app/orchestration/`
- `src/psychoanalyst_app/services/`
- `src/psychoanalyst_app/utils/`
- `src/psychoanalyst_app/styles/`
- `src/psychoanalyst_app/ui/`

Mechanics:
- Move one subpackage per PR (Option A), updating imports from:
  - `from models...` → `from psychoanalyst_app.models...`
  - `from services...` → `from psychoanalyst_app.services...`
  - etc.
- Keep the layer boundaries from `docs/design-principles.md` intact; do not “fix” unrelated architecture while moving files.

Acceptance:
- No remaining imports depend on `sys.path` hacks.
- Import graph remains acyclic at the layer level (gateway → orchestration → agents → services).

Status (codebase):
- Done. All backend modules live under `src/psychoanalyst_app/`.

### P6.4 Remove `sys.path` injection from runtime and tooling

Remove (or replace) `sys.path.insert(...)` in:
- runtime entry points under `src/psychoanalyst_app/` (`main.py`, `server.py`, `e2e_server.py`)
- scripts that generate/validate schemas:
  - `scripts/generate_schemas.py`
  - `scripts/validate_schemas.py`
- test bootstrap code (`tests/conftest.py`) and standalone runners under `tests/`

Replacement rule:
- Scripts import the installed package (preferred) rather than mutating `sys.path`.

Acceptance:
- `rg "sys.path.insert" src scripts tests` returns zero occurrences (or only explicitly-deprecated transitional adapters, if Option A is used).

Status (codebase):
- Done. No `sys.path.insert(...)` remains; schema scripts delegate to packaged modules.
- Decision: keep `PYTHONPATH=src` for local host runs (Makefile/docs).

### P6.5 Fix hardcoded “src-relative” runtime paths (styles, prompts, etc.)

Primary target:
- `src/psychoanalyst_app/services/style_service.py` should avoid hardcoded `src/...` paths.

End-state behavior:
- Default style pack location resolves via `importlib.resources` within `psychoanalyst_app.styles`.
- Allow overriding via configuration (recommended new setting such as `STYLES_DIR`) for local/dev experimentation.

Acceptance:
- Style packs load correctly both:
  - from an editable install (`pip install -e .`), and
  - from a non-editable install (Docker/CI simulation).

Status (codebase):
- Done. `StyleService` uses `importlib.resources`, and `STYLES_DIR` is supported.

### P6.6 Align Python version targets across tooling and docs

Update:
- `pyproject.toml`
  - Black target: `py311`
  - Ruff target: `py311`
  - mypy `python_version`: `3.11`
- Docker/runtime docs and any pinned Python versions (ensure they all agree)
- Any text in docs that says “3.10” or “3.11+” ambiguously (pick one consistent statement)

Acceptance:
- There is exactly one supported Python version range stated across:
  - Docker base image
  - CI setup-python
  - `pyproject.toml` tooling configuration
  - `docs/` setup/run instructions

### P6.7 Move dev-only tooling out of production requirements

Current status (codebase):
- `ruff` already lives in `requirements-dev.in` and is not in `requirements.in`.

Plan:
- Keep dev-only tools in `requirements-dev.in`, and keep `requirements.in` runtime-only.
- Regenerate locked files via the existing `uv pip compile` flow.

Acceptance:
- `requirements.txt` contains only runtime dependencies.
- Docker production stage installs only `requirements.txt` (no linters/type checkers).

Status (codebase):
- Done.

### P6.8 Update Makefile/Docker/CI to use the package entry points

Update the primary run paths:
- `Makefile`:
  - run targets already use `python -m psychoanalyst_app` / `.server` / `.e2e_server`
  - `dev-install` builds Docker images; editable installs happen in the Dockerfile
- `Dockerfile`:
  - already installs the package and runs `python -m psychoanalyst_app.server`
- `.github/workflows/type-safety.yml` (and any other workflows):
  - ensure the package is installable before schema/test steps

Acceptance:
- Local: `make run` works after `make dev-install`.
- Docker: image runs without relying on copying `src/` as an import path hack.
- CI: schema generation and tests import through the package namespace (no `sys.path` shims).

Status (codebase):
- Done. Decision: keep `PYTHONPATH=src` for host runs.

### P6.9 Documentation polish (execution + version target)

Update developer-facing docs so they match the new execution story and Python version target:
- `docs/QUICKSTART.md`:
  - update the “run locally” command(s) to `python -m ...`
  - remove stale references to `unified_server.py`
  - align env var naming with runtime truth (`GOOGLE_API_KEY` vs older doc names)
- `docs/TYPE_SYSTEM.md`:
  - ensure schema generation instructions still work (and reflect package imports)
- `docs/design-principles.md` updates (tracked explicitly below)

Acceptance:
- A new contributor can follow docs to: install deps, run the backend, and regenerate schemas/types without guessing import paths or Python versions.

Status (codebase):
- Done in current docs. `unified_server.py` references removed; `PYTHONPATH=src` host guidance retained.

## Suggested PR Breakdown (Minimize Risk)

Most steps are already complete. If additional work is needed, focus on:
1) **Validation pass** — ensure schemas/types generation and entry points still match docs.

## Validation Checklist

Packaging/execution:
- `python -m pip install -e .`
- `python -m psychoanalyst_app --help` (if a CLI dispatcher is implemented) or `python -m psychoanalyst_app` (terminal UI)
- `python -m psychoanalyst_app.server` starts the server

Repo hygiene:
- `rg "sys.path.insert" src scripts tests` is empty (or only transitional adapters that are explicitly scheduled for removal)
- `ruff check .` and `mypy` targets run on moved modules

Behavioral (guardrails):
- HTTP DTO schemas still generate: `make generate-schemas` and `make validate-schemas`
- WebSocket protocol contract tests still pass (no message shape drift)

## DESIGN_CHOICES Updates Required After Implementation

Current status (codebase):
- `docs/design-principles.md` already reflects package paths, Python 3.11, canonical
  entry points, and `importlib.resources` style pack loading with `STYLES_DIR`.

## Exit Criteria (Phase 6 is Done When…)

- The backend is installable and runnable without any `sys.path` hacks.
- All primary run paths (local, Docker, CI) use `python -m ...` entry points.
- Tooling targets and docs consistently state Python 3.11 support.
- Production requirements do not include dev-only tools (at minimum: `ruff` is removed from `requirements.in`).
