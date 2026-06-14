#!/bin/bash
# Install git hooks for the project
# Run this script to set up pre-commit and pre-push validation

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

install_hook() {
    local hook_name="$1"
    local source="$SCRIPT_DIR/$hook_name"
    local target="$HOOKS_DIR/$hook_name"

    if [ ! -f "$source" ]; then
        echo "❌ Error: Hook source not found at $source"
        exit 1
    fi

    if [ -f "$target" ]; then
        echo "⚠️  $hook_name hook already exists at: $target"
        echo ""
        read -p "Do you want to overwrite it? (y/N) " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "❌ Installation cancelled"
            exit 1
        fi
        echo "Overwriting existing hook..."
    fi

    cp "$source" "$target"
    chmod +x "$target"
    echo "Installed $hook_name hook at: $target"
}

install_hook pre-commit
install_hook pre-push

echo ""
echo "✅ Git hooks installed successfully!"
echo ""
echo "What happens now:"
echo "  • Every time you commit, tests will run automatically (make docker-test)"
echo "  • Every time you push, finalization-check will run automatically"
echo "  • Commit will be blocked if tests fail"
echo "  • Push will be blocked if finalization-check fails"
echo "  • You can skip commit hook with: git commit --no-verify (not recommended)"
echo "  • You can skip push hook with: git push --no-verify (not recommended)"
echo ""
echo "To uninstall:"
echo "  rm $HOOKS_DIR/pre-commit $HOOKS_DIR/pre-push"
echo ""
echo "Happy coding! 🚀"
