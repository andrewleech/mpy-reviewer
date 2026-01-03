#!/bin/bash
# Claude Code SessionStart hook to ensure codanna is installed
set -e

# Check if codanna is already available
if command -v codanna &> /dev/null; then
    echo "✓ codanna is installed"
    exit 0
fi

echo "⚠ codanna not found - attempting installation..."

# Check if cargo is available
if ! command -v cargo &> /dev/null; then
    echo ""
    echo "╔══════════════════════════════════════════════════════════════════════╗"
    echo "║ ERROR: Rust/cargo not found                                          ║"
    echo "╠══════════════════════════════════════════════════════════════════════╣"
    echo "║                                                                      ║"
    echo "║ codanna requires Rust to compile and install.                       ║"
    echo "║                                                                      ║"
    echo "║ Install Rust:                                                        ║"
    echo "║   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh    ║"
    echo "║                                                                      ║"
    echo "║ After installing Rust, restart your terminal and run Claude again.  ║"
    echo "║                                                                      ║"
    echo "╚══════════════════════════════════════════════════════════════════════╝"
    echo ""
    exit 1
fi

# Install codanna
echo "Installing codanna via cargo (this may take a few minutes)..."
cargo install codanna --all-features

# Verify installation
if command -v codanna &> /dev/null; then
    echo "✓ codanna installed successfully"

    # Ensure cargo bin is in PATH for future sessions
    if [ -n "$CLAUDE_ENV_FILE" ]; then
        echo 'export PATH="$HOME/.cargo/bin:$PATH"' >> "$CLAUDE_ENV_FILE"
    fi

    exit 0
else
    echo "ERROR: codanna installation failed"
    exit 1
fi
