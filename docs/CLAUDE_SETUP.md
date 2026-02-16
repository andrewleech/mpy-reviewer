# Claude Code Setup for mpy-review

This document describes how to use the mpy-review skill with Claude Code, including automatic dependency management.

## Overview

The mpy-review skill provides code review assistance for MicroPython. It requires:
- Python dependencies (installed via pip)
- **codanna** for semantic code search (installed via cargo)

## Automatic Setup (Recommended)

The project includes a Claude Code SessionStart hook that automatically installs codanna when you first use Claude in this project.

### Prerequisites

1. **Rust and cargo** must be installed:
   ```bash
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
   source ~/.cargo/env
   ```

2. **Verify cargo is in PATH:**
   ```bash
   which cargo
   # Should output: /home/username/.cargo/bin/cargo
   ```

### How It Works

When you start Claude Code in this project:

1. The **SessionStart hook** (`.claude/hooks/ensure-codanna.sh`) runs automatically
2. It checks if `codanna` is installed
3. If not found, it runs `cargo install codanna --all-features`
4. Installation takes ~5-10 minutes on first run
5. Subsequent sessions skip installation (codanna already installed)

### What You'll See

**First session (codanna not installed):**
```
⚠ codanna not found - attempting installation...
Installing codanna via cargo (this may take a few minutes)...
   Compiling codanna v0.8.7
   ...
✓ codanna installed successfully
```

**Subsequent sessions:**
```
✓ codanna is installed
```

## Manual Setup

If you prefer to install dependencies manually:

### 1. Install Rust/cargo

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source ~/.cargo/env
```

### 2. Install codanna

```bash
cargo install codanna --all-features
```

### 3. Install Python dependencies

```bash
cd /home/anl/mpy/mpy-reviewer
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

### 4. Verify Installation

```bash
# Check codanna
codanna --version

# Check Python package
mpy-reviewer stats
```

## Using the Skill

Once setup is complete, use the skill by asking Claude:

```
Can you review my current branch?
Can you /mpy-review the current branch?
Can you review commit abc123?
Can you find examples of memory allocation reviews?
```

**Note:** Skills are invoked BY Claude, not directly by users. See [SKILL_USAGE.md](../SKILL_USAGE.md) for details.

## Troubleshooting

### codanna installation fails

**Error: cargo not found**
```
Install Rust first:
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
  source ~/.cargo/env
```

**Error: compilation failed**
```
Check you have build tools:
  # Ubuntu/Debian
  sudo apt-get install build-essential

  # macOS
  xcode-select --install
```

### SessionStart hook doesn't run

The hook only runs when:
- Starting a new Claude Code session
- Using `claude --resume` to resume a session
- Running `/clear` command

To force it to run:
```bash
# Restart Claude Code in this directory
claude
```

### codanna installed but not found

Ensure `~/.cargo/bin` is in PATH:
```bash
# Add to ~/.bashrc or ~/.zshrc
export PATH="$HOME/.cargo/bin:$PATH"

# Reload shell
source ~/.bashrc  # or source ~/.zshrc
```

### Python dependencies not installed

```bash
cd /home/anl/mpy/mpy-reviewer
source venv/bin/activate
pip install -e .
```

## Advanced: Hook Configuration

The SessionStart hook is configured in `.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/ensure-codanna.sh",
            "description": "Ensure codanna is installed for codebase analysis"
          }
        ]
      }
    ]
  }
}
```

### Disabling Automatic Installation

To disable the automatic installation:

```bash
# Rename the settings file
mv .claude/settings.json .claude/settings.json.disabled
```

You'll then need to manually ensure codanna is installed.

## Why codanna is Required

The mpy-review skill uses codanna for:
- **Semantic code search**: Finding symbol definitions across the MicroPython codebase
- **Call graph analysis**: Understanding function relationships
- **Fast lookups**: <10ms symbol queries with memory-mapped caching
- **Cross-file tracking**: Following includes, dependencies, and usage

Without codanna, the tool **will fail with a prominent error** directing you to install it.

## Performance Notes

**First-time setup:**
- Rust installation: ~5 minutes
- codanna compilation: ~5-10 minutes
- Total: ~10-15 minutes

**Subsequent usage:**
- SessionStart hook: <1 second (just checks if installed)
- Review operations: 5-20 seconds depending on diff size

The one-time setup cost is worth it for the significant quality improvement codanna provides.
