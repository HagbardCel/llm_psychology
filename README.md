# Local Therapist Tool

Local-laptop therapy workflow research tool backed by an asyncio FastAPI
`/api/v1` service (`jung-api`), SQLite persistence, and the maintained
`jung-console` client.

## Quick Start

1. Start an OpenAI-compatible local model server such as llama.cpp, LM Studio,
   or Ollama on the host.
2. Copy `.env.example` to `.env` and set `LLM_BASE_URL` and `MODEL_NAME`.
3. Install and run natively:

```bash
uv sync --locked
make run-api
make run-console
```

Optional packaged Docker path:

```bash
make docker-build
make docker-up
```

Or start the supported client against a packaged API with `make ui-console`.

Manual user testing reuses the single parameterized `api` service under an
isolated Compose project and data directory (`make ui-console-test`). No
duplicate Compose service is defined.

## Maintainer Checks

```bash
make finalization-check
```

For faster partial feedback while iterating:

```bash
make lint
make validate-docs
make test
make probe-console
```

See [docs/README.md](docs/README.md) for architecture, contracts, and local
maintenance guidance. Start with the target architecture, API v1 contract, and
workflow specification.

## Local Database

The target runtime stores SQLite under `JUNG_DATA_DIR` as `jung.db`
(Compose uses `data/local` and `data/usertest`). Databases with incompatible
schemas are recreated rather than migrated. Stop the application. If the
contents should be retained, first archive the SQLite database together with
any existing `-wal` and `-shm` sibling files; then delete the original files or
use a fresh data directory.

## Naming

The user-facing product language is **therapist**. The supported runtime package
is `jung`. Legacy import namespaces, runtime entry points, and compatibility
aliases have been removed.
