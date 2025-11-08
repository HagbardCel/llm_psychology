# Web Interface Setup Guide

This guide explains how to run the Psychoanalyst application with the graphical web interface.

## Quick Start

### Option 1: Using Shell Scripts (Recommended)

**Development Mode (with hot reload):**
```bash
cd /app
./todos/start-web-development.sh
```

**Production Mode:**
```bash
cd /app  
./todos/start-web-production.sh
```

**Stop Services:**
```bash
./todos/stop-web.sh
```

### Option 2: Using Make Commands

```bash
cd /app

# Development mode
make -f todos/Makefile.web web-dev

# Production mode  
make -f todos/Makefile.web web-prod

# Stop services
make -f todos/Makefile.web web-stop

# View logs
make -f todos/Makefile.web web-logs
```

### Option 3: Using Docker Compose Directly

**Development:**
```bash
docker-compose -f todos/docker-compose.web-dev.yml up --build
```

**Production:**
```bash
docker-compose -f todos/docker-compose.web.yml up --build
```

## Access Points

Once running, you can access:

- **Web Interface (Dev):** http://localhost:5173
- **Web Interface (Prod):** http://localhost:3000  
- **API Server:** http://localhost:8000
- **WebSocket Server:** http://localhost:8000

## Architecture

The web interface consists of:

### Frontend
- **Technology:** React 18 + TypeScript + Vite
- **UI Library:** Material-UI 
- **Features:** PWA, real-time communication, responsive design
- **Development:** Hot reload with Vite dev server
- **Production:** Optimized build served by Nginx

### Backend Services  
- **API Server:** REST endpoints for session management, user data, therapy operations
- **WebSocket Server:** Real-time communication for therapy sessions
- **Database:** Shared SQLite database with terminal interface

### Integration
- **Service Communication:** Frontend proxies API requests to backend
- **Real-time Updates:** WebSocket connection for live therapy sessions
- **Data Persistence:** Same database as terminal interface
- **Session Continuity:** Can switch between web and terminal interfaces

## Development Workflow

### 1. Environment Setup
Ensure you have a `.env` file with:
```
GOOGLE_API_KEY=your_api_key_here
```

### 2. Start Development Services
```bash
./todos/start-web-development.sh
```

This starts:
- Backend API server on port 8000
- WebSocket server on port 8000  
- Frontend dev server on port 5173 with hot reload

### 3. Development Features
- **Hot Reload:** Frontend changes auto-refresh
- **API Proxy:** Vite proxies `/api/*` to backend
- **WebSocket Proxy:** Vite proxies `/socket.io/*` to WebSocket server
- **Shared Database:** Same data as terminal interface

## Production Deployment

### 1. Build and Start
```bash
./todos/start-web-production.sh
```

### 2. Production Features
- **Optimized Build:** Minified and compressed frontend
- **Nginx Serving:** Production web server with caching
- **Health Checks:** Docker health monitoring
- **Auto Restart:** Services restart on failure

## Troubleshooting

### Services Not Starting
```bash
# Check Docker is running
docker info

# Check port availability
netstat -tulpn | grep -E ':(3000|5173|8000|8000)'

# View service logs
make -f todos/Makefile.web web-logs
```

### Permission Issues
```bash
# Ensure scripts are executable
chmod +x todos/*.sh

# Check Docker permissions
docker ps
```

### API Connection Issues
```bash
# Test API health
curl http://localhost:8000/health

# Test WebSocket
curl http://localhost:8000
```

### Frontend Build Issues
```bash
# Rebuild frontend container
docker-compose -f todos/docker-compose.web-dev.yml build frontend-dev --no-cache
```

## File Structure

```
/app/
├── todos/
│   ├── docker-compose.web.yml          # Production web services
│   ├── docker-compose.web-dev.yml      # Development web services  
│   ├── start-web-production.sh         # Production startup script
│   ├── start-web-development.sh        # Development startup script
│   ├── stop-web.sh                     # Stop all web services
│   ├── Makefile.web                    # Web interface commands
│   └── WEB_INTERFACE_GUIDE.md          # This guide
├── frontend/
│   ├── Dockerfile                      # Production frontend image
│   ├── Dockerfile.dev                  # Development frontend image
│   ├── nginx.conf                      # Nginx configuration
│   └── ...                            # React application files
└── src/
    ├── api_server.py                   # REST API server
    └── websocket_server/               # WebSocket implementation
```

## Integration with Existing System

### Dual Interface Support
- **Terminal Interface:** `python src/main.py` (unchanged)
- **Web Interface:** Docker-based services (new)
- **Shared Data:** Same SQLite database and user profiles
- **Session Continuity:** Can resume sessions across interfaces

### Service Layer
Both interfaces use the same:
- Service Container pattern
- Database Service  
- LLM Service (Google Gemini)
- RAG Service (ChromaDB)
- Agent implementations

### Configuration
- Same `.env` file configuration
- Shared logging system
- Unified error handling
- Consistent data models

## Next Steps

1. **Start Development:** `./todos/start-web-development.sh`
2. **Access Web UI:** http://localhost:5173
3. **Test Integration:** Create user profile and start session
4. **Compare Interfaces:** Try same operations in terminal vs web
5. **Deploy Production:** `./todos/start-web-production.sh`

## Support

- **Logs:** `make -f todos/Makefile.web web-logs`
- **Health Checks:** Check API at http://localhost:8000/health
- **Clean Reset:** `make -f todos/Makefile.web web-clean`
- **Terminal Fallback:** `python src/main.py` always available