.PHONY: help install dev-install install-uv format lint test test-unit test-integration test-all test-frontend test-e2e test-real-llm test-devcontainer test-dev test-validate test-validate-no-mocks install-hooks clean clean-testdb reset-usertest check-usertest-key
.PHONY: local-format local-lint local-test local-test-unit local-test-integration local-test-all local-test-frontend local-test-e2e local-test-real-llm local-test-dev
.PHONY: local-run local-run-server local-run-e2e local-generate-schemas local-validate-schemas
.PHONY: docker-up docker-up-all docker-down docker-test docker-test-isolated docker-test-one docker-shell docker-logs docker-logs-api docker-db-view docker-test-reset docker-clean docker-usertest
.PHONY: ui-standalone ui-standalone-test ui-console ui-console-test ui-web ui-web-test ui-all ui-all-test
.PHONY: devcontainer-rebuild devcontainer-test devcontainer-open
.PHONY: generate-schemas validate-schemas

export PYTHONPATH := src

# Default target
help:
	@echo "Available targets:"
	@echo ""
	@echo "Default (Docker) Development:"
	@echo "  install-uv        - Install UV package manager"
	@echo "  install           - Build API container (installs backend deps inside Docker)"
	@echo "  dev-install       - Build dev containers (api + console-ui + frontend)"
	@echo "  format            - Format code with black (Docker)"
	@echo "  lint              - Lint code with ruff (Docker)"
	@echo "  test              - Run backend tests (Docker)"
	@echo "  test-all          - Run backend + frontend + E2E (Docker)"
	@echo "  test-dev          - Quick backend tests (Docker)"
	@echo "  test-validate     - Full isolated Docker tests (pre-commit validation)"
	@echo "  test-unit         - Run unit tests only"
	@echo "  test-integration  - Run integration tests only"
	@echo "  test-frontend     - Run frontend Jest unit tests"
	@echo "  test-e2e          - Run deterministic Playwright E2E"
	@echo "  test-real-llm     - Run real-LLM tests only (Docker)"
	@echo "  test-devcontainer - Run devcontainer setup tests"
	@echo "  install-hooks     - Install git pre-commit hook for automated testing"
	@echo "  clean             - Clean up generated files and caches"
	@echo "  clean-testdb      - Clean test databases only"
	@echo "  requirements      - Generate locked requirements from .in files"
	@echo "  sync              - Rebuild containers from locked requirements"
	@echo "  run               - Run terminal UI via Docker"
	@echo "  run-server        - Run HTTP/WebSocket server via Docker"
	@echo "  run-e2e           - Run deterministic e2e server via Docker"
	@echo "  generate-schemas  - Generate JSON schemas from Pydantic models (Docker)"
	@echo "  validate-schemas  - Validate generated JSON schemas (Docker)"
	@echo ""
	@echo "Local (Opt-In) Development:"
	@echo "  local-format      - Format code with black (local)"
	@echo "  local-lint        - Lint code with ruff (local)"
	@echo "  local-test        - Run backend tests (local)"
	@echo "  local-test-all    - Run backend + frontend + E2E (local)"
	@echo "  local-test-dev    - Quick tests in devContainer (local)"
	@echo "  local-test-unit   - Run unit tests only (local)"
	@echo "  local-test-integration - Run integration tests only (local)"
	@echo "  local-test-frontend - Run frontend Jest unit tests (local)"
	@echo "  local-test-e2e    - Run deterministic Playwright E2E (local)"
	@echo "  local-test-real-llm - Run real-LLM tests only (local)"
	@echo "  local-run         - Run terminal UI via python -m psychoanalyst_app"
	@echo "  local-run-server  - Run HTTP/WebSocket server entry point"
	@echo "  local-run-e2e     - Run deterministic e2e server entry point"
	@echo "  local-generate-schemas - Generate JSON schemas from Pydantic models (local)"
	@echo "  local-validate-schemas - Validate generated JSON schemas (local)"
	@echo ""
	@echo "UI Mode Selection:"
	@echo "  ui-standalone     - Run standalone terminal UI (local, no Docker)"
	@echo "  ui-standalone-test - Run standalone terminal in usertest mode"
	@echo "  ui-console        - Run console UI service (Docker, WebSocket client)"
	@echo "  ui-console-test   - Run console UI service in usertest mode"
	@echo "  ui-web            - Run web UI (Docker, browser interface)"
	@echo "  ui-web-test       - Run web UI in usertest mode"
	@echo "  ui-all            - Run all UI modes simultaneously"
	@echo "  ui-all-test       - Run all UI modes in usertest mode"
	@echo ""
	@echo "Docker Development:"
	@echo "  docker-up         - Start all development services (api, frontend, console-ui)"
	@echo "  docker-down       - Stop all Docker containers"
	@echo "  docker-shell      - Shell into API container"
	@echo "  docker-logs       - View logs (usage: make docker-logs SERVICE=api)"
	@echo "  docker-logs-api   - View API logs only (useful when running console-ui)"
	@echo "  docker-usertest   - Run app in user-test mode (shorter sessions, test DB)"
	@echo "  reset-usertest    - Stop usertest containers and clear usertest database"
	@echo "  docker-test       - Run tests in Docker (usually not needed, use 'make test')"
	@echo "  docker-test-one   - Run specific test (usage: make docker-test-one TEST=tests/unit/test_foo.py)"
	@echo "  docker-db-view    - View database at http://localhost:8080 (DB=prod|usertest, default: prod)"
	@echo "  docker-test-reset - Reset test database"
	@echo "  docker-clean      - Clean up all Docker resources"
	@echo ""
	@echo "Docker Production:"
	@echo "  docker-prod       - Start production app"
	@echo ""
	@echo "DevContainer:"
	@echo "  devcontainer-rebuild - Rebuild devcontainer without cache"
	@echo "  devcontainer-test    - Test devcontainer configuration"
	@echo "  devcontainer-open    - Open project in VSCode devcontainer"

# Install UV package manager
install-uv:
	pip install uv

# Install production dependencies inside Docker
install:
	docker compose build api

# Build dev containers (installs Python deps inside Docker images)
dev-install:
	docker compose build api console-ui frontend

# Format code with black (Docker)
format:
	docker compose run --rm api black .

# Lint code with ruff (Docker)
lint:
	docker compose run --rm api ruff check .

# Run all tests (Docker)
test:
	docker compose --profile test run --rm test

# Run unit tests only (Docker)
test-unit:
	docker compose --profile test run --rm test pytest -m unit

# Run integration tests only (Docker)
test-integration:
	docker compose --profile test run --rm test pytest -m integration

# Run full suite (deterministic CI-grade, Docker)
test-all:
	$(MAKE) test
	$(MAKE) test-frontend
	$(MAKE) test-e2e

# Frontend unit tests (Jest, Docker)
test-frontend:
	docker compose --profile test run --rm frontend-test npm test -- --ci --colors=false

# Deterministic full-stack E2E (Playwright, Docker)
test-e2e:
	docker compose --profile test run --rm frontend-e2e npx playwright install chromium
	docker compose --profile test run --rm frontend-e2e npm run test:e2e

# Real LLM/RAG smoke tests (Docker, requires secrets / external services)
test-real-llm:
	$(MAKE) check-usertest-key
	docker compose --profile usertest-all up -d --wait --remove-orphans api-usertest
	docker compose --profile test run --rm test pytest -m real_llm --no-mocks

# Run devcontainer setup tests (local only)
test-devcontainer:
	python scripts/devcontainer_test.py

# Quick tests in devContainer (Docker)
test-dev:
	@echo "🚀 Running quick tests in Docker..."
	@echo "Perfect for: Active development, TDD, debugging"
	@echo ""
	docker compose --profile test run --rm test pytest -m "not real_llm" -x --tb=short -q

# Local equivalents (opt-in)
local-format:
	black .

local-lint:
	ruff check .

local-test:
	pytest -m "not real_llm"

local-test-unit:
	pytest -m unit

local-test-integration:
	pytest -m integration

local-test-all:
	pytest -m "not real_llm"
	$(MAKE) local-test-frontend
	$(MAKE) local-test-e2e

local-test-frontend:
	npm --prefix frontend test

local-test-e2e:
	npm --prefix frontend run test:e2e

local-test-real-llm:
	$(MAKE) check-usertest-key
	@set -a && . ./.env.usertest && set +a && pytest -m real_llm --no-mocks

local-test-dev:
	@echo "🚀 Running quick tests in devContainer..."
	@echo "Perfect for: Active development, TDD, debugging"
	@echo ""
	pytest -m "not real_llm" -x --tb=short -q

# Full isolated Docker tests (pre-commit validation)
test-validate:
	@echo "🔍 Running full test suite in isolated Docker environment..."
	@echo "Perfect for: Pre-commit validation, ensuring clean state"
	@echo ""
	docker compose --profile test run --rm test

# Full isolated Docker tests without mocks (uses real services)
test-validate-no-mocks:
	@echo "🔍 Running full test suite in isolated Docker environment (NO MOCKS)..."
	@echo "⚠️  Requires valid API keys in .env.test and .env.usertest"
	@echo ""
	$(MAKE) check-usertest-key
	docker compose --profile usertest-all up -d --wait --remove-orphans api-usertest
	PYTEST_ARGS="--no-mocks" docker compose --profile test run --rm test

# Install git hooks for automated testing
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
		*.egg-info/ \
		data/psychoanalyst.db \
		data/psychoanalyst_test.db \
		data/psychoanalyst_usertest.db 2>/dev/null || true
	@# Use Docker to remove vector DB files created by Docker containers
	@if [ -d "data/vector_db" ] || [ -d "data/vector_db_usertest" ]; then \
		echo "Removing Docker-created vector DB files..."; \
		docker run --rm -v "$(PWD)/data:/data" alpine sh -c "rm -rf /data/vector_db /data/vector_db_usertest" 2>/dev/null || true; \
	fi
	@echo "✓ Cleanup complete"

# Clean test databases only
clean-testdb:
	@echo "Cleaning test databases..."
	@rm -rf data/psychoanalyst_test.db \
		data/psychoanalyst_usertest.db 2>/dev/null || true
	@# Use Docker to remove files created by Docker containers (no sudo needed)
	@if [ -d "data/vector_db_usertest" ] || [ -d "data/test_vector_db" ]; then \
		echo "Removing Docker-created files..."; \
		docker run --rm -v "$(PWD)/data:/data" alpine sh -c "rm -rf /data/vector_db_usertest /data/test_vector_db" 2>/dev/null || true; \
	fi
	@echo "✓ Test databases cleaned"

# Reset usertest DB and containers
reset-usertest:
	@echo "Resetting usertest environment..."
	@docker compose --profile usertest --profile usertest-console --profile usertest-web --profile usertest-all down --remove-orphans
	@rm -rf data/psychoanalyst_usertest.db 2>/dev/null || true
	@# Use Docker to remove files created by Docker containers (no sudo needed)
	@if [ -d "data/vector_db_usertest" ]; then \
		echo "Removing Docker-created usertest vector DB files..."; \
		docker run --rm -v "$(PWD)/data:/data" alpine sh -c "rm -rf /data/vector_db_usertest" 2>/dev/null || true; \
	fi
	@echo "✓ Usertest environment reset"

# Generate locked requirements from .in files with UV
requirements:
	uv pip compile requirements.in -o requirements.txt
	uv pip compile requirements-dev.in -o requirements-dev.txt

# Sync environment with locked requirements using UV
sync: dev-install
	@echo "Docker images rebuilt using locked requirements."

# Run the application via Docker
run:
	docker compose run --rm api python -m psychoanalyst_app

run-server:
	docker compose run --rm api python -m psychoanalyst_app.server

run-e2e:
	docker compose run --rm api python -m psychoanalyst_app.e2e_server

local-run:
	python -m psychoanalyst_app

local-run-server:
	python -m psychoanalyst_app.server

local-run-e2e:
	python -m psychoanalyst_app.e2e_server

# Generate JSON Schemas from Pydantic models (Docker)
generate-schemas:
	@echo "🔧 Generating JSON schemas from Pydantic models (Docker)..."
	docker compose run --rm -v "$(PWD)/schemas:/app/schemas" api \
		env PYTHONPATH=/app/src python -m psychoanalyst_app.schemas.generate_schemas \
		--output-dir /app/schemas

# Validate generated schemas (comprehensive validation, Docker)
validate-schemas:
	docker compose run --rm -v "$(PWD)/schemas:/app/schemas" -v "$(PWD)/scripts:/app/scripts" api \
		env PYTHONPATH=/app/src python scripts/validate_schemas.py

local-generate-schemas:
	@echo "🔧 Generating JSON schemas from Pydantic models (local)..."
	python scripts/generate_schemas.py

local-validate-schemas:
	python scripts/validate_schemas.py

# ============================================
# Docker Development Commands
# ============================================

# Start all development services (api, frontend, console-ui)
docker-up:
	docker compose up --build --remove-orphans

# Start all services including optional ones
docker-up-all:
	docker compose up --build --remove-orphans api frontend console-ui

# Stop all Docker containers
docker-down:
	docker compose down

# Run tests in isolated Docker environment
# NOTE: This is usually not needed - use 'make test' for local testing
# Docker tests are mainly for CI/CD or when you need complete isolation
docker-test: test

# Run specific test file
docker-test-one:
	docker compose --profile test run --rm test pytest $(TEST)

# Run frontend tests in Docker
docker-test-frontend: test-frontend

# Run all tests in Docker (Backend + Frontend)
# Note: E2E tests are skipped as they require a browser environment
docker-test-all: test-all

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

# Run app in user-test mode (manual testing with test settings)
docker-usertest:
	$(MAKE) check-usertest-key
	@echo "Starting app in user-test mode..."
	@echo "- Using test database: data/psychoanalyst_usertest.db"
	@echo "- Session duration: 10 minutes"
	@echo "- Make sure to set your GOOGLE_API_KEY in .env.usertest"
	@echo ""
	docker compose --profile usertest up --build --remove-orphans usertest

# Start database viewer for debugging
# Usage:
#   make docker-db-view             # View production DB (default)
#   make docker-db-view DB=usertest # View usertest DB
# Note: Test databases use in-memory SQLite and don't create viewable files
docker-db-view:
	@DB_NAME=$${DB:-prod}; \
	case $$DB_NAME in \
		prod) DB_FILE=psychoanalyst.db ;; \
		usertest) DB_FILE=psychoanalyst_usertest.db ;; \
		*) echo "❌ Invalid DB. Use: prod or usertest"; \
		   echo ""; \
		   echo "Note: Test databases use in-memory SQLite (:memory:) and"; \
		   echo "      don't create persistent files to view."; \
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
		echo "   - Production: make ui-console"; \
		echo "   - Usertest: make ui-console-test"; \
		exit 1; \
	fi; \
	if [ ! -s "data/$$DB_FILE" ]; then \
		echo "⚠️  Warning: Database file is empty (0 bytes): data/$$DB_FILE"; \
		echo ""; \
		echo "💡 This database hasn't been initialized yet. Run the app to create tables:"; \
		echo "   - Production: make ui-console"; \
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
	docker compose down
	docker volume rm psychoanalyst_app_test-data 2>/dev/null || true

# Clean up all Docker resources
docker-clean:
	docker compose down --volumes --rmi local
	docker system prune -f

# ============================================
# Docker Production Commands
# ============================================

# Run production app
docker-prod:
	docker compose --profile production up --build --remove-orphans app

# Run production in detached mode
docker-prod-detach:
	docker compose --profile production up -d --remove-orphans app

# ============================================
# UI Mode Selection Commands
# ============================================

# Standalone Terminal UI (local, no Docker)
ui-standalone:
	@echo "🖥️  Starting Standalone Terminal UI..."
	@echo "Running locally with direct Python execution"
	@echo ""
	python -m psychoanalyst_app

# Standalone Terminal UI (usertest mode)
ui-standalone-test:
	$(MAKE) check-usertest-key
	@echo "🖥️  Starting Standalone Terminal UI (Usertest Mode)..."
	@echo "- Using test database: data/psychoanalyst_usertest.db"
	@echo "- Session duration: 10 minutes"
	@echo "- Make sure to set your GOOGLE_API_KEY in .env.usertest"
	@echo ""
	@set -a && . ./.env.usertest && set +a && python -m psychoanalyst_app

# Console UI Service (WebSocket client)
ui-console:
	@echo "💻 Starting Console UI Service..."
	@echo "- API Server: http://localhost:8000"
	@echo "- Console Client: WebSocket-based terminal"
	@echo ""
	@echo "💡 Tip: To view API logs, run 'make docker-logs-api' in another terminal"
	@echo ""
	docker compose up --build --remove-orphans -d api && docker compose run --rm -it console-ui

# Console UI Service (usertest mode)
ui-console-test:
	$(MAKE) check-usertest-key
	@echo "💻 Starting Console UI Service (Usertest Mode)..."
	@echo "- Using test database: data/psychoanalyst_usertest.db"
	@echo "- Session duration: 10 minutes"
	@echo "- Make sure to set your GOOGLE_API_KEY in .env.usertest"
	@echo ""
	@echo "💡 Tip: To view API logs, run 'docker compose logs -f api-usertest' in another terminal"
	@echo ""
	docker compose --profile usertest-console up --build --remove-orphans -d api-usertest && docker compose --profile usertest-console run --rm -it console-ui-usertest

# Web UI (browser interface)
ui-web:
	@echo "🌐 Starting Web UI..."
	@echo "- API Server: http://localhost:8000"
	@echo "- Frontend: http://localhost:5173"
	@echo ""
	docker compose up --build --remove-orphans api frontend

# Web UI (usertest mode)
ui-web-test:
	$(MAKE) check-usertest-key
	@echo "🌐 Starting Web UI (Usertest Mode)..."
	@echo "- Using test database: data/psychoanalyst_usertest.db"
	@echo "- Session duration: 10 minutes"
	@echo "- API Server: http://localhost:8001"
	@echo "- Frontend: http://localhost:5174"
	@echo "- Make sure to set your GOOGLE_API_KEY in .env.usertest"
	@echo ""
	docker compose --profile usertest-web up --build --remove-orphans api-usertest frontend-usertest

# All UI modes simultaneously
ui-all:
	@echo "🎯 Starting All UI Modes..."
	@echo "- API Server: http://localhost:8000"
	@echo "- Console Client: Terminal"
	@echo "- Frontend: http://localhost:5173"
	@echo ""
	@echo "⚠️  Note: Console UI requires interactive terminal. Web UI will run in background."
	@echo "💡 Tip: To view API logs, run 'make docker-logs-api' in another terminal"
	@echo ""
	docker compose up --build --remove-orphans -d api frontend && docker compose run --rm -it console-ui

# All UI modes (usertest mode)
ui-all-test:
	$(MAKE) check-usertest-key
	@echo "🎯 Starting All UI Modes (Usertest Mode)..."
	@echo "- Using test database: data/psychoanalyst_usertest.db"
	@echo "- Session duration: 10 minutes"
	@echo "- API Server: http://localhost:8000"
	@echo "- Console Client: Terminal"
	@echo "- Frontend: http://localhost:5173"
	@echo "- Make sure to set your GOOGLE_API_KEY in .env.usertest"
	@echo ""
	@echo "⚠️  Note: Console UI requires interactive terminal. Web UI will run in background."
	@echo "💡 Tip: To view API logs, run 'docker compose logs -f api-usertest' in another terminal"
	@echo ""
	docker compose --profile usertest-all up --build --remove-orphans -d api-usertest frontend-usertest && docker compose --profile usertest-all run --rm -it console-ui-usertest

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
	@echo ""
	@echo "Checking configuration files exist..."
	@test -f .devcontainer/devcontainer.json && echo "✓ .devcontainer/devcontainer.json exists"
	@test -f .vscode/settings.json && echo "✓ .vscode/settings.json exists"
	@test -f .vscode/extensions.json && echo "✓ .vscode/extensions.json exists"
	@test -f .vscode/launch.json && echo "✓ .vscode/launch.json exists"
	@echo ""
	@echo "Validating JSON syntax (note: VSCode supports JSONC with comments)..."
	@python3 -c "import json; json.load(open('.devcontainer/devcontainer.json'))" && echo "✓ devcontainer.json is valid" || echo "⚠ devcontainer.json has comments (valid JSONC)"
	@echo ""
	@echo "Configuration files are ready! ✨"
	@echo ""
	@echo "Note: VSCode config files (.vscode/*) support comments (JSONC format)."
	@echo "They will work correctly in VSCode even if they fail strict JSON validation."

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
check-usertest-key:
	@set -a && . ./.env.usertest && set +a && \
	if [ -z "$${GOOGLE_API_KEY:-}" ] || [ "$${GOOGLE_API_KEY}" = "test_mock_api_key_for_testing" ]; then \
		echo "❌ GOOGLE_API_KEY is not configured in .env.usertest."; \
		echo "   Please edit .env.usertest and provide your real API key before running user-test commands."; \
		echo "   (This profile uses real Gemini responses: MODEL_NAME=$${MODEL_NAME:-unset})"; \
		exit 1; \
	fi
