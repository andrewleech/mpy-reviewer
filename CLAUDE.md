# dpgeorge-review-db CLAUDE.md

This file provides context for AI coding agents working on the dpgeorge Review Database project.

## Project Overview

This project creates a queryable RAG (Retrieval-Augmented Generation) system of Damien George's (dpgeorge) code review patterns from the micropython/micropython GitHub repository. The goal is to enable AI-assisted PR reviews that match dpgeorge's technical standards and communication style.

**Key Features:**
- Collect all review comments from dpgeorge via GitHub API
- Categorize comments using 13-field enhanced schema via Claude CLI
- Build vector index with Jina embeddings for semantic search
- Hybrid retrieval (dense + full-text) with metadata filtering
- CLI for searching and generating review context

**Current Status:**
- ✅ Data collection complete (22,805 comments from 5,542 PRs)
- ✅ Categorization complete (18,614 categorized comments)
- ✅ Vector index built (LanceDB with 768-dim Jina embeddings)
- ✅ Semantic search validated and working
- ✅ CLI tools operational
- ✅ Claude Code skill available
- ✅ Usage logging and performance analysis enabled

## Directory Structure

```
dpgeorge-review-db/
├── data/
│   ├── dpgeorge_reviews.db        # SQLite database (source of truth)
│   └── lance/                     # LanceDB vector index
│       └── dpgeorge_reviews.lance/
├── rag/                           # RAG Python package
│   ├── __init__.py
│   ├── cli.py                     # Command-line interface
│   ├── config.py                  # Configuration management
│   ├── embeddings.py              # Jina embeddings wrapper
│   ├── indexer.py                 # SQLite → LanceDB indexer
│   ├── retriever.py               # Hybrid search implementation
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
├── skill/
│   └── SKILL.md                   # Claude Code skill configuration
├── docs/                          # Documentation and notes
├── logs/                          # Script logs
├── venv/                          # Python virtual environment
├── pyproject.toml                 # Package configuration
├── requirements.txt               # Dependencies
├── schema.sql                     # SQLite schema definition
└── CLAUDE.md                      # This file
```

## Quick Start

### Setup Environment

```bash
cd /home/anl/mpy/dpgeorge-review-db

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install all dependencies (includes reranking and codebase context)
pip install -e .

# For CPU-only PyTorch (recommended for WSL2/systems without CUDA):
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

### Using the CLI

```bash
# Show index statistics
mpy-review-rag stats

# Search for similar reviews
mpy-review-rag search "memory allocation error handling" -k 5

# Search with filters
mpy-review-rag search "GPIO configuration" --component port_specific --domain api_design

# Generate review context for a PR
mpy-review-rag review --pr 17321

# Generate review context from a diff file
mpy-review-rag review --diff path/to/changes.diff

# Output as JSON for programmatic use
mpy-review-rag search "type checking" --json
```

### Using as a Claude Code Skill

The system can be installed as a Claude Code skill for conversational access within Claude Code sessions.

**Installation:**

```bash
# Create skill directory
mkdir -p ~/.claude/skills/mpy-review

# Link the SKILL.md file
ln -s /home/anl/mpy/dpgeorge-review-db/skill/SKILL.md \
      ~/.claude/skills/mpy-review/SKILL.md
```

**Usage:**

Once installed, ask Claude to review your code using natural language:

```
# Review your current changes
Can you review my current branch?
Can you /mpy-review the current branch?

# Review specific commit
Can you review commit ca65d543?
Can you /mpy-review commit ca65d543?

# Review specific files
Can you review my changes to py/gc.c?

# Find review examples
Can you find examples of memory allocation reviews?
Can you /mpy-review find examples of memory allocation?

# Get quick context
What has dpgeorge said about error handling?
```

**Note:** Skills are invoked BY Claude, not directly by users. You ask Claude to use the skill, and Claude runs the appropriate commands.

**Features:**
- Natural language interface (no CLI arguments needed)
- Agent interprets intent and runs appropriate git/search commands
- Semantic search across 18,614 categorized review comments
- Automatic diff generation for commits, branches, files
- Generates dpgeorge-style review feedback

**How it works:**
The skill agent parses your natural language request, runs the appropriate git commands to generate diffs, pipes them to the review tool, and presents the results conversationally.

**Documentation:** See `skill/SKILL.md` for the agent's complete instructions including:
- Intent parsing and command mapping
- Git integration patterns
- When to use different options
- Error handling

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

## Complete Workflow: Collecting and Indexing New Reviews

To extend the database with newer review data:

### Step 1: Collect New Reviews from GitHub

```bash
cd /home/anl/mpy/dpgeorge-review-db
source venv/bin/activate

# Run collection (incremental if previous sync exists)
python scripts/collect.py

# This will:
# - Search for PRs where dpgeorge commented
# - Use year-based pagination to work around GitHub's 1000-result limit
# - Fetch PR details, review comments, issue comments, and reviews
# - Store in data/dpgeorge_reviews.db
# - Checkpoint progress for resume capability

# Time: ~20-30 min for full collection, faster for incremental
# Rate: Limited by GitHub API (~5000 requests/hour)
```

### Step 2: Categorize New Comments with Claude CLI

```bash
# Run categorization (uses checkpoint/resume)
nohup python scripts/categorize_headless.py > logs/categorization_$(date +%Y%m%d_%H%M%S).log 2>&1 &

# Monitor progress
tail -f logs/categorization_*.log

# Check categorization status
python -c "
import sqlite3
conn = sqlite3.connect('data/dpgeorge_reviews.db')
total = conn.execute('SELECT COUNT(*) FROM review_comments').fetchone()[0]
total += conn.execute('SELECT COUNT(*) FROM issue_comments').fetchone()[0]
total += conn.execute('SELECT COUNT(*) FROM reviews WHERE body IS NOT NULL').fetchone()[0]
categorized = conn.execute('SELECT COUNT(*) FROM comment_categories WHERE theme != \"FAILED_CATEGORIZATION\"').fetchone()[0]
print(f'Categorized: {categorized}/{total} ({100*categorized/total:.1f}%)')
"

# Cost: ~$2-4 total for full dataset (using Haiku)
# Time: ~40-100 minutes for full dataset
```

### Step 3: Build Vector Index

For large datasets or memory-constrained systems, use the resume-capable indexing approach:

```python
#!/usr/bin/env python3
"""Resume-capable index builder with memory management."""
import logging
import gc
import os

os.chdir('/home/anl/mpy/dpgeorge-review-db')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger('transformers').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

import lancedb
from rag.indexer import get_sqlite_connection, iter_all_comments, count_comments
from rag.embeddings import get_embedder
from rag.config import get_config
from tqdm import tqdm

config = get_config()
db = lancedb.connect(str(config.lance_db_path))

# Check for existing index
try:
    table = db.open_table("dpgeorge_reviews")
    existing = table.to_pandas()[['comment_id', 'comment_type']]
    indexed_keys = set(zip(existing['comment_id'], existing['comment_type']))
    logger.info(f"Resuming: {len(indexed_keys)} records already indexed")
except:
    table = None
    indexed_keys = set()
    logger.info("Starting fresh index build")

conn = get_sqlite_connection()
total = count_comments(conn)
remaining = total - len(indexed_keys)
logger.info(f"Total: {total}, Remaining: {remaining}")

embedder = get_embedder()
batch_size = 4  # Small batches for memory-constrained systems
gc_interval = 50  # Force GC every N batches

batch_texts = []
batch_records = []
processed = 0
batch_count = 0

for comment in tqdm(iter_all_comments(conn), total=total, desc="Indexing"):
    key = (comment['comment_id'], comment['comment_type'])
    if key in indexed_keys:
        continue

    text = comment["body"] or ""
    if comment["diff_hunk"]:
        text = f"{text}\n\nCode context:\n{comment['diff_hunk']}"

    batch_texts.append(text)
    batch_records.append(comment)

    if len(batch_texts) >= batch_size:
        embeddings = embedder.embed_batch(batch_texts)
        for i, record in enumerate(batch_records):
            record["vector"] = embeddings[i].tolist()

        if table is None:
            table = db.create_table("dpgeorge_reviews", batch_records, mode="overwrite")
        else:
            table.add(batch_records)

        processed += len(batch_records)
        batch_count += 1

        if batch_count % 25 == 0:
            logger.info(f"Progress: {processed} new records (total: {len(indexed_keys) + processed})")

        if batch_count % gc_interval == 0:
            gc.collect()

        batch_texts = []
        batch_records = []

# Process remaining
if batch_texts:
    embeddings = embedder.embed_batch(batch_texts)
    for i, record in enumerate(batch_records):
        record["vector"] = embeddings[i].tolist()
    if table is None:
        table = db.create_table("dpgeorge_reviews", batch_records, mode="overwrite")
    else:
        table.add(batch_records)
    processed += len(batch_records)

logger.info(f"=== COMPLETE: {len(indexed_keys) + processed} total records indexed ===")

# Create full-text search index (required for hybrid retrieval)
if table is not None:
    logger.info("Creating full-text search index on 'body' column...")
    table.create_fts_index("body", replace=True)
    logger.info("✓ Full-text search index created successfully")

conn.close()
```

Save as `scripts/build_index_resume.py` and run:

```bash
source venv/bin/activate
python scripts/build_index_resume.py 2>&1 | tee logs/index_build_$(date +%Y%m%d_%H%M%S).log

# Or run in background
nohup python scripts/build_index_resume.py > logs/index_build.log 2>&1 &
tail -f logs/index_build.log
```

**Performance Characteristics:**
- Time: ~5 hours for 18,614 records on CPU (WSL2, 45GB RAM)
- Memory: ~6GB peak usage with batch_size=4
- Speed: Variable 2-13 items/sec depending on text length
- Model: Jina Embeddings v2 Base Code (768 dimensions)

### Step 4: Verify the Index

```bash
# Check index status
mpy-review-rag stats

# Test a search
mpy-review-rag search "memory allocation" -k 5

# Python verification
python -c "
import lancedb
db = lancedb.connect('data/lance')
t = db.open_table('dpgeorge_reviews')
print(f'Total records: {len(t)}')
print(f'Schema: {[f.name for f in t.schema]}')
df = t.to_pandas()
print(f'\\nDomain distribution:')
print(df['domain'].value_counts().head(5))
"
```

## Database Schema

### SQLite Tables (data/dpgeorge_reviews.db)

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

### LanceDB Schema (data/lance/dpgeorge_reviews.lance)

All categorization fields plus:
- `vector`: 768-dimensional Jina embedding
- Full-text search index on `body` field

### Categorization Fields (13 total)

**Core Fields:**
- `domain`: code_style, memory, error_handling, api_design, performance, portability, documentation, testing, security, architecture, build_system, correctness
- `theme`: Concise description of specific issue/pattern
- `severity`: blocking, suggestion, nitpick
- `is_style_example`: Boolean - demonstrates dpgeorge's communication style

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

This is expected. CPU-only embedding with Jina v2 Base Code processes 2-13 items/sec. For 18,614 records:
- Expected time: 4-6 hours
- The script supports resume, so interruptions are safe

### LanceDB Table Not Found

If the index doesn't exist yet:

```bash
# Check if table exists
python -c "import lancedb; db = lancedb.connect('data/lance'); print(db.table_names())"

# Build or rebuild the index
python scripts/build_index_resume.py
```

### Full-Text Search Error

If you get an error like:
```
RuntimeError: lance error: Invalid user input: Cannot perform full text search unless an INVERTED index has been created
```

The LanceDB table is missing the full-text search (FTS) index. This happens if the index was built before FTS indexing was added. Fix it with:

```bash
source venv/bin/activate
python scripts/add_fts_index.py
```

This adds the FTS index to the existing table without rebuilding embeddings (takes ~5 seconds).

**Note:** `scripts/build_index_resume.py` and `mpy-review-rag index` now automatically create the FTS index, so this should only be needed for indices built with older versions.

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
    ├──► Dense Search (Jina embeddings → cosine similarity)
    │         └─► Top 100 candidates
    │
    ├──► Full-Text Search (LanceDB FTS on body field)
    │         └─► Top 100 candidates
    │
    └──► Metadata Filters (domain, severity, component, language)
              │
              ▼
    Reciprocal Rank Fusion (RRF k=60)
              │
              ▼
    MMR Diversity Selection (balance domain/severity)
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
| `rag/indexer.py` | SQLite → LanceDB vector index builder |
| `rag/embeddings.py` | Jina v2 Base Code embeddings wrapper |
| `rag/retriever.py` | Hybrid dense+FTS search with RRF fusion |
| `rag/cli.py` | `mpy-review-rag` command-line interface |
| `rag/usage_logger.py` | Usage tracking and performance logging |
| `rag/config.py` | Paths, model settings, retrieval parameters |
| `scripts/collect.py` | GitHub API → SQLite collection |
| `scripts/categorize_headless.py` | Claude CLI batch categorization |
| `scripts/analyze_usage.py` | Performance analysis from usage logs |

## Dependencies

Core:
- `lancedb>=0.4.0` - Vector database
- `transformers>=4.36.0` - Jina model loading
- `torch>=2.0.0` - PyTorch (CPU or CUDA)
- `click>=8.0.0` - CLI framework
- `tqdm` - Progress bars
- `pyarrow` - LanceDB backend

Optional:
- `sentence-transformers` - For cross-encoder re-ranking
- `pandas` - For data inspection (used during resume indexing)
