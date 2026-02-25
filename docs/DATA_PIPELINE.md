# Data Pipeline

The review database is built in three stages: collect, categorize, index. This document is the authoritative reference for running each stage.

## Prerequisites

- **uv** — Python package manager (`uv --version`); run `uv sync` to install all dependencies
- **`gh` CLI** — authenticated with a GitHub token that has repo read access (`gh auth status`)
- **`claude` CLI** — needed for the categorization step (`claude --version`)
- **Rust/cargo** — only if building codanna for codebase context features

## Step 1: Collect Reviews from GitHub

```bash
uv run python scripts/collect.py
```

Fetches PR metadata, review comments, issue comments, and review verdicts for all PRs where `dpgeorge` commented on `micropython/micropython`. Data is stored in `data/reviews.db`.

**Multi-repo collection:** Use `--repo` to collect from other repositories:

```bash
uv run python scripts/collect.py --repo micropython/micropython-lib
```

Each repo's sync state is tracked independently (`last_sync:{repo}` in `sync_state`). PR numbers are scoped by repo via `UNIQUE(repo, number)` in the `prs` table.

**Behaviour:**
- On first run: queries year-by-year (2013–present) to work around GitHub's 1000-result search limit.
- On subsequent runs: incremental sync from the `last_sync` date stored in `sync_state`.
- Checkpoints every 10 PRs — safe to interrupt and resume.

**Hardcoded values** (in `scripts/collect.py`):
| Constant | Value | Purpose |
|----------|-------|---------|
| `--repo` (default) | `micropython/micropython` | Target repository |
| `REVIEWER` | `dpgeorge` | Lead maintainer login |
| `REQUESTS_PER_HOUR` | 5000 | GitHub API rate limit budget |
| `REQUEST_DELAY` | ~0.72s | Per-request throttle |

**Rate limits:** ~674 PRs/hour (4 API calls per PR). Full collection takes 20–30 minutes; incremental runs are faster. Check remaining quota with `gh api rate_limit`.

## Step 2: Categorize Comments

```bash
nohup env -u CLAUDECODE uv run python scripts/categorize_headless.py > logs/categorization_$(date +%Y%m%d_%H%M%S).log 2>&1 &
tail -f logs/categorization_*.log
```

Uses `claude -p` in headless mode with JSON schema enforcement to classify each comment across 13 fields (domain, severity, component, language_context, etc.). Runs against the Haiku model for cost efficiency.

**Note:** The `env -u CLAUDECODE` is required when running from within a Claude Code session to allow nested `claude` CLI invocations.

**Hardcoded values** (in `scripts/categorize_headless.py`):
| Constant | Value | Purpose |
|----------|-------|---------|
| `BATCH_SIZE` | 10 | Comments per Claude invocation |
| `MAX_BUDGET` | `$50.00` | Spend cap per run |
| `TIMEOUT_SECONDS` | 300 | Per-batch timeout |

**Cost:** ~$2–4 for the full dataset (~19,500 comments).

**Check progress:**
```bash
uv run python -c "
import sqlite3
conn = sqlite3.connect('data/reviews.db')
total = conn.execute('SELECT COUNT(*) FROM review_comments').fetchone()[0]
total += conn.execute('SELECT COUNT(*) FROM issue_comments').fetchone()[0]
total += conn.execute(\"SELECT COUNT(*) FROM reviews WHERE body IS NOT NULL AND body != ''\").fetchone()[0]
categorized = conn.execute('SELECT COUNT(*) FROM comment_categories WHERE theme != \"FAILED_CATEGORIZATION\"').fetchone()[0]
print(f'Categorized: {categorized}/{total} ({100*categorized/total:.1f}%)')
"
```

Categorization uses a checkpoint system and can be interrupted and resumed.

## Step 3: Build Vector Index

```bash
uv run python scripts/build_index_resume.py 2>&1 | tee logs/index_build_$(date +%Y%m%d_%H%M%S).log
```

Embeds all categorized comments using CodeRankEmbed (768 dimensions) into a sqlite-vec `vec0` virtual table, with an FTS5 full-text index alongside it.

**Performance (CPU, WSL2, 45GB RAM):**
- ~5 hours for ~19,500 records
- ~6GB peak memory with batch_size=4
- 2–13 items/sec depending on text length

The script supports resume — interruptions are safe. Progress is checkpointed per batch.

## Step 4: Verify

```bash
# Index statistics
uv run mpy-reviewer stats

# Test search
uv run mpy-reviewer search "memory allocation" -k 5

# Programmatic check
uv run python -c "
from rag.indexer import get_sqlite_connection, _vec_table_exists
conn = get_sqlite_connection()
print(f'Index exists: {_vec_table_exists(conn)}')
row = conn.execute('SELECT count(*) FROM vec_reviews').fetchone()
print(f'Total records: {row[0]}')
conn.close()
"
```

## Troubleshooting

### Out of Memory During Indexing

The resume-capable script uses batch_size=4 and periodic GC by default. If memory is still an issue, edit the script's `batch_size` and `gc_interval` constants.

### Vector Index Not Found

```bash
uv run python -c "from rag.indexer import get_sqlite_connection, _vec_table_exists; conn = get_sqlite_connection(); print(_vec_table_exists(conn))"

# Rebuild
uv run python scripts/build_index_resume.py
```

### FTS5 Index Missing or Corrupted

```bash
uv run python scripts/add_fts_index.py
```

Rebuilds the FTS5 index from vec_reviews data without re-embedding (~5 seconds).

### Claude CLI Categorization Errors

```bash
claude --version          # Verify CLI is installed
uv run python scripts/debug_categorization.py  # Debug a single categorization
```

### GitHub API Rate Limits

```bash
gh api rate_limit
```

The collection script auto-throttles at ~0.72s per request.

## Useful SQL Queries

**Count comments by domain:**
```sql
SELECT d.name, COUNT(*) as count
FROM comment_categories cc
JOIN domains d ON cc.domain_id = d.id
WHERE cc.theme != 'FAILED_CATEGORIZATION'
GROUP BY d.name
ORDER BY count DESC;
```

**Style examples by component:**
```sql
SELECT cc.component, COUNT(*) as examples
FROM comment_categories cc
WHERE cc.is_style_example = 1
GROUP BY cc.component
ORDER BY examples DESC;
```

**Port-specific review counts:**
```sql
SELECT cc.port, COUNT(*) as count
FROM comment_categories cc
WHERE cc.port IS NOT NULL
GROUP BY cc.port
ORDER BY count DESC;
```
