# Phase 8B Outcome

Frozen results from the Phase 8B server-batching benchmark (Qwen3.8-27B fixture).
Protocol: [`evals/README.md`](../README.md) Phase 8B section. Operator scripts:
[`evals/phase8b/README.md`](README.md).

## Fixture

| Item | Value |
|---|---|
| Benchmark source base | `6c221c2dcbafa172b7b1708bb68d64682acafd2d` (HEAD when matrix started 2026-08-16) |
| Working tree at run time | dirty — uncommitted `evals.behavioral_report --workload {full,screen}` changes |
| Relevant benchmark diff | `evals/behavioral_report.py`, tests, `evals/README.md`, `docs/development.md`, `Makefile` |
| Final equivalent implementation commit | `ad36cf9` — benchmarked dirty-tree implementation committed unchanged |
| Model family | Qwen3.8-27B, thinking enabled |
| Structured mode | `json_schema` |
| Extras | `enable_thinking=true`, `top_p=0.95`, `top_k=20` |
| MTPLX | **2.7.1**, `Youssofal/Qwen3.8-27B-MTPLX-Optimized-Speed`, timed rows `--ssd-session-cache off` |
| llama.cpp | Q4_K_M GGUF, build `b10428-885c5bbe8`, `--parallel N`, `--ctx-size 32768×N`, `--min-p 0` |

Cross-backend quantizations are not bit-equivalent — operational configuration comparison only.

## Funnel

### Stage 1 — one `--workload screen` run per admitted row (n=1 each)

| ID | Wall s | Overlap | Attempts | Notes |
|---|---:|---:|---:|---|
| M1 | 603.3 | 1.000 | 15 | MTPLX serial |
| M4 | 607.9 | 3.520 | 15 | MTPLX serial + client N=4 |
| A2 | 703.6 | 1.827 | 15 | ar_batch N=2 |
| A4 | 695.7 | 2.925 | 15 | ar_batch N=4 |
| L1 | 1923.6 | 1.000 | 15 | llama.cpp |
| L2 | 1477.4 | 1.914 | 15 | llama.cpp parallel=2 |
| L4 | failed | | | post_session_update timeout @600s |
| T4 | N/A | | | unsupported lane |

Dropped for Stage 2: L1/L2 (clear losers), L4 (fail), T4 (N/A), A2/A4 (outside ~10% of second).

### Stage 2 — three alternating screen runs each (n=3)

| ID | c1 | c2 | c3 | median |
|---|---:|---:|---:|---:|
| **M4** | 596.3 | 577.5 | 739.7 | **596.3** |
| M1 | 617.6 | 595.8 | 679.9 | 617.6 |

Margin (median): M4 ~3.6% faster than M1.

### Stage 3 — `--workload full` (n=1 per completed row)

| ID | Wall s | Overlap | Attempts | Notes |
|---|---:|---:|---:|---|
| L1-full | **failed** | | | assessment `LLMTimeout` @600s and @1800s |
| M4-full | 2310.2 | 3.827 | 57 | |
| M1-full | 2384.4 | 1.000 | 57 | +3.1% vs M4-full |

### Stage 4 — tie-break (full gap 3.2% < 10%; n=1 s4 run per finalist)

| ID | Wall s | Overlap | Attempts |
|---|---:|---:|---:|
| M4-full-s4a | 2342.6 | 3.793 | 57 |
| M1-full-s4b | 2330.1 | 1.000 | 57 |

| ID | Stage 3 | Stage 4 | Mean (n=2) |
|---|---:|---:|---:|
| **M4** | 2310.2 | 2342.6 | **2326.4** |
| M1 | 2384.4 | 2330.1 | 2357.3 |

Mean margin: ~1.3%. Ranking matches screen confirmation (M4 ahead).

## Selection

**M4** is the selected Phase 8B operational configuration for concurrent
`eval-report`: MTPLX **serial** scheduling with **client concurrency 4**. Its
full-workload tie-break advantage over M1 was modest. This result does **not**
demonstrate server-side parallel inference or batching efficiency — M4 is the
control row showing four outstanding client requests on a serial server, not
backend batching.

- **Concurrent eval-report default:** M4
- **Interactive/reference serial configuration:** M1
- Phase 8B did **not** benchmark interactive TTFT or user-perceived latency; M4
  must not be promoted as an interactive-performance result.

## Limitations

- L1-full failed at 600 s and 1800 s — no clean full llama.cpp baseline
- No ≥1.5× **full-workload** speedup claim vs L1
- M4 does not establish backend parallel execution
- Screen and full workloads are not numerically comparable (do not mix metrics)
- Fixture-specific result; not a global MTPLX-vs-llama.cpp ranking
- Screen-only note (not Stage 3): L1 screen 1923.6 / M4 screen median 596.3 ≈
  3.2× on `--workload screen` only

## Evidence

Complete machine-specific provenance, metrics sidecars, and run logs:

```text
logs/evals/phase8b/   (gitignored operator workspace)
```
