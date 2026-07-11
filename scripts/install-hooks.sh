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

HOOKS=(pre-commit pre-push)

confirm_overwrite() {
    local hook_name="$1"
    local target="$2"

    echo "⚠️  $hook_name hook already exists at: $target"
    echo ""
    read -p "Do you want to overwrite it? (y/N) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "❌ Installation cancelled; no hooks were changed."
        exit 1
    fi
    echo "Will overwrite existing $hook_name hook..."
}

# Pass 1: validate sources and collect overwrite confirmations
for hook_name in "${HOOKS[@]}"; do
    source="$SCRIPT_DIR/$hook_name"
    target="$HOOKS_DIR/$hook_name"

    if [ ! -f "$source" ]; then
        echo "❌ Error: Hook source not found at $source"
        exit 1
    fi

    if [ -f "$target" ]; then
        confirm_overwrite "$hook_name" "$target"
    fi
done

# Pass 2: install all hooks
for hook_name in "${HOOKS[@]}"; do
    source="$SCRIPT_DIR/$hook_name"
    target="$HOOKS_DIR/$hook_name"

    cp "$source" "$target"
    chmod +x "$target"
    echo "Installed $hook_name hook at: $target"
done

echo ""
echo "✅ Git hooks installed successfully!"
echo ""
echo "What happens now:"
echo "  • Commits run lint plus targeted docs/generated-contract checks on staged paths"
echo "  • Pushes to the Phase 1 branch run artifact validation and test-refactor-fast"
echo "  • Pushes to main or HOOK_FULL=1 run full finalization-check"
echo "  • Phase 1 PRs run the phase-1-evidence job after standard finalization"
echo "  • CI remains authoritative for release-candidate validation"
echo ""
echo "To uninstall:"
echo "  rm $HOOKS_DIR/pre-commit $HOOKS_DIR/pre-push"
echo ""
echo "Happy coding! 🚀"
