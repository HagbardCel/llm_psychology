# Quick Start Guide

## Getting Started with the Therapy Platform

This guide will get you up and running with the Virtual LLM-Driven Psychoanalyst in minutes.

## Prerequisites

- Docker and Docker Compose
- Google Gemini API key ([Get one here](https://makersuite.google.com/app/apikey))
- Modern web browser (for frontend)

## Installation

### 1. Clone and Setup

```bash
cd psychoanalyst_app
cp .env.example .env
```

### 2. Configure Environment

Edit `.env` and add your Gemini API key:

```bash
GEMINI_API_KEY=your_api_key_here
DATABASE_PATH=data/psychoanalyst.db
```

### 3. Start the Server

```bash
# Start the unified server (HTTP API + WebSocket)
docker-compose up unified-server

# Or run locally (requires Python 3.11+)
python src/unified_server.py
```

The server will start on `http://localhost:8000`

## Using the Platform

### Option 1: Web Frontend (Recommended)

1. Navigate to the frontend directory:
```bash
cd frontend
npm install
npm run dev
```

2. Open `http://localhost:5173` in your browser

3. Features:
   - Real-time streaming responses
   - Visual typing indicators
   - Session management
   - Progress tracking

### Option 2: API Integration

#### Create a User Profile

```bash
curl -X POST http://localhost:8000/api/user/profile \
  -H "Content-Type: application/json" \
  -d '{
    "name": "John Doe",
    "birthdate": "1990-01-01",
    "profession": "Engineer"
  }'
```

Response:
```json
{
  "user_id": "user_abc123",
  "name": "John Doe",
  "created_at": "2025-01-08T12:00:00"
}
```

#### Check User Status

```bash
curl http://localhost:8000/api/user/status?user_id=user_abc123
```

Response:
```json
{
  "user_id": "user_abc123",
  "workflow_state": "new",
  "next_agent": "INTAKE"
}
```

#### Start an Intake Session

```bash
curl -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_abc123",
    "type": "INTAKE"
  }'
```

Response:
```json
{
  "session_id": "session_xyz789",
  "agent_type": "INTAKE",
  "workflow_state": "intake_in_progress",
  "created_at": "2025-01-08T12:05:00"
}
```

### Option 3: WebSocket Integration

```javascript
import { io } from 'socket.io-client';

// Connect
const socket = io('http://localhost:8000', {
  auth: {
    user_id: 'user_abc123',
    token: 'auth_token'
  }
});

// Listen for streaming responses
socket.on('chat_response_chunk', (data) => {
  if (!data.is_complete) {
    // Accumulate chunks
    currentMessage += data.chunk;
    displayChunk(data.chunk);
  } else {
    // Response complete
    console.log('Full response:', data.full_response);
  }
});

// Send a message
socket.emit('message', {
  type: 'chat_message',
  data: {
    message: 'I need help with anxiety',
    session_id: 'session_xyz789'
  }
});
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

- Default session: 50 minutes
- Max 2 extensions of 5 minutes each
- Warnings at 10 and 5 minutes remaining

```javascript
// Extend session via WebSocket
socket.emit('message', {
  type: 'session_extension',
  data: {
    session_id: 'session_xyz789'
  }
});

// Response
socket.on('session_extended', (data) => {
  console.log('Session extended by', data.additional_minutes, 'minutes');
});
```

### Ending a Session

Sessions automatically end when:
- Time expires
- User ends session
- Agent determines session complete

```bash
# Via API
curl -X POST http://localhost:8000/api/sessions/session_xyz789/end
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

socket.on('chat_response_chunk', (data) => {
  if (!data.is_complete) {
    currentMessage += data.chunk;
    updateUI(data.chunk); // Update UI incrementally
  } else {
    finalizeMessage(data.full_response);
  }
});
```

### Workflow State Tracking

Monitor user progress through therapy:

```bash
GET /api/user/status?user_id=user_abc123
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
- Verify CORS settings in `src/unified_server.py`
- Check browser console for errors
- Try `ws://localhost:8000` vs `http://localhost:8000`

### Streaming Not Working

**Problem**: Messages not streaming

**Solutions**:
- Check `chat_response_chunk` event handler
- Verify LLM service streaming is enabled
- Check network tab for WebSocket frames
- Ensure Socket.IO client version >= 4.0

### Invalid State Transition

**Problem**: `InvalidStateTransitionError`

**Solutions**:
- Check current workflow state: `GET /api/user/status`
- Review valid transitions in `src/orchestration/workflow_engine.py`
- Ensure proper sequence (can't skip intake/assessment)

### API Key Issues

**Problem**: LLM not responding

**Solutions**:
- Verify `GEMINI_API_KEY` in `.env`
- Check API quota/limits
- View logs: `docker-compose logs unified-server`

## Production Deployment

### Environment Variables

```bash
# Required
GEMINI_API_KEY=your_production_key
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
      - GEMINI_API_KEY=${GEMINI_API_KEY}
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
- [Development Guide](../CLAUDE.md) - Contributing and development

## Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/psychoanalyst/issues)
- **Documentation**: See `docs/` directory
- **Examples**: See `frontend/src/` for React implementation

---

**Version**: 2.0
**Last Updated**: 2025-01-08
