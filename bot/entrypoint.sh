#!/bin/bash
set -euo pipefail

MPY_CHECKOUT="${MPY_CHECKOUT:-/workspace/micropython}"

# Uses unauthenticated HTTPS clone. Works for public repos only.
# Clone MicroPython if the checkout volume is empty
if [ ! -d "$MPY_CHECKOUT/.git" ]; then
    echo "Cloning micropython/micropython into $MPY_CHECKOUT..."
    # depth=50 covers most PR histories. For PRs targeting older commits,
    # the review still works (diff comes from API), but codanna index and
    # filesystem exploration will be limited to recent history.
    git clone --depth=50 https://github.com/micropython/micropython.git "$MPY_CHECKOUT"
fi

# Build codanna index if available
if command -v codanna &>/dev/null; then
    echo "Building codanna index..."
    cd "$MPY_CHECKOUT"
    codanna index || echo "codanna index failed (non-fatal)"
    cd -
fi

# Execute the service command (passed as CMD)
exec "$@"
