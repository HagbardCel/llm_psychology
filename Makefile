.PHONY: help sync format format-check lint docs-links test probe-console \
	smoke-local-llm run run-api run-console check \
	clean test-unit test-integration \
	evals eval-report simulate-local-llm

export PYTHONPATH := src

LOCAL_LLM_SMOKE_TARGET ?= tests/smoke/test_local_llm_compatibility.py
LOCAL_LLM_SMOKE_PYTEST_ARGS ?= -q
CONSOLE_E2E_TEST := tests/e2e/test_console_workflow.py
PROBE_OUTPUT_DIR ?= logs/workflow-probes/console-v1
PROBE_ABS_OUTPUT_DIR := $(abspath $(PROBE_OUTPUT_DIR))
SIM_ARGS ?=
EVAL_REPORT_ARGS ?=

help:
	@echo "Native uv workflow:"
	@echo "  sync                 - uv sync --locked"
	@echo "  format / format-check / lint"
	@echo "  docs-links           - local Markdown path/section link check"
	@echo "  test                 - unit + integration (not real_llm)"
	@echo "  probe-console        - deterministic console E2E once"
	@echo "  check                - deterministic release gate (native)"
	@echo "  run                  - normal local application"
	@echo "  run-api / run-console - standalone API / console client"
	@echo "  smoke-local-llm      - manual local-model smoke"
	@echo "  evals                - hard real-model invariants (pass/fail)"
	@echo "  eval-report          - diagnostic behavioral report under logs/evals"
	@echo "  simulate-local-llm   - whole-product longitudinal journey audit"

sync:
	uv sync --locked

format:
	uv run --locked ruff format .

format-check:
	uv run --locked ruff format --check .

lint:
	uv run --locked ruff check .

docs-links:
	uvx --from 'md-link-checker==1.10' md-link-checker --no-urls \
		README.md AGENTS.md $$(find docs -type f -name '*.md' -print) \
		tests/README.md evals/README.md

test:
	uv run --locked pytest -m "not real_llm" tests/unit tests/integration

probe-console:
	@mkdir -p "$(PROBE_ABS_OUTPUT_DIR)"
	PROBE_OUTPUT_DIR="$(PROBE_ABS_OUTPUT_DIR)" \
		uv run --locked pytest $(CONSOLE_E2E_TEST) -v

run:
	uv run --locked jung

run-api:
	uv run --locked jung-api

run-console:
	uv run --locked jung-console --api-url http://127.0.0.1:8000

smoke-local-llm:
	uv run --locked pytest $(LOCAL_LLM_SMOKE_TARGET) \
		-m real_llm --no-mocks \
		-o asyncio_mode=strict \
		$(LOCAL_LLM_SMOKE_PYTEST_ARGS)

# Hard behavioral oracles. Opt-in like the smoke; not part of check.
evals:
	uv run --locked pytest evals/test_hard_invariants.py \
		-m "eval and real_llm" --no-mocks -o asyncio_mode=strict

# Diagnostic report for human review; never a gate.
# Example: make eval-report EVAL_REPORT_ARGS="--concurrency 4"
eval-report:
	@mkdir -p logs/evals
	uv run --locked python -m evals.behavioral_report $(EVAL_REPORT_ARGS)

# Whole-product longitudinal journey over real HTTP. Opt-in; not part of check.
# Uses production Jung LLM settings (LLM_BASE_URL / MODEL_NAME / …), not
# LOCAL_LLM_SMOKE_*.
simulate-local-llm:
	uv run --locked python -m evals.simulation $(SIM_ARGS)

# Deterministic native release gate. No live LLM; no Docker.
check: sync
	$(MAKE) format-check
	$(MAKE) lint
	$(MAKE) docs-links
	$(MAKE) test
	$(MAKE) probe-console

test-unit:
	uv run --locked pytest tests/unit

test-integration:
	uv run --locked pytest tests/integration

clean:
	@rm -rf __pycache__ .pytest_cache .ruff_cache build dist *.egg-info 2>/dev/null || true
