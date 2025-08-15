.PHONY: help install dev-install format lint test test-unit test-integration test-devcontainer clean

# Default target
help:
	@echo "Available targets:"
	@echo "  install           - Install production dependencies"
	@echo "  dev-install       - Install development dependencies"
	@echo "  format            - Format code with black"
	@echo "  lint              - Lint code with ruff"
	@echo "  test              - Run all tests"
	@echo "  test-unit         - Run unit tests only"
	@echo "  test-integration  - Run integration tests only"
	@echo "  test-devcontainer - Run devcontainer setup tests"
	@echo "  clean             - Clean up generated files"

# Install production dependencies
install:
	pip install -r requirements.txt

# Install development dependencies
dev-install:
	pip install -r requirements-dev.txt

# Format code with black
format:
	black .

# Lint code with ruff
lint:
	ruff check .

# Run all tests
test:
	pytest

# Run unit tests only
test-unit:
	pytest -m unit

# Run integration tests only
test-integration:
	pytest -m integration

# Run devcontainer setup tests
test-devcontainer:
	pytest tests/test_devcontainer.py -v

# Clean up generated files
clean:
	rm -rf __pycache__ */
__pycache__ */
*.pyc */
*.pyo */
*.pyd */
.pytest_cache/
.mypy_cache/
.pytype/
build/
dist/
*.egg-info/
data/vector_db/
data/psychoanalyst.db
data/psychoanalyst_test.db

# Generate locked requirements from .in files
requirements:
	pip-compile requirements.in
	pip-compile requirements-dev.in

# Sync environment with locked requirements
sync:
	pip-sync requirements.txt requirements-dev.txt

# Run the application
run:
	python src/main.py

# Run with Docker
docker-run:
	docker-compose up --build

# Run Docker in detached mode
docker-detach:
	docker-compose up -d

# Stop Docker containers
docker-stop:
	docker-compose down
