# Git Commit Strategy for dpgeorge-review-db

## Overview

This document outlines the logical sequence of commits to establish project history that reflects the development workflow: architecture → collection → raw data → processing → final data.

## Repository Statistics

- **Total committable source**: ~500KB (code + docs)
- **Total to ignore**: ~2.1GB (venv, logs, build artifacts)
- **Total requiring LFS**: ~1.4GB (database + vector index)

## Prerequisites

```bash
cd /home/anl/mpy/dpgeorge-review-db

# Ensure git is initialized
git init

# Install Git LFS if not already available
git lfs install
```

---

## Phase 0: Repository Setup

### Step 0.1: Update .gitignore

**Files to add/update:**
- `.gitignore`

**Current .gitignore status:** Exists (202 bytes), needs enhancement.

**Add these patterns:**

```gitignore
# Virtual environments
venv/
env/
.venv/
ENV/

# Package distribution and build
mpy_review_rag.egg-info/
build/
dist/
*.egg-info/

# Logs and temporary files
*.log
logs/

# Generated output
output/

# Unused directories
eval/
tests/

# Python cache
__pycache__/
*.py[cod]
*$py.class
.pytest_cache/

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db
```

**Command:**
```bash
# Edit .gitignore to add above patterns
git add .gitignore
git commit -m "build: Configure .gitignore for Python project.

Exclude virtual environments, build artifacts, logs, and generated files.
Prevents committing temporary operational files and auto-generated content.

Signed-off-by: Andrew Leech <andrew@alelec.net>"
```

### Step 0.2: Configure Git LFS

**Purpose:** Track large binary data files (28M SQLite DB, 1.4G vector index).

**Commands:**
```bash
# Track database and vector index files
git lfs track "data/dpgeorge_reviews.db"
git lfs track "data/lance/**/*.lance"

# This creates .gitattributes
git add .gitattributes
git commit -m "build: Add Git LFS tracking for large data files.

Track SQLite database (28MB) and LanceDB vector index (1.4GB) via LFS.
Enables versioning of large binary artifacts without bloating repository.

Signed-off-by: Andrew Leech <andrew@alelec.net>"
```

---

## Phase 1: Project Groundwork and Architecture

**Purpose:** Establish project foundation - database schema, package configuration, core documentation.

**Rationale:** These files define the structure that everything else builds upon.

### Commit 1.1: Database Schema

**Files:**
- `schema.sql` (3.8K)

**Command:**
```bash
git add schema.sql
git commit -m "schema: Add SQLite database schema definition.

Define tables for PRs, review comments, issue comments, reviews, and
categorization metadata. Supports 13-field enhanced categorization schema
with domain taxonomy, component classification, and technical context.

Tables:
- prs: PR metadata
- review_comments: Inline code comments with diff hunks
- issue_comments: PR discussion comments
- reviews: Overall review verdicts
- comment_categories: 13-field categorizations
- domains: Domain lookup table
- sync_state: Checkpoint tracking for resumable operations

Signed-off-by: Andrew Leech <andrew@alelec.net>"
```

### Commit 1.2: Package Configuration

**Files:**
- `pyproject.toml` (779 bytes)
- `requirements.txt` (477 bytes)

**Command:**
```bash
git add pyproject.toml requirements.txt
git commit -m "build: Add Python package configuration.

Define mpy-review-rag package with dependencies for vector search (LanceDB,
transformers), CLI (click), and data processing (pandas, tqdm).

Entry point: mpy-review-rag CLI tool for semantic search and review context.

Dependencies:
- lancedb>=0.4.0 (vector database)
- transformers>=4.36.0 (Jina embeddings)
- torch>=2.0.0 (CPU or CUDA)
- click>=8.0.0 (CLI framework)

Signed-off-by: Andrew Leech <andrew@alelec.net>"
```

### Commit 1.3: Core Configuration Module

**Files:**
- `rag/__init__.py`
- `rag/config.py`

**Command:**
```bash
git add rag/__init__.py rag/config.py
git commit -m "rag: Add configuration management module.

Centralize paths for SQLite database, LanceDB vector index, and model settings.
Supports environment variable overrides for deployment flexibility.

Defaults:
- SQLite: data/dpgeorge_reviews.db
- LanceDB: data/lance/
- Model: jinaai/jina-embeddings-v2-base-code (768-dim)

Signed-off-by: Andrew Leech <andrew@alelec.net>"
```

### Commit 1.4: Core Documentation

**Files:**
- `README.md` (15K)
- `CLAUDE.md` (16K)

**Command:**
```bash
git add README.md CLAUDE.md
git commit -m "docs: Add project README and AI agent instructions.

README covers:
- Project goals (AI-assisted PR review with dpgeorge's style)
- Data collection results (22,805 comments from 5,542 PRs)
- Categorization schema (13 fields)
- Usage examples (CLI and Python API)
- Repository structure

CLAUDE.md provides:
- Development workflow for extending the database
- CLI usage patterns
- Python API reference
- Troubleshooting guide
- Current index statistics

Signed-off-by: Andrew Leech <andrew@alelec.net>"
```

---

## Phase 2: Data Collection Infrastructure

**Purpose:** Scripts and tools for collecting review data from GitHub.

### Commit 2.1: GitHub Collection Script

**Files:**
- `scripts/collect.py`

**Command:**
```bash
git add scripts/collect.py
git commit -m "scripts: Add GitHub review collection script.

Collect dpgeorge's review feedback from micropython/micropython via GitHub API.
Handles pagination limits (1000 results) using year-based query splitting.
Supports resumable operation via sync_state checkpoints.

Collects:
- Review comments (inline code feedback with diff context)
- Issue comments (PR discussion)
- Review verdicts (APPROVED/CHANGES_REQUESTED)
- PR metadata (title, files changed, labels)

Rate limiting: ~674 PRs/hour (GitHub API: 5000 req/hr)
Storage: SQLite database (schema.sql)

Usage: python scripts/collect.py

Signed-off-by: Andrew Leech <andrew@alelec.net>"
```

---

## Phase 3: Raw Collected Data

**Purpose:** Commit the source data collected from GitHub (via Git LFS).

### Commit 3.1: SQLite Database with Review Comments

**Files:**
- `data/dpgeorge_reviews.db` (28M, via LFS)

**Command:**
```bash
git add data/dpgeorge_reviews.db
git commit -m "data: Add collected review comments database.

SQLite database containing 22,805 comments from 5,542 PRs (2013-2025):
- 6,842 review comments (inline code feedback)
- 11,379 issue comments (PR discussion)
- 4,584 review verdicts

Collected via scripts/collect.py from micropython/micropython repository.
Tracked via Git LFS (28MB).

Collection timeframe: Full project history (2013-2025)
Success rate: 99.995% (1 HTTP 504 error in ~22,168 API calls)

Signed-off-by: Andrew Leech <andrew@alelec.net>"
```

---

## Phase 4: Processing and Indexing Infrastructure

**Purpose:** Tools and code for categorizing comments and building the vector index.

### Commit 4.1: Categorization Infrastructure

**Files:**
- `scripts/categorize_headless.py`

**Command:**
```bash
git add scripts/categorize_headless.py
git commit -m "scripts: Add batch categorization script.

Categorize review comments using Claude CLI with 13-field schema:
- Core: domain, theme, severity, is_style_example
- Component: component, port, subsystem
- Technical: language_context, code_construct, concern_type
- Metadata: feedback_type, is_pattern, cpython_related, has_code_suggestion, keywords

Uses claude -p (headless mode) with JSON schema enforcement.
Processes 20 comments per call for efficiency.
Supports checkpoint/resume via sync_state table.

Cost: ~\$2-4 for full dataset (18,614 comments) using Haiku.
Time: ~40-100 minutes for full dataset.

Usage: python scripts/categorize_headless.py

Signed-off-by: Andrew Leech <andrew@alelec.net>"
```

### Commit 4.2: Embeddings Module

**Files:**
- `rag/embeddings.py`

**Command:**
```bash
git add rag/embeddings.py
git commit -m "rag: Add Jina embeddings wrapper.

Wrapper for jinaai/jina-embeddings-v2-base-code model (768 dimensions).
Supports CPU-only mode for systems without CUDA.

Features:
- Mean pooling with L2 normalization
- Batch processing for efficiency
- Device auto-detection (cuda/cpu)

Model: jinaai/jina-embeddings-v2-base-code
Dimensions: 768
Performance: 2-13 items/sec on CPU (WSL2)

Signed-off-by: Andrew Leech <andrew@alelec.net>"
```

### Commit 4.3: Indexer Module

**Files:**
- `rag/indexer.py`
- `scripts/build_index_resume.py`

**Command:**
```bash
git add rag/indexer.py scripts/build_index_resume.py
git commit -m "rag: Add LanceDB index builder with resume capability.

Build vector index from categorized SQLite comments to LanceDB.

Features:
- Resume from interruptions (checks existing records, skips already indexed)
- Memory management (small batches, periodic GC)
- Incremental writes (add records as they're processed)
- Full-text search index on body field

indexer.py: Core indexing logic and SQLite iterators
build_index_resume.py: Standalone resume-capable builder script

Performance (CPU-only, WSL2, 45GB RAM):
- Time: ~5 hours for 18,614 records
- Memory: ~6GB peak with batch_size=4
- Speed: 2-13 items/sec (depends on text length)

Usage: python scripts/build_index_resume.py

Signed-off-by: Andrew Leech <andrew@alelec.net>"
```

### Commit 4.4: Retrieval System

**Files:**
- `rag/retriever.py`
- `rag/fusion.py`
- `rag/reranker.py`

**Command:**
```bash
git add rag/retriever.py rag/fusion.py rag/reranker.py
git commit -m "rag: Add hybrid retrieval system.

Hybrid search combining dense vector search and full-text search:

retriever.py:
- Dense search via Jina embeddings (cosine similarity)
- Full-text search via LanceDB FTS
- Reciprocal Rank Fusion (RRF) for result merging
- MMR diversity selection (balance domain/severity)
- Metadata filtering (domain, component, port, severity, etc.)

fusion.py:
- RRF implementation (k=60)
- Score normalization utilities

reranker.py:
- Optional cross-encoder re-ranking (BGE-reranker-large)
- Improves precision for top results

Pipeline: Dense + FTS → RRF Fusion → MMR Diversity → Optional Re-ranking

Signed-off-by: Andrew Leech <andrew@alelec.net>"
```

### Commit 4.5: CLI and Supporting Modules

**Files:**
- `rag/cli.py`
- `rag/prompt_builder.py`
- `rag/codebase.py`
- `rag/evaluator.py`

**Command:**
```bash
git add rag/cli.py rag/prompt_builder.py rag/codebase.py rag/evaluator.py
git commit -m "rag: Add CLI and supporting utilities.

cli.py:
- mpy-review-rag command-line interface
- Commands: stats, search, review, eval
- JSON output support for programmatic use

prompt_builder.py:
- Generate review context from PR diffs
- Extract files changed, subsystems affected
- Construct prompts for AI-assisted review

codebase.py:
- MicroPython codebase structure context
- Component and subsystem taxonomy
- File path → component mapping

evaluator.py:
- Retrieval quality metrics
- Domain/component/severity distributions
- Hit rate analysis

Entry point: mpy-review-rag (defined in pyproject.toml)

Signed-off-by: Andrew Leech <andrew@alelec.net>"
```

### Commit 4.6: Schema Migration Script

**Files:**
- `scripts/migrate_schema.py`

**Command:**
```bash
git add scripts/migrate_schema.py
git commit -m "scripts: Add database schema migration utility.

Support schema evolution for comment_categories table.
Handles migration from 4-field to 13-field enhanced schema.

Migrations:
- Add new columns with appropriate types and defaults
- Preserve existing categorization data
- Update domain_id references

Usage: python scripts/migrate_schema.py

Signed-off-by: Andrew Leech <andrew@alelec.net>"
```

### Commit 4.7: Additional Documentation

**Files:**
- `docs/`
- `DEVELOPMENT_STATUS.md`
- `IMPLEMENTATION_PLAN.md`
- `QUICKSTART.md`
- `README_RAG.md`
- `REVIEW_DATABASE_GUIDE.md`
- `SESSION_SUMMARY.md`
- `STATUS.txt`

**Command:**
```bash
git add docs/ DEVELOPMENT_STATUS.md IMPLEMENTATION_PLAN.md QUICKSTART.md README_RAG.md REVIEW_DATABASE_GUIDE.md SESSION_SUMMARY.md STATUS.txt
git commit -m "docs: Add development documentation and guides.

Development documentation:
- DEVELOPMENT_STATUS.md: Project milestones and completion status
- IMPLEMENTATION_PLAN.md: Technical design and architecture decisions
- SESSION_SUMMARY.md: Progress snapshots

User guides:
- QUICKSTART.md: Quick start instructions
- README_RAG.md: RAG system detailed documentation
- REVIEW_DATABASE_GUIDE.md: Database schema and usage guide
- STATUS.txt: Current project status

Technical documentation (docs/):
- Categorization schema design
- Search pipeline architecture
- Evaluation methodology
- Performance benchmarks

Signed-off-by: Andrew Leech <andrew@alelec.net>"
```

---

## Phase 5: Final Processed Data

**Purpose:** Commit the vector index (processed data ready for semantic search).

### Commit 5.1: Vector Index

**Files:**
- `data/lance/` (1.4GB, via LFS)

**Command:**
```bash
git add data/lance/
git commit -m "data: Add LanceDB vector index.

Vector index of 18,614 categorized review comments.

Index characteristics:
- Embedding model: jinaai/jina-embeddings-v2-base-code
- Dimensions: 768
- Records: 18,614 (filtered from 22,805 raw comments)
- Size: 1.4GB
- Full-text search index: Enabled on body field

Generated via scripts/build_index_resume.py from SQLite database.
Tracked via Git LFS.

Build time: ~5 hours (CPU-only, WSL2)
Memory usage: ~6GB peak

Distribution:
- Domain: correctness (21.2%), code_style (17.3%), api_design (12.7%)
- Component: port_specific (32.4%), py_core (31.9%), extmod (9.8%)
- Severity: suggestion (57.9%), nitpick (28.5%), blocking (13.6%)

Signed-off-by: Andrew Leech <andrew@alelec.net>"
```

---

## Execution Plan Summary

### Phase 0: Setup (2 commits)
1. Update .gitignore
2. Configure Git LFS (.gitattributes)

### Phase 1: Groundwork (4 commits)
1. Database schema
2. Package configuration
3. Core config module
4. Core documentation

### Phase 2: Collection (1 commit)
1. GitHub collection script

### Phase 3: Raw Data (1 commit)
1. SQLite database (via LFS)

### Phase 4: Processing (7 commits)
1. Categorization script
2. Embeddings module
3. Indexer with resume script
4. Retrieval system (hybrid search)
5. CLI and utilities
6. Schema migration script
7. Additional documentation

### Phase 5: Final Data (1 commit)
1. Vector index (via LFS)

**Total: 16 commits**

---

## Verification Steps

After each phase:

```bash
# Check what's staged
git status

# Review commit before pushing
git log --oneline --graph

# Verify LFS tracking
git lfs ls-files

# Check repository size (should be small without LFS objects)
du -sh .git/

# Verify ignored files aren't tracked
git status --ignored
```

Final verification:

```bash
# Total commits
git log --oneline | wc -l  # Should be 16

# LFS objects
git lfs ls-files  # Should show dpgeorge_reviews.db and lance/**/*.lance

# Repository size (excluding LFS)
git count-objects -vH  # Should be ~500KB-1MB for code/docs only
```

---

## Post-Commit: Remote Setup

Once local commits are complete:

```bash
# Add remote (replace with your GitHub URL)
git remote add origin git@github.com:username/dpgeorge-review-db.git

# Push with LFS
git lfs push --all origin main
git push -u origin main
```

---

## Notes

1. **Git LFS Required:** Ensure Git LFS is installed and initialized before Phase 0.2.

2. **Commit Messages:** All follow conventional commit format with component prefix (build/schema/scripts/rag/data/docs).

3. **Signed-off-by:** Replace "Andrew Leech <andrew@alelec.net>" with your actual name/email or use `git commit -s`.

4. **LFS Bandwidth:** Initial push with 1.4GB vector index will consume LFS bandwidth. Ensure your hosting provider supports this size.

5. **Reproducibility:** This commit history reflects the logical development flow: architecture → collection → raw data → processing → final data. Each phase is independently verifiable and builds on previous work.

6. **Documentation First:** Core documentation (README, CLAUDE.md) committed early so future commits can reference it.

7. **Optional Commits:** Additional utility scripts in `scripts/` (analyze_style.py, query.py, etc.) can be committed as a bonus Phase 4.8 if desired.
