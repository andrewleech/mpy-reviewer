# Contributing to mpy-reviewer

## Development Setup

```bash
git clone https://github.com/andrewleech/mpy-reviewer.git
cd mpy-reviewer

uv sync --all-extras

# For codebase analysis features
cargo install codanna --all-features
```

CPU-only PyTorch is configured automatically via `[tool.uv.sources]` in pyproject.toml.

## Repository Structure

```
mpy-reviewer/
├── data/
│   └── reviews.db                 # SQLite database + vec0 vector index
├── mcp_server.py                  # FastMCP server (stdio transport)
├── rag/                           # RAG Python package
│   ├── cli.py                     # CLI entry point
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
│   ├── collect.py                 # GitHub API data collection
│   ├── categorize_headless.py     # Claude CLI batch categorization
│   ├── build_index_resume.py      # Resume-capable index builder
│   ├── analyze_usage.py           # Usage log analysis
│   └── migrate_schema.py          # Database schema migrations
├── skills/review/SKILL.md         # Claude Code skill definition
├── hooks/                         # Plugin hooks
├── .claude-plugin/                # Plugin manifest
├── .mcp.json                      # MCP server config
├── schema.sql                     # SQLite schema definition
├── pyproject.toml                 # Package configuration
└── CLAUDE.md                      # AI agent context
```

## Data Pipeline

The review database is built in three stages: collection, categorization, and indexing.

### 1. Collect Reviews from GitHub

```bash
source venv/bin/activate
python scripts/collect.py
```

This fetches PR metadata, review comments, issue comments, and review verdicts from micropython/micropython via the GitHub API. Collection is incremental — it checkpoints progress and picks up where it left off.

**Performance:** ~674 PRs/hour, limited by GitHub API rate limits (5000 requests/hour). Full collection from scratch takes 20-30 minutes; incremental runs are faster.

**GitHub API notes:**
- The search API returns max 1000 results per query. The script works around this by querying year-by-year (2013-present).
- Rate limiting is handled automatically with ~0.72s delay between requests.

### 2. Categorize Comments

```bash
nohup python scripts/categorize_headless.py > logs/categorization_$(date +%Y%m%d_%H%M%S).log 2>&1 &
tail -f logs/categorization_*.log
```

Categorization uses Claude CLI (`claude -p`) in headless mode with JSON schema enforcement. Each comment is classified across 13 fields using the Haiku model for cost efficiency.

**Performance:** 40-100 minutes for the full dataset, ~$2-4 total cost.

**Check progress:**
```bash
python -c "
import sqlite3
conn = sqlite3.connect('data/reviews.db')
total = conn.execute('SELECT COUNT(*) FROM review_comments').fetchone()[0]
total += conn.execute('SELECT COUNT(*) FROM issue_comments').fetchone()[0]
total += conn.execute('SELECT COUNT(*) FROM reviews WHERE body IS NOT NULL').fetchone()[0]
categorized = conn.execute('SELECT COUNT(*) FROM comment_categories WHERE theme != \"FAILED_CATEGORIZATION\"').fetchone()[0]
print(f'Categorized: {categorized}/{total} ({100*categorized/total:.1f}%)')
"
```

### 3. Build Vector Index

```bash
python scripts/build_index_resume.py 2>&1 | tee logs/index_build_$(date +%Y%m%d_%H%M%S).log
```

Embeds all categorized comments using CodeRankEmbed (768 dimensions) into a sqlite-vec `vec0` virtual table with an FTS5 full-text index alongside it.

**Performance:** ~5 hours for 18,614 records on CPU (WSL2, 45GB RAM). The script supports resume, so interruptions are safe. Memory usage peaks at ~6GB with default batch size.

**Verify:**
```bash
mpy-reviewer stats
```

## Database Schema

### Tables

| Table | Purpose |
|-------|---------|
| `prs` | PR metadata (number, title, author, state, dates, changed files) |
| `review_comments` | Inline code review comments with diff_hunk context |
| `issue_comments` | PR discussion comments |
| `reviews` | Review verdicts (APPROVED, CHANGES_REQUESTED) with body |
| `comment_categories` | 13-field categorization for each comment |
| `domains` | Domain lookup table |
| `sync_state` | Checkpoint tracking for resumable collection/categorization |

### Categorization Fields

**Core:** domain, theme, severity, is_style_example

**Component:** component, port, subsystem

**Technical context:** language_context, code_construct, concern_type

**Comment characteristics:** feedback_type, is_pattern, cpython_related, has_code_suggestion, keywords

See `CLAUDE.md` for full field descriptions and allowed values.

### Vector Index

| Table | Purpose |
|-------|---------|
| `vec_reviews` | vec0 virtual table with 768-dim cosine embeddings + all categorization metadata |
| `review_fts` | FTS5 contentless table on comment body text |
| `vec_index_meta` | Index build metadata |

## Technical Notes

### Categorization Challenges

- Some comments are purely procedural (merges, closes) and get tagged as such
- `is_pattern` determination requires understanding broader context — some false negatives are expected
- `domain` and `concern_type` have intentional overlap (domain is the broad category, concern_type is the specific nature of the feedback)

### Data Quality

From validation on 40 samples:
- 100% of comments were categorizable with the 13-field schema
- <5% ambiguity in field assignment (mostly domain vs concern_type)
- Appropriate NULL usage (subsystem is NULL for ~46% of general comments)
- 30% of comments include concrete code suggestions

### Database Design

- Diff context is stored with review comments for self-contained retrieval
- Original GitHub IDs preserved for traceability
- Separate tables for different comment types (review vs issue vs verdict)
- Denormalized categories table for query performance

## Running Tests

```bash
source venv/bin/activate
pytest
```

## See Also

- `CLAUDE.md` — full project context for AI agents, including retrieval pipeline architecture and configuration details
- `skills/review/SKILL.md` — Claude Code skill definition
