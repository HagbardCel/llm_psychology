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
2. Copy the environment template:

```bash
cp .env.example .env
```

3. Edit `.env` if needed:

```dotenv
LLM_BASE_URL=http://127.0.0.1:8080/v1
MODEL_NAME=<your-server-model-name>
```

The port depends on your model server. Leave `.env.example` itself unchanged.

4. Install dependencies:

```bash
uv sync --locked
```

5. Run the API and console in two terminals (`make run-api` is blocking):

**Terminal 1:**

```bash
make run-api
```

**Terminal 2:**

```bash
make run-console
```

## Next steps

See [docs/README.md](docs/README.md) for documentation navigation.
Developer commands, configuration guidance, tests, and the release gate are in
[docs/development.md](docs/development.md).

The deterministic release gate is `make check` (native only; no live LLM).

## Naming

The user-facing product language is **therapist**. The supported runtime package
is `jung`.
