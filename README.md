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

Run the release-candidate validation path through Docker:

```bash
make finalization-check
```

For faster partial feedback while iterating:

```bash
make lint
make validate-docs
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

## Optional Devcontainer

The checked-in devcontainer is supported optional tooling for contributors who
want a containerized editor environment. Validate its setup with
`make devcontainer-test`; the Docker-first commands above remain the canonical
workflow.

Existing local `.env` files are not rewritten automatically. Change
`APP_ENV=production` to `APP_ENV=local` when updating an older checkout.

## Naming

The user-facing product language is **therapist**. Internal package names,
scripts, container identifiers, and SQLite filenames retain
`psychoanalyst_app` or `psychoanalyst` for compatibility.
