#!/usr/bin/env bash
# x-poster setup script
# Installs the x-poster tool directly (no virtual environment).
#
# Usage:
#   bash scripts/setup.sh [project_dir]
#
# Arguments:
#   project_dir  Path to the x-poster project root (default: auto-detect from script location)

set -euo pipefail

# Determine project root
if [ -n "${1:-}" ]; then
    PROJECT_DIR="$1"
else
    # Try to find the project root by looking for pyproject.toml
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    # Walk up from .codebuddy/skills/x-poster/scripts/ to project root
    PROJECT_DIR="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
fi

if [ ! -f "$PROJECT_DIR/pyproject.toml" ]; then
    echo "❌ Error: pyproject.toml not found in $PROJECT_DIR"
    echo "   Please provide the correct project directory path."
    exit 1
fi

echo "📦 Setting up x-poster in: $PROJECT_DIR"

# Step 1: Upgrade pip
echo "⬆️  Upgrading pip..."
pip install --upgrade pip -q 2>/dev/null || true

# Step 2: Install the project
echo "📥 Installing x-poster..."
pip install -e "$PROJECT_DIR" -q 2>&1 | tail -3

# Step 3: Verify installation
if command -v xpost &>/dev/null; then
    VERSION=$(xpost --version 2>&1 || echo "unknown")
    echo "✅ x-poster installed successfully: $VERSION"
else
    echo "❌ Installation failed. xpost command not found."
    echo "   Make sure pip's bin directory is in your PATH."
    exit 1
fi

# Step 3: Run environment check
echo ""
echo "🔍 Running environment check..."
xpost check 2>&1

echo ""
echo "🎉 Setup complete! Use the tool with:"
echo "   xpost <command> [options]"
