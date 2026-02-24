# mpy-review-rag Development Status

**Date**: 2025-12-28
**Status**: Phase 1-2 partially complete, blocked on disk space

## Files to Transfer

The entire `/home/corona/mpy/dpgeorge-review-db/` directory should be transferred. Key contents:

```
dpgeorge-review-db/
├── data/
│   └── dpgeorge_reviews.db      # 29MB - THE CORE DATA (18,614 categorized reviews)
├── scripts/
│   ├── collect.py               # Fetch PRs from GitHub API
│   ├── categorize_headless.py   # Categorize comments using Claude CLI
│   ├── retry_failed.py          # Retry failed categorizations
│   └── ...                      # Other utility scripts
├── rag/
│   ├── config.py                # Configuration
│   ├── embeddings.py            # Jina embedder
│   ├── indexer.py               # Build LanceDB index
│   ├── retriever.py             # Hybrid search
│   └── cli.py                   # CLI tool
├── IMPLEMENTATION_PLAN.md       # Full architecture and design
├── REVIEW_DATABASE_GUIDE.md     # Schema, collection, categorization, maintenance
├── DEVELOPMENT_STATUS.md        # This file
├── pyproject.toml               # Package config
└── requirements.txt             # Dependencies
```

**Total size**: ~35MB (mostly the SQLite database)

## Database Contents

The SQLite database (`data/dpgeorge_reviews.db`) contains:
- **5,542 PRs** from micropython/micropython
- **18,614 categorized review comments** by dpgeorge
  - 6,842 inline code review comments (with diff context)
  - 11,379 issue/discussion comments
  - 393 review summaries (with body text)
- **13-field categorization** for each comment (domain, severity, component, etc.)
- **12 predefined domains** (correctness, code_style, memory, etc.)

See `REVIEW_DATABASE_GUIDE.md` for:
- Complete schema documentation
- How the data was collected (GitHub API)
- How it was categorized (Claude CLI with JSON schema)
- **How to add new content** (3 options documented)

## Current State

### Completed

1. **Project Structure** - All directories and files created:
   ```
   rag/
   ├── __init__.py      # Package init
   ├── config.py        # Configuration management
   ├── embeddings.py    # Jina v2 Base Code embedder with batching
   ├── indexer.py       # SQLite → LanceDB indexing
   ├── retriever.py     # Hybrid search (dense + FTS)
   └── cli.py           # Click-based CLI
   ```

2. **Dependencies Installed**:
   - lancedb 0.26.0
   - pyarrow 22.0.0
   - torch 2.9.1+cpu (CPU-only version)
   - transformers 4.57.3
   - click, tqdm, numpy

3. **CLI Tool Installed**:
   ```bash
   mpy-review-rag --version  # Works: 0.1.0
   mpy-review-rag stats      # Works: shows index status
   ```

4. **Jina Model Downloaded**:
   - Model: `jinaai/jina-embeddings-v2-base-code`
   - Location: `~/.cache/huggingface/hub/models--jinaai--jina-embeddings-v2-base-code/`
   - Single text embedding works (~1s on CPU)

### Blocked

**Index Building** - Disk space insufficient on current machine:
- Available: ~2.8GB
- Required: ~5-10GB for torch + model + index building temp files
- Error: `OSError: [Errno 28] No space left on device`

The indexing started but failed after embedding ~31 records:
```
Indexing:   0%|          | 31/18614 [01:18<13:00:26,  2.52s/it]
```

### Not Yet Implemented

- `reranker.py` - Cross-encoder re-ranking
- `codebase.py` - Codanna integration
- `fusion.py` - RRF fusion
- `prompt_builder.py` - Context assembly
- `evaluator.py` - Metrics
- Evaluation dataset construction
- Skill integration

## Data Sources

### SQLite Database
- **Path**: `data/dpgeorge_reviews.db`
- **Size**: 29 MB
- **Contents**:
  - 5,542 PRs
  - 6,842 review_comments (inline code reviews)
  - 11,379 issue_comments (discussion comments)
  - 393 reviews (with body text)
  - 18,614 total categorized comments
  - 12 domains, full metadata (severity, component, etc.)

### Database Schema
See `REVIEW_DATABASE_GUIDE.md` for complete schema documentation.

## Key Technical Decisions

1. **Embedding Model**: Jina v2 Base Code
   - 8K token context (handles large diffs)
   - 768 dimensions
   - 30 programming languages
   - ~650MB VRAM (runs on CPU)

2. **Vector Store**: LanceDB
   - Portable (copy directory or Git LFS)
   - No external services
   - Hybrid search (dense + FTS)
   - ~40-80 MB expected index size

3. **Search Strategy**: Multi-stage hybrid
   - Stage 1: Dense + FTS retrieval (RRF fusion)
   - Stage 2: Metadata filtering
   - Stage 3: Cross-encoder re-ranking (not yet implemented)
   - Stage 4: Diversity selection (MMR)

## To Continue Development

### Prerequisites on New Machine

```bash
# Minimum disk space: 10GB free recommended
# Python 3.10+

cd /path/to/dpgeorge-review-db

# Install dependencies
pip install -e .

# Or for CPU-only torch (smaller):
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e .
```

### Build the Index

```bash
# This will download the Jina model (~1.3GB) and embed all 18,614 comments
mpy-review-rag index --force --batch-size 32

# Expected time: ~2-3 hours on CPU, ~15-20 min on GPU
# Expected output size: 40-80 MB in data/lance/
```

### Test Search

```bash
# After indexing completes:
mpy-review-rag search "memory allocation" -k 5
mpy-review-rag search "return type" --domain correctness
```

### Next Implementation Steps

1. **Complete indexing** (requires more disk space)
2. **Test search quality** - verify retrieval works
3. **Implement reranker.py** - cross-encoder for better ranking
4. **Implement codebase.py** - Codanna integration
5. **Build evaluation dataset** - sample 100 PRs
6. **Tune parameters** based on metrics
7. **Create skill** at `~/.claude/skills/dpgeorge-review.md`

## Files Reference

| File | Purpose | Status |
|------|---------|--------|
| `IMPLEMENTATION_PLAN.md` | Full architecture and design | Complete |
| `REVIEW_DATABASE_GUIDE.md` | Schema, collection, categorization, maintenance | Complete |
| `rag/config.py` | Configuration management | Complete |
| `rag/embeddings.py` | Jina embedding generation | Complete |
| `rag/indexer.py` | Build LanceDB index | Complete, untested |
| `rag/retriever.py` | Hybrid search | Complete, untested |
| `rag/cli.py` | CLI interface | Partial |
| `pyproject.toml` | Package config | Complete |
| `requirements.txt` | Dependencies | Complete |

## Environment Notes

- Developed on Ubuntu Linux
- torch CPU-only version used (CUDA version too large)
- Model caches to `~/.cache/huggingface/`
- LanceDB stores data in `data/lance/`

## Troubleshooting

### Disk Space Issues
The main blocker. Solutions:
1. Move to machine with more space
2. Clean up pip cache: `pip cache purge`
3. Clean huggingface cache: `rm -rf ~/.cache/huggingface/hub/`
4. Use smaller batch size: `--batch-size 8`

### Slow Embedding on CPU
Expected ~2-3s per batch of 8-32 texts. Total time ~2-3 hours for 18K records.
GPU dramatically faster (~15-20 min).

### LanceDB FTS Index
If FTS index creation fails, the dense search still works. FTS can be added later.
