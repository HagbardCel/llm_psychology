#!/bin/bash
#
# Stop all web interface services
#

set -e

echo "🛑 Stopping Psychoanalyst Web Interface Services"
echo "=============================================="

# Stop production services if running
if docker-compose -f todos/docker-compose.web.yml ps -q > /dev/null 2>&1; then
    echo "📦 Stopping production services..."
    docker-compose -f todos/docker-compose.web.yml down
fi

# Stop development services if running
if docker-compose -f todos/docker-compose.web-dev.yml ps -q > /dev/null 2>&1; then
    echo "📦 Stopping development services..."
    docker-compose -f todos/docker-compose.web-dev.yml down
fi

echo ""
echo "✅ All web interface services stopped!"
echo ""
echo "🧹 To clean up Docker images:"
echo "  docker system prune"
echo ""
echo "🗑️ To remove all containers and volumes:"
echo "  docker-compose -f todos/docker-compose.web.yml down --volumes --rmi all"
echo "  docker-compose -f todos/docker-compose.web-dev.yml down --volumes --rmi all"