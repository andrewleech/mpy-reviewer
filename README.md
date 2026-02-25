# mpy-reviewer

Code review feedback for MicroPython projects, based on historical review patterns from the micropython/micropython repository. Surfaces relevant past reviews, coding conventions, and common issues to help you catch problems before submitting a PR.

## What It Does

When you're working on MicroPython code, mpy-reviewer searches a database of ~19.5K categorized review comments to find feedback relevant to your changes. It covers:

- **Correctness** — logic bugs, edge cases, missing error handling
- **Memory safety** — allocation patterns, leaks, embedded constraints
- **API design** — clean interfaces, constructor conventions, backwards compatibility
- **Code style** — MicroPython naming, formatting, preprocessor conventions
- **Portability** — cross-platform assumptions, struct alignment, platform-specific behavior
- **Testing** — coverage gaps, board-specific vs generic tests

Results are filtered by component (py_core, extmod, ports, etc.), severity (blocking, suggestion, nitpick), and domain, so feedback is targeted to the code you're actually changing.

## Quick Start

### Claude Code Plugin (recommended)

```
/plugin marketplace add andrewleech/mpy-reviewer
/plugin install mpy-reviewer@mpy-reviewer
```

The plugin's SessionStart hook installs dependencies via uv and starts the MCP server automatically. Requires Python 3.10+, uv, and Rust/cargo (codanna is installed automatically for codebase-aware search).

Once installed, ask Claude to review your code:

```
Can you review my current branch?
Can you review commit ca65d543?
Can you review my changes to py/gc.c?
Find examples of memory allocation reviews.
```

### CLI

For use outside Claude Code:

```bash
cd /path/to/mpy-reviewer
uv sync
uv run mpy-reviewer stats
```

## What Kind of Feedback to Expect

Reviews follow the patterns established in the MicroPython project's review history: terse, technical, and direct. No filler, no gratuitous praise.

### Communication Style

Feedback is characteristically brief. Nitpicks are extremely short (median 45 characters), blocking comments are concise but include enough technical detail to explain why.

Common patterns:
- Direct statement: "This should be...", "This needs...", "This will..."
- Question: "Is there a reason...?", "Why not...?", "Can this...?"
- Instruction: "Please use...", "Please reorder...", "Please add..."
- Suggestion: "Maybe use...", "Would it be better to...?"

Examples from real reviews:
```
"please no blank lines at start of files"
"please put `void` in arg list"
"this can just be a `bool`"
"Why not `mp_obj_get_int(args[3])`? That will do error checking that it's an int."
"Please use `mp_hal_pin_config(...)`"
"To avoid labels and goto (which is nice if possible)..."
"I think this function should be called X. Is that what it's doing?"
```

### Recurring Patterns

These are the most common categories of feedback across the project's review history:

**API Design:**
- Use constructor arguments with sensible defaults
- Use descriptive function names that explain purpose
- Use MicroPython HAL abstraction functions for consistency
- Clarify meaning of special values (like 0, -1, NULL)

**Code Style:**
- Prefer bool over int for boolean values
- Avoid negation in preprocessor conditionals (use positive logic)
- Avoid goto statements, prefer fall-through logic
- Wrap macro arguments in parentheses
- Watch for macro double-evaluation side effects
- Comment when intentionally discarding return values
- Extract repeated code to helper functions

**Portability:**
- Consider struct member alignment for cross-platform compatibility
- Test on multiple platforms before assuming behavior

**Testing:**
- Prefer generic tests that work on all boards over board-specific tests
- Keep tests focused and separated
- Ensure test coverage before merge

**Documentation:**
- Provide examples rather than just descriptions
- Reference shared documentation instead of duplicating

## Usage

### CLI

```bash
# Search for relevant past reviews
mpy-reviewer search "memory allocation error handling" -k 10

# Search with filters
mpy-reviewer search "GPIO configuration" --component port_specific --domain api_design

# Review a PR
mpy-reviewer review --pr 17321

# Review a diff from stdin
git diff main | mpy-reviewer review --stdin --output prompt

# Review a diff file
mpy-reviewer review --diff changes.patch

# Show index statistics
mpy-reviewer stats
```

### Python API

```python
from rag.retriever import search, find_similar

# Semantic search
results = search("memory allocation in C", top_k=10)

# Search with filters
results = search(
    "error handling",
    top_k=10,
    domain="correctness",
    component="py_core",
    severity="blocking",
)

# Find similar reviews for a code diff
results = find_similar(diff_text, top_k=8)
```

Use `uv run python` or activate the venv first (`source .venv/bin/activate`).

### MCP Tools (Claude Code)

When running as a plugin, the MCP server provides these tools:

| Tool | Purpose |
|------|---------|
| `review_diff` | Review a unified diff against historical patterns |
| `review_pr` | Review a GitHub PR by number |
| `search_reviews` | Semantic search with metadata filters |
| `find_style_examples` | Find comments that exemplify the review style |
| `get_review_stats` | Index statistics |
| `get_pr_review_history` | Full review thread history for a PR |

### Filter Dimensions

| Filter | Values |
|--------|--------|
| Domain | correctness, code_style, api_design, memory, performance, portability, documentation, testing, security, architecture, build_system |
| Severity | blocking, suggestion, nitpick |
| Component | py_core, extmod, port_specific, drivers, tools, tests, docs, build_system |
| Language | c_code, python_code, documentation, makefile, yaml, shell_script |

## How It Works

Review comments from the MicroPython repository have been categorized across 13 dimensions (domain, severity, component, language, etc.) and indexed for semantic search.

When you submit code for review, the system finds past reviews that are relevant to your changes — matching on code similarity, file paths, and component context. Results are selected for diversity across severity levels and domains so you get a balanced set of feedback, not just the closest matches.

## Roadmap

- GitHub Actions integration for automated review suggestions on PRs
- Continuous collection of new reviews as the project evolves
- Author-aware review context — calibrate feedback depth based on contributor history
- Incremental index updates without full rebuild

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, the data pipeline (collecting and indexing new reviews), and database schema details.

## License

Data collected from the public GitHub repository micropython/micropython.
Scripts and tools: MIT License.
