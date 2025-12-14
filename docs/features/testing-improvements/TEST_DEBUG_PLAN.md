# Test Failure Debugging Plan: test_natural_patient_flow

## Error Summary

**Test**: `tests/integration/test_natural_patient_flow.py::test_natural_patient_flow`
**Error**: `ConnectionRefusedError: [Errno 111] Error connecting to ('127.0.0.1', 50959): Connection refused`
**Root Cause**: WebSocket connection attempt before server is ready to accept connections

## Problem Analysis

### 1. **Orchestrator Initialization Issue** (CRITICAL)
**Location**: [test_natural_patient_flow.py:277](tests/integration/test_natural_patient_flow.py#L277)

```python
yield {
    "url": f"http://127.0.0.1:{port}",
    "ws_url": f"ws://127.0.0.1:{port}",
    "orchestrator": server.orchestrator,  # ⚠️ PROBLEM: orchestrator doesn't exist yet!
    "db_service": db_service,
}
```

**Issue**: The fixture tries to access `server.orchestrator`, but this attribute is only created inside `TrioServer.run()` at line 369, which runs asynchronously AFTER the fixture starts yielding.

**Evidence**:
- [trio_server.py:369](src/trio_server.py#L369): `self._initialize_orchestration(nursery)` is called inside `run()`
- [trio_server.py:65-67](src/trio_server.py#L65-L67): `self.orchestrator` is created in `_initialize_orchestration()`
- The test fixture starts the server with `nursery.start_soon(server.run)` but immediately yields, before `run()` has a chance to initialize the orchestrator

### 2. **Race Condition: Server Not Ready**
**Location**: [test_natural_patient_flow.py:271-273](tests/integration/test_natural_patient_flow.py#L271-L273)

```python
async with trio.open_nursery() as nursery:
    nursery.start_soon(server.run)
    await trio.sleep(0.5)  # ⚠️ PROBLEM: Not enough time, no proper signal
```

**Issue**: The test waits 0.5 seconds, but there's no guarantee that:
1. Hypercorn has started accepting connections
2. The orchestration layer is initialized
3. The WebSocket endpoint is ready to handle connections

**Evidence**:
- Server logs show: "🚀 Trio server running on http://127.0.0.1:50959" (line 62)
- But connection is refused (line 25), indicating Hypercorn isn't ready yet
- The print statement happens BEFORE `serve()` is called at [trio_server.py:374](src/trio_server.py#L374)

### 3. **No Startup Coordination**
**Location**: [trio_server.py:354-374](src/trio_server.py#L354-L374)

```python
async def run(self, task_status=trio.TASK_STATUS_IGNORED):
    """Run the Trio server using Hypercorn."""
    await self.db_service.initialize()

    # ... prints happen here ...

    async with trio.open_nursery() as nursery:
        self._initialize_orchestration(nursery)
        task_status.started()  # ⚠️ Signals before serve() is ready!
        await serve(self.app, config)  # This is when server actually starts
```

**Issue**: `task_status.started()` is called before `serve()` is ready to accept connections. The `serve()` function is blocking and doesn't provide a readiness signal.

## Proposed Solutions

### Solution 1: Use `nursery.start()` with Proper Coordination (RECOMMENDED)

**Changes Required**:

1. **Modify `TrioServer.run()` to pre-initialize orchestration**
   - Move orchestrator initialization outside the `serve()` nursery
   - Signal readiness AFTER verification

2. **Modify test fixture to use `nursery.start()` instead of `start_soon()`**
   - Wait for actual server readiness signal
   - Access orchestrator after it's initialized

3. **Add health check polling for verification**
   - Poll `/health` endpoint to verify server is accepting connections
   - Only then attempt WebSocket connection

**Implementation**:

```python
# In trio_server.py
async def run(self, task_status=trio.TASK_STATUS_IGNORED):
    await self.db_service.initialize()

    config = HypercornConfig()
    config.bind = [f"{self.host}:{self.port}"]

    async with trio.open_nursery() as server_nursery:
        # Initialize orchestration BEFORE signaling ready
        self._initialize_orchestration(server_nursery)

        # Start Hypercorn in background
        server_nursery.start_soon(serve, self.app, config)

        # Wait a moment for Hypercorn to bind
        await trio.sleep(0.1)

        # Signal that we're ready (orchestration initialized, server starting)
        task_status.started()

        # Log after signaling
        logger.info(f"Trio server running on {self.host}:{self.port}")

# In test fixture
async def test_server(...):
    server = TrioServer(container, host="127.0.0.1", port=port)

    async with trio.open_nursery() as nursery:
        # Use start() to wait for server readiness
        await nursery.start(server.run)

        # Verify server is actually accepting connections
        import httpx
        async with httpx.AsyncClient() as client:
            for _ in range(10):  # Retry up to 10 times
                try:
                    response = await client.get(f"http://127.0.0.1:{port}/health")
                    if response.status_code == 200:
                        break
                except:
                    pass
                await trio.sleep(0.1)

        # NOW the orchestrator exists and server is ready
        yield {
            "url": f"http://127.0.0.1:{port}",
            "ws_url": f"ws://127.0.0.1:{port}",
            "orchestrator": server.orchestrator,
            "db_service": db_service,
        }

        nursery.cancel_scope.cancel()
```

### Solution 2: Simpler Polling Approach (QUICK FIX)

**Changes Required**: Only modify test fixture

**Implementation**:

```python
async def test_server(...):
    server = TrioServer(container, host="127.0.0.1", port=port)

    async with trio.open_nursery() as nursery:
        nursery.start_soon(server.run)

        # Wait for orchestrator to be initialized
        for _ in range(50):  # 5 seconds max
            if hasattr(server, 'orchestrator'):
                break
            await trio.sleep(0.1)
        else:
            raise RuntimeError("Server orchestrator not initialized")

        # Wait for server to accept connections
        import httpx
        async with httpx.AsyncClient() as client:
            for _ in range(50):  # 5 seconds max
                try:
                    response = await client.get(f"http://127.0.0.1:{port}/health")
                    if response.status_code == 200:
                        break
                except:
                    pass
                await trio.sleep(0.1)
            else:
                raise RuntimeError("Server failed to start")

        yield {
            "url": f"http://127.0.0.1:{port}",
            "ws_url": f"ws://127.0.0.1:{port}",
            "orchestrator": server.orchestrator,
            "db_service": db_service,
        }

        nursery.cancel_scope.cancel()
```

### Solution 3: Separate Orchestrator Initialization (CLEANEST)

**Changes Required**: Refactor server initialization

1. **Create orchestrator in `__init__`** instead of in `run()`
2. **Pass existing orchestrator nursery** when server runs
3. **Pre-initialize everything** before starting serve

**Implementation**:

```python
# In trio_server.py
class TrioServer:
    def __init__(self, container, host="0.0.0.0", port=8000):
        self.container = container
        self.host = host
        self.port = port
        self.app = QuartTrio(__name__)
        self.db_service = container.get("trio_db_service")

        # Orchestration will be initialized when run() is called
        self.orchestrator = None
        self.workflow_engine = None
        self.conversation_manager = None

        self._setup_http_routes()
        self._setup_websocket_handler()

    async def run(self, task_status=trio.TASK_STATUS_IGNORED):
        await self.db_service.initialize()

        config = HypercornConfig()
        config.bind = [f"{self.host}:{self.port}"]

        async with trio.open_nursery() as nursery:
            # Initialize orchestration in this nursery
            self._initialize_orchestration(nursery)

            # Start server
            nursery.start_soon(serve, self.app, config)

            # Small delay for binding
            await trio.sleep(0.2)

            # Signal ready
            task_status.started()
            logger.info(f"Server ready on {self.host}:{self.port}")

# Test fixture unchanged - use nursery.start()
```

## Testing Strategy

### Step 1: Verify Current State
```bash
# Run with verbose output to see exact timing
pytest tests/integration/test_natural_patient_flow.py -v -s --no-mocks

# Check if orchestrator exists
python -c "
from tests.integration.test_natural_patient_flow import test_server
# Try to access orchestrator in fixture
"
```

### Step 2: Add Debug Logging
Add logging to see initialization sequence:
- When `server.run()` is called
- When `_initialize_orchestration()` completes
- When `serve()` is called
- When server is ready to accept connections

### Step 3: Implement Solution
Choose solution based on scope:
- **Solution 1**: Best for production (proper coordination)
- **Solution 2**: Quick fix for immediate testing
- **Solution 3**: Cleanest architecture (requires more changes)

### Step 4: Validate Fix
```bash
# Run test multiple times to ensure no race conditions
for i in {1..10}; do
    pytest tests/integration/test_natural_patient_flow.py --no-mocks || break
done

# Run with different timing conditions
# (e.g., under load, with slow disk I/O)
```

## Additional Recommendations

### 1. Add Explicit Server Readiness Endpoint
```python
# In trio_server.py
self.app.route("/readiness")(self._readiness_check)

async def _readiness_check(self):
    """Readiness check - only returns 200 when fully initialized."""
    if not hasattr(self, 'orchestrator') or self.orchestrator is None:
        return jsonify({"status": "initializing"}), 503

    db_healthy = await self.db_service.health_check()
    if not db_healthy:
        return jsonify({"status": "database unavailable"}), 503

    return jsonify({"status": "ready"}), 200
```

### 2. Add Timeout Guards
All test sleeps should have explicit timeouts:
```python
with trio.fail_after(10):  # 10 second timeout
    # wait for server ready
```

### 3. Improve Test Isolation
- Each test should use completely isolated database
- Tests should not depend on timing-based delays
- Use explicit coordination primitives (events, channels)

## Expected Outcome

After implementing one of the solutions:
1. ✅ `server.orchestrator` will exist when accessed in test
2. ✅ Server will be accepting connections before WebSocket connect
3. ✅ Test will pass reliably without race conditions
4. ✅ No more `ConnectionRefusedError`

## Files to Modify

1. **[src/trio_server.py](src/trio_server.py)** - Server initialization and readiness signaling
2. **[tests/integration/test_natural_patient_flow.py](tests/integration/test_natural_patient_flow.py)** - Test fixture coordination
3. **(Optional)** [tests/conftest.py](tests/conftest.py) - Shared fixtures if pattern is reusable

## Priority

**CRITICAL** - This blocks integration testing of the core patient flow.

## Scope Impact

⚠️ **Multiple Test Files Affected**: This is a SYSTEMATIC issue affecting at least:
1. **[tests/integration/test_natural_patient_flow.py:233-283](tests/integration/test_natural_patient_flow.py#L233-L283)** - Main failing test
2. **[tests/integration/test_console_ui_patient_flow.py:236-278](tests/integration/test_console_ui_patient_flow.py#L236-L278)** - Same pattern (waits only 0.1s!)

Both fixtures have:
- ❌ Access to `server.orchestrator` before it's initialized (line 273 in console_ui, line 277 in natural_flow)
- ❌ Insufficient/missing coordination with `nursery.start_soon()`
- ❌ Fixed sleep delays instead of proper readiness checking

**Any solution must be applied to ALL affected test files.**

## Estimated Effort

- **Solution 2 (Quick Fix)**: 30 minutes per test file = ~1 hour total
- **Solution 1 (Proper Coordination)**: 2-3 hours (includes server changes + all tests)
- **Solution 3 (Cleanest)**: 3-4 hours (includes refactoring + all tests)

## Next Steps

1. Review this plan with team/reviewer
2. Choose solution based on time constraints
3. Implement chosen solution in **src/trio_server.py**
4. Update **ALL** affected test fixtures:
   - tests/integration/test_natural_patient_flow.py
   - tests/integration/test_console_ui_patient_flow.py
5. Run full integration test suite to verify
6. Create a reusable fixture pattern to prevent future issues
