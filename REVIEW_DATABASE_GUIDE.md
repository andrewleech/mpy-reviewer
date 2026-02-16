# MicroPython Review Database - Structure and Maintenance

## Overview
This database contains all review comments from the MicroPython lead maintainer across 5,542 PRs with 18,614 categorized comments.

## Database Schema

### Raw Data Tables

#### `prs`
Stores metadata about each PR reviewed by the lead maintainer.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| number | INTEGER | GitHub PR number |
| title | TEXT | PR title |
| body | TEXT | PR description |
| author | TEXT | GitHub username of PR author |
| state | TEXT | PR state (open/closed) |
| created_at | TEXT | ISO 8601 timestamp |
| merged_at | TEXT | ISO 8601 timestamp (NULL if not merged) |
| closed_at | TEXT | ISO 8601 timestamp (NULL if still open) |
| changed_files | INTEGER | Number of files changed |
| commits | INTEGER | Number of commits |
| additions | INTEGER | Lines added |
| deletions | INTEGER | Lines deleted |
| base_branch | TEXT | Target branch (usually 'master') |

#### `review_comments`
Inline code review comments on specific lines of code.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | GitHub comment ID |
| pr_number | INTEGER | Foreign key to prs.number |
| body | TEXT | Comment text (Markdown) |
| path | TEXT | File path being commented on |
| line | INTEGER | Line number in diff |
| original_line | INTEGER | Original line number (NULL if N/A) |
| diff_hunk | TEXT | Code context (diff format) |
| created_at | TEXT | ISO 8601 timestamp |
| updated_at | TEXT | ISO 8601 timestamp of last update |
| in_reply_to_id | INTEGER | ID of parent comment if this is a reply |
| commit_id | TEXT | Git commit SHA this comment refers to |

#### `issue_comments`
General comments on the PR discussion thread.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | GitHub comment ID |
| pr_number | INTEGER | Foreign key to prs.number |
| body | TEXT | Comment text (Markdown) |
| created_at | TEXT | ISO 8601 timestamp |
| updated_at | TEXT | ISO 8601 timestamp of last update |

#### `reviews`
Review summaries submitted at the PR level (can be empty).

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | GitHub review ID |
| pr_number | INTEGER | Foreign key to prs.number |
| state | TEXT | Review state (APPROVED, COMMENTED, etc.) |
| body | TEXT | Review summary text (can be NULL/empty) |
| created_at | TEXT | ISO 8601 timestamp |
| commit_id | TEXT | Git commit SHA this review refers to |

**Note:** Total of 4,584 reviews, but only 393 have non-empty body text and are categorized.

### Categorization Tables

#### `domains`
Predefined categorization domains for review comments.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Domain ID |
| name | TEXT UNIQUE | Domain name |
| description | TEXT | Domain description |

**Current domains:**
1. code_style - Formatting, naming, indentation
2. memory - RAM/ROM usage, memory leaks
3. error_handling - Exception handling, edge cases
4. api_design - Public interfaces, function signatures
5. performance - Speed optimization, efficiency
6. portability - Cross-platform compatibility
7. documentation - Docstrings, comments, docs
8. testing - Test coverage, test correctness
9. security - Security vulnerabilities
10. architecture - System design, module structure
11. build_system - Make, compilation, toolchain
12. correctness - Logic bugs, incorrect behavior

#### `comment_categories`
The main categorization table with 13 fields per comment.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| comment_id | INTEGER | ID of the comment (from review_comments/issue_comments/reviews) |
| comment_type | TEXT | Type: 'review_comment', 'issue_comment', or 'review' |
| domain_id | INTEGER | Foreign key to domains |
| theme | TEXT | Specific issue description |
| severity | TEXT | 'blocking', 'suggestion', or 'nitpick' |
| is_style_example | BOOLEAN | 1 if exemplifies the lead maintainer's style |
| categorized_at | TEXT | ISO 8601 timestamp of categorization |
| component | TEXT | 'py_core', 'extmod', 'port_specific', etc. |
| port | TEXT | Port name if port-specific (NULL otherwise) |
| subsystem | TEXT | 'bluetooth', 'networking', etc. (NULL if N/A) |
| language_context | TEXT | 'c_code', 'python_code', 'documentation', etc. |
| code_construct | TEXT | 'function', 'macro', 'class', etc. |
| concern_type | TEXT | 'correctness', 'style', 'performance', etc. |
| feedback_type | TEXT | 'question', 'suggestion', 'requirement', etc. |
| is_pattern | BOOLEAN | 1 if represents a recurring pattern |
| cpython_related | BOOLEAN | 1 if mentions CPython compatibility |
| has_code_suggestion | BOOLEAN | 1 if includes specific code examples |
| keywords | TEXT | JSON array of 2-5 technical terms |

**Unique constraint:** `(comment_id, comment_type)`

#### `sync_state`
Key-value store for tracking data collection and processing state.

| Column | Type | Description |
|--------|------|-------------|
| key | TEXT PRIMARY KEY | State key |
| value | TEXT | State value |
| updated_at | TEXT | ISO 8601 timestamp |

**Current keys:**
- `last_synced_pr` - Last PR number fetched from GitHub
- `categorize_headless_checkpoint` - Progress checkpoint for bulk categorization

## Data Collection Process

### Initial Collection (completed)

The database was populated using `scripts/fetch_reviews.py`:

1. **Fetch all merged PRs** from micropython/micropython repository
2. **Filter PRs reviewed by the lead maintainer** using GitHub API
3. **For each PR, collect:**
   - PR metadata
   - Review comments (inline on code)
   - Issue comments (general discussion)
   - Review summaries

4. **Store in SQLite** with timestamps and relationships

### Categorization Process (completed)

All 18,614 comments were categorized using `scripts/categorize_headless.py`:

1. **File-based approach:** Comments written to temp files, Claude reads them
2. **Batch processing:** 10 comments per batch with 2-second delays
3. **Retry logic:** 3 attempts per batch, 300-second timeout
4. **Schema enforcement:** JSON schema validation for all 13 fields
5. **Checkpoint system:** Resume capability for long-running operations

**Result:** 100% completion, 100% success rate (18,614 categorized, 0 failed)

## Adding New Content

### Option 1: Manual Update (Recommended for periodic updates)

Update the database with new PRs since last sync:

```bash
cd /home/anl/mpy/mpy-reviewer

# Fetch new PRs and comments
python3 scripts/fetch_reviews.py --update

# Categorize new comments
python3 scripts/categorize_headless.py

# Retry any failures
python3 scripts/retry_failed.py --batch-size 1 --delay 3
```

### Option 2: Automated Update Script

Create a cron job or scheduled task:

```bash
#!/bin/bash
# Update MicroPython review database weekly

cd /home/anl/mpy/mpy-reviewer

# Fetch new data
python3 scripts/fetch_reviews.py --update > logs/update_$(date +%Y%m%d).log 2>&1

# Categorize new comments
python3 scripts/categorize_headless.py > logs/categorize_$(date +%Y%m%d).log 2>&1

# Retry failures
python3 scripts/retry_failed.py --batch-size 1 --delay 3 >> logs/categorize_$(date +%Y%m%d).log 2>&1

# Send notification
echo "Database updated: $(python3 -c 'import sqlite3; print(sqlite3.connect(\"data/reviews.db\").execute(\"SELECT COUNT(*) FROM comment_categories\").fetchone()[0])') total categorizations"
```

### Option 3: Incremental Sync

For continuous monitoring:

```bash
# Check for new PRs every hour
python3 scripts/fetch_reviews.py --update --since "1 hour ago"

# Auto-categorize new comments as they arrive
python3 scripts/categorize_headless.py --auto-continue
```

## Key Files and Scripts

### Data Collection
- `scripts/fetch_reviews.py` - Fetches PR data from GitHub API
- `scripts/categorize_headless.py` - Bulk categorization using Claude CLI
- `scripts/retry_failed.py` - Retry failed categorizations

### Analysis Tools
- `scripts/investigate_batches.py` - Debug specific batch failures
- `scripts/test_file_approach.py` - Test categorization on large comments

### Configuration
- `CLAUDE.md` - Project documentation for Claude Code
- `REVIEW_DATABASE_GUIDE.md` - This file

### Data
- `data/reviews.db` - Main SQLite database
- `logs/` - Categorization and update logs

## Querying the Database

### Example Queries

**Count comments by domain:**
```sql
SELECT d.name, COUNT(*) as count
FROM comment_categories cc
JOIN domains d ON cc.domain_id = d.id
WHERE cc.theme != 'FAILED_CATEGORIZATION'
GROUP BY d.name
ORDER BY count DESC;
```

**Find all blocking issues:**
```sql
SELECT pr.pr_number, pr.title, cc.theme, rc.body
FROM comment_categories cc
JOIN review_comments rc ON cc.comment_id = rc.id
JOIN pull_requests pr ON rc.pr_number = pr.pr_number
WHERE cc.severity = 'blocking'
  AND cc.comment_type = 'review_comment';
```

**CPython compatibility concerns:**
```sql
SELECT pr.pr_number, cc.theme, cc.keywords
FROM comment_categories cc
JOIN review_comments rc ON cc.comment_id = rc.id
JOIN pull_requests pr ON rc.pr_number = pr.pr_number
WHERE cc.cpython_related = 1
  AND cc.comment_type = 'review_comment';
```

**Style examples by component:**
```sql
SELECT cc.component, COUNT(*) as examples
FROM comment_categories cc
WHERE cc.is_style_example = 1
GROUP BY cc.component
ORDER BY examples DESC;
```

**Port-specific reviews:**
```sql
SELECT cc.port, COUNT(*) as count
FROM comment_categories cc
WHERE cc.port IS NOT NULL
GROUP BY cc.port
ORDER BY count DESC;
```

## Maintenance Notes

### Database Integrity
- Always backup before major updates: `cp data/reviews.db data/reviews.db.backup`
- Vacuum periodically: `sqlite3 data/reviews.db "VACUUM;"`
- Check for orphaned records: See `scripts/check_integrity.py`

### Categorization Quality
- Review failed categorizations: `python3 scripts/retry_failed.py --show-only`
- Audit random samples: `python3 scripts/audit_sample.py --count 50`
- Check field completion rates: `python3 scripts/check_completeness.py`

### GitHub API Rate Limits
- GitHub API limit: 5000 requests/hour (authenticated)
- Current implementation uses ~10 requests per PR
- For large updates, consider using `--rate-limit-wait` flag

## Schema Version
- Current version: 2.0 (13-field categorization schema)
- Date: 2024-12-25
- Total records: 18,614 categorized comments

## Future Enhancements
- [ ] Add sentiment analysis field
- [ ] Track review response times
- [ ] Link to commit SHAs
- [ ] Add PR review outcomes (merged as-is, modified, rejected)
- [ ] Export to other formats (JSON, CSV, Parquet)
