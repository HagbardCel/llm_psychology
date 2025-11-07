#!/bin/bash
# Interactive launcher for Virtual LLM-Driven Psychoanalyst
# Helps users select UI mode and environment configuration

set -e

# Colors for output
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  🧠 Virtual LLM-Driven Psychoanalyst${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "This application supports multiple interface modes."
echo ""
echo -e "${GREEN}Available UI Modes:${NC}"
echo ""
echo "  1) Standalone Terminal UI"
echo "     - Direct Python execution (no Docker)"
echo "     - Single process, local-only"
echo "     - Best for: Quick local use, development"
echo ""
echo "  2) Console UI Service"
echo "     - WebSocket-based terminal client (Docker)"
echo "     - Networked architecture with API server"
echo "     - Best for: Testing WebSocket, multi-user scenarios"
echo ""
echo "  3) Web UI"
echo "     - React-based browser interface (Docker)"
echo "     - Modern graphical experience"
echo "     - Best for: End users, PWA features"
echo ""
echo "  4) All Services"
echo "     - Run all UIs simultaneously"
echo "     - Best for: Development, comparison testing"
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Get UI mode selection
read -p "Select UI mode [1-4]: " ui_choice

# Validate UI choice
case $ui_choice in
  1|2|3|4) ;;
  *)
    echo -e "${YELLOW}Invalid choice. Please run again and select 1-4.${NC}"
    exit 1
    ;;
esac

echo ""
echo -e "${GREEN}Environment Configuration:${NC}"
echo ""
echo "  Normal Mode:"
echo "    - Uses .env configuration"
echo "    - Standard session duration (45 min)"
echo "    - Production database"
echo ""
echo "  Usertest Mode:"
echo "    - Uses .env.usertest configuration"
echo "    - Shorter session duration (10 min)"
echo "    - Isolated test database"
echo "    - Best for: Manual testing, experimentation"
echo ""

# Get usertest mode selection
read -p "Run in usertest mode? [y/N]: " usertest_choice
usertest_choice=${usertest_choice:-n}

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Determine command based on selections
case $ui_choice in
  1)
    if [[ $usertest_choice =~ ^[Yy]$ ]]; then
      echo -e "${GREEN}Starting: Standalone Terminal UI (Usertest Mode)${NC}"
      echo ""
      echo "Access: Direct terminal interaction"
      echo "Database: data/psychoanalyst_usertest.db"
      echo "Session Duration: 10 minutes"
      echo ""
      make ui-standalone-test
    else
      echo -e "${GREEN}Starting: Standalone Terminal UI${NC}"
      echo ""
      echo "Access: Direct terminal interaction"
      echo ""
      make ui-standalone
    fi
    ;;
  2)
    if [[ $usertest_choice =~ ^[Yy]$ ]]; then
      echo -e "${GREEN}Starting: Console UI Service (Usertest Mode)${NC}"
      echo ""
      echo "API Server: http://localhost:8000"
      echo "Console Client: WebSocket terminal"
      echo "Database: data/psychoanalyst_usertest.db"
      echo "Session Duration: 10 minutes"
      echo ""
      make ui-console-test
    else
      echo -e "${GREEN}Starting: Console UI Service${NC}"
      echo ""
      echo "API Server: http://localhost:8000"
      echo "Console Client: WebSocket terminal"
      echo ""
      make ui-console
    fi
    ;;
  3)
    if [[ $usertest_choice =~ ^[Yy]$ ]]; then
      echo -e "${GREEN}Starting: Web UI (Usertest Mode)${NC}"
      echo ""
      echo "API Server: http://localhost:8000"
      echo "Frontend: http://localhost:5173"
      echo "Database: data/psychoanalyst_usertest.db"
      echo "Session Duration: 10 minutes"
      echo ""
      echo -e "${YELLOW}Open your browser to http://localhost:5173 after services start${NC}"
      echo ""
      make ui-web-test
    else
      echo -e "${GREEN}Starting: Web UI${NC}"
      echo ""
      echo "API Server: http://localhost:8000"
      echo "Frontend: http://localhost:5173"
      echo ""
      echo -e "${YELLOW}Open your browser to http://localhost:5173 after services start${NC}"
      echo ""
      make ui-web
    fi
    ;;
  4)
    if [[ $usertest_choice =~ ^[Yy]$ ]]; then
      echo -e "${GREEN}Starting: All UI Services (Usertest Mode)${NC}"
      echo ""
      echo "API Server: http://localhost:8000"
      echo "Console Client: Terminal"
      echo "Frontend: http://localhost:5173"
      echo "Database: data/psychoanalyst_usertest.db"
      echo "Session Duration: 10 minutes"
      echo ""
      echo -e "${YELLOW}Open your browser to http://localhost:5173 for web UI${NC}"
      echo ""
      make ui-all-test
    else
      echo -e "${GREEN}Starting: All UI Services${NC}"
      echo ""
      echo "API Server: http://localhost:8000"
      echo "Console Client: Terminal"
      echo "Frontend: http://localhost:5173"
      echo ""
      echo -e "${YELLOW}Open your browser to http://localhost:5173 for web UI${NC}"
      echo ""
      make ui-all
    fi
    ;;
esac
