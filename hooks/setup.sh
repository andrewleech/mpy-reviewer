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

_codanna_bin=""
if command -v codanna &>/dev/null; then
    _codanna_bin="$(command -v codanna)"
elif [ -x "$HOME/.cargo/bin/codanna" ]; then
    _codanna_bin="$HOME/.cargo/bin/codanna"
fi

_needs_install=false
_needs_index=false

if [ -z "$_codanna_bin" ]; then
    _needs_install=true
    _needs_index=true
elif [ -n "$CLAUDE_PROJECT_DIR" ] && [ ! -d "$CLAUDE_PROJECT_DIR/.codanna" ]; then
    _needs_index=true
fi

# If nothing to do, report and exit
if ! $_needs_install && ! $_needs_index; then
    echo "✓ codanna is installed"
    exit 0
fi

# Background helper: install codanna and/or build index
_setup_codanna_bg() {
    set -e
    trap '_cleanup_locks' EXIT

    _cleanup_locks() {
        rm -f "$HOME/.codanna/install.lock"
        if [ -n "$CLAUDE_PROJECT_DIR" ]; then
            rm -f "$CLAUDE_PROJECT_DIR/.codanna/.building"
        fi
    }

    # --- Install phase ---
    if $_needs_install; then
        if ! command -v cargo &>/dev/null; then
            echo "WARNING: Rust/cargo not found — codanna will not be available."
            echo "Install Rust: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
            echo "Or download a binary from https://github.com/bartolli/codanna/releases"
            exit 0
        fi

        mkdir -p "$HOME/.codanna"
        echo $$ > "$HOME/.codanna/install.lock"

        cargo install codanna --all-features 2>&1
        rm -f "$HOME/.codanna/install.lock"

        # Verify install succeeded
        if [ -x "$HOME/.cargo/bin/codanna" ]; then
            _codanna_bin="$HOME/.cargo/bin/codanna"
            if [ -n "$CLAUDE_ENV_FILE" ]; then
                echo 'export PATH="$HOME/.cargo/bin:$PATH"' >> "$CLAUDE_ENV_FILE"
            fi
        else
            echo "WARNING: codanna installation failed — codebase analysis will be unavailable"
            exit 0
        fi
    fi

    # --- Index phase ---
    if $_needs_index && [ -n "$CLAUDE_PROJECT_DIR" ]; then
        # Create .codanna/ and write the building lock BEFORE init
        # so _ensure_index() never sees a half-built directory without a lock.
        mkdir -p "$CLAUDE_PROJECT_DIR/.codanna"
        echo $$ > "$CLAUDE_PROJECT_DIR/.codanna/.building"

        # init is idempotent if settings.toml already exists
        "$_codanna_bin" init --path "$CLAUDE_PROJECT_DIR" 2>&1

        "$_codanna_bin" index --no-progress "$CLAUDE_PROJECT_DIR" 2>&1
        rm -f "$CLAUDE_PROJECT_DIR/.codanna/.building"

        # Add .codanna/ to .git/info/exclude if not already there
        _git_exclude="$CLAUDE_PROJECT_DIR/.git/info/exclude"
        if [ -f "$_git_exclude" ]; then
            if ! grep -qE '^\s*\.codanna/?$' "$_git_exclude"; then
                echo ".codanna/" >> "$_git_exclude"
            fi
        fi
    fi
}

_setup_codanna_bg &
disown

echo "codanna setup running in background"
