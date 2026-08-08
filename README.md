# Local Therapist Tool

Local-laptop therapy workflow research tool backed by an asyncio FastAPI
`/api/v1` service (`jung-api`), SQLite persistence, and the maintained
`jung-console` client.

This is a research tool, not emergency support or a substitute for professional
care. Review the [safety and data-handling guidance](docs/safety-and-data.md)
before entering personal information.

## Quick Start

1. Start an OpenAI-compatible local model server such as llama.cpp, LM Studio,
   or Ollama on the host.
2. Copy the environment template and adjust for native execution:

```bash
cp .env.example .env
# For native jung-api talking to a model server on host port 8080:
# change LLM_BASE_URL to:
LLM_BASE_URL=http://127.0.0.1:8080/v1
# MODEL_NAME=<your-server-model-name>
```

The port depends on your model server. Leave `.env.example` itself unchanged;
Compose loads it into the API container where `host.docker.internal` is
intentional. See [development.md](docs/development.md) for native ↔ Docker URL
switching.

3. Install and run natively:

```bash
uv sync --locked
make run-api
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
