# Quick Start Guide

## Getting Started with the Therapy Platform

This guide will get you up and running with the Virtual LLM-Driven Psychoanalyst in minutes.

## Prerequisites

- Docker and Docker Compose
- A local llama.cpp OpenAI-compatible server on `localhost:8080`
- Modern web browser (for frontend)

## Installation

### 1. Clone and Setup

```bash
cd psychoanalyst_app
cp .env.example .env
```

### 2. Configure Environment

The default `.env` expects llama.cpp to expose an OpenAI-compatible API on
`http://localhost:8080/v1`. If your server uses a different model alias, update:

```bash
MODEL_NAME=local-model
DATABASE_PATH=data/psychoanalyst.db
```

To use Gemini instead, set `LLM_PROVIDER=gemini`, choose Gemini model names, and
add `GOOGLE_API_KEY`.

If you need to reset local databases during development, run:

```bash
make clean-testdb
```

To protect local therapy transcripts and plans before resetting or upgrading,
create a SQLite backup:

```bash
make docker-db-backup
```

Backups are written to `data/backups/` with a manifest and can be verified with
`make docker-db-backup-verify BACKUP=data/backups/<backup>.db`. See
`docs/reference/ARCHITECTURE_OPERATIONS_GUIDE.md` for restore steps.

### 3. Build Dev Containers (Installs Dependencies Inside Docker)

Run:

```bash
make dev-install
```

This builds the API/console/frontend Docker images and installs all Python dependencies *inside* those containers (packages are not installed globally on your host). The project workflow is Docker-only; avoid running Python/Node directly on the host for regular development.

### 4. Start the Server

```bash
# Start the unified server (HTTP API + WebSocket, Docker)
make run-server

# Or use Docker Compose directly
docker compose up api
```

The server listens on `http://localhost:8000`.

## Using the Platform

### Option 1: Web Frontend (Recommended)

1. Start the web UI with Docker:
```bash
make ui-web
```

2. Open `http://localhost:5173` in your browser

3. Features:
   - Real-time streaming responses
   - Visual typing indicators
   - Session management
   - Progress tracking

### Option 2: API Integration

#### Register Profile (Required)

```bash
# Register a user profile before opening a WebSocket connection.
curl -X POST http://localhost:8000/api/user/register \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_abc123",
    "name": "John Doe",
    "primary_language": "English",
    "data_of_birth": "1990-01-01",
    "profession": "Engineer"
  }'
```

Response:
```json
{
  "session": {
    "session_id": "session_xyz789",
    "user_id": "user_abc123",
    "timestamp": "2025-01-08T12:00:00"
  },
  "workflow_next_action": {
    "user_id": "user_abc123",
    "workflow_state": "intake_in_progress",
    "required_action": "start_intake",
    "prompt": "Start or continue the intake session.",
    "blocking": false
  }
}
```

Open WebSocket afterward: `ws://localhost:8000/ws?user_id=user_abc123`

#### Check Workflow Status

```bash
curl http://localhost:8000/api/user/status?user_id=user_abc123\&session_id=session_xyz789
```

Response:
```json
{
  "user_id": "user_abc123",
  "workflow_state": "new",
  "timestamp": "2025-01-08T12:01:00"
}
```

#### Get Next Workflow Action

```bash
curl http://localhost:8000/api/workflow/next?user_id=user_abc123\&session_id=session_xyz789
```

Response:
```json
{
  "user_id": "user_abc123",
  "workflow_state": "intake_in_progress",
  "required_action": "start_intake",
  "prompt": "Start or continue the intake session.",
  "blocking": false
}
```

### Option 3: WebSocket Integration

```javascript
// Native WebSocket client (no Socket.IO)
const ws = new WebSocket('ws://localhost:8000/ws?user_id=user_abc123');

ws.addEventListener('open', () => {
  // Session is auto-created on connect; wait for session_started
});

ws.addEventListener('message', (event) => {
  const message = JSON.parse(event.data);

  if (message.type === 'chat_response_chunk') {
    const { chunk, is_complete } = message.data || {};
    if (!is_complete) {
      displayChunk(chunk);
    } else {
      console.log('Response complete');
    }
  }
});

// Send a chat message (after session_started)
ws.send(
  JSON.stringify({
    type: 'chat_message',
    data: { message: 'I need help with anxiety' }
  })
);
```

## Complete Therapy Workflow

### Step 1: Intake (Information Gathering)

**State**: `NEW` → `INTAKE_IN_PROGRESS` → `INTAKE_COMPLETE`

**Purpose**: Collect user information and current concerns

**Topics Covered**:
- Current concerns and symptoms
- Therapy goals
- Previous therapy experience
- Life context

**Example Interaction**:
```
User: I've been feeling anxious and it's affecting my sleep.
Agent: Thank you for sharing that. Can you tell me more about when
       these feelings of anxiety started?
```

### Step 2: Assessment (Style Recommendation)

**State**: `INTAKE_COMPLETE` → `ASSESSMENT_IN_PROGRESS` → `ASSESSMENT_COMPLETE`

**Purpose**: Analyze intake and recommend therapy styles

**Process**:
1. Agent analyzes intake session
2. Generates 3 therapy style recommendations
3. User selects preferred style
4. Therapy plan created

**Available Styles**:
- **CBT (Cognitive Behavioral Therapy)**: Focus on thought patterns
- **Freudian Psychoanalysis**: Unconscious mind and childhood
- **Jungian Analysis**: Archetypes and collective unconscious

**Example**:
```
Agent: Based on your intake, I recommend:
       1. CBT - Great for anxiety and practical coping strategies
       2. Freudian - Explore deeper roots of anxiety
       3. Jungian - Understand symbolic patterns

       Which resonates most with you?

User: I'd like to try CBT.

Agent: Excellent choice! CBT will help you identify and change
       negative thought patterns causing anxiety.
```

### Step 3: Therapy Sessions

**State**: `ASSESSMENT_COMPLETE` → `THERAPY_IN_PROGRESS`

**Purpose**: Main therapeutic work

**Features**:
- 50-minute sessions (extendable)
- Style-specific therapeutic approach
- RAG-enhanced responses (domain knowledge)
- Real-time streaming

**Example CBT Session**:
```
User: I keep thinking everyone at work judges me.

Agent: That's a common anxious thought. Let's examine the evidence.
       What specific situations make you think this?

User: Yesterday I made a mistake in the presentation.

Agent: I see. When we catastrophize, we often overlook context.
       Did anyone actually say something negative?
```

### Step 4: Reflection (Post-Session)

**State**: `THERAPY_IN_PROGRESS` → `REFLECTION_IN_PROGRESS` → `PLAN_COMPLETE`

**Purpose**: Process insights and update therapy plan

**Process**:
1. Review session transcript
2. Identify progress and insights
3. Update therapy plan
4. Prepare for next session

## Therapy Styles

### CBT (Cognitive Behavioral Therapy)

**Focus**: Identifying and changing negative thought patterns

**Techniques**:
- Thought records
- Behavioral experiments
- Cognitive restructuring

**Best For**:
- Anxiety and depression
- Specific phobias
- Goal-oriented individuals

**Example Prompt**:
```
"Let's challenge that thought. What evidence supports it?
What evidence contradicts it?"
```

### Freudian Psychoanalysis

**Focus**: Unconscious mind, childhood experiences, and defense mechanisms

**Techniques**:
- Free association
- Dream analysis
- Transference interpretation

**Best For**:
- Deep-rooted patterns
- Personality exploration
- Understanding past influences

**Example Prompt**:
```
"That's interesting. Do you recall any early experiences
that might relate to this feeling?"
```

### Jungian Analysis

**Focus**: Archetypes, collective unconscious, and individuation

**Techniques**:
- Active imagination
- Symbol interpretation
- Shadow work

**Best For**:
- Spiritual growth
- Creative blocks
- Midlife transitions

**Example Prompt**:
```
"This dream symbol is fascinating. In Jungian terms,
water often represents the unconscious. What comes to mind?"
```

## Session Management

### Time Management

- Default session: 45 minutes (configurable via `SESSION_DURATION_MINUTES`)
- Max 2 extensions of 5 minutes each (tracked in session context)
- Session timer is available via the HTTP endpoint:

```bash
GET /api/sessions/session_xyz789/timer?user_id=user_abc123&session_id=session_xyz789
```

### Ending a Session

Sessions automatically end when:
- Time expires
- User ends session
- Agent determines session complete

```bash
# Via WebSocket
{"type": "end_session", "data": {"reason": "User ended session"}}
```

## Advanced Features

### RAG (Retrieval-Augmented Generation)

The system uses domain knowledge to enhance responses:

- **Knowledge Base**: Curated therapy literature
- **Semantic Search**: Finds relevant knowledge for context
- **Style Filtering**: Returns knowledge specific to therapy style
- **Integration**: Seamlessly injected into LLM prompts

### Streaming Responses

Real-time chunk-by-chunk message delivery:

**Benefits**:
- Immediate feedback (feels more human)
- Reduced perceived latency
- Better user engagement

**Implementation**:
```javascript
let currentMessage = '';

ws.addEventListener('message', (event) => {
  const message = JSON.parse(event.data);
  if (message.type !== 'chat_response_chunk') {
    return;
  }

  const { chunk, is_complete } = message.data || {};
  if (!is_complete) {
    currentMessage += chunk;
    updateUI(chunk); // Update UI incrementally
  } else {
    finalizeMessage(currentMessage);
    currentMessage = '';
  }
});
```

### Workflow State Tracking

Monitor user progress through therapy:

```bash
GET /api/user/status?user_id=user_abc123&session_id=session_xyz789
```

Returns:
- Current workflow state
- Next recommended agent
- Available actions

## Troubleshooting

### Connection Issues

**Problem**: WebSocket won't connect

**Solutions**:
- Check server is running on port 8000
- Verify CORS settings in `src/psychoanalyst_app/trio_server.py`
- Check browser console for errors
- Try `ws://localhost:8000` vs `http://localhost:8000`

### Streaming Not Working

**Problem**: Messages not streaming

**Solutions**:
- Check `chat_response_chunk` event handler
- Verify LLM service streaming is enabled
- Check network tab for WebSocket frames
- Ensure the client uses native WebSocket (no Socket.IO)

### Invalid State Transition

**Problem**: `InvalidStateTransitionError`

**Solutions**:
- Check current workflow state: `GET /api/user/status?user_id=...&session_id=...`
- Review valid transitions in `src/psychoanalyst_app/orchestration/trio_workflow_engine.py`
- Ensure proper sequence (can't skip intake/assessment)

### LLM Connection Issues

**Problem**: LLM not responding

**Solutions**:
- For local llama.cpp, verify it is running on `localhost:8080` and serving an
  OpenAI-compatible `/v1` API.
- Verify `LLM_PROVIDER`, `LLM_BASE_URL`, and `MODEL_NAME` in `.env`.
- For Gemini only, verify `GOOGLE_API_KEY` in `.env` (or `GEMINI_API_KEY` as a
  legacy alias) and check API quota/limits.
- View logs: `docker compose logs -f api`

## Production Deployment

### Environment Variables

```bash
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=http://host.docker.internal:8080/v1
MODEL_NAME=local-model
DATABASE_PATH=/app/data/psychoanalyst.db

# Optional
PORT=8000
LOG_LEVEL=INFO
MAX_CONNECTIONS=100
```

### Docker Compose

```yaml
version: '3.8'

services:
  unified-server:
    build: .
    ports:
      - "8000:8000"
    environment:
      - LLM_PROVIDER=${LLM_PROVIDER}
      - LLM_BASE_URL=${LLM_BASE_URL}
      - MODEL_NAME=${MODEL_NAME}
      - DATABASE_PATH=/app/data/psychoanalyst.db
    volumes:
      - ./data:/app/data
    restart: unless-stopped
```

### Scaling

For production load:

1. **Database**: Migrate to PostgreSQL
2. **State**: Use Redis for session state
3. **Load Balancing**: Nginx + multiple server instances
4. **Monitoring**: Prometheus + Grafana

## Next Steps

- [Architecture Documentation](./ARCHITECTURE.md) - Deep dive into system design
- [API Reference](./API.md) - Complete API documentation

## Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/psychoanalyst/issues)
- **Documentation**: See `docs/` directory
- **Examples**: See `frontend/src/` for React implementation

---

**Version**: 2.0
**Last Updated**: 2025-01-08
