---
owner: engineering
status: active
last_reviewed: 2026-08-08
review_cycle_days: 30
source_of_truth_for: Developer onboarding, workflow commands, and configuration guidance
---

# Development

> This page is the primary workflow guide. Run `make help` for common commands;
> inspect the `Makefile` for the exhaustive executable command inventory.
> Package layout inside `src/jung/` is documented in
> [Architecture](architecture.md). Test-suite ownership lives in
> [`tests/README.md`](../tests/README.md). Real-model evaluation philosophy
> lives in [`evals/README.md`](../evals/README.md).

## Repository map

```text
src/      runtime
tests/    deterministic tests
evals/    opt-in real-model evaluations
scripts/  repository tooling
docs/     canonical documentation
data/     local SQLite data
logs/     generated diagnostics
```

## Prerequisites

- Python ≥3.11
- [uv](https://docs.astral.sh/uv/) for package management
- `make`
- An OpenAI-compatible local model server (llama.cpp, LM Studio, Ollama, …) when exercising real LLM paths
- Docker only when using Compose packaging or `make finalization-check` (which includes `smoke-compose-api`)

## Native setup

```bash
cp .env.example .env
uv sync --locked
```

Edit `.env` to set (port depends on the model server):

```dotenv
LLM_BASE_URL=http://127.0.0.1:8080/v1
MODEL_NAME=<your-server-model-name>
```

`.env.example` defaults to `host.docker.internal` for Compose-friendly values.
Leave the template unchanged; adjust the copied `.env` for the execution mode
you are using. Ordinary Compose loads `${ENV_FILE:-.env}` into the API
container (`smoke-compose-api` may point `ENV_FILE` at `.env.example`).

Run the API and console in separate terminals (`make run-api` is blocking):

**Terminal 1:**

```bash
make run-api
```

**Terminal 2:**

```bash
make run-console
```

## Configuration guidance

Do not treat this page as an exhaustive environment-variable catalogue. Explain
important groups here and use [`.env.example`](../.env.example) as the
supported example reference. Runtime settings code remains executable truth for
parsing and defaults:

- [`src/jung/config.py`](../src/jung/config.py) — application settings
- [`src/jung/api/settings.py`](../src/jung/api/settings.py) — API host/bind/CORS and related defaults

Common groups:

- **LLM gateway:** `LLM_BASE_URL`, optional `LLM_API_KEY`, `MODEL_NAME`
- **Data directory:** `JUNG_DATA_DIR` (SQLite at `{JUNG_DATA_DIR}/jung.db`)
- **API bind / CORS:** `JUNG_API_HOST`, `JUNG_API_PORT`, `JUNG_API_ALLOWED_ORIGINS`, `JUNG_API_ALLOW_REMOTE_BIND`
- **Diagnostics:** optional `JUNG_DEBUG_RUN_DIR` (see [safety-and-data.md](safety-and-data.md))

### Native ↔ Docker LLM URL

When switching the API itself from native to Docker while the model server
remains on the host, set `LLM_BASE_URL` back to
`http://host.docker.internal:<port>/v1`. Ordinary Compose loads
`${ENV_FILE:-.env}` into the container; `127.0.0.1` inside the container is the
container itself, not the host model server.

## Run commands

```bash
make sync
```

**Terminal 1:** `make run-api`

**Terminal 2:** `make run-console`

Native equivalents:

**Terminal 1:**

```bash
uv run --locked jung-api
```

**Terminal 2:**

```bash
uv run --locked jung-console --api-url http://127.0.0.1:8000
```

## Tests and release gate

```bash
make test                 # unit + integration (not real_llm)
make test-unit
make test-integration
make probe-console        # deterministic console E2E once; not part of make test
make lint
make validate-docs
make finalization-check   # includes smoke-compose-api → requires Docker
```

Opt-in real-model surfaces (not part of `make test` or `make finalization-check`):

```bash
make smoke-local-llm
make evals
make eval-report
```

See [`tests/README.md`](../tests/README.md) and [`evals/README.md`](../evals/README.md)
for suite ownership and hard-versus-diagnostic semantics.

## Optional Docker workflow

- `make docker-build` — build the packaged API image
- `make docker-up` — run the packaged API in the foreground
- `make ui-console` — start the packaged API detached and launch `jung-console`
- `make ui-console-test` — isolated manual-test environment
- `make docker-shell` — shell into an already running API container

Docker is packaging and smoke infrastructure, not a requirement for day-to-day
native development.

## Diagnostics

- Ordinary logs under the process logger / `./logs` as configured
- Opt-in correlated debug traces via `JUNG_DEBUG_RUN_DIR` — see [safety-and-data.md](safety-and-data.md)
- Database reset and data erasure — see [safety-and-data.md](safety-and-data.md)
