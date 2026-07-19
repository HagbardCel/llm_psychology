.PHONY: help install dev-install install-uv format lint test test-unit test-integration test-devcontainer test-dev test-validate install-hooks clean check-usertest-key
.PHONY: docker-up docker-down docker-test docker-test-isolated docker-test-one docker-shell docker-logs docker-logs-api docker-db-view docker-test-reset docker-clean
.PHONY: ui-console ui-console-test
.PHONY: probe probe-console-deterministic probe-console-v1-deterministic probe-console-intake-notes probe-logs probe-db check-usertest-env
.PHONY: devcontainer-rebuild devcontainer-test devcontainer-open
.PHONY: generate-schemas validate-schemas generate-ws-protocol validate-generated-contracts validate-docs validate-architecture finalization-check finalization-check-full finalization-check-target
.PHONY: prepare-runtime-dirs characterization-smoke characterization-full characterization-test test-refactor-fast validate-refactor-phase-1 phase-2-test validate-refactor-phase-2 phase-3-test validate-refactor-phase-3 smoke-refactor-phase-3-local-llm smoke-target-local-llm phase-5-test validate-refactor-phase-5 validate-refactor-phase-6 test-target _phase-5-console-v1 hook-commit hook-push

export PYTHONPATH := src
export HOST_UID ?= $(shell id -u)
export HOST_GID ?= $(shell id -g)
CONSOLE_UI_LOG ?= logs/console-ui.log
CONSOLE_UI_LOG_TEST ?= logs/console-ui-usertest.log
PHASE3_SMOKE_TARGET ?= tests/smoke/jung/test_phase3_local_llm.py
PHASE3_SMOKE_PYTEST_ARGS ?= -q

# Default target
help:
	@echo "Available targets:"
	@echo ""
	@echo "Default (Docker) Development:"
	@echo "  install-uv        - Deprecated local installer target (no-op)"
	@echo "  install           - Build API container (installs backend deps inside Docker)"
	@echo "  dev-install       - Build dev containers (api + console-ui)"
	@echo "  format            - Format code with black (Docker)"
	@echo "  lint              - Lint code with ruff (Docker)"
	@echo "  test              - Run backend tests (Docker)"
	@echo "  test-dev          - Quick backend tests (Docker)"
	@echo "  test-validate     - Full isolated Docker tests (pre-commit validation)"
	@echo "  test-unit         - Run unit tests only"
	@echo "  test-integration  - Run integration tests only"
	@echo "  test-devcontainer - Run devcontainer setup tests (Docker)"
	@echo "  install-hooks     - Install git pre-commit and pre-push hooks for automated validation"
	@echo "  clean             - Clean up generated files and caches"
	@echo "  requirements      - Generate locked requirements from .in files"
	@echo "  sync              - Rebuild containers from locked requirements"
	@echo "  run-server        - Run HTTP/WebSocket server via Docker"
	@echo "  generate-schemas  - Generate JSON schemas from Pydantic models (Docker)"
	@echo "  validate-schemas  - Validate generated JSON schemas (Docker)"
	@echo "  validate-generated-contracts - Validate committed generated protocol/types (Docker)"
	@echo "  validate-docs     - Validate docs metadata + canonical active-doc index (Docker)"
	@echo "  validate-architecture - Validate architecture budgets and layer boundaries (Docker)"
	@echo "  finalization-check - Standard release-candidate checks, including characterization smoke (Docker)"
	@echo "  finalization-check-target - Target-runtime release gate candidate (Phase 6)"
	@echo "  test-target         - Complete deterministic Jung test suite once (Phase 6)"
	@echo "  validate-refactor-phase-6 - Validate Phase 6 cutover invariants (Docker)"
	@echo "  smoke-target-local-llm - Manual local-model smoke alias (Phase 6 closure)"
	@echo "  validate-refactor-phase-2 - Validate Phase 2 jung domain/persistence (Docker)"
	@echo "  phase-3-test            - Run Phase 3 LLM and processor tests (Docker)"
	@echo "  validate-refactor-phase-3 - Validate Phase 3 jung llm/phases (Docker)"
	@echo "  smoke-refactor-phase-3-local-llm - Manual local-model smoke for Phase 3 schemas"
	@echo ""
	@echo "UI Mode Selection:"
	@echo "  ui-console        - Run console UI service (Docker, WebSocket client)"
	@echo "  ui-console-test   - Run console UI service in usertest mode"
	@echo "  probe             - Run local-LLM full-stack console workflow probe"
	@echo "  probe-console-deterministic - Run deterministic full-stack console workflow probe"
	@echo "  probe-console-v1-deterministic - Run Phase 5 Jung console deterministic probes"
	@echo "  probe-console-intake-notes - Run gate-enabled intake note tracking deterministic probe"
	@echo "  probe-logs        - Print latest workflow probe summary"
	@echo "  probe-db          - Print rows created by latest workflow probe"
	@echo ""
	@echo "Docker Development:"
	@echo "  docker-up         - Start backend API service"
	@echo "  docker-down       - Stop all Docker containers"
	@echo "  docker-shell      - Shell into API container"
	@echo "  docker-logs       - View logs (usage: make docker-logs SERVICE=api)"
	@echo "  docker-logs-api   - View API logs only (useful when running console-ui)"
	@echo "  docker-test       - Run tests in Docker (usually not needed, use 'make test')"
	@echo "  docker-test-one   - Run specific test (usage: make docker-test-one TEST=tests/unit/test_foo.py)"
	@echo "  docker-db-view    - View database at http://localhost:8080 (DB=local|usertest, default: local)"
	@echo "  docker-test-reset - Reset test database"
	@echo "  docker-clean      - Clean up all Docker resources"
	@echo ""
	@echo "DevContainer:"
	@echo "  devcontainer-rebuild - Rebuild devcontainer without cache"
	@echo "  devcontainer-test    - Test devcontainer configuration"
	@echo "  devcontainer-open    - Open project in VSCode devcontainer"

# Prepare run-time dirs
prepare-runtime-dirs:
	@mkdir -p data logs logs/workflow-probes
	@if [ "$${CI:-}" = "true" ]; then \
		chmod -R a+rwX data logs; \
	else \
		chmod -R u+rwX,g+rwX data logs; \
	fi

# Install UV package manager
install-uv:
	@echo "⚠️  install-uv is deprecated in Docker-only workflow."
	@echo "    Use 'make requirements' to compile lockfiles in Docker."

# Install runtime dependencies inside Docker
install:
	docker compose build api

# Build dev containers (installs Python deps inside Docker images)
dev-install:
	docker compose build api console-ui

# Format code with black (Docker)
format: prepare-runtime-dirs
	docker compose run --rm api black .

# Lint code with ruff (Docker)
lint: prepare-runtime-dirs
	docker compose run --rm api ruff check .

# Run all tests (Docker)
test:
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test

# Run unit tests only (Docker)
test-unit:
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest -m unit

# Run integration tests only (Docker)
test-integration:
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest -m integration

TARGET_SUPPORT_TESTS := \
	tests/unit/test_validate_refactor_phase_5.py \
	tests/unit/test_validate_refactor_phase_6.py \
	tests/unit/test_recording_fake_llm.py \
	tests/unit/test_measure_codebase.py

PHASE_6_PYTEST_OPTIONS := \
	-o trio_mode=false \
	-o asyncio_mode=auto

test-target: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest \
		$(PHASE_6_PYTEST_OPTIONS) \
		-m "not real_llm" \
		tests/unit/jung/ \
		tests/integration/jung/ \
		$(TARGET_SUPPORT_TESTS)

smoke-target-local-llm: smoke-refactor-phase-3-local-llm

finalization-check-target: prepare-runtime-dirs
	$(MAKE) lint
	$(MAKE) validate-docs
	$(MAKE) test-target
	docker compose -f docker-compose.yml --profile test run --rm --no-deps \
		--entrypoint /usr/local/bin/python \
		--volume "$(CURDIR):/workspace:ro" \
		--workdir /workspace \
		--env PYTHONPATH=/workspace/src \
		test scripts/validate_refactor_phase_6.py --stage pre-cutover
	docker compose -f docker-compose.yml --profile test run --rm --no-deps \
		--entrypoint /usr/local/bin/python \
		--volume "$(CURDIR):/workspace:ro" \
		--workdir /workspace \
		--env PYTHONPATH=/workspace/src \
		test scripts/validate_refactor_phase_5.py
	$(MAKE) probe-console-v1-deterministic

validate-refactor-phase-6: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test ruff check \
		scripts/validate_refactor_phase_6.py \
		tests/unit/test_validate_refactor_phase_6.py
	docker compose -f docker-compose.yml --profile test run --rm --no-deps \
		--entrypoint /usr/local/bin/python \
		--volume "$(CURDIR):/workspace:ro" \
		--workdir /workspace \
		--env PYTHONPATH=/workspace/src \
		test scripts/validate_refactor_phase_6.py --stage pre-cutover
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest \
		$(PHASE_6_PYTEST_OPTIONS) \
		tests/unit/test_validate_refactor_phase_6.py -q

# Full release-candidate validation path.
finalization-check: prepare-runtime-dirs
	$(MAKE) lint
	$(MAKE) validate-docs
	$(MAKE) validate-schemas
	$(MAKE) validate-generated-contracts
	$(MAKE) validate-architecture
	$(MAKE) test-validate
	docker compose -f docker-compose.yml --profile test run --rm --no-deps \
		--entrypoint /usr/local/bin/python \
		--volume "$(CURDIR):/workspace:ro" \
		--workdir /workspace \
		--env PYTHONPATH=/workspace/src \
		test scripts/validate_refactor_phase_5.py
	$(MAKE) characterization-smoke
	$(MAKE) probe-console-deterministic

# Heavier release-candidate path: layers the gate-enabled intake-note probe on
# top of the default finalization-check. Kept separate so the default path stays
# fast for local iteration; run before merging an intake-tracking change.
finalization-check-full: finalization-check
	$(MAKE) characterization-full
	$(MAKE) probe-console-intake-notes

# Fast Phase 1 checkpoint: retained deterministic unit coverage plus real smoke.
test-refactor-fast: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest tests/unit/test_intake_record_merge.py tests/unit/test_intake_slot_evidence_adapter.py tests/unit/test_note_taker_intake_patch.py tests/unit/test_planning_analysis.py tests/unit/test_reflection_plan_snapshot.py tests/unit/test_agent_output_validators.py
	$(MAKE) characterization-smoke

characterization-smoke: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest tests/characterization -m characterization_smoke

characterization-full: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest tests/characterization -m characterization_full

characterization-test: prepare-runtime-dirs
	$(MAKE) characterization-smoke
	$(MAKE) characterization-full

validate-refactor-phase-1: prepare-runtime-dirs
	$(MAKE) validate-docs
	docker compose run --rm -v "$(PWD)/scripts:/app/scripts" -v "$(PWD)/docs:/app/docs" -v "$(PWD)/requirements.in:/app/requirements.in:ro" -v "$(PWD)/requirements-dev.in:/app/requirements-dev.in:ro" api python scripts/validate_refactor_phase_1.py
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest tests/unit/test_measure_codebase.py tests/unit/test_validate_refactor_phase_1.py

phase-2-test: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest \
		tests/unit/jung/test_domain_models.py \
		tests/unit/jung/domain/test_plan_content.py \
		tests/unit/jung/test_json_validation.py \
		tests/unit/jung/test_sqlite_support.py \
		tests/unit/jung/test_workflow.py \
		tests/unit/jung/test_import_boundaries.py::test_phase2_packages_have_no_forbidden_imports \
		tests/integration/jung/test_store_chat.py \
		tests/integration/jung/test_store_recovery.py \
		tests/integration/jung/test_store_schema.py \
		tests/integration/jung/test_store_workflow.py \
		-q

validate-refactor-phase-2: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test ruff check \
		src/jung/domain \
		src/jung/persistence \
		src/jung/workflow.py \
		tests/unit/jung/test_domain_models.py \
		tests/unit/jung/domain/test_plan_content.py \
		tests/unit/jung/test_json_validation.py \
		tests/unit/jung/test_sqlite_support.py \
		tests/unit/jung/test_workflow.py \
		tests/unit/jung/test_import_boundaries.py \
		tests/integration/jung/test_store_chat.py \
		tests/integration/jung/test_store_recovery.py \
		tests/integration/jung/test_store_schema.py \
		tests/integration/jung/test_store_workflow.py
	$(MAKE) phase-2-test

phase-3-test: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest \
		-o trio_mode=false \
		-o asyncio_mode=auto \
		tests/unit/jung/llm \
		tests/unit/jung/phases \
		tests/unit/jung/test_styles.py \
		tests/unit/jung/test_import_boundaries.py \
		tests/integration/jung/test_processor_store_seams.py \
		tests/unit/jung/smoke/test_smoke_diagnostics.py \
		-q

phase-4-test: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest \
		-o trio_mode=false \
		-o asyncio_mode=auto \
		tests/unit/jung/test_events.py \
		tests/unit/jung/test_supervisor.py \
		tests/unit/jung/test_application_helpers.py \
		tests/unit/jung/test_workflow.py \
		tests/unit/jung/llm/test_structured_output.py \
		tests/unit/jung/test_import_boundaries.py \
		tests/integration/jung/test_application_workflow.py \
		tests/integration/jung/test_application_chat.py \
		tests/integration/jung/test_application_operations.py \
		tests/integration/jung/test_application_recovery.py \
		tests/integration/jung/test_application_composition.py \
		tests/integration/jung/test_application_session_history.py \
		tests/integration/jung/test_application_read_models.py \
		tests/integration/jung/test_store_workflow.py \
		tests/integration/jung/test_store_chat.py \
		tests/integration/jung/test_store_recovery.py \
		tests/integration/jung/test_processor_store_seams.py \
		-q

PHASE_5_PYTEST_OPTIONS := \
	-o trio_mode=false \
	-o asyncio_mode=auto

PHASE_5_CONSOLE_TEST := tests/e2e/test_console_v1_workflow.py

phase-5-test: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest \
		$(PHASE_5_PYTEST_OPTIONS) \
		tests/unit/jung/api/ \
		tests/unit/jung/client/ \
		tests/unit/jung/test_events.py \
		tests/unit/jung/test_application_helpers.py \
		tests/unit/jung/test_import_boundaries.py \
		tests/unit/jung/test_composition_settings.py \
		tests/unit/jung/llm/test_openai_compatible.py \
		tests/integration/jung/test_application_composition.py \
		tests/unit/test_recording_fake_llm.py \
		tests/unit/test_validate_refactor_phase_5.py \
		tests/integration/jung/test_application_chat.py::test_chat_worker_persists_sanitized_error_message \
		tests/integration/jung/test_application_operations.py::test_operation_worker_persists_sanitized_error_message \
		tests/integration/jung/api/ \
		tests/integration/jung/client/ \
		-q
	$(MAKE) _phase-5-console-v1

_phase-5-console-v1: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest \
		$(PHASE_5_PYTEST_OPTIONS) \
		$(PHASE_5_CONSOLE_TEST) \
		-q

.PHONY: probe-console-v1-deterministic

PROBE_V1_OUTPUT_DIR ?= logs/workflow-probes/phase-5-v1
PROBE_V1_ABS_OUTPUT_DIR := $(abspath $(PROBE_V1_OUTPUT_DIR))

probe-console-v1-deterministic: prepare-runtime-dirs
	@mkdir -p "$(PROBE_V1_ABS_OUTPUT_DIR)"
	docker compose -f docker-compose.yml --profile test run --rm --no-deps \
		-v "$(PROBE_V1_ABS_OUTPUT_DIR):/app/probe-output" \
		-e PROBE_OUTPUT_DIR=/app/probe-output \
		test pytest $(PHASE_5_PYTEST_OPTIONS) $(PHASE_5_CONSOLE_TEST) -v

validate-refactor-phase-5: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test ruff check \
		src/jung/api \
		src/jung/client \
		src/jung/composition.py \
		src/jung/_env.py \
		src/jung/llm/openai_compatible.py \
		tests/jung_api_fixtures.py \
		tests/integration/jung/resilience_support.py \
		tests/integration/jung/api \
		tests/integration/jung/client \
		tests/integration/jung/test_application_composition.py \
		tests/unit/jung/test_composition_settings.py \
		tests/unit/jung/llm/test_openai_compatible.py \
		tests/unit/jung/api \
		tests/unit/jung/client \
		scripts/validate_refactor_phase_5.py \
		tests/unit/test_validate_refactor_phase_5.py \
		tests/unit/test_recording_fake_llm.py \
		tests/unit/jung/test_import_boundaries.py
	docker compose -f docker-compose.yml --profile test run --rm --no-deps \
		--entrypoint /usr/local/bin/python \
		--volume "$(CURDIR):/workspace:ro" \
		--workdir /workspace \
		--env PYTHONPATH=/workspace/src \
		test scripts/validate_refactor_phase_5.py
	$(MAKE) phase-5-test

validate-refactor-phase-4: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test ruff check \
		src/jung/application.py \
		src/jung/events.py \
		src/jung/supervisor.py \
		src/jung/composition.py \
		src/jung/llm/structured.py \
		src/jung/domain/commands.py \
		src/jung/domain/errors.py \
		src/jung/domain/models.py \
		src/jung/domain/results.py \
		src/jung/workflow.py \
		src/jung/persistence/sqlite_store.py \
		src/jung/phases/transcript.py \
		tests/unit/jung/test_events.py \
		tests/unit/jung/test_supervisor.py \
		tests/unit/jung/test_application_helpers.py \
		tests/unit/jung/test_workflow.py \
		tests/unit/jung/llm/test_structured_output.py \
		tests/integration/jung/application_fixtures.py \
		tests/integration/jung/assessment_test_data.py \
		tests/integration/jung/scenarios.py \
		tests/integration/jung/test_application_workflow.py \
		tests/integration/jung/test_application_chat.py \
		tests/integration/jung/test_application_operations.py \
		tests/integration/jung/test_application_recovery.py \
		tests/integration/jung/test_application_composition.py \
		tests/integration/jung/test_application_session_history.py \
		tests/integration/jung/test_application_read_models.py \
		tests/integration/jung/test_store_workflow.py \
		tests/integration/jung/test_store_chat.py \
		tests/integration/jung/test_store_recovery.py \
		tests/integration/jung/test_processor_store_seams.py \
		tests/unit/jung/test_import_boundaries.py
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test python scripts/validate_refactor_phase_4.py
	$(MAKE) phase-4-test

validate-refactor-target-all: prepare-runtime-dirs
	$(MAKE) validate-refactor-phase-1
	$(MAKE) validate-refactor-phase-2
	$(MAKE) validate-refactor-phase-3
	$(MAKE) validate-refactor-phase-4
	$(MAKE) validate-refactor-phase-5

validate-refactor-phase-3: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test ruff check \
		src/jung/llm \
		src/jung/phases \
		src/jung/styles \
		tests/unit/jung/llm \
		tests/unit/jung/phases \
		tests/unit/jung/smoke \
		tests/smoke/jung \
		tests/unit/jung/test_styles.py \
		tests/unit/jung/test_import_boundaries.py \
		tests/integration/jung/test_processor_store_seams.py
	$(MAKE) phase-3-test

smoke-refactor-phase-3-local-llm: prepare-runtime-dirs
	docker compose -f docker-compose.yml --profile test run --rm --no-deps \
		-e PHASE3_SMOKE_SERVER \
		-e PHASE3_SMOKE_BASE_URL \
		-e PHASE3_SMOKE_MODEL \
		-e PHASE3_SMOKE_TIMEOUT \
		-e PHASE3_SMOKE_REQUEST_TIMEOUT \
		-e PHASE3_SMOKE_STRUCTURED_MODE \
		-e PHASE3_SMOKE_EXTRA_BODY \
		-e PHASE3_SMOKE_MAX_COMPLETION_TOKENS \
		-e PHASE3_SMOKE_THERAPY_MAX_SECONDS \
		-e PHASE3_SMOKE_ASSESSMENT_MAX_SECONDS \
		-e PHASE3_SMOKE_POST_SESSION_MAX_SECONDS \
		-e PHASE3_SMOKE_STRICT_ACCEPTANCE \
		-e PHASE3_SMOKE_LOG_PROMPT_PREVIEWS \
		test pytest $(PHASE3_SMOKE_TARGET) \
			-m real_llm --no-mocks \
			-o trio_mode=false -o asyncio_mode=strict \
			$(PHASE3_SMOKE_PYTEST_ARGS)

# Fast local validation. Full release validation remains an explicit checkpoint.
hook-commit: lint

hook-push: hook-commit

# Run devcontainer setup tests (Docker)
test-devcontainer: devcontainer-test

# Quick tests in devContainer (Docker)
test-dev:
	@echo "🚀 Running quick tests in Docker..."
	@echo "Perfect for: Active development, TDD, debugging"
	@echo ""
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest -m "not real_llm" --ignore=tests/characterization -x --tb=short -q

# Full isolated Docker tests (pre-commit validation)
test-validate: prepare-runtime-dirs
	@echo "🔍 Running full test suite in isolated Docker environment..."
	@echo "Perfect for: Pre-commit validation, ensuring clean state"
	@echo ""
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest tests --ignore=tests/characterization \
		--ignore=tests/e2e \
		--ignore=tests/unit/jung/llm \
		--ignore=tests/unit/jung/api \
		--ignore=tests/unit/jung/client \
		--ignore=tests/unit/jung/test_events.py \
		--ignore=tests/unit/jung/test_supervisor.py \
		--ignore=tests/smoke/jung \
		--ignore=tests/integration/jung/api \
		--ignore=tests/integration/jung/client \
		--ignore-glob='tests/integration/jung/test_application_*.py'
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest \
		-o trio_mode=false \
		-o asyncio_mode=auto \
		tests/unit/jung/api/ \
		tests/unit/jung/client/ \
		tests/unit/jung/llm \
		tests/unit/jung/test_events.py \
		tests/unit/jung/test_supervisor.py \
		tests/smoke/jung \
		tests/integration/jung/test_application_workflow.py \
		tests/integration/jung/test_application_chat.py \
		tests/integration/jung/test_application_operations.py \
		tests/integration/jung/test_application_recovery.py \
		tests/integration/jung/test_application_composition.py \
		tests/integration/jung/test_application_session_history.py \
		tests/integration/jung/test_application_read_models.py \
		tests/integration/jung/api/ \
		tests/integration/jung/client/ \
		tests/e2e/

# Install git pre-commit and pre-push hooks for automated validation
install-hooks:
	@echo "🔧 Installing git hooks..."
	@./scripts/install-hooks.sh

# Clean up generated files
clean:
	@echo "Cleaning generated files and caches..."
	@rm -rf __pycache__ */__pycache__ \
		*.pyc */*.pyc \
		*.pyo */*.pyo \
		*.pyd */*.pyd \
		.pytest_cache/ \
		.mypy_cache/ \
		.pytype/ \
		build/ \
		dist/ \
		*.egg-info/ 2>/dev/null || true
	@echo "✓ Cleanup complete"

# Generate locked requirements from .in files with UV
requirements: prepare-runtime-dirs
	docker compose run --rm -v "$(PWD):/app" api uv pip compile requirements.in -o requirements.txt
	docker compose run --rm -v "$(PWD):/app" api uv pip compile requirements-dev.in -o requirements-dev.txt

# Sync environment with locked requirements using UV
sync: dev-install
	@echo "Docker images rebuilt using locked requirements."

run-server: prepare-runtime-dirs
	docker compose run --rm api python -m psychoanalyst_app.server

# Generate JSON Schemas from Pydantic models (Docker)
generate-schemas: prepare-runtime-dirs
	@echo "🔧 Generating JSON schemas from Pydantic models (Docker)..."
	docker compose run --rm -v "$(PWD)/schemas:/app/schemas" api \
		env PYTHONPATH=/app/src python -m psychoanalyst_app.schemas.generate_schemas \
		--output-dir /app/schemas

# Validate generated schemas (comprehensive validation, Docker)
validate-schemas: prepare-runtime-dirs generate-schemas
	docker compose run --rm -v "$(PWD)/schemas:/app/schemas" -v "$(PWD)/scripts:/app/scripts" api \
		env PYTHONPATH=/app/src python scripts/validate_schemas.py

# Generate committed WebSocket protocol constants.
generate-ws-protocol: prepare-runtime-dirs
	docker compose run --rm -v "$(PWD)/scripts:/app/scripts" -v "$(PWD)/schemas:/app/schemas" -v "$(PWD)/src:/app/src" -v "$(PWD)/console-ui/src:/app/console-ui/src" api \
		env PYTHONPATH=/app/src python scripts/generate_ws_protocol.py

# Validate generated backend and console WebSocket constants without rewriting files.
validate-generated-contracts: prepare-runtime-dirs
	docker compose run --rm -v "$(PWD)/scripts:/app/scripts" -v "$(PWD)/schemas:/app/schemas" -v "$(PWD)/src:/app/src" -v "$(PWD)/console-ui/src:/app/console-ui/src" api \
		env PYTHONPATH=/app/src python scripts/generate_ws_protocol.py --check

# Validate docs metadata and canonical docs index (Docker)
validate-docs: prepare-runtime-dirs
	docker compose run --rm -v "$(PWD)/docs:/app/docs" -v "$(PWD)/scripts:/app/scripts" api \
		env PYTHONPATH=/app/src python scripts/validate_docs_metadata.py

# Validate architecture budgets and layering boundaries (Docker)
validate-architecture: prepare-runtime-dirs
	docker compose run --rm -v "$(PWD)/src:/app/src" -v "$(PWD)/scripts:/app/scripts" api \
		env PYTHONPATH=/app/src python scripts/check_architecture_budgets.py

# ============================================
# Docker Development Commands
# ============================================

# Start the backend API service.
docker-up: prepare-runtime-dirs
	docker compose up --build --remove-orphans api

# Stop all Docker containers
docker-down:
	docker compose down

# Run tests in isolated Docker environment
# NOTE: This is usually not needed - use 'make test' for local testing
# Docker tests are mainly for CI/CD or when you need complete isolation
docker-test: test

# Run specific test file
docker-test-one:
	docker compose -f docker-compose.yml --profile test run --rm --no-deps test pytest $(TEST)

# Shell into API container
docker-shell:
	docker compose exec api bash

# View logs (default: all services, or specify SERVICE=api)
docker-logs:
	docker compose logs -f $(SERVICE)

# View API logs only (useful when console-ui is running interactively)
docker-logs-api:
	@echo "📋 Viewing API logs..."
	@echo "API logs are suppressed from console output to keep UI clean."
	@echo "Use this command to monitor API activity when debugging."
	@echo ""
	@if docker compose ps | grep -q "api-usertest"; then \
		docker compose logs -f api-usertest; \
	else \
		docker compose logs -f api; \
	fi

# Start database viewer for debugging
# Usage:
#   make docker-db-view             # View local DB (default)
#   make docker-db-view DB=usertest # View usertest DB
# Note: The automated test database is stored in the Docker-managed test-data
# volume. It is intentionally not exposed through docker-db-view. Use
# make docker-test-reset to remove it; the next test run recreates it.
docker-db-view:
	@DB_NAME=$${DB:-local}; \
	case $$DB_NAME in \
		local) DB_FILE=psychoanalyst.db ;; \
		usertest) DB_FILE=psychoanalyst_usertest.db ;; \
		*) echo "❌ Invalid DB. Use: local or usertest"; \
		   echo ""; \
		   echo "Note: The automated test database is stored in the Docker-managed"; \
		   echo "      test-data volume. It is intentionally not exposed through"; \
		   echo "      docker-db-view. Use make docker-test-reset to remove it;"; \
		   echo "      the next test run recreates it."; \
		   echo ""; \
		   echo "Example: make docker-db-view DB=usertest"; \
		   exit 1 ;; \
	esac; \
	if [ ! -f "data/$$DB_FILE" ]; then \
		echo "❌ Database file not found: data/$$DB_FILE"; \
		echo ""; \
		echo "Available databases:"; \
		ls -1 data/*.db 2>/dev/null || echo "  (none)"; \
		echo ""; \
		echo "💡 Tip: Run the app to create databases:"; \
		echo "   - Local: make ui-console"; \
		echo "   - Usertest: make ui-console-test"; \
		exit 1; \
	fi; \
	if [ ! -s "data/$$DB_FILE" ]; then \
		echo "⚠️  Warning: Database file is empty (0 bytes): data/$$DB_FILE"; \
		echo ""; \
		echo "💡 This database hasn't been initialized yet. Run the app to create tables:"; \
		echo "   - Local: make ui-console"; \
		echo "   - Usertest: make ui-console-test"; \
		echo ""; \
		read -p "Continue anyway? (y/N) " -n 1 -r; \
		echo ""; \
		if [[ ! $$REPLY =~ ^[Yy]$$ ]]; then \
			echo "Cancelled."; \
			exit 1; \
		fi; \
	fi; \
	echo "🔍 Starting database viewer for $$DB_NAME database..."; \
	echo "📁 Database file: data/$$DB_FILE"; \
	echo "🌐 Access at: http://localhost:8080"; \
	echo ""; \
	DB_FILE=$$DB_FILE docker compose --profile debug up db-viewer

# Reset test database (removes test data volume)
docker-test-reset:
	docker compose -f docker-compose.yml --profile test down --volumes --remove-orphans

# Clean up all Docker resources
docker-clean:
	docker compose down --volumes --rmi local
	docker system prune -f

# ============================================
# UI Mode Selection Commands
# ============================================

# Console UI Service (WebSocket client)
ui-console: prepare-runtime-dirs
	@printf "\n[%s] make ui-console\n" "$$(date -Iseconds)" >> $(CONSOLE_UI_LOG)
	@docker compose up --build --remove-orphans -d api >> $(CONSOLE_UI_LOG) 2>&1
	@docker compose run --rm -it console-ui 2>> $(CONSOLE_UI_LOG)

# Console UI Service (usertest mode)
ui-console-test: prepare-runtime-dirs
	$(MAKE) check-usertest-key
	@printf "\n[%s] make ui-console-test\n" "$$(date -Iseconds)" >> $(CONSOLE_UI_LOG_TEST)
	@docker compose --profile usertest-console up --build --remove-orphans -d api-usertest >> $(CONSOLE_UI_LOG_TEST) 2>&1
	@docker compose --profile usertest-console run --rm -it console-ui-usertest 2>> $(CONSOLE_UI_LOG_TEST)

# Local full-stack diagnostic probe. This is intentionally not a CI gate.
probe: prepare-runtime-dirs
	@./scripts/probe_local_llm.sh

probe-console-deterministic: prepare-runtime-dirs
	@./scripts/probe_deterministic.sh

probe-console-intake-notes: prepare-runtime-dirs
	@./scripts/probe_intake_notes.sh

probe-logs:
	@if [ -f logs/workflow-probes/latest/summary.md ]; then \
		cat logs/workflow-probes/latest/summary.md; \
	else \
		echo "No workflow probe summary found at logs/workflow-probes/latest/summary.md"; \
		exit 1; \
	fi

probe-db:
	@if [ -f logs/workflow-probes/latest/created_rows.json ]; then \
		cat logs/workflow-probes/latest/created_rows.json; \
	else \
		echo "No workflow probe database artifact found at logs/workflow-probes/latest/created_rows.json"; \
		exit 1; \
	fi

# ============================================
# DevContainer Commands
# ============================================

# Rebuild devcontainer without cache
devcontainer-rebuild:
	@echo "🔄 Rebuilding devcontainer..."
	@echo "This will rebuild the container from scratch without using cache."
	@echo ""
	@if command -v devcontainer > /dev/null 2>&1; then \
		devcontainer build --workspace-folder . --no-cache; \
	else \
		echo "❌ devcontainer CLI not found."; \
		echo "Install it with: npm install -g @devcontainers/cli"; \
		echo ""; \
		echo "Alternative: Rebuild from VSCode:"; \
		echo "1. Open Command Palette (Ctrl+Shift+P)"; \
		echo "2. Run 'Dev Containers: Rebuild Container'"; \
		exit 1; \
	fi

# Test devcontainer configuration
devcontainer-test:
	@echo "✅ Testing devcontainer setup..."
	@test -f .devcontainer/devcontainer.json && echo "✓ .devcontainer/devcontainer.json exists"
	@test -f .vscode/settings.json && echo "✓ .vscode/settings.json exists"
	@test -f .vscode/extensions.json && echo "✓ .vscode/extensions.json exists"
	@test -f .vscode/launch.json && echo "✓ .vscode/launch.json exists"
	docker compose --profile devcontainer config --quiet
	@echo "✓ Docker Compose devcontainer profile is valid"

# Open project in VSCode devcontainer
devcontainer-open:
	@echo "🚀 Opening project in VSCode devcontainer..."
	@if command -v code > /dev/null 2>&1; then \
		code --folder-uri vscode-remote://dev-container+$(shell pwd | sed 's/\//\%2F/g')/app; \
	else \
		echo "❌ VSCode CLI not found."; \
		echo ""; \
		echo "Manual steps:"; \
		echo "1. Open this folder in VSCode"; \
		echo "2. Press Ctrl+Shift+P"; \
		echo "3. Run 'Dev Containers: Reopen in Container'"; \
	fi
check-usertest-key: check-usertest-env
	@set -a && . ./.env.usertest && set +a && \
	if [ -z "$${GOOGLE_API_KEY:-}" ] || [ "$${GOOGLE_API_KEY}" = "test_mock_api_key_for_testing" ] || [ "$${GOOGLE_API_KEY}" = "your_gemini_api_key_here" ]; then \
		echo "❌ GOOGLE_API_KEY is not configured in .env.usertest."; \
		echo "   Please edit .env.usertest and provide your real API key before running user-test commands."; \
		echo "   (This profile uses real Gemini responses: MODEL_NAME=$${MODEL_NAME:-unset})"; \
		exit 1; \
	fi

check-usertest-env:
	@if [ ! -f .env.usertest ]; then \
		echo "❌ .env.usertest is missing."; \
		echo "   Copy .env.usertest.template to .env.usertest and configure the backend LLM."; \
		exit 1; \
	fi
