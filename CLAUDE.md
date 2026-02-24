# mpy-reviewer CLAUDE.md

This file provides context for AI coding agents working on the MicroPython Review Database project.

## Project Overview

This project creates a queryable RAG (Retrieval-Augmented Generation) system of the MicroPython lead maintainer's code review patterns from the micropython/micropython GitHub repository. The goal is to enable AI-assisted PR reviews that match the lead maintainer's technical standards and communication style.

**Key Features:**
- Collect all review comments from the lead maintainer via GitHub API
- Categorize comments using 13-field enhanced schema via Claude CLI
- Build vector index with CodeRankEmbed embeddings for semantic search
- Hybrid retrieval (dense + full-text) with metadata filtering and heuristic boosting
- MCP server for persistent warm-model access during Claude Code sessions
- CLI for searching and generating review context
- Graph-aware context expansion (reply chains, PR sibling comments, file-level aggregation)

**Current Status:**
- ✅ Data collection complete (22,805 comments from 5,542 PRs)
- ✅ Categorization complete (18,614 categorized comments)
- ✅ Vector index built (sqlite-vec with 768-dim CodeRankEmbed embeddings)
- ✅ Semantic search validated and working
- ✅ CLI tools operational
- ✅ MCP server with 6 tools (review_diff, review_pr, search_reviews, find_style_examples, get_review_stats, get_pr_review_history)
- ✅ Claude Code skill available (fallback for non-MCP sessions)
- ✅ Usage logging and performance analysis enabled

**MCP Output Architecture:**
The `review_diff` and `review_pr` MCP tools use a file-based output strategy to stay within Claude Code's 25K-token MCP result limit. Instead of returning a monolithic JSON blob with inline examples and duplicated diff text, they:
1. Write each retrieved review example to its own temp file under `/tmp/mpy-review-*/`
2. Return a compact orchestration prompt (~5-8K chars) containing a summary table of file paths/sizes, the style guide, and workflow instructions
3. The calling agent reads example files as needed — small ones directly, large ones via subagents

This avoids echoing the diff (already in the caller's context) and eliminates data duplication between `prompt` and `examples` fields.

## Directory Structure

```
mpy-reviewer/
├── data/
│   └── reviews.db                 # SQLite database + vec0 vector index
├── mcp_server.py                  # FastMCP server (stdio transport)
├── rag/                           # RAG Python package
│   ├── __init__.py
│   ├── cli.py                     # Command-line interface
│   ├── config.py                  # Configuration management
│   ├── embeddings.py              # CodeRankEmbed embeddings wrapper
│   ├── graph_expander.py          # Reply chain / PR context expansion
│   ├── indexer.py                 # sqlite-vec index builder
│   ├── retriever.py               # Hybrid search with heuristic boosting
│   ├── reranker.py                # Cross-encoder re-ranking
│   ├── codebase.py                # MicroPython codebase context
│   ├── fusion.py                  # Rank fusion utilities
│   ├── prompt_builder.py          # Review prompt generation
│   ├── evaluator.py               # Retrieval evaluation
│   └── usage_logger.py            # Performance logging
├── scripts/
│   ├── collect.py                 # Collect reviews from GitHub
│   ├── categorize_headless.py     # Batch categorize with Claude CLI
│   ├── build_index_resume.py      # Resume-capable index builder
│   ├── analyze_usage.py           # Analyze usage logs for performance
│   ├── migrate_schema.py          # Database schema migrations
│   └── ...                        # Other utility scripts
├── skills/
│   └── review/
│       └── SKILL.md               # Claude Code skill configuration
├── hooks/
│   ├── hooks.json                 # Plugin hook definitions
│   └── setup.sh                   # Venv, package, and codanna setup
├── .claude-plugin/
│   ├── plugin.json                # Plugin manifest
│   └── marketplace.json           # Marketplace catalog
├── .mcp.json                      # MCP server config (plugin installs)
├── docs/                          # Documentation and notes
├── logs/                          # Script logs
├── venv/                          # Python virtual environment
├── pyproject.toml                 # Package configuration
├── requirements.txt               # Dependencies
├── schema.sql                     # SQLite schema definition
└── CLAUDE.md                      # This file
```

## Quick Start

### Install as Claude Code Plugin

```
/plugin marketplace add andrewleech/mpy-reviewer
/plugin install mpy-reviewer@mpy-reviewer
```

The plugin's SessionStart hook creates the venv, installs the package, and installs codanna automatically. Requires Python 3.10+ and Rust/cargo.

### Manual Setup

For development on this repo or use outside Claude Code:

```bash
cd /home/anl/mpy/mpy-reviewer

python3 -m venv venv
source venv/bin/activate

pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e .

cargo install codanna --all-features
```

### Using the CLI

```bash
# Show index statistics
mpy-reviewer stats

# Search for similar reviews
mpy-reviewer search "memory allocation error handling" -k 5

# Search with filters
mpy-reviewer search "GPIO configuration" --component port_specific --domain api_design

# Generate review context for a PR
mpy-reviewer review --pr 17321

# Generate review context from a diff file
mpy-reviewer review --diff path/to/changes.diff

# Output as JSON for programmatic use
mpy-reviewer search "type checking" --json
```

### Using as a Claude Code Skill

Once the plugin is installed, ask Claude to review code using natural language:

```
Can you review my current branch?
Can you review commit ca65d543?
Can you review my changes to py/gc.c?
Can you find examples of memory allocation reviews?
```

Skills are invoked by Claude, not directly by users. See `skills/review/SKILL.md` for the skill's instructions.

### Python API

```python
from rag.retriever import get_retriever, search, find_similar
from rag.embeddings import get_embedder

# Simple search
results = search("memory allocation in C", top_k=10)

# Search with filters
results = search(
    "error handling",
    top_k=10,
    domain="correctness",
    component="py_core",
    severity="blocking"
)

# Find similar reviews for a code diff
diff_text = "..." # Your diff content
results = find_similar(diff_text, top_k=8)

# Direct embedding access
embedder = get_embedder()
vec = embedder.embed_single("some query text")
```

### Usage Logging and Performance Analysis

All CLI operations are automatically logged to `logs/usage.jsonl` for performance analysis. The logging captures:
- Operation type (search, review, index, eval)
- All parameters (query, filters, options)
- Duration in milliseconds
- Result count
- Any errors that occurred

**View usage logs:**

```bash
# Analyze performance metrics
python scripts/analyze_usage.py

# Or manually inspect the JSONL file
cat logs/usage.jsonl | jq '.'

# Filter to specific operations
cat logs/usage.jsonl | jq 'select(.operation == "review")'

# Calculate average duration for reviews
cat logs/usage.jsonl | jq -s 'map(select(.operation == "review" and .error == null)) | add / length | {avg_duration_ms: .duration_ms}'
```

**Example analysis output:**

```
=== Performance Analysis ===

Total operations: 42
Total errors: 0
Success rate: 100.0%

review:
  Count: 24
  Avg duration: 3247 ms
  Min duration: 1832 ms
  Max duration: 12403 ms
  Avg results: 8.0

  With --rerank: 8234 ms (n=8)
  Without --rerank: 1947 ms (n=16)
  Rerank overhead: +6287 ms (+323%)

  With --codebase: 4521 ms (n=12)
  Without --codebase: 2103 ms (n=12)
  Codebase overhead: +2418 ms (+115%)

search:
  Count: 18
  Avg duration: 892 ms
  Avg results: 10.2
```

**Log entry format:**

```json
{
  "timestamp": "2026-01-03T14:20:43.166079",
  "operation": "review",
  "params": {
    "pr_number": null,
    "diff_file": "changes.patch",
    "use_stdin": false,
    "top_k": 8,
    "rerank": true,
    "codebase": true,
    "output": "prompt"
  },
  "duration_ms": 4521.34,
  "result_count": 8,
  "error": null
}
```

The usage logs help identify performance bottlenecks, measure the impact of different options (--rerank, --codebase), and track success rates over time.

## Data Pipeline

The database is extended via a 3-stage pipeline: collect → categorize → index. Each stage is resumable.

```bash
source venv/bin/activate
python scripts/collect.py                # 1. Fetch from GitHub API (requires gh CLI)
python scripts/categorize_headless.py    # 2. Classify via Claude CLI
python scripts/build_index_resume.py     # 3. Embed + build vec0/FTS5 index
mpy-reviewer stats                       # 4. Verify
```

See [docs/DATA_PIPELINE.md](docs/DATA_PIPELINE.md) for prerequisites, hardcoded values, performance notes, and troubleshooting.

## Database Schema

### SQLite Tables (data/reviews.db)

**prs** - Pull request metadata
- id, number, title, body, author, state, created_at, merged_at, etc.

**review_comments** - Inline code comments
- id, pr_number, body, path, line, diff_hunk, created_at

**issue_comments** - PR discussion comments
- id, pr_number, body, created_at

**reviews** - Overall PR reviews (APPROVED/CHANGES_REQUESTED)
- id, pr_number, state, body, created_at

**comment_categories** - 13-field categorizations
- Links to comments via comment_id + comment_type
- See Categorization Fields below

### vec0 Virtual Table (vec_reviews in reviews.db)

All categorization fields stored as vec0 metadata or auxiliary columns, plus:
- `embedding`: 768-dimensional CodeRankEmbed vector (cosine distance)
- FTS5 index on `body` field (contentless `review_fts` table)
- Index metadata in `vec_index_meta` table

### Categorization Fields (13 total)

**Core Fields:**
- `domain`: code_style, memory, error_handling, api_design, performance, portability, documentation, testing, security, architecture, build_system, correctness
- `theme`: Concise description of specific issue/pattern
- `severity`: blocking, suggestion, nitpick
- `is_style_example`: Boolean - demonstrates the lead maintainer's communication style

**Enhanced Fields:**
- `component`: py_core, extmod, port_specific, drivers, tools, tests, docs, build_system, examples
- `port`: esp32, stm32, rp2, unix, etc. (null for generic)
- `subsystem`: bluetooth, usb, uart, gc, vm, etc. (null if not applicable)
- `language_context`: c_code, python_code, documentation, makefile, cmake, shell_script, yaml
- `code_construct`: function, macro, struct, typedef, class, module, test_case, etc.
- `concern_type`: correctness, safety, api_design, style, performance, portability, etc.
- `feedback_type`: question, suggestion, requirement, information, praise, merge
- `is_pattern`: Boolean - reusable across contexts
- `cpython_related`: Boolean - mentions CPython/PEP standards
- `has_code_suggestion`: Boolean - includes code examples
- `keywords`: JSON array of 2-5 technical terms

## Current Index Statistics (December 2024)

```
Total indexed records: 18,614

Domain Distribution:
  correctness:   3,939 (21.2%)
  code_style:    3,212 (17.3%)
  api_design:    2,369 (12.7%)
  documentation: 2,138 (11.5%)
  architecture:  2,098 (11.3%)
  testing:       1,547 (8.3%)
  build_system:  1,334 (7.2%)
  portability:     675 (3.6%)
  performance:     604 (3.2%)
  memory:          554 (3.0%)

Component Distribution:
  port_specific: 6,039 (32.4%)
  py_core:       5,943 (31.9%)
  extmod:        1,827 (9.8%)
  docs:          1,201 (6.5%)
  tests:         1,150 (6.2%)
  build_system:  1,142 (6.1%)
  tools:           831 (4.5%)
  drivers:         406 (2.2%)

Severity Distribution:
  suggestion: 10,778 (57.9%)
  nitpick:     5,297 (28.5%)
  blocking:    2,539 (13.6%)

Language Context:
  c_code:        12,437 (66.8%)
  python_code:    3,196 (17.2%)
  documentation:  1,715 (9.2%)
  makefile:         649 (3.5%)
  yaml:             302 (1.6%)
  shell_script:     172 (0.9%)

Quality Metrics:
  Reusable patterns (is_pattern=true): 55.9%
  Has code suggestion: 33.1%
```

## Troubleshooting

### Out of Memory During Indexing

Reduce batch size and increase GC frequency:

```python
batch_size = 4     # Reduce from default 100
gc_interval = 50   # Force GC every 50 batches
```

The resume-capable script above handles this automatically.

### Slow Indexing on CPU

This is expected. CPU-only embedding with CodeRankEmbed processes 2-13 items/sec. For 18,614 records:
- Expected time: 4-6 hours
- The script supports resume, so interruptions are safe

### Vector Index Not Found

If the vec_reviews table doesn't exist yet:

```bash
# Check if table exists
python -c "from rag.indexer import get_sqlite_connection, _vec_table_exists; conn = get_sqlite_connection(); print(_vec_table_exists(conn))"

# Build or rebuild the index
python scripts/build_index_resume.py
```

### Full-Text Search Error

If the FTS5 index is missing or corrupted, rebuild it:

```bash
source venv/bin/activate
python scripts/add_fts_index.py
```

This rebuilds the FTS5 index from vec_reviews data without re-embedding (takes ~5 seconds).

### Claude CLI Categorization Errors

```bash
# Debug single categorization
python scripts/debug_categorization.py

# Check Claude CLI works
claude --version

# Check budget/rate limits in script output
```

### GitHub Collection Rate Limits

```bash
# Check remaining API calls
gh api rate_limit

# The collection script auto-throttles at ~0.72 seconds/request
```

## Retrieval Pipeline Architecture

```
Query Text
    │
    ├──► Dense Search (CodeRankEmbed → cosine similarity)
    │         └─► Top 100 candidates
    │
    ├──► Full-Text Search (FTS5 on body field)
    │         └─► Top 100 candidates
    │
    └──► Metadata Filters (domain, severity, component, language)
              │
              ▼
    Reciprocal Rank Fusion (RRF k=60)
              │
              ▼
    Heuristic Boosts (file-path affinity, pattern/code-suggestion preference)
              │
              ▼
    MMR Diversity Selection (severity constraints + domain diversity)
              │
              ▼
    Graph Expansion (reply chains attached as thread metadata)
              │
              ▼
    Optional: Cross-Encoder Re-ranking (BGE-reranker-large)
              │
              ▼
    Final Top-K Results
```

## Files Reference

| File | Purpose |
|------|---------|
| `mcp_server.py` | FastMCP server (6 tools, stdio transport) |
| `rag/indexer.py` | sqlite-vec index builder (vec0 + FTS5) |
| `rag/embeddings.py` | CodeRankEmbed embeddings (query/doc distinction) |
| `rag/retriever.py` | Hybrid dense+FTS search with heuristic boosting |
| `rag/graph_expander.py` | Reply chain, PR sibling, and file-level expansion |
| `rag/prompt_builder.py` | Data-driven style guide and prompt assembly |
| `rag/cli.py` | `mpy-reviewer` command-line interface |
| `rag/usage_logger.py` | Usage tracking and performance logging |
| `rag/config.py` | Paths, model settings, retrieval parameters |
| `scripts/collect.py` | GitHub API → SQLite collection |
| `scripts/categorize_headless.py` | Claude CLI batch categorization |
| `scripts/analyze_usage.py` | Performance analysis from usage logs |

## Dependencies

Core:
- `sqlite-vec>=0.1.6` - Vector search extension for SQLite
- `transformers>=4.36.0` - Model loading
- `torch>=2.0.0` - PyTorch (CPU or CUDA)
- `click>=8.0.0` - CLI framework
- `tqdm` - Progress bars

Optional:
- `sentence-transformers` - For cross-encoder re-ranking
