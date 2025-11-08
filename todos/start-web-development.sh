#!/bin/bash
#
# Start the web interface in development mode with hot reload
#

set -e

echo "🚀 Starting Psychoanalyst Web Interface (Development)"
echo "===================================================="

# Check if .env file exists
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found!"
    echo "Please create a .env file with your Google Gemini API key:"
    echo "GOOGLE_API_KEY=your_api_key_here"
    exit 1
fi

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Error: Docker is not running!"
    echo "Please start Docker and try again."
    exit 1
fi

echo "📦 Building and starting development services..."

# Start services using the development docker-compose file
docker-compose -f todos/docker-compose.web-dev.yml up --build -d

echo ""
echo "✅ Development services started successfully!"
echo ""
echo "🌐 Frontend (Dev): http://localhost:5173"
echo "🔌 Unified Server (API + WebSocket): http://localhost:8000"
echo ""
echo "🔥 Hot reload enabled for frontend development"
echo ""
echo "📊 To view logs:"
echo "  docker-compose -f todos/docker-compose.web-dev.yml logs -f"
echo ""
echo "🛑 To stop services:"
echo "  docker-compose -f todos/docker-compose.web-dev.yml down"
echo ""

# Wait a moment for services to start
sleep 5

# Check service health
echo "🔍 Checking service health..."

if curl -s http://localhost:8000/health > /dev/null; then
    echo "✅ Backend API is healthy"
else
    echo "⚠️ Backend API may still be starting..."
fi

if curl -s http://localhost:5173 > /dev/null; then
    echo "✅ Frontend dev server is healthy"
else
    echo "⚠️ Frontend dev server may still be starting..."
fi

echo ""
echo "🎉 Development setup complete! Visit http://localhost:5173 for hot-reload development."