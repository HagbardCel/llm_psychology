# Local Therapist Tool

Local-laptop therapy workflow research tool backed by a Trio HTTP/WebSocket
service, SQLite persistence, and one maintained console client.

## Quick Start

1. Start an OpenAI-compatible local model server such as llama.cpp, LM Studio,
   or Ollama on the host.
2. Copy `.env.example` to `.env` and set the provider, base URL, and model name.
3. Build the Docker images with `make dev-install`.
4. Start the supported client with `make ui-console`.

## Maintainer Checks

Run validation through Docker:

```bash
make validate-architecture
make test-validate
make probe-console-deterministic
```

See [docs/README.md](docs/README.md) for architecture, contracts, and local
maintenance guidance.

## Local Database

Back up SQLite with `make docker-db-backup`. Before an intentional pre-release
schema reset, create a backup and then run `make reset-foundation-db`. Older
therapy-plan schemas are rejected at startup instead of migrated implicitly.

## Naming

The user-facing product language is **therapist**. Internal package names,
scripts, container identifiers, and SQLite filenames retain
`psychoanalyst_app` or `psychoanalyst` for compatibility.
