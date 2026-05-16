# Integration with Terminal UI

This React frontend is designed to work alongside the existing terminal interface, not replace it.

## Dual Interface Architecture

The application now supports two interfaces:

### 1. Terminal Interface (Existing)
- **Path**: `python -m psychoanalyst_app`
- **Features**: Full terminal-based interaction
- **Use Case**: CLI users, server environments, debugging

### 2. Web Interface (New)
- **Path**: Frontend + Backend API
- **Features**: Modern browser-based interaction
- **Use Case**: General users, better UX, mobile support

## Integration Points

### Backend Service Layer
Both interfaces use the same:
- Service Container
- Database Service
- LLM Service
- RAG Service
- Agent implementations

### Data Persistence
- Shared SQLite database
- Same user profiles and sessions
- Cross-interface session resumption

### Configuration
- Same `.env` configuration
- Shared logging system
- Unified error handling

## Running Instructions

### Terminal Only
```bash
cd /app
python -m psychoanalyst_app
```

### Web Interface
```bash
# Terminal 1: Backend API
cd /app
# Note: Web server component needs to be implemented
python -m uvicorn src.web_api:app --reload --port 8000

# Terminal 2: Frontend
cd /app/frontend
npm install
npm run dev
```

### Both Interfaces
Users can switch between terminal and web interfaces at any time:
- Session data persists across interfaces
- Same user profiles and therapy plans
- Seamless experience transition

## Implementation Status

✅ **Completed:**
- React frontend framework
- Component architecture
- State management
- UI/UX design
- TypeScript configuration

🔄 **Next Steps:**
- Backend API endpoints (Task 2)
- WebSocket integration
- Real-time communication

The terminal interface remains fully functional and available as a backup option.
