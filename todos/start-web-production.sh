#!/bin/bash
#
# Start the web interface in production mode
#

set -e

echo "🚀 Starting Psychoanalyst Web Interface (Production)"
echo "================================================="

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

echo "📦 Building and starting services..."

# Start services using the web docker-compose file
docker-compose -f todos/docker-compose.web.yml up --build -d

echo ""
echo "✅ Services started successfully!"
echo ""
echo "🌐 Web Interface: http://localhost:3000"
echo "🔌 API Server: http://localhost:8000"
echo "📡 WebSocket: http://localhost:8765"
echo ""
echo "📊 To view logs:"
echo "  docker-compose -f todos/docker-compose.web.yml logs -f"
echo ""
echo "🛑 To stop services:"
echo "  docker-compose -f todos/docker-compose.web.yml down"
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

if curl -s http://localhost:3000 > /dev/null; then
    echo "✅ Frontend is healthy"
else
    echo "⚠️ Frontend may still be starting..."
fi

echo ""
echo "🎉 Setup complete! Visit http://localhost:3000 to use the web interface."