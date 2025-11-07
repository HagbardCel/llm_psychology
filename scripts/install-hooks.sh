#!/bin/bash
# Install git hooks for the project
# Run this script to set up pre-commit testing

set -e

echo "🔧 Installing git hooks..."
echo ""

# Find the git root directory
GIT_DIR=$(git rev-parse --git-dir 2>/dev/null)

if [ -z "$GIT_DIR" ]; then
    echo "❌ Error: Not in a git repository"
    exit 1
fi

# Create hooks directory if it doesn't exist
HOOKS_DIR="$GIT_DIR/hooks"
mkdir -p "$HOOKS_DIR"

# Get the script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Install pre-commit hook
PRE_COMMIT_SOURCE="$SCRIPT_DIR/pre-commit"
PRE_COMMIT_TARGET="$HOOKS_DIR/pre-commit"

if [ -f "$PRE_COMMIT_TARGET" ]; then
    echo "⚠️  Pre-commit hook already exists at: $PRE_COMMIT_TARGET"
    echo ""
    read -p "Do you want to overwrite it? (y/N) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "❌ Installation cancelled"
        exit 1
    fi
    echo "Overwriting existing hook..."
fi

# Copy and make executable
cp "$PRE_COMMIT_SOURCE" "$PRE_COMMIT_TARGET"
chmod +x "$PRE_COMMIT_TARGET"

echo ""
echo "✅ Git hooks installed successfully!"
echo ""
echo "Pre-commit hook location: $PRE_COMMIT_TARGET"
echo ""
echo "What happens now:"
echo "  • Every time you commit, tests will run automatically"
echo "  • Tests run in isolated Docker environment"
echo "  • Commit will be blocked if tests fail"
echo "  • You can skip with: git commit --no-verify (not recommended)"
echo ""
echo "To uninstall:"
echo "  rm $PRE_COMMIT_TARGET"
echo ""
echo "Happy coding! 🚀"
