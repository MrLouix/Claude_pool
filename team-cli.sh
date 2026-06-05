#!/bin/bash
# TeamCLI - Launcher Script
# This script handles installation and execution of TeamCLI multi-CLI task manager

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
    echo "=== TeamCLI - Installation ==="
    echo ""

    # Check Python
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}❌ Python 3 is not installed${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓${NC} Python found: $(python3 --version)"

    # Check for at least one AI CLI
    CLI_COUNT=0
    if command -v claude &> /dev/null; then
        echo -e "${GREEN}✓${NC} Claude CLI found: $(claude --version 2>&1 | head -1)"
        CLI_COUNT=$((CLI_COUNT + 1))
    else
        echo -e "${YELLOW}⚠${NC} Claude CLI not found (optional)"
    fi

    if command -v vibe-acp &> /dev/null; then
        echo -e "${GREEN}✓${NC} Mistral CLI (vibe-acp) found: $(vibe-acp --version 2>&1 | head -1)"
        CLI_COUNT=$((CLI_COUNT + 1))
    else
        echo -e "${YELLOW}⚠${NC} Mistral CLI (vibe-acp) not found (optional)"
    fi

    if command -v llama &> /dev/null; then
        echo -e "${GREEN}✓${NC} Llama CLI found: $(llama --version 2>&1 | head -1)"
        CLI_COUNT=$((CLI_COUNT + 1))
    else
        echo -e "${YELLOW}⚠${NC} Llama CLI not found (optional)"
    fi

    if command -v agy &> /dev/null; then
        echo -e "${GREEN}✓${NC} Google CLI (agy/antigravity) found: $(agy --version 2>&1 | head -1)"
        CLI_COUNT=$((CLI_COUNT + 1))
    else
        echo -e "${YELLOW}⚠${NC} Google CLI (agy/antigravity) not found (optional)"
    fi

    if command -v openai &> /dev/null; then
        echo -e "${GREEN}✓${NC} OpenAI CLI found: $(openai --version 2>&1 | head -1)"
        CLI_COUNT=$((CLI_COUNT + 1))
    else
        echo -e "${YELLOW}⚠${NC} OpenAI CLI not found (optional)"
    fi

    if [ $CLI_COUNT -eq 0 ]; then
        echo -e "${YELLOW}ℹ${NC} No AI CLI detected. TeamCLI supports: claude, vibe-acp, llama, agy, openai"
        echo "   Install at least one from:"
        echo "   - Claude: https://claude.ai/code"
        echo "   - Mistral: https://console.mistral.ai/ (vibe-acp CLI)"
        echo "   - Llama: https://github.com/ggerganov/llama.cpp"
        echo "   - Google: https://antigravity.dev/ (agy CLI)"
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
    echo "Installing TeamCLI..."
    . venv/bin/activate
    pip install -e ".[dev]" -q
    echo -e "${GREEN}✓${NC} Installation complete!"

    echo ""
    echo "Usage:"
    echo "  ./team-cli.sh --pool examples/pool.json"
    echo "  ./team-cli.sh --serve --port 8000"
    echo "  ./team-cli.sh --help"
    echo ""
    exit 0
fi

# Normal execution mode

# Check if venv exists
if [ ! -d "venv" ]; then
    echo -e "${RED}❌ Virtual environment not found${NC}"
    echo "Run installation first: ./team-cli.sh install"
    exit 1
fi

# Activate venv and run team-cli
. venv/bin/activate

# Check if team-cli is installed
if ! command -v team-cli &> /dev/null; then
    echo -e "${RED}❌ team-cli not installed in virtual environment${NC}"
    echo "Run installation: ./team-cli.sh install"
    exit 1
fi

# Execute team-cli with all arguments
exec team-cli "$@"
