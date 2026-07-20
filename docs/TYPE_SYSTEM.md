---
owner: engineering
status: supporting
last_reviewed: 2026-07-20
review_cycle_days: 90
source_of_truth_for: Backend schema and WebSocket protocol generation pipeline
---

# Type System Documentation

> Legacy supporting reference. This document does not describe the supported Phase 6C runtime. See the [target architecture](refactor/target-architecture.md), [API v1 contract](refactor/api-v1-contract.md), and [workflow specification](refactor/workflow-specification.md). It remains temporarily available pending the Phase 7 documentation rewrite.

## Overview

Backend Pydantic DTOs are the source of truth for HTTP wire models. The
repository generates transient JSON schemas for validation and documentation.
Generated DTO schemas are intentionally ignored by Git.

WebSocket message names are sourced from tracked `schemas/ws_protocol.json`.
The generator writes committed Python constants for the backend and supported
`console-ui` client.

## HTTP Schema Pipeline

```text
backend DTOs
  -> psychoanalyst_app.schemas.generate_schemas
  -> transient schemas/*.json
  -> scripts/validate_schemas.py
```

Run:

```bash
make generate-schemas
make validate-schemas
```

`make validate-schemas` regenerates schemas first so validation behaves the
same in a clean clone and a developer workspace.

## WebSocket Protocol Pipeline

```text
schemas/ws_protocol.json
  -> scripts/generate_ws_protocol.py
  -> src/psychoanalyst_app/utils/ws_protocol.py
  -> console-ui/src/websocket_protocol.py
```

Run:

```bash
make generate-ws-protocol
make validate-generated-contracts
```

The generated Python files are committed. Do not edit them by hand.

## Contract Change Rules

When an HTTP DTO changes:

1. Update the backend DTO and contract documentation.
2. Run `make validate-schemas`.
3. Add or update deterministic backend tests.

When the WebSocket inventory changes:

1. Update `schemas/ws_protocol.json` and `docs/WEBSOCKET_PROTOCOL.md`.
2. Run `make generate-ws-protocol`.
3. Update backend helpers and `console-ui` handling.
4. Run `make validate-generated-contracts` and relevant tests.
