# RAG System

Retrieval-Augmented Generation system built from the MicroPython lead
maintainer's code review history.

## What it contains

- ~19,465 categorized review comments from `micropython/micropython`
  (5,646 PRs) and `micropython/micropython-lib` (252 PRs)
- 768-dimensional CodeRankEmbed embeddings stored in a sqlite-vec virtual
  table (`vec_reviews`)
- Full-text search via FTS5 contentless table (`review_fts`)
- 13-field categorization schema per comment: domain, theme, severity,
  component, port, subsystem, language_context, code_construct,
  concern_type, feedback_type, is_pattern, cpython_related,
  has_code_suggestion, is_style_example, keywords
- Hybrid retrieval: dense cosine similarity + FTS5 BM25, fused with
  reciprocal rank fusion (RRF k=60), heuristic file-path affinity boosts,
  and MMR diversity selection

## How it was built

Three-stage pipeline, each stage resumable:

1. **Collect** -- `scripts/collect.py` fetches PR metadata and review
   comments from the GitHub API via `gh` CLI. Targets the `dpgeorge`
   reviewer on `micropython/micropython` and `micropython/micropython-lib`.
   Incremental: skips PRs already in the database.

2. **Categorize** -- `scripts/categorize_headless.py` classifies each
   uncategorized comment using Claude CLI with a 13-field JSON schema.
   Batch-processes with rate limiting and retry logic.

3. **Index** -- `scripts/build_index_resume.py` generates CodeRankEmbed
   embeddings and builds the sqlite-vec + FTS5 index. Resume-capable:
   tracks progress in `vec_index_meta` and skips already-indexed records.
   CPU-only embedding runs at 2-13 items/sec (~4-6 hours for the full set).

## How to update

```bash
# 1. Collect new reviews (incremental, skips existing)
uv run python scripts/collect.py

# 2. Categorize uncategorized comments
uv run python scripts/categorize_headless.py

# 3. Rebuild index (resume-capable)
uv run python scripts/build_index_resume.py

# 4. Verify
uv run mpy-reviewer stats
```

## How to regenerate development patterns

The `extract_patterns.py` script clusters review comments and distills
recurring patterns into a markdown document.

```bash
# With LLM distillation (uses Claude CLI)
uv run python scripts/extract_patterns.py --output mpy-rules/rules/development-patterns.md

# Heuristic mode (no Claude CLI needed)
uv run python scripts/extract_patterns.py --skip-llm --output /tmp/patterns_draft.md
```

## How to query

### CLI

```bash
# Semantic search
uv run mpy-reviewer search "memory allocation error handling" -k 10

# Search with filters
uv run mpy-reviewer search "GPIO configuration" --component port_specific --domain api_design

# Index statistics
uv run mpy-reviewer stats

# Generate review context from a diff file
uv run mpy-reviewer review --diff path/to/changes.diff

# JSON output for programmatic use
uv run mpy-reviewer search "type checking" --json
```

### Python API

```python
from rag.retriever import ReviewRetriever, search, find_similar
from rag.embeddings import get_embedder

# Simple search
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

### Direct SQL

```bash
sqlite3 data/reviews.db "SELECT COUNT(*) FROM comment_categories"
sqlite3 data/reviews.db "SELECT domain, COUNT(*) FROM comment_categories GROUP BY domain ORDER BY COUNT(*) DESC"
```

## Current statistics

- Total indexed records: ~19,465
- Repos: micropython/micropython (5,646 PRs), micropython/micropython-lib (252 PRs)

Domain distribution:

| Domain | Count | % |
|--------|-------|---|
| correctness | 4,100 | 21.1 |
| code_style | 3,328 | 17.1 |
| api_design | 2,493 | 12.8 |
| documentation | 2,244 | 11.5 |
| architecture | 2,236 | 11.5 |
| testing | 1,611 | 8.3 |
| build_system | 1,395 | 7.2 |
| portability | 695 | 3.6 |
| performance | 641 | 3.3 |
| memory | 575 | 3.0 |

Severity distribution:

| Severity | Count | % |
|----------|-------|---|
| suggestion | 11,393 | 58.6 |
| nitpick | 5,427 | 27.9 |
| blocking | 2,645 | 13.6 |
