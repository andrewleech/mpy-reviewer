#!/bin/bash
# Plugin SessionStart hook: ensure venv, package, and codanna are installed
set -e

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-.}"

# --- Python venv and package ---

VENV_DIR="$PLUGIN_ROOT/venv"

if command -v uv &>/dev/null; then
    # uv manages the venv and install in one step
    if [ ! -d "$VENV_DIR" ] || ! "$VENV_DIR/bin/python" -c "import rag" 2>/dev/null; then
        echo "Installing mpy-reviewer package via uv..."
        uv sync --project "$PLUGIN_ROOT" --python-preference system
    fi
elif command -v pip &>/dev/null || command -v pip3 &>/dev/null; then
    if [ ! -d "$VENV_DIR" ]; then
        echo "Creating Python virtual environment..."
        python3 -m venv "$VENV_DIR"
    fi
    if ! "$VENV_DIR/bin/python" -c "import rag" 2>/dev/null; then
        echo "Installing mpy-reviewer package via pip..."
        "$VENV_DIR/bin/pip" install -e "$PLUGIN_ROOT" --quiet
    fi
else
    echo ""
    echo "ERROR: Neither uv nor pip found. Install uv to use mpy-reviewer:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo ""
    exit 1
fi

# --- codanna (semantic code search) ---

if command -v codanna &>/dev/null; then
    echo "✓ codanna is installed"
    exit 0
fi

echo "⚠ codanna not found - attempting installation..."

if ! command -v cargo &>/dev/null; then
    echo ""
    echo "WARNING: Rust/cargo not found — codanna will not be available."
    echo "Install Rust to enable codebase analysis:"
    echo "  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
    echo ""
    # Non-fatal: the review tool works without codanna, just without --codebase
    exit 0
fi

echo "Installing codanna via cargo (this may take a few minutes)..."
cargo install codanna --all-features

if command -v codanna &>/dev/null; then
    echo "✓ codanna installed successfully"
    if [ -n "$CLAUDE_ENV_FILE" ]; then
        echo 'export PATH="$HOME/.cargo/bin:$PATH"' >> "$CLAUDE_ENV_FILE"
    fi
else
    echo "WARNING: codanna installation failed — codebase analysis will be unavailable"
fi
