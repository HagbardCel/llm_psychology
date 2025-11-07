# Quick Start: Web Interface

## TL;DR - How to Run the Graphical UI

### One-Command Setup

**For Development (with hot reload):**
```bash
cd /app
./todos/start-web-development.sh
```
Then visit: http://localhost:5173

**For Production:**
```bash  
cd /app
./todos/start-web-production.sh
```
Then visit: http://localhost:3000

### What This Does

✅ **Automatically starts:**
- Backend API server (port 8000)
- WebSocket server (port 8765)  
- React frontend (port 5173 dev / 3000 prod)

✅ **Provides:**
- Modern web interface for therapy sessions
- Real-time communication via WebSockets
- Same database and functionality as terminal
- Hot reload for development

### Requirements

- Docker and Docker Compose installed
- `.env` file with `GOOGLE_API_KEY=your_key`
- Ports 3000, 5173, 8000, 8765 available

### Stopping Services

```bash
./todos/stop-web.sh
```

### Alternative Methods

**Using Make:**
```bash
make -f todos/Makefile.web web-dev
```

**Using Docker Compose directly:**
```bash
docker-compose -f todos/docker-compose.web-dev.yml up
```

## What's Different from Manual Setup

**Before (Manual):**
1. Start backend API server manually
2. Start WebSocket server manually  
3. Install npm dependencies
4. Start frontend dev server
5. Configure environment variables
6. Handle port conflicts
7. Coordinate service startup

**Now (Automated):**
1. Run one script
2. Everything starts automatically
3. Proper service orchestration
4. Health checks included
5. Easy cleanup

This solves the original problem of requiring many manual steps to run the graphical UI!