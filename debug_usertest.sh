#!/bin/bash
# Diagnostic script for usertest debugging

echo "==================================================="
echo "🔍 Psychoanalyst UserTest Diagnostic Tool"
echo "==================================================="
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running or not accessible"
    echo "Please start Docker and try again"
    exit 1
fi

echo "✅ Docker is running"
echo ""

# Check running containers
echo "📦 Running containers:"
docker ps --filter "name=psychoanalyst" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""

# Check if api-usertest is running
if docker ps | grep -q "psychoanalyst_api_usertest"; then
    echo "✅ API usertest container is running"
    echo ""

    # Get last 50 lines of logs
    echo "📋 Last 50 lines of API logs:"
    echo "---------------------------------------------------"
    docker logs psychoanalyst_api_usertest --tail 50
    echo "---------------------------------------------------"
    echo ""

    # Test health endpoint
    echo "🏥 Testing health endpoint..."
    if curl -s http://localhost:8001/health | jq . 2>/dev/null; then
        echo "✅ Health endpoint is responding"
    else
        echo "⚠️  Health endpoint returned non-JSON or errored"
    fi
    echo ""

    # Test WebSocket endpoint
    echo "🔌 Testing WebSocket availability..."
    if nc -zv localhost 8001 2>&1 | grep -q "succeeded"; then
        echo "✅ Port 8001 is accessible"
    else
        echo "❌ Port 8001 is not accessible"
    fi
else
    echo "❌ API usertest container is not running"
    echo ""
    echo "Recent container logs (if any):"
    docker logs psychoanalyst_api_usertest --tail 20 2>/dev/null || echo "(no logs available)"
fi

echo ""
echo "==================================================="
echo "💡 Next steps:"
echo "1. Check the API logs above for errors"
echo "2. Verify the health endpoint shows 'healthy'"
echo "3. If issues persist, try:"
echo "   - make clean-testdb"
echo "   - docker compose down"
echo "   - docker compose --profile usertest-console up --build"
echo "==================================================="
