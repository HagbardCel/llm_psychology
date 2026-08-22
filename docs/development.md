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

- **Session LLM gateway:** `LLM_BASE_URL`, optional `LLM_API_KEY`, `MODEL_NAME`
- **Optional supervisor LLM:** `JUNG_SUPERVISOR_LLM_BASE_URL`, `JUNG_SUPERVISOR_MODEL_NAME`, `JUNG_SUPERVISOR_LLM_API_KEY`, `JUNG_SUPERVISOR_LLM_EXTRA_BODY_JSON`, `JUNG_SUPERVISOR_LLM_DEFAULT_HEADERS_JSON` — omitted values inherit session settings; an explicitly empty supervisor API key clears the inherited credential (it does not mean a different SDK auth mode); `{}` clears inherited role-level headers/extra body while task-specific `extra_body` in `JUNG_LLM_TASK_CONFIG_JSON` still applies
- **Data directory:** `JUNG_DATA_DIR` (SQLite at `{JUNG_DATA_DIR}/jung.db`; default `./data`)
- **Standalone API bind:** `JUNG_API_HOST`, `JUNG_API_PORT`, `JUNG_API_ALLOW_REMOTE_BIND` — parsed as part of shared `JungSettings` but used for socket binding only by standalone `jung-api`; the managed `jung` listener always uses an ephemeral IPv4 loopback port
- **API logging / CORS:** `JUNG_API_LOG_LEVEL`, `JUNG_API_ALLOWED_ORIGINS` — still affect the managed runtime (Uvicorn logging and `create_app()` middleware respectively)
- **Diagnostics:** optional `JUNG_DEBUG_RUN_DIR` (see [safety-and-data.md](safety-and-data.md))

One-model setup (default):

```dotenv
LLM_BASE_URL=http://127.0.0.1:8080/v1
MODEL_NAME=local-model
LLM_API_KEY=
```

Optional stronger supervisor:

```dotenv
LLM_BASE_URL=http://127.0.0.1:8080/v1
MODEL_NAME=session-model

JUNG_SUPERVISOR_LLM_BASE_URL=http://127.0.0.1:8081/v1
JUNG_SUPERVISOR_MODEL_NAME=stronger-model
JUNG_SUPERVISOR_LLM_API_KEY=
```

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
make eval-report EVAL_REPORT_ARGS="--concurrency 4"
make eval-report EVAL_REPORT_ARGS="--workload screen --concurrency 4"
make simulate-local-llm \
  SIM_ARGS="--scenario anxiety_sleep --sessions 2 --turns-per-session 4"
make simulate-local-llm \
  SIM_ARGS="--scenario social_anxiety --sessions 2 --turns-per-session 4 \
  --style jung"
```

Style-path comparison (ecological longitudinal evidence; assessment is never
bypassed):

```bash
make simulate-local-llm \
  SIM_ARGS="--scenario social_anxiety --style cbt --sessions 4 --turns-per-session 8"
make simulate-local-llm \
  SIM_ARGS="--scenario social_anxiety --style jung --sessions 4 --turns-per-session 8"
make simulate-local-llm \
  SIM_ARGS="--scenario social_anxiety --style freud --sessions 4 --turns-per-session 8"
```

`simulate-local-llm` uses normal Jung production LLM settings (`LLM_BASE_URL`,
`MODEL_NAME`, `LLM_API_KEY`, `JUNG_SUPERVISOR_*`, …), not `LOCAL_LLM_SMOKE_*`.
The latter remain exclusive to the processor-level smoke/eval tooling. Pass
simulation flags through `SIM_ARGS`; extra tokens after `make` are Make
options. Each invocation writes an isolated evidence bundle under
`logs/simulations/run-<UTC>-<suffix>/`. `--output-dir`, when provided, is the
exact journey directory. Optional flags include `--style` (`auto` or a packaged
style id), `--patient-timeout`, `--workflow-timeout`, `--overall-timeout`,
`--patient-history-chars`, `--patient-base-url`, `--patient-model`, and
`--patient-extra-body-json`. Do not parallelize turns inside one journey. Cite
simulation **run IDs** in PR notes rather than committing artifact trees. Closed
Phase 8C experiment: [`evals/phase8c/OUTCOME.md`](../evals/phase8c/OUTCOME.md).

See [`tests/README.md`](../tests/README.md) and [`evals/README.md`](../evals/README.md)
for hard-versus-diagnostic semantics.

## Evaluating a new local backend

Jung talks only to an OpenAI-compatible endpoint. Processor-level smoke, hard
evals, and `eval-report` use `LOCAL_LLM_SMOKE_*`. Interactive `make run` uses
`LLM_BASE_URL` / `MODEL_NAME`. Do not mix the namespaces.

Use the same standard `eval-report` concurrency for every backend candidate;
do **not** tune concurrency as part of routine backend comparison.

1. Start the candidate OpenAI-compatible backend (outside Jung).
2. Run provider compatibility smoke if needed (`make smoke-local-llm`).
3. Run the fixed screen workload once:

   ```bash
   make eval-report EVAL_REPORT_ARGS="--workload screen --concurrency <standard>"
   ```

4. Repeat with the same workload and concurrency for the comparison backend.
5. Compare wall time, failures, request count, and reported token usage.
6. Run one representative confirmation only if the screen result would change
   the selected backend.
7. Stop.

Backend launch tuning belongs outside Jung. Request-specific extensions use
`LOCAL_LLM_SMOKE_EXTRA_BODY` / production `extra_body` — not backend-specific
Python classes.

Shared eval/smoke exports:

```bash
export LOCAL_LLM_SMOKE_BASE_URL=http://127.0.0.1:8080/v1
export LOCAL_LLM_SMOKE_MODEL=<requested-model-id>
export LOCAL_LLM_SMOKE_STRUCTURED_MODE=json_schema
export LOCAL_LLM_SMOKE_REQUEST_TIMEOUT=600
export LOCAL_LLM_SMOKE_EXTRA_BODY='{"chat_template_kwargs":{"enable_thinking":true},"top_p":0.95,"top_k":20}'
```

Historical Phase 8B measurements are archived under
[`evals/phase8b/README.md`](../evals/phase8b/README.md).

### Diagnostics

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
