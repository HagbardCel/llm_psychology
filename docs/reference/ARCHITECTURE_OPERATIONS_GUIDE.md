---
owner: engineering
status: supporting
last_reviewed: 2026-02-22
review_cycle_days: 180
source_of_truth_for: Operational and troubleshooting notes for runtime architecture
---

# Architecture Operations Guide

This companion guide stores deployment/testing/operations details that were moved
out of `docs/ARCHITECTURE.md` to keep the active architecture doc concise.

## Deployment

### Production Setup

```yaml
# docker-compose.yml
services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
      target: production
    profiles: ["production"]
    ports:
      - "8000:8000"
    environment:
      - GOOGLE_API_KEY=${GOOGLE_API_KEY}
      - DATABASE_PATH=/app/data/psychoanalyst.db
    volumes:
      - ./data:/app/data
```

### Starting the Server

```bash
# Development (Docker)
make run-server

# Production
docker compose --profile production up app
```

## Testing

### Test Structure

```
tests/
├── unit/
│   ├── test_workflow_engine.py       # State machine tests
│   ├── test_conversation_manager.py  # Streaming & context tests
│   ├── test_agent_orchestrator.py    # Orchestration tests
│   └── test_websocket_gateway.py     # WebSocket tests
└── integration/
    └── test_orchestration_flow.py    # End-to-end workflow tests
```

### Running Tests

```bash
# All tests (Docker)
make test

# Unit tests only (Docker)
make test-unit

# Integration tests only (Docker)
make test-integration

# Specific component
make docker-test-one TEST=tests/unit/test_workflow_engine.py
```

## Performance Considerations

### Streaming Latency
- First chunk typically arrives in <100ms
- Subsequent chunks stream in real-time
- No buffering delays

### Concurrent Users
- Agent instances cached per user/session
- State machine supports multiple concurrent users
- Database connection pooling (future enhancement)

### Scalability

Current architecture supports:
- Multiple concurrent WebSocket connections
- Session isolation per user
- Stateless HTTP API

Future enhancements:
- Redis for session state (horizontal scaling)
- Message queue for async processing
- Load balancing across instances

## Security

### Current Implementation
- Session isolation
- Input validation on API endpoints
- Error handling with safe error messages

### Future Enhancements
- Rate limiting
- Encryption at rest (database)
- HTTPS/WSS in production
- Audit logging

## Development Guidelines

### Adding a New Agent
1. Create agent class extending `BaseConversationalAgent`
2. Implement `process_message()` method
3. Add agent to `ServiceContainer`
4. Add state-to-agent mapping in `WorkflowEngine`
5. Add workflow events and transitions
6. Create unit tests

### Adding a New API Endpoint
1. Add route in `UnifiedServer._setup_http_routes()`
2. Implement handler method
3. Use orchestrator for business logic
4. Return JSON response
5. Add error handling
6. Document in the architecture docs

### Adding a New WebSocket Event
1. Add event handler in `WebSocketGateway`
2. Extract and validate data
3. Use orchestrator for processing
4. Emit response events
5. Add to frontend WebSocket service
6. Update TypeScript types

## Troubleshooting

### Common Issues

WebSocket won't connect:
- Check CORS configuration in `UnifiedServer`
- Verify WebSocket client compatibility and URL path
- Verify the `user_id` query parameter is provided

Streaming not working:
- Verify `chat_response_chunk` handler in frontend
- Check LLM service streaming implementation
- Verify network allows SSE/WebSocket

State transition failed:
- Check workflow state in database
- Verify transition is valid in `WorkflowEngine`
- Check logs for `InvalidStateTransitionError`

## Monitoring

### Logging

```python
import logging
logger = logging.getLogger(__name__)

# Logs to stdout/stderr
logger.info("User connected")
logger.error("Error processing message", exc_info=True)
```

### Metrics (Future)
- Active connections count
- Message throughput
- Average response latency
- Error rates by endpoint
- State transition counts

## Migration from Legacy

Before:
- Agents directly interacted with UI
- Full session management in each agent
- No central orchestration

After:
- Agents return prompts (pure business logic)
- Orchestrator handles session management
- Streaming handled by `ConversationManager`
- State machine coordinates workflow

Backward compatibility:
- Agents still support legacy `conduct_session()` method
- This can be removed in a future major version
