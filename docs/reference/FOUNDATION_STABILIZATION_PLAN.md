---
owner: engineering
status: active
last_reviewed: 2026-05-31
review_cycle_days: 30
source_of_truth_for: Foundation stabilization strategy and temporary client policy
---

# Foundation Stabilization Plan

## Purpose

Operate the project as a backend and protocol-contract system while workflow,
persistence, and LLM behavior are stabilized. Maintain one reference frontend:
the HTTP/WebSocket `console-ui` client.

## Active Product Surface

Tier 0 foundation components are always maintained:

- workflow state machine and session lifecycle
- persistence and migrations
- HTTP DTOs and WebSocket protocol
- transient JSON schema generation and committed protocol constants
- LLM abstraction and deterministic fake-provider behavior
- backend, architecture, documentation, and workflow-probe validation

Tier 1 is the maintained `console-ui` reference frontend. It exercises
registration, connection, workflow-next-action events, streaming, session
ending, style selection, and deterministic full-stack probes.

Removed frontend implementations are not part of the maintained product
surface. See `docs/ui-scope.md`.

## Design Rules

1. Backend orchestration is the only authority for workflow progression.
2. Clients render workflow state and submit explicit actions; they do not
   mutate workflow state directly.
3. Contract changes update specs, DTOs, schemas or protocol constants, and
   deterministic tests together.
4. Prefer backend, protocol, and workflow-probe coverage over frontend logic.
5. Do not recreate removed clients unless explicitly approved as separate
   product work.
6. Keep optional RAG, dashboard polish, and multi-client support deferred.

## Foundation-Complete Checklist

The foundation phase can end when:

1. Major workflow transitions are explicit, validated, and regression tested.
2. Session create, reconnect, resume, end, and post-session behavior is
   deterministic.
3. HTTP DTOs do not leak persistence models and errors have consistent shapes.
4. WebSocket envelopes, streaming, reconnect, and invalid-message behavior are
   documented and tested.
5. Schema and protocol generation detect contract drift.
6. Persistence migrations, session immutability, and enrichment jobs are
   deterministic.
7. LLM provider failure, quota, timeout, and invalid-output behavior has
   deterministic handling.
8. `console-ui` works against the current backend.
9. `make finalization-check` passes.

## Validation Strategy

Use these Docker-backed layers:

| Layer | Purpose |
|---|---|
| `make validate-docs` | active-document governance |
| `make validate-schemas` | transient HTTP DTO schema generation and validation |
| `make validate-generated-contracts` | committed backend and console WS constants |
| `make validate-architecture` | layer boundaries and budgets |
| `make test-validate` | backend and console-related pytest suite |
| `make probe-console-deterministic` | no-network full-stack reference-client flow |
| `make ui-console-test` | optional manual real-LLM console validation |

## Deferred Work

- browser UI product work
- UI redesign and dashboard features
- multi-client feature parity
- mobile-specific UX
- local retrieval extensions
- multi-instance deployment behavior unless it changes core architecture

## Exit Review

After the checklist passes, choose deliberately whether the project should stay
API-first, restore a removed browser client through a porting effort, or add a
new client against the stabilized contracts.
