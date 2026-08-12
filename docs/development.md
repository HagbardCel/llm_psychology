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
docs/     documentation
data/     local SQLite data
logs/     generated diagnostics
```

## Prerequisites

- Python ≥3.11
- [uv](https://docs.astral.sh/uv/) for package management
- `make`
- An OpenAI-compatible local model server (llama.cpp, LM Studio, Ollama, …) when exercising real LLM paths

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

Leave `.env.example` unchanged; adjust the copied `.env` as needed.

## Normal local use

```bash
make run
```

Native equivalent:

```bash
uv run --locked jung
```

For a disposable manual-test profile, point the runtime at a separate data
directory (no special target or env file required):

```bash
JUNG_DATA_DIR=./data/manual-test make run
```

## Separate server/client development

Use these when developing or debugging the API or console independently:

**Terminal 1:**

```bash
make run-api
```

**Terminal 2:**

```bash
make run-console
```

Native equivalents:

```bash
uv run --locked jung-api
uv run --locked jung-console --api-url http://127.0.0.1:8000
```

## Configuration guidance

Do not treat this page as an exhaustive environment-variable catalogue. Use
[`.env.example`](../.env.example) as the supported example reference.
`jung.config.load_settings()` / [`src/jung/config.py`](../src/jung/config.py) is
the sole production environment-backed settings owner.

Common groups:

- **LLM gateway:** `LLM_BASE_URL`, optional `LLM_API_KEY`, `MODEL_NAME`
- **Data directory:** `JUNG_DATA_DIR` (SQLite at `{JUNG_DATA_DIR}/jung.db`; default `./data`)
- **Standalone API bind:** `JUNG_API_HOST`, `JUNG_API_PORT`, `JUNG_API_ALLOW_REMOTE_BIND` — parsed as part of shared `JungSettings` but used for socket binding only by standalone `jung-api`; the managed `jung` listener always uses an ephemeral IPv4 loopback port
- **API logging / CORS:** `JUNG_API_LOG_LEVEL`, `JUNG_API_ALLOWED_ORIGINS` — still affect the managed runtime (Uvicorn logging and `create_app()` middleware respectively)
- **Diagnostics:** optional `JUNG_DEBUG_RUN_DIR` (see [safety-and-data.md](safety-and-data.md))

## Run commands

```bash
make sync
make run          # normal local application
make run-api      # standalone API
make run-console  # standalone console (requires --api-url when invoked via uv)
```

## Tests and release gate

Deterministic gate (native; no live LLM):

```bash
make test                 # unit + integration (not real_llm)
make test-unit
make test-integration
make probe-console        # deterministic console E2E once; not part of make test
make lint
make docs-links
make check                # format-check + lint + docs-links + test + probe-console
```

Opt-in real-model surfaces (not part of `make test` or `make check`):

```bash
make smoke-local-llm
make evals
make eval-report
```

See [`tests/README.md`](../tests/README.md) and [`evals/README.md`](../evals/README.md)
for suite ownership and hard-versus-diagnostic semantics.

## Diagnostics

- Ordinary logs under the process logger / `./logs` as configured
- Opt-in diagnostic capture via `JUNG_DEBUG_RUN_DIR` — see
  [safety-and-data.md](safety-and-data.md)

```bash
JUNG_DEBUG_RUN_DIR=./logs/debug-runs/example make run
```

Standalone API equivalent:

```bash
JUNG_DEBUG_RUN_DIR=./logs/debug-runs/example make run-api
```

After shutdown, inspect primary evidence:

```bash
sqlite3 ./logs/debug-runs/example/db_snapshot.sqlite
```

- Database reset and data erasure — see [safety-and-data.md](safety-and-data.md)
