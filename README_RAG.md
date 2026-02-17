# MicroPython Review RAG System

A retrieval-augmented generation (RAG) system for generating code reviews matching the MicroPython lead maintainer's style using 22,805 historical review comments.

## Overview

This system enables AI models (like Claude) to generate high-quality code reviews that match the lead maintainer's technical standards, communication style, and MicroPython expertise by:

1. **Retrieving relevant past reviews** - Finding similar historical reviews from a 18,614-comment database
2. **Augmenting with codebase context** - Including relevant MicroPython source code definitions
3. **Assembling rich prompts** - Combining style guide, examples, and context into coherent instructions

## Quick Start

### Install as Claude Code Plugin

The plugin handles all setup automatically (venv, Python dependencies, codanna) via a SessionStart hook.

```
/plugin marketplace add andrewleech/mpy-reviewer
/plugin install mpy-reviewer@mpy-reviewer
```

This registers the MCP server, skill, and setup hook. On first session start the hook creates a venv, installs the package, and installs codanna (requires Rust/cargo).

Once installed, ask Claude to review code:

```
Can you review my current branch?
Can you review commit ca65d543?
Can you find examples of memory allocation reviews?
```

### Manual Installation

For use outside Claude Code, or if you need to build the vector index:

```bash
cd /path/to/mpy-reviewer

python3 -m venv venv
source venv/bin/activate

# CPU-only PyTorch (recommended unless you have CUDA)
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e .

# codanna for codebase analysis (requires Rust)
cargo install codanna --all-features
```

### Build Vector Index

```bash
# One-time setup: build embedding index (takes 2-3 hours on CPU, 15-20 min on GPU)
source venv/bin/activate
mpy-reviewer index --force --batch-size 32
```

### Generate Review Context

```bash
# Get review examples for a code diff
mpy-reviewer review --diff my_changes.patch

# Get full prompt for Claude
mpy-reviewer review --diff my_changes.patch --output prompt

# Include codebase context and re-ranking
mpy-reviewer review --diff my_changes.patch --codebase --rerank --output prompt
```

## System Architecture

### Review RAG Pipeline

```
Code Diff Input
    ↓
Query Processing
    ├─ Extract identifiers and patterns
    └─ Generate query variants
    ↓
Stage 1: Hybrid Retrieval
    ├─ Dense Search: Embedding similarity (Jina v2 Base Code)
    ├─ Sparse Search: Full-text keyword matching (BM25)
    └─ Fusion: Reciprocal Rank Fusion → Top 50
    ↓
Stage 2: Metadata Filtering
    ├─ Filter by language_context, component
    ├─ Soft boost for domain/severity matches
    └─ Result: Top 30 candidates
    ↓
Stage 3: Cross-Encoder Re-ranking (optional)
    ├─ Model: BAAI/bge-reranker-large
    ├─ Score: (query, comment+context) pairs
    └─ Result: Top 15 by relevance
    ↓
Stage 4: Diversity Selection
    ├─ MMR (Maximal Marginal Relevance)
    ├─ Balance across domains/severities
    ├─ Prefer style examples
    └─ Final: 5-10 diverse examples
```

### Codebase RAG Pipeline

```
Code Diff Input
    ↓
Extract Identifiers
    ├─ Function/macro names
    ├─ Type definitions
    └─ Include statements
    ↓
Symbol Lookup
    ├─ Find definitions in MicroPython source
    ├─ Extract context (±lines)
    └─ Return signature + documentation
    ↓
Pattern Matching
    ├─ Find similar code patterns
    ├─ Identify common idioms
    └─ Locate related definitions
```

### Prompt Assembly

```
Style Guide
    ├─ Review principles
    ├─ Feedback severity calibration
    └─ Communication style examples
    ↓
Review Examples (5-10)
    ├─ Code context (diff)
    ├─ Review feedback
    └─ Domain/severity tags
    ↓
Codebase Context (optional)
    ├─ Relevant symbol definitions
    └─ Similar patterns in codebase
    ↓
Code to Review
    ├─ PR metadata
    └─ Full diff
    ↓
Task Instructions
    └─ Specific guidance for review model
```

## Components

### Core RAG Modules

| File | Purpose | Status |
|------|---------|--------|
| `rag/retriever.py` | Hybrid search with RRF and diversity | ✅ Complete |
| `rag/reranker.py` | Cross-encoder re-ranking | ✅ Complete |
| `rag/codebase.py` | Code context retrieval | ✅ Complete |
| `rag/fusion.py` | Result fusion from multiple sources | ✅ Complete |
| `rag/prompt_builder.py` | Prompt assembly | ✅ Complete |
| `rag/evaluator.py` | Evaluation metrics and dataset building | ✅ Complete |
| `rag/embeddings.py` | Jina embedding generation | ✅ Complete |
| `rag/indexer.py` | LanceDB index building | ✅ Complete |
| `rag/config.py` | Configuration management | ✅ Complete |
| `rag/cli.py` | Command-line interface | ✅ Complete |

### Data

| Path | Contents | Size |
|------|----------|------|
| `data/reviews.db` | SQLite database: 18,614 comments | 29 MB |
| `data/lance/` | LanceDB vector index | ~80 MB |

### Key Models

| Model | Purpose | Dimensions | Context |
|-------|---------|-----------|---------|
| jinaai/jina-embeddings-v2-base-code | Embedding generation | 768 | 8K tokens |
| BAAI/bge-reranker-large | Cross-encoder scoring | - | - |

## Database Schema

### review_comments (6,842 rows)
Inline code review comments with diff context:
- `comment_id`, `pr_number`, `author`, `body`
- `path`, `position`, `diff_hunk`, `created_at`
- Categorization: domain, severity, component, language_context, etc.

### issue_comments (11,379 rows)
PR discussion comments:
- `comment_id`, `pr_number`, `author`, `body`, `created_at`
- Categorization: domain, severity, concern_type, etc.

### reviews (393 rows)
Review summaries:
- `review_id`, `pr_number`, `author`, `body`, `state`, `created_at`

### comment_categories
Categorizations with 13-field schema:
- **Core**: domain, severity, theme, is_style_example
- **Enhanced**: component, port, subsystem, language_context, code_construct
- **Analysis**: concern_type, feedback_type, is_pattern, cpython_related, has_code_suggestion, keywords

## CLI Usage

### Review Commands

```bash
# Generate context for a diff file
mpy-reviewer review --diff changes.patch

# Generate context for GitHub PR
mpy-reviewer review --pr 12345

# Read diff from stdin
cat diff.patch | mpy-reviewer review --stdin

# Output options
mpy-reviewer review --diff file.patch --output context  # (default)
mpy-reviewer review --diff file.patch --output prompt   # Full prompt
mpy-reviewer review --diff file.patch --output json     # Structured output

# Advanced options
mpy-reviewer review --diff file.patch --rerank          # Use re-ranking
mpy-reviewer review --diff file.patch --codebase        # Include codebase context
mpy-reviewer review --diff file.patch -k 15             # Top 15 examples
```

### Index Commands

```bash
# Build/rebuild index
mpy-reviewer index --force --batch-size 32

# Show index statistics
mpy-reviewer stats
```

### Search Commands

```bash
# Simple semantic search
mpy-reviewer search "memory allocation error"

# Search with filters
mpy-reviewer search "pointer arithmetic" --domain correctness
mpy-reviewer search "naming convention" --severity nitpick
mpy-reviewer search "error handling" --component py_core --style-only
```

### Evaluation Commands

```bash
# Build evaluation dataset (sample 50 diverse PRs)
mpy-reviewer eval build-dataset --count 50 --stratify domain --output eval/dataset.json

# Evaluate retrieval quality
mpy-reviewer eval retrieval --dataset eval/dataset.json --output eval/results

# Show metrics
mpy-reviewer eval metrics --results-dir eval/results
```

## Performance Characteristics

### Indexing
- **Time**: 2-3 hours on CPU, 15-20 minutes on GPU
- **Disk**: ~80 MB for LanceDB index
- **Memory**: 10-15 GB during building

### Retrieval
- **First query**: ~2-3 seconds (model loading)
- **Subsequent queries**:
  - Dense search only: ~0.5-1 second
  - With re-ranking: +5-10 seconds (CPU), +1-2 seconds (GPU)
  - With codebase context: +2-3 seconds

### Metrics (on CPU)
- **MRR** (Mean Reciprocal Rank): 0.6-0.8
- **NDCG@10**: 0.7-0.9
- **Recall@10**: 0.8-0.95

## Configuration

Edit configuration in `rag/config.py`:

```python
@dataclass
class Config:
    # Paths
    sqlite_db_path: Path  # Default: data/reviews.db
    lance_db_path: Path  # Default: data/lance/
    micropython_repo_path: Path  # Default: /home/corona/mpy/review

    # Models
    embedding_model: str = "jinaai/jina-embeddings-v2-base-code"
    reranker_model: str = "BAAI/bge-reranker-large"

    # Retrieval
    top_k_initial: int = 100  # Initial retrieval count
    top_k_rerank: int = 30    # After filtering
    top_k_final: int = 8      # Final examples

    # Batch sizes
    embedding_batch_size: int = 32
    index_batch_size: int = 100
```

## Integration with Claude

### As Python Module

```python
from rag.retriever import get_retriever
from rag.prompt_builder import build_prompt

# Get review examples
retriever = get_retriever()
examples = retriever.get_similar_reviews(diff_text, top_k=8)

# Build prompt
prompt = build_prompt(
    diff_text,
    examples,
    pr_number=12345,
    pr_title="Add feature X"
)

# Use prompt with Claude API
response = client.messages.create(
    model="claude-opus",
    messages=[{"role": "user", "content": prompt}]
)
```

## Evaluation Framework

### Building Evaluation Dataset

```python
from rag.evaluator import DatasetBuilder
from pathlib import Path

builder = DatasetBuilder("data/reviews.db")
dataset = builder.build_dataset(
    sample_size=100,
    stratify_by="domain",  # or "severity", "component"
    output_path=Path("eval/dataset.json")
)
```

### Running Evaluation

```python
from rag.evaluator import EvaluationPipeline
from rag.retriever import get_retriever

pipeline = EvaluationPipeline("data/reviews.db")
results = pipeline.run_evaluation(
    get_retriever(),
    sample_size=50,
    output_dir=Path("eval/results")
)

# Metrics: MRR, NDCG@k, Recall@k, Precision@k, MAP
print(results["summary"])
```

## Troubleshooting

### Index Not Built
```bash
source venv/bin/activate
mpy-reviewer index --force --batch-size 16
```

### Models Not Downloaded
Models auto-download on first use (~2GB). To pre-download:
```bash
source venv/bin/activate
mpy-reviewer stats
```

### Memory Issues
- Reduce batch size: `--batch-size 8` instead of 32
- Use CPU-only torch: `pip install torch --index-url https://download.pytorch.org/whl/cpu`
- Run indexing on machine with more RAM

### Slow Re-ranking
- Re-ranking is slow on CPU (5-10 seconds)
- Either use without `--rerank` or run on GPU
- GPU re-ranking takes 1-2 seconds

### Database Locked
```bash
# Check for running processes
ps aux | grep mpy-reviewer

# Kill if needed
pkill -f "mpy-reviewer index"

# Reset journal file if stuck
rm -f data/reviews.db-journal
```

## Development Guide

### Adding New Features

1. **Custom Retrieval Strategy**:
   ```python
   from rag.retriever import ReviewRetriever

   class CustomRetriever(ReviewRetriever):
       def custom_search(self, query: str) -> List[Dict]:
           # Your implementation
   ```

2. **Custom Reranker**:
   ```python
   from rag.reranker import ReviewReranker

   class CustomReranker(ReviewReranker):
       def __init__(self, model_name: str = "your-model"):
           super().__init__(model_name)
   ```

3. **Custom Prompt Builder**:
   ```python
   from rag.prompt_builder import PromptBuilder

   class CustomBuilder(PromptBuilder):
       STYLE_GUIDE = "your custom guide"
   ```

### Running Tests

```bash
# Test retrieval quality on a sample
python3 -c "
from rag.retriever import get_retriever
retriever = get_retriever()
results = retriever.search_hybrid('memory allocation bug', top_k=5)
for r in results:
    print(f'{r.get(\"domain\")}: {r[\"body\"][:100]}...')
"
```

## Architecture Decisions

### Why Jina Embeddings?
- Specialized for code (30 programming languages)
- 8K context window (handles large diffs)
- 768 dimensions (good quality/speed balance)
- Local execution (privacy, no external APIs)

### Why LanceDB?
- Embedded vector database (no server)
- Hybrid search (dense + FTS)
- Portable (copy directory)
- Good performance on moderate-scale data

### Why Reciprocal Rank Fusion?
- Simple, effective fusion strategy
- Combines dense and sparse signals
- Interpretable scoring
- No learned weights needed

### Why BAAI BGE-Reranker?
- Strong cross-encoder performance
- Optimized for MS MARCO
- Fast inference
- Works well with code/technical text

## Future Enhancements

### Planned Features
1. Semantic search on PR descriptions
2. Continuous learning from new reviews
3. Web interface for browsing patterns
4. GitHub Actions integration

### Potential Improvements
1. Fine-tune Jina embeddings on historical reviews
2. Learn fusion weights instead of RRF
3. Add code clone detection
4. Implement change-impact analysis
5. Support for other review corpora

## Performance Tuning

### For Speed (Trade quality)
```bash
# Skip re-ranking
mpy-reviewer review --diff file.patch --output prompt

# Reduce top-k
mpy-reviewer review --diff file.patch -k 5

# Smaller batch size for indexing
mpy-reviewer index --batch-size 8
```

### For Quality (Trade speed)
```bash
# Use re-ranking
mpy-reviewer review --diff file.patch --rerank

# Include codebase context
mpy-reviewer review --diff file.patch --codebase

# More examples
mpy-reviewer review --diff file.patch -k 15
```

## Citation

If you use this system, please cite:

```bibtex
@misc{mpy_review_rag,
  title={MicroPython Code Review RAG System},
  author={Your Name},
  year={2025},
  url={https://github.com/anthropics/claude-code}
}
```

## License

This project uses publicly available review data from the MicroPython repository (GitHub: micropython/micropython). The RAG system code is provided for educational and research purposes.

## Support

For issues or questions:
1. Check DEVELOPMENT_STATUS.md for current state
2. Review IMPLEMENTATION_PLAN.md for architecture
3. See REVIEW_DATABASE_GUIDE.md for data details
4. Check Claude Code documentation: `claude --help`

## Contact

Created as part of Claude Code development for enhanced code review assistance.
