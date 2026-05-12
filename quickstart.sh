#!/bin/bash
# Quick start script for Claude Pool TUI

set -e

echo "=== Claude Pool TUI - Quick Start ==="
echo ""

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed"
    exit 1
fi

echo "✓ Python 3 found: $(python3 --version)"

# Check if claude CLI is available
if ! command -v claude &> /dev/null; then
    echo "❌ Claude CLI is not installed"
    echo "   Please install it first: https://claude.ai/code"
    exit 1
fi

echo "✓ Claude CLI found: $(claude --version 2>&1 | head -1)"

# Create virtual environment if not exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
. venv/bin/activate

# Install package
echo "Installing Claude Pool TUI..."
pip install -e ".[dev]" -q

echo ""
echo "✓ Installation complete!"
echo ""
echo "Example usage:"
echo "  1. Create a pool.json file with your tasks"
echo "  2. Run: claude-pool --pool pool.json"
echo ""
echo "Or try the example:"
echo "  claude-pool --pool examples/pool.json --no-tui"
echo ""
echo "For help: claude-pool --help"
