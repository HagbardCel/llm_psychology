# Codex Agent Guide

Canonical product docs: `docs/README.md`

Developer workflow: `docs/development.md`

Test ownership: `tests/README.md`

Real-model evals: `evals/README.md`

Canonical documentation governs product architecture, runtime behavior, and
contracts. `AGENTS.md` contains agent-specific workflow constraints. If this
file restates a product fact inconsistently with canonical documentation, the
canonical documentation wins and `AGENTS.md` must be corrected.

## Active Scope
Treat the Jung backend, workflow, persistence, `/api/v1` contracts, LLM gateway,
deterministic tests, and `jung-console` probes as the main product.

- Maintain `jung-console` as the only supported frontend.
- Do not add additional supported frontends unless explicitly requested.
- Do not add multi-frontend orchestration modes.
- Prefer Jung unit/integration tests and the v1 console probe.
- Clients use `/api/v1` only; do not import application internals from clients.
- Do not add Trio/asyncio compatibility adapters to runtime code.
- Prefer existing utilities and services before adding new ones.
- If HTTP/WS contracts or API-facing models change, update `docs/api-v1.md`.
- Add deterministic tests for new behavior.

## Foundation Failure Policy
Do not hide workflow, LLM, persistence, protocol, or contract failures behind
fallback behavior unless explicitly requested.

- Prefer fail-fast, diagnostic errors with preserved workflow state and deterministic tests.
- Treat fallbacks as product decisions; document and test them when they are intentionally added.
- Workflow probes must not convert real backend failures into passes.
- For LLM structured-output failures, preserve enough bounded diagnostic context to identify the phase, schema, provider, model, and parse failure without leaking full prompts or transcripts by default.

## Version Control Guidelines
- Branch from `main` using `feat/<topic>` or `fix/<topic>`.
- Keep commits small and scoped; use conventional prefixes (`feat:`, `fix:`, `docs:`).
- Run `make test` (or `uv run --locked pytest -m "not real_llm" tests/unit tests/integration`) before committing.
- Avoid force pushes to shared branches; rebase only on local branches.
