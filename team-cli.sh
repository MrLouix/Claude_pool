#!/bin/bash
# TeamCLI TUI - Launcher Script
# This script handles installation and execution of claude-pool

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if we're in installation mode
if [[ "$1" == "install" ]] || [[ "$1" == "setup" ]]; then
    echo "=== TeamCLI TUI - Installation ==="
    echo ""

    # Check Python
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}❌ Python 3 is not installed${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓${NC} Python found: $(python3 --version)"

    # Check Claude CLI
    if ! command -v claude &> /dev/null; then
        echo -e "${YELLOW}⚠${NC}  Claude CLI not found (optional for testing)"
        echo "   Install from: https://claude.ai/code"
    else
        echo -e "${GREEN}✓${NC} Claude CLI found: $(claude --version 2>&1 | head -1)"
    fi

    # Create virtual environment
    if [ ! -d "venv" ]; then
        echo ""
        echo "Creating virtual environment..."
        python3 -m venv venv
        echo -e "${GREEN}✓${NC} Virtual environment created"
    else
        echo -e "${GREEN}✓${NC} Virtual environment already exists"
    fi

    # Install package
    echo ""
    echo "Installing TeamCLI TUI..."
    . venv/bin/activate
    pip install -e ".[dev]" -q
    echo -e "${GREEN}✓${NC} Installation complete!"

    echo ""
    echo "Usage:"
    echo "  ./claude-pool.sh --pool examples/pool.json"
    echo "  ./claude-pool.sh --help"
    echo ""
    exit 0
fi

# Normal execution mode

# Check if venv exists
if [ ! -d "venv" ]; then
    echo -e "${RED}❌ Virtual environment not found${NC}"
    echo "Run installation first: ./claude-pool.sh install"
    exit 1
fi

# Activate venv and run claude-pool
. venv/bin/activate

# Check if claude-pool is installed
if ! command -v claude-pool &> /dev/null; then
    echo -e "${RED}❌ claude-pool not installed in virtual environment${NC}"
    echo "Run installation: ./claude-pool.sh install"
    exit 1
fi

# Execute claude-pool with all arguments
exec claude-pool "$@"
