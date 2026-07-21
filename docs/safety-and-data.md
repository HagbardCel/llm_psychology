---
owner: engineering
status: active
last_reviewed: 2026-07-21
review_cycle_days: 90
source_of_truth_for: Product safety, sensitive-data handling, network exposure, and local data erasure
---

# Safety and Data Handling

## Not professional care

This application is a local research tool. It is **not** emergency or crisis
support and is **not** a substitute for professional medical, psychiatric, or
psychological care.

Generated responses can be inaccurate, inappropriate, or misleading. No
clinician or human operator monitors the conversation.

In an emergency or immediate risk of harm, contact local emergency services or
an appropriate crisis service in your area.

## Sensitive local data

The local SQLite database may contain highly sensitive personal information,
including profile details, session transcripts, and derived clinical-style
notes. Protect database files, backups, and any copied exports accordingly.

## Remote model providers

When configured to use a remote OpenAI-compatible endpoint, the application
sends constructed prompt context (profile and conversation content) to that
provider. Deleting local files does **not** erase data that a remote provider
may retain under its own policies.

## Network exposure

The API provides no authentication or transport encryption. Keep it
loopback-bound unless equivalent authentication, encryption, access control,
and network isolation are supplied externally.

Native execution defaults to loopback (`127.0.0.1`). Non-loopback native
binding requires `JUNG_API_ALLOW_REMOTE_BIND=true`.

In supported Docker Compose, the process listens on `0.0.0.0` inside the
container (required for container networking) while the host port is published
only on `127.0.0.1`. Do not broaden that host binding casually or assume the
application provides authentication when changing port mappings.

## Tracing and logs

`JUNG_ENABLE_LLM_TRACING=true` records operational metadata (task, model,
mode, timing, role sequence, message counts, and character counts).

`JUNG_LOG_PROMPT_PREVIEWS=true`, which requires tracing to be enabled,
additionally logs prompt prefixes and can expose sensitive content. Treat logs
as potentially sensitive when previews are enabled.

## Erasing local data

Stop the application before removing files.

### Native

When `JUNG_DATA_DIR` is unset, the native runtime stores `./data/jung.db`
together with any `jung.db-wal` and `jung.db-shm` sidecars. The environment
template may recommend `JUNG_DATA_DIR=./data/local` for an organized layout,
which would instead produce `./data/local/jung.db` and its sidecars.

When `JUNG_DATA_DIR` is set, remove `${JUNG_DATA_DIR}/jung.db` and its
sidecars.

### Docker Compose

- **Default Compose:** remove `./data/local/jung.db` and sidecars on the host.
- **User-test Compose:** remove `./data/usertest/jung.db` and sidecars.
- **Custom host data:** remove files under `${JUNG_HOST_DATA_DIR}`, not merely
  files inside a disposable container.

### Logs, backups, and copies

Remove relevant files under `./logs`, manual archives, backups, workflow-probe
artifacts that may contain user text, and any copied database exports
separately.

## Related canonical documentation

- [Documentation Index](README.md)
- [Target Architecture](refactor/target-architecture.md)
