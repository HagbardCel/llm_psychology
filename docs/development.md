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

Run the API and console in separate terminals (`make run-api` is blocking):

**Terminal 1:**

```bash
make run-api
```

**Terminal 2:**

```bash
make run-console
```

For a disposable manual-test profile, point the API at a separate data
directory (no special target or env file required):

```bash
JUNG_DATA_DIR=./data/manual-test make run-api
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
- **Data directory:** `JUNG_DATA_DIR` (SQLite at `{JUNG_DATA_DIR}/jung.db`; default `./data`)
- **API bind / CORS:** `JUNG_API_HOST`, `JUNG_API_PORT`, `JUNG_API_ALLOWED_ORIGINS`, `JUNG_API_ALLOW_REMOTE_BIND`
- **Diagnostics:** optional `JUNG_DEBUG_RUN_DIR` (see [safety-and-data.md](safety-and-data.md))

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
- Opt-in debug bundles via `JUNG_DEBUG_RUN_DIR` (`manifest.json`, `trace.jsonl`,
  `state.json`, `transcript.md`, conditional `failure_summary.md`) — see
  [safety-and-data.md](safety-and-data.md)
- Export a SQLite snapshot into an existing run directory:

```bash
jung-debug-export --run-dir "$JUNG_DEBUG_RUN_DIR" --database data/jung.db
```

- Database reset and data erasure — see [safety-and-data.md](safety-and-data.md)
