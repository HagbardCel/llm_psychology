# Project Improvement Plan

## Executive Summary
This plan outlines the steps to modernize the "Virtual LLM-Driven Psychoanalyst" codebase. The primary goals are to achieve a lean, maintainable architecture by removing legacy artifacts, enforcing best practices, and finalizing the transition to a pure Trio-based async architecture.

## 1. Codebase Cleanup & Organization

### 1.1 Remove Legacy & Temporary Files
- [ ] **Delete `trio_poc/`**: The main application has successfully migrated to Trio; this proof-of-concept is obsolete.
- [ ] **Delete `validate_trio.py`**: Temporary validation script no longer needed.
- [ ] **Delete `reset_databases.py`**: Database management should be handled via `TrioDatabaseService` methods or `make` commands.
- [ ] **Delete `simple_performance_test.py`**: Ad-hoc testing script to be replaced by proper integration tests.

### 1.2 Documentation Consolidation
- [ ] **Archive/Delete Root Markdown Files**: The root directory is cluttered with planning documents.
    - Move `*_PLAN.md`, `*_STATUS.md`, `*_ANALYSIS.md` to `docs/archive/` or delete if fully implemented.
    - Keep `README.md`, `CLAUDE.md`, and `docs/`.
    - Create a single `ROADMAP.md` if future planning is needed.

## 2. Code Refactoring & Best Practices

### 2.1 Configuration Modernization
- [ ] **Remove Legacy `Config` Class**: `src/config.py` contains a `Config` class explicitly marked "For backward compatibility".
    - Refactor `src/container/service_container.py` to use the `settings` instance from `src/config.py`.
    - Refactor `src/main.py` and other consumers to use `settings`.
    - Delete the `Config` class.

### 2.2 Service Container Improvements
- [ ] **Remove Hardcoded API Key Checks**: `src/container/service_container.py` checks for `"your_actual_google_gemini_api_key_here"`.
    - Replace with a robust validation in `settings` or let the service initialization fail naturally with a clear error message.
- [ ] **Type Safety**: Ensure strict type checking is enabled.
    - Verify `mypy` configuration.
    - Ensure all service retrieval methods in `ServiceContainer` are properly typed (e.g., using `overload` or specific getter methods instead of generic `get`).

### 2.3 Database Service Refinement
- [ ] **Remove Legacy Fallbacks**: `src/services/trio_db_service.py` contains commented-out legacy initialization code and fallback logic.
    - Remove `if self.migration_service: ... else: ...` fallback. `MigrationService` should be mandatory.
    - Remove commented-out `_sync_initialize_legacy` calls.

## 3. Architecture & Testing

### 3.1 Testing Strategy
- [ ] **Verify Test Suite**: Ensure `pytest` runs correctly with the Trio plugin.
- [ ] **Remove Legacy Tests**: Scan `tests/` for any synchronous tests that haven't been ported to Trio and remove/update them.

### 3.2 Dependency Management
- [ ] **Review Requirements**: Ensure `requirements.txt` and `requirements-dev.txt` are up-to-date and minimal.

## 4. Implementation Roadmap

### Phase 1: Cleanup (Immediate)
1. Delete identified legacy files.
2. Move documentation to `docs/archive`.

### Phase 2: Refactoring (High Priority)
1. Refactor `config.py` and update consumers.
2. Clean up `ServiceContainer` and `TrioDatabaseService`.

### Phase 3: Verification
1. Run full test suite.
2. Perform manual smoke test of the CLI.
