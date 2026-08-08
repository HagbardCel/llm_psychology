# Local Therapist Tool

Local-laptop therapy workflow research tool backed by an asyncio FastAPI
`/api/v1` service (`jung-api`), SQLite persistence, and the maintained
`jung-console` client.

This is a research tool, not emergency support or a substitute for professional
care. Review the [safety and data-handling guidance](docs/safety-and-data.md)
before entering personal information.

## Prerequisites

- Python ≥3.11
- [uv](https://docs.astral.sh/uv/)
- `make`

## Quick Start

1. Start an OpenAI-compatible local model server such as llama.cpp, LM Studio,
   or Ollama on the host.
2. Copy the environment template and edit the copy for native execution:

```bash
cp .env.example .env
```

Edit `.env` to set:

```dotenv
LLM_BASE_URL=http://127.0.0.1:8080/v1
MODEL_NAME=<your-server-model-name>
```

The port depends on your model server. Leave `.env.example` itself unchanged.
Ordinary Compose loads `.env` (`${ENV_FILE:-.env}`); when you move the API into
Compose while the model server remains on the host, set `LLM_BASE_URL` back to
`http://host.docker.internal:<port>/v1`. See
[development.md](docs/development.md) for native ↔ Docker URL switching.

3. Install and run natively (two terminals; `make run-api` is blocking):

```bash
uv sync --locked
```

**Terminal 1:**

```bash
make run-api
```

**Terminal 2:**

```bash
make run-console
```

Optional packaged Docker path (see [development.md](docs/development.md) for
`LLM_BASE_URL` when the API runs in Compose):

```bash
make docker-build
make docker-up
```

Or start the supported client against a packaged API with `make ui-console`.

## Next steps

See [docs/README.md](docs/README.md) for canonical documentation navigation.
Developer commands, configuration guidance, tests, and the release gate are in
[docs/development.md](docs/development.md).

Native development is the normal path. `make finalization-check` includes
`smoke-compose-api` and therefore requires Docker.

## Naming

The user-facing product language is **therapist**. The supported runtime package
is `jung`.
