#!/bin/bash
# Test script for console-UI with unified server

set -e

echo "🧪 Testing Console-UI with Unified Server"
echo "=========================================="
echo ""

# Check if unified server is running
echo "📡 Checking if unified server is running on port 8000..."
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "✅ Unified server is running"
else
    echo "❌ Unified server is NOT running"
    echo ""
    echo "Please start the unified server first:"
    echo "  python src/unified_server.py"
    echo ""
    echo "Or with Docker:"
    echo "  docker-compose up unified-server"
    exit 1
fi

echo ""
echo "🎯 Testing API endpoints..."

# Test health endpoint
echo -n "  - GET /health: "
if curl -s http://localhost:8000/health | grep -q "healthy"; then
    echo "✅"
else
    echo "❌ Failed"
fi

# Test user status endpoint
echo -n "  - GET /api/user/status: "
if curl -s "http://localhost:8000/api/user/status?user_id=test_user" | grep -q "workflow_state"; then
    echo "✅"
else
    echo "❌ Failed"
fi

# Test therapy styles endpoint
echo -n "  - GET /api/therapy/styles: "
if curl -s http://localhost:8000/api/therapy/styles | grep -q "styles"; then
    echo "✅"
else
    echo "❌ Failed"
fi

echo ""
echo "✨ API tests passed!"
echo ""
echo "🚀 Starting console-UI client..."
echo "   You can now chat with the therapist."
echo "   Type 'quit' to exit."
echo ""

# Start console-UI
cd console-ui
python main.py
