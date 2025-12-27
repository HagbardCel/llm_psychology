# Phase 4 Implementation Plan: Authentication & Polish

**Date**: 2025-12-03
**Prerequisites**: Phases 1-3 completed (API client layer, refactored web frontend, type safety)
**Estimated Duration**: 2 weeks (10 working days)
**Status**: Planning

---

## Overview

Phase 4 focuses on production readiness by implementing real authentication, schema versioning, comprehensive integration testing, and performance optimization. This phase transforms the application from a development prototype to a production-ready system.

### Goals

1. **Security**: Replace fake authentication with real JWT-based auth
2. **Reliability**: Implement schema versioning for graceful API evolution
3. **Quality**: Comprehensive integration tests across both clients
4. **Performance**: Optimize bottlenecks identified through profiling

### Success Criteria

- [ ] JWT authentication working for both console and web clients
- [ ] Zero authentication bypasses possible
- [ ] Schema version negotiation between client and server
- [ ] Integration tests achieve >85% coverage of user workflows
- [ ] P95 response time <500ms for API endpoints
- [ ] WebSocket message latency <100ms

---

## Task Breakdown

### Task 4.1: Implement Real Authentication (Days 1-4)

#### 4.1.1: Backend Authentication Infrastructure (Day 1)

**Objective**: Create JWT-based authentication system in backend

**Steps**:

1. **Add authentication dependencies**
   ```bash
   # requirements.in
   PyJWT>=2.8.0
   passlib[bcrypt]>=1.7.4
   python-multipart>=0.0.6  # For form data
   ```

2. **Create authentication models**
   - File: `src/models/auth_models.py`
   - Models:
     - `LoginRequest(BaseModel)`: username, password
     - `LoginResponse(BaseModel)`: access_token, token_type, expires_in
     - `TokenPayload(BaseModel)`: user_id, exp, iat
     - `UserCredentials(BaseModel)`: user_id, username, password_hash, created_at

3. **Create authentication service**
   - File: `src/services/auth_service.py`
   - Class: `AuthService`
   - Methods:
     - `create_user(username: str, password: str) -> str`: Create user, return user_id
     - `verify_password(username: str, password: str) -> Optional[str]`: Return user_id if valid
     - `create_access_token(user_id: str, expires_delta: timedelta) -> str`: Generate JWT
     - `verify_token(token: str) -> Optional[TokenPayload]`: Validate JWT
     - `hash_password(password: str) -> str`: Bcrypt hash
     - `_get_user_credentials(username: str) -> Optional[UserCredentials]`: DB lookup

4. **Add auth tables to database**
   - File: `src/services/trio_db_service.py`
   - Migration function: `_create_auth_tables()`
   - Table: `user_credentials`
     ```sql
     CREATE TABLE IF NOT EXISTS user_credentials (
         user_id TEXT PRIMARY KEY,
         username TEXT UNIQUE NOT NULL,
         password_hash TEXT NOT NULL,
         created_at TEXT NOT NULL,
         last_login TEXT
     )
     ```

5. **Add authentication configuration**
   - File: `src/config.py`
   - Add:
     - `JWT_SECRET_KEY`: From environment variable (required in production)
     - `JWT_ALGORITHM`: "HS256"
     - `ACCESS_TOKEN_EXPIRE_MINUTES`: 60 (1 hour)
     - `REQUIRE_AUTHENTICATION`: bool (default True in production)

**Tests**:
- `tests/unit/test_auth_service.py`:
  - `test_create_user_success()`
  - `test_create_user_duplicate_username()`
  - `test_verify_password_correct()`
  - `test_verify_password_incorrect()`
  - `test_create_access_token()`
  - `test_verify_token_valid()`
  - `test_verify_token_expired()`
  - `test_verify_token_invalid_signature()`

**Validation**:
```bash
pytest tests/unit/test_auth_service.py -v
```

---

#### 4.1.2: Backend Authentication Endpoints (Day 2)

**Objective**: Add login/logout REST endpoints with JWT generation

**Steps**:

1. **Create authentication routes**
   - File: `src/api/auth_routes.py` (new)
   - Endpoints:
     - `POST /api/auth/register`: Create new user
     - `POST /api/auth/login`: Authenticate and return JWT
     - `POST /api/auth/logout`: Invalidate token (optional, client-side deletion sufficient)
     - `GET /api/auth/me`: Get current user info (requires auth)
     - `POST /api/auth/refresh`: Refresh access token

2. **Implement authentication middleware**
   - File: `src/api/middleware/auth_middleware.py` (new)
   - Decorator: `@require_auth`
   - Functionality:
     - Extract JWT from `Authorization: Bearer <token>` header
     - Validate token using `AuthService.verify_token()`
     - Attach `user_id` to request context
     - Return 401 if token missing/invalid

3. **Protect existing endpoints**
   - Update `src/trio_server.py`:
     - Apply `@require_auth` to all endpoints except:
       - `/api/auth/register`
       - `/api/auth/login`
       - `/api/health` (health check)
   - WebSocket endpoint requires auth token as query param:
     - `/ws?token=<jwt_token>`

4. **Add token blacklist (optional, for logout)**
   - Redis-based or in-memory set for invalidated tokens
   - Check blacklist before accepting token
   - TTL matches token expiration

**Example Implementation**:
```python
# src/api/middleware/auth_middleware.py
from functools import wraps
from quart import request, jsonify

def require_auth(f):
    @wraps(f)
    async def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Missing or invalid authorization header'}), 401

        token = auth_header.split(' ')[1]
        auth_service = get_auth_service()  # From service container

        payload = auth_service.verify_token(token)
        if not payload:
            return jsonify({'error': 'Invalid or expired token'}), 401

        # Attach user_id to request context
        request.user_id = payload.user_id

        return await f(*args, **kwargs)

    return decorated_function
```

**Tests**:
- `tests/integration/test_auth_endpoints.py`:
  - `test_register_new_user()`
  - `test_register_duplicate_username()`
  - `test_login_success()`
  - `test_login_invalid_credentials()`
  - `test_protected_endpoint_without_token()`
  - `test_protected_endpoint_with_valid_token()`
  - `test_protected_endpoint_with_expired_token()`
  - `test_websocket_connection_with_token()`
  - `test_websocket_connection_without_token()`

**Validation**:
```bash
pytest tests/integration/test_auth_endpoints.py -v
make test-validate  # Full isolated test
```

---

#### 4.1.3: Console Client Authentication (Day 3)

**Objective**: Add login flow to console UI

**Steps**:

1. **Add login prompt**
   - File: `console-ui/src/console_client.py`
   - Function: `async def authenticate() -> Optional[str]`
   - Flow:
     1. Prompt for username (or "register" for new user)
     2. Prompt for password (hidden input)
     3. POST to `/api/auth/login` or `/api/auth/register`
     4. Store JWT token in memory
     5. Return token or None if failed

2. **Update HTTP client with authentication**
   - Add `Authorization: Bearer <token>` header to all HTTP requests
   - Store token in `ConsoleClient.token` attribute

3. **Update WebSocket connection with authentication**
   - Pass token as query parameter: `/ws?token=<jwt_token>`
   - Handle 401 errors and prompt for re-authentication

4. **Add session persistence (optional)**
   - Store token in `~/.psychoanalyst/token` file (chmod 600)
   - Load token on startup
   - Validate token before use
   - Prompt for login if token expired

**Example Implementation**:
```python
# console-ui/src/console_client.py
async def authenticate(self, api_url: str) -> Optional[str]:
    """Authenticate user and return JWT token."""
    print("\n=== Authentication ===")
    print("Enter 'register' to create a new account")

    username = await trio.to_thread.run_sync(
        input, "Username: ", cancellable=True
    )

    if username.lower() == 'register':
        return await self._register_new_user(api_url)

    password = await trio.to_thread.run_sync(
        getpass.getpass, "Password: ", cancellable=True
    )

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{api_url}/api/auth/login",
                json={"username": username, "password": password}
            )

            if response.status_code == 200:
                data = response.json()
                print("✓ Authentication successful")
                return data['access_token']
            else:
                print(f"✗ Authentication failed: {response.json().get('error')}")
                return None
        except Exception as e:
            print(f"✗ Connection error: {e}")
            return None
```

**Tests**:
- `tests/integration/test_console_auth_flow.py`:
  - `test_console_login_success()`
  - `test_console_login_failure()`
  - `test_console_register_and_login()`
  - `test_console_expired_token_reauth()`

**Validation**:
```bash
# Manual test
cd console-ui
python main.py

# Automated test
pytest tests/integration/test_console_auth_flow.py -v
```

---

#### 4.1.4: Web Frontend Authentication (Day 4)

**Objective**: Replace fake auth with real JWT authentication

**Steps**:

1. **Update AuthContext**
   - File: `frontend/src/contexts/AppContext.tsx`
   - Remove fake token generation
   - Add real login/register functions:
     - `login(username: string, password: string): Promise<void>`
     - `register(username: string, password: string): Promise<void>`
     - `logout(): void`
   - Store JWT in memory (state) and httpOnly cookie (if supported)
   - Remove default user creation

2. **Create login/register pages**
   - File: `frontend/src/pages/LoginPage.tsx` (new)
   - File: `frontend/src/pages/RegisterPage.tsx` (new)
   - Forms with validation:
     - Username: 3-20 characters, alphanumeric
     - Password: min 8 characters, complexity requirements
   - Error handling for invalid credentials
   - Redirect to dashboard after successful auth

3. **Update API client with authentication**
   - File: `frontend/src/services/apiClient.ts`
   - Add `Authorization: Bearer <token>` header to all requests
   - Implement token refresh logic
   - Handle 401 responses (redirect to login)

4. **Add protected route component**
   - File: `frontend/src/components/ProtectedRoute.tsx`
   - Check authentication status
   - Redirect to login if not authenticated
   - Wrap all pages except login/register

5. **Update WebSocket service**
   - File: `frontend/src/services/websocketService.ts`
   - Pass token in WebSocket URL: `ws://localhost:8000/ws?token=${token}`
   - Handle 401 errors and trigger re-authentication

6. **Add token storage strategy**
   - Primary: React state (in-memory)
   - Backup: sessionStorage for page refresh (not localStorage for security)
   - Clear on logout or token expiration

**Example Implementation**:
```typescript
// frontend/src/contexts/AppContext.tsx
export function AppProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(
    () => sessionStorage.getItem('auth_token')
  );
  const [user, setUser] = useState<User | null>(null);

  const login = async (username: string, password: string) => {
    const response = await fetch(`${API_URL}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });

    if (!response.ok) {
      throw new Error('Login failed');
    }

    const data = await response.json();
    setToken(data.access_token);
    sessionStorage.setItem('auth_token', data.access_token);

    // Fetch user profile
    await fetchUserProfile(data.access_token);
  };

  const logout = () => {
    setToken(null);
    setUser(null);
    sessionStorage.removeItem('auth_token');
  };

  // Auto-load user on mount if token exists
  useEffect(() => {
    if (token) {
      fetchUserProfile(token).catch(() => logout());
    }
  }, [token]);

  return (
    <AppContext.Provider value={{ token, user, login, logout }}>
      {children}
    </AppContext.Provider>
  );
}
```

**Tests**:
- `frontend/src/__tests__/auth.test.tsx`:
  - `test_login_page_renders()`
  - `test_login_success_redirects()`
  - `test_login_failure_shows_error()`
  - `test_protected_route_redirects_when_not_authenticated()`
  - `test_logout_clears_token()`

**Validation**:
```bash
cd frontend
npm test -- auth.test.tsx
npm run build  # Ensure no build errors
```

---

### Task 4.2: Implement Schema Versioning (Days 5-6)

#### 4.2.1: Backend Schema Version Management (Day 5)

**Objective**: Add version negotiation to API responses

**Steps**:

1. **Define schema version**
   - File: `src/config.py`
   - Add:
     - `API_VERSION = "2.0.0"` (major.minor.patch)
     - `MIN_CLIENT_VERSION = "2.0.0"`
     - `SUPPORTED_API_VERSIONS = ["2.0.0", "1.0.0"]`

2. **Add version to API responses**
   - Create response wrapper model:
     ```python
     # src/models/api_models.py
     class ApiResponse(BaseModel):
         api_version: str
         data: Any
         meta: Optional[Dict[str, Any]] = None
     ```
   - Update all endpoints to return `ApiResponse`

3. **Add version negotiation endpoint**
   - Endpoint: `GET /api/version`
   - Response:
     ```json
     {
       "api_version": "2.0.0",
       "min_client_version": "2.0.0",
       "supported_versions": ["2.0.0", "1.0.0"],
       "deprecations": [
         {
           "version": "1.0.0",
           "deprecated_at": "2025-12-01",
           "removed_at": "2026-03-01",
           "message": "Version 1.0.0 will be removed on March 1, 2026"
         }
       ]
     }
     ```

4. **Add client version validation middleware**
   - File: `src/api/middleware/version_middleware.py`
   - Check `X-Client-Version` header in requests
   - Return 426 Upgrade Required if version too old
   - Add deprecation warnings to response headers

5. **Create version migration utilities**
   - File: `src/api/version_adapter.py`
   - Functions to transform responses between versions
   - Handle field name changes (e.g., `snake_case` ↔ `camelCase`)
   - Backfill deprecated fields for old clients

**Example Implementation**:
```python
# src/api/middleware/version_middleware.py
from packaging import version
from quart import request, jsonify

async def validate_client_version():
    """Middleware to validate client version before processing request."""
    client_version = request.headers.get('X-Client-Version')

    if not client_version:
        # Allow requests without version for backward compatibility
        # But log warning for monitoring
        logger.warning(f"Request without X-Client-Version header: {request.path}")
        return

    try:
        client_ver = version.parse(client_version)
        min_ver = version.parse(MIN_CLIENT_VERSION)

        if client_ver < min_ver:
            return jsonify({
                'error': 'Client version too old',
                'min_version': MIN_CLIENT_VERSION,
                'your_version': client_version,
                'upgrade_url': 'https://example.com/download'
            }), 426  # Upgrade Required

    except Exception as e:
        logger.error(f"Invalid client version format: {client_version}")
        return jsonify({'error': 'Invalid client version format'}), 400
```

**Tests**:
- `tests/unit/test_version_negotiation.py`:
  - `test_version_endpoint_returns_correct_info()`
  - `test_old_client_version_rejected()`
  - `test_supported_client_version_accepted()`
  - `test_no_version_header_allowed()`
  - `test_version_adapter_transforms_response()`

**Validation**:
```bash
pytest tests/unit/test_version_negotiation.py -v
```

---

#### 4.2.2: Client Version Management (Day 6)

**Objective**: Add version checking to both clients

**Steps**:

1. **Console client version checking**
   - File: `console-ui/src/console_client.py`
   - On startup:
     - GET `/api/version`
     - Compare client version with `min_client_version`
     - Display upgrade message if outdated
     - Allow user to continue (dev mode) or exit
   - Add `X-Client-Version` header to all requests

2. **Web frontend version checking**
   - File: `frontend/src/config/version.ts` (new)
     ```typescript
     export const CLIENT_VERSION = "2.0.0";  // From package.json
     ```
   - File: `frontend/src/services/apiClient.ts`
   - Add `X-Client-Version` header to all requests
   - On app startup:
     - Fetch `/api/version`
     - Compare versions
     - Show modal if upgrade required
     - Prevent interaction until upgraded

3. **Add version mismatch UI**
   - Console: Print warning banner
   - Web: Modal dialog with download link

4. **Auto-update check (optional)**
   - Periodic version check (every 1 hour)
   - Service worker cache invalidation on version change
   - Prompt user to reload

**Tests**:
- `tests/integration/test_version_compatibility.py`:
  - `test_old_client_receives_upgrade_message()`
  - `test_current_client_works_normally()`
  - `test_version_header_sent_with_requests()`

**Validation**:
```bash
pytest tests/integration/test_version_compatibility.py -v
```

---

### Task 4.3: Integration Tests for Both Clients (Days 7-8)

#### 4.3.1: Define Integration Test Scenarios (Day 7, Morning)

**Objective**: Document comprehensive user workflows to test

**Steps**:

1. **Create test scenario document**
   - File: `tests/integration/INTEGRATION_TEST_SCENARIOS.md`
   - Define scenarios:
     - **Scenario 1: New User Registration and First Session**
     - **Scenario 2: Returning User Continues Therapy**
     - **Scenario 3: Style Switch During Assessment**
     - **Scenario 4: Session Interruption and Reconnection**
     - **Scenario 5: Concurrent Users**
     - **Scenario 6: Authentication Failure Handling**
     - **Scenario 7: Schema Version Mismatch**

2. **Define test data fixtures**
   - File: `tests/integration/fixtures/test_users.py`
   - Create test users with different states:
     - New user (no profile)
     - User at intake stage
     - User at assessment stage
     - User with active therapy plan

**Deliverable**: Test scenario document with expected behaviors

---

#### 4.3.2: Console Client Integration Tests (Day 7, Afternoon)

**Objective**: Test complete workflows in console client

**Steps**:

1. **Create console integration test suite**
   - File: `tests/integration/test_console_client_workflows.py`
   - Tests:
     - `test_console_new_user_full_flow()`: Register → Intake → Assessment → Session
     - `test_console_returning_user_resumes()`: Login → Resume session
     - `test_console_authentication_failure()`: Invalid credentials handled
     - `test_console_websocket_reconnection()`: Connection loss recovery
     - `test_console_streaming_responses()`: LLM streaming works correctly

2. **Use test automation tools**
   - Library: `pexpect` for terminal interaction automation
   - Simulate user input programmatically
   - Assert on console output

3. **Run against real server**
   - Start test server in background
   - Run console client tests
   - Verify database state after tests

**Example Test**:
```python
# tests/integration/test_console_client_workflows.py
import pexpect
import pytest

@pytest.mark.trio
async def test_console_new_user_full_flow(test_server):
    """Test complete new user workflow through console client."""
    # Start console client as subprocess
    child = pexpect.spawn('python console-ui/main.py')

    # Registration
    child.expect('Username:')
    child.sendline('testuser123')
    child.expect('Password:')
    child.sendline('testpass123')
    child.expect('Authentication successful')

    # Intake
    child.expect('What brings you here today?')
    child.sendline('I have been feeling anxious')
    child.expect('Can you tell me more')
    child.sendline('It happens mostly at work')
    # ... continue workflow

    # Verify in database
    db_service = test_server.get_service('db')
    user = await db_service.get_user_by_username('testuser123')
    assert user.status == UserStatus.INTAKE_COMPLETE
```

**Validation**:
```bash
pytest tests/integration/test_console_client_workflows.py -v -m trio
```

---

#### 4.3.3: Web Frontend Integration Tests (Day 8)

**Objective**: Test complete workflows in web frontend

**Steps**:

1. **Set up end-to-end testing framework**
   - Install Playwright or Cypress
   - Configure test environment
   - Create page object models

2. **Create web integration test suite**
   - File: `frontend/tests/e2e/workflows.spec.ts`
   - Tests:
     - `test_web_new_user_registration_and_intake()`
     - `test_web_dashboard_navigation()`
     - `test_web_therapy_session_streaming()`
     - `test_web_session_history_pagination()`
     - `test_web_profile_update()`
     - `test_web_authentication_redirect()`

3. **Test WebSocket functionality**
   - Verify streaming messages display correctly
   - Test reconnection on network loss
   - Verify typing indicators

4. **Test responsive design (optional)**
   - Mobile viewport tests
   - Tablet viewport tests
   - Desktop viewport tests

**Example Test (Playwright)**:
```typescript
// frontend/tests/e2e/workflows.spec.ts
import { test, expect } from '@playwright/test';

test('new user registration and intake flow', async ({ page }) => {
  // Navigate to app
  await page.goto('http://localhost:3000');

  // Should redirect to login
  await expect(page).toHaveURL(/.*login/);

  // Register
  await page.click('text=Register');
  await page.fill('input[name="username"]', 'testuser456');
  await page.fill('input[name="password"]', 'testpass456');
  await page.click('button[type="submit"]');

  // Should redirect to dashboard
  await expect(page).toHaveURL(/.*dashboard/);

  // Start intake
  await page.click('text=Start Intake');
  await expect(page).toHaveURL(/.*intake/);

  // Enter message
  await page.fill('textarea[name="message"]', 'I need help with stress');
  await page.click('button:has-text("Send")');

  // Wait for streaming response
  await expect(page.locator('.therapist-message')).toBeVisible({ timeout: 10000 });

  // Verify response content
  const response = await page.textContent('.therapist-message');
  expect(response).toContain('stress');
});
```

**Validation**:
```bash
cd frontend
npx playwright test
```

---

#### 4.3.4: Cross-Client Consistency Tests (Day 8, Afternoon)

**Objective**: Ensure both clients produce identical backend state

**Steps**:

1. **Create consistency test suite**
   - File: `tests/integration/test_cross_client_consistency.py`
   - Test strategy:
     1. Perform action in console client
     2. Verify state in database
     3. Perform same action in web client
     4. Verify identical state in database

2. **Tests**:
   - `test_intake_produces_same_database_state()`
   - `test_assessment_produces_same_plan()`
   - `test_session_messages_stored_identically()`
   - `test_profile_updates_equivalent()`

3. **Use database snapshots**
   - Capture DB state after console action
   - Capture DB state after web action
   - Assert equality (ignoring timestamps)

**Example Test**:
```python
@pytest.mark.trio
async def test_intake_produces_same_database_state(test_server, db_service):
    """Verify console and web clients produce identical intake data."""

    # Console client intake
    console_user = await perform_intake_via_console(
        username='console_user',
        responses=['I feel anxious', 'Work stress', 'No']
    )

    # Web client intake
    web_user = await perform_intake_via_web(
        username='web_user',
        responses=['I feel anxious', 'Work stress', 'No']
    )

    # Compare database state
    console_intake = await db_service.get_intake_data(console_user.user_id)
    web_intake = await db_service.get_intake_data(web_user.user_id)

    # Should have same structure (excluding IDs and timestamps)
    assert console_intake.topics == web_intake.topics
    assert console_intake.status == web_intake.status
```

---

### Task 4.4: Performance Optimization (Days 9-10)

#### 4.4.1: Performance Profiling and Baseline (Day 9, Morning)

**Objective**: Identify performance bottlenecks

**Steps**:

1. **Set up profiling tools**
   - Install `py-spy` for Python profiling
   - Install `hyperfine` for benchmarking
   - Set up Prometheus + Grafana (optional)

2. **Define performance metrics**
   - File: `docs/PERFORMANCE_METRICS.md`
   - Metrics:
     - API endpoint response times (P50, P95, P99)
     - WebSocket message latency
     - Database query times
     - LLM call duration (external, not optimizable)
     - Memory usage
     - CPU usage

3. **Create benchmark suite**
   - File: `tests/performance/benchmark_api.py`
   - Load test scenarios:
     - 10 concurrent users
     - 50 concurrent users
     - 100 concurrent users
   - Tool: `locust` for load testing

4. **Run baseline benchmarks**
   ```bash
   # API endpoints
   locust -f tests/performance/benchmark_api.py --headless -u 50 -r 10 -t 5m

   # Profile server
   py-spy record -o profile.svg -- python -m psychoanalyst_app.server
   ```

5. **Document baseline performance**
   - Record current metrics
   - Identify top 5 bottlenecks
   - Set optimization targets

**Deliverable**: Performance baseline report

---

#### 4.4.2: Database Query Optimization (Day 9, Afternoon)

**Objective**: Optimize slow database queries

**Steps**:

1. **Add database query logging**
   - File: `src/services/trio_db_service.py`
   - Log query execution time
   - Identify slow queries (>100ms)

2. **Add database indexes**
   - Analyze query patterns
   - Add indexes for:
     - `user_profiles(status)`: For status filtering
     - `sessions(user_id, created_at)`: For session history
     - `messages(session_id, created_at)`: For message retrieval
     - `therapy_plans(user_id)`: For plan lookup

3. **Optimize N+1 queries**
   - Use batch loading where possible
   - Example: Load all messages for session in one query

4. **Add query result caching**
   - Cache user profiles (TTL: 5 minutes)
   - Cache therapy plans (TTL: 10 minutes)
   - Use `cachetools` library

**Example Optimization**:
```python
# Before: N+1 query
for session in sessions:
    messages = await db.get_messages(session.session_id)  # N queries

# After: Single query with JOIN
sessions_with_messages = await db.get_sessions_with_messages(user_id)  # 1 query
```

**Validation**:
```bash
# Re-run benchmarks
locust -f tests/performance/benchmark_api.py --headless -u 50 -r 10 -t 5m

# Compare results
python tests/performance/compare_benchmarks.py baseline.json optimized.json
```

---

#### 4.4.3: API Response Optimization (Day 10, Morning)

**Objective**: Reduce API response times

**Steps**:

1. **Implement response compression**
   - Enable gzip compression in Quart
   - Compress responses >1KB

2. **Optimize JSON serialization**
   - Use `orjson` instead of standard `json`
   - Profile serialization of large responses

3. **Add response caching**
   - Cache static data (therapy styles, etc.)
   - Add `Cache-Control` headers
   - Use ETags for conditional requests

4. **Implement request coalescing**
   - Combine multiple API calls into single batch endpoint
   - Example: `/api/batch` accepts multiple requests

5. **Optimize WebSocket message size**
   - Remove unnecessary fields
   - Use message abbreviations
   - Implement binary format for large data (optional)

**Example**:
```python
# Add compression middleware
from quart_compress import Compress

app = Quart(__name__)
Compress(app)

# Use orjson for faster serialization
import orjson

@app.route('/api/sessions')
async def get_sessions():
    sessions = await db.get_sessions(user_id)
    return orjson.dumps([s.dict() for s in sessions]), 200, {
        'Content-Type': 'application/json',
        'Cache-Control': 'private, max-age=300'  # Cache 5 minutes
    }
```

---

#### 4.4.4: Frontend Performance Optimization (Day 10, Afternoon)

**Objective**: Optimize web frontend performance

**Steps**:

1. **Code splitting**
   - Split routes into separate bundles
   - Lazy load pages with `React.lazy()`
   - Reduce initial bundle size

2. **Optimize re-renders**
   - Use `React.memo()` for expensive components
   - Use `useMemo()` and `useCallback()` appropriately
   - Profile with React DevTools

3. **Optimize WebSocket handling**
   - Batch message updates
   - Debounce rapid updates
   - Use virtual scrolling for long message lists

4. **Add service worker for caching**
   - Cache static assets
   - Offline support for UI
   - Background sync for messages (optional)

5. **Run Lighthouse audit**
   ```bash
   lighthouse http://localhost:3000 --output=html --output-path=./lighthouse-report.html
   ```
   - Target: >90 performance score
   - Optimize based on recommendations

**Validation**:
```bash
cd frontend
npm run build
npm run preview

# Measure bundle size
npx webpack-bundle-analyzer dist/stats.json

# Run Lighthouse
lighthouse http://localhost:3000
```

---

## Testing Strategy

### Unit Tests
- All new functions have unit tests
- Target: >90% code coverage for new code
- Run before each commit

### Integration Tests
- Test complete user workflows
- Test both clients (console and web)
- Test cross-client consistency
- Run before merge to main

### Performance Tests
- Baseline benchmarks before optimization
- Regression tests after optimization
- Monitor in production

### Test Commands
```bash
# Unit tests only
make test-unit

# Integration tests only
make test-integration

# Performance tests
make test-performance

# All tests
make test-validate
```

---

## Deployment Checklist

### Pre-Production
- [ ] All Phase 4 tasks completed
- [ ] All tests passing (unit, integration, performance)
- [ ] Security audit completed
- [ ] Documentation updated
- [ ] Performance targets met

### Production Environment Setup
- [ ] Set `JWT_SECRET_KEY` environment variable (strong random value)
- [ ] Set `REQUIRE_AUTHENTICATION=true`
- [ ] Set `MIN_CLIENT_VERSION` appropriately
- [ ] Configure HTTPS/TLS for production
- [ ] Set up monitoring and alerting
- [ ] Configure log aggregation

### Post-Deployment
- [ ] Monitor error rates
- [ ] Monitor performance metrics
- [ ] Test authentication in production
- [ ] Verify version negotiation works
- [ ] User acceptance testing

---

## Risk Assessment

### High Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Authentication bypass vulnerability | Critical | Low | Security audit, penetration testing |
| Token storage security issues | High | Medium | Use httpOnly cookies, short expiration |
| Schema version conflicts | High | Medium | Comprehensive version testing |
| Performance regression | Medium | Medium | Baseline benchmarks, regression tests |

### Medium Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Integration test flakiness | Medium | High | Use deterministic test data, retry logic |
| Database migration issues | Medium | Low | Test migration on copy of production data |
| WebSocket authentication issues | Medium | Medium | Thorough testing of connection flow |

---

## Dependencies

### External Dependencies
- PyJWT >= 2.8.0
- passlib[bcrypt] >= 1.7.4
- cachetools >= 5.3.0
- orjson >= 3.9.0
- playwright (for web testing)
- locust (for load testing)

### Internal Dependencies
- Phases 1-3 completed:
  - ✓ API client layer implemented
  - ✓ Web frontend refactored to thin client
  - ✓ TypeScript types generated from backend

---

## Success Metrics

### Functional Metrics
- [ ] 100% of API endpoints require authentication
- [ ] Zero fake authentication code remaining
- [ ] Schema version negotiation working for both clients
- [ ] Integration test coverage >85% of user workflows

### Performance Metrics
- [ ] API P95 response time <500ms (excluding LLM calls)
- [ ] WebSocket message latency <100ms
- [ ] Web frontend Lighthouse score >90
- [ ] Database queries <50ms (P95)

### Quality Metrics
- [ ] Zero high-severity security vulnerabilities
- [ ] Test suite passes in isolated Docker environment
- [ ] All tests passing (126+ tests, target: 200+ tests)
- [ ] Documentation complete and up-to-date

---

## Timeline Summary

| Day | Task | Deliverable |
|-----|------|-------------|
| 1 | Backend auth infrastructure | Auth service + tests |
| 2 | Backend auth endpoints | REST endpoints + middleware |
| 3 | Console client auth | Login flow |
| 4 | Web frontend auth | Login/register pages |
| 5 | Backend schema versioning | Version negotiation API |
| 6 | Client version management | Version checking UI |
| 7 | Console integration tests | Test suite passing |
| 8 | Web integration tests | E2E tests passing |
| 9 | Performance profiling + DB optimization | Performance baseline + indexes |
| 10 | API + frontend optimization | Performance targets met |

**Total**: 10 working days (2 weeks)

---

## Next Steps

1. **Review this plan** with team/stakeholders
2. **Set up development branch**: `git checkout -b phase-4-auth-polish`
3. **Begin Task 4.1.1**: Backend authentication infrastructure
4. **Daily standups**: Review progress, blockers, adjust plan
5. **Track progress**: Update checklist in this document

---

**Plan created by**: Claude Code
**Date**: 2025-12-03
**Status**: Ready for implementation
**Prerequisites**: Phases 1-3 completed
