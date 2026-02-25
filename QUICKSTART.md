# Quick Start Guide - MicroPython Review RAG System

Get started with the MicroPython code review assistant in 5 minutes.

## Install as Claude Code Plugin

The plugin handles Python dependencies (via uv) and codanna installation automatically.

```
/plugin marketplace add andrewleech/mpy-reviewer
/plugin install mpy-reviewer@mpy-reviewer
```

This registers the MCP server, skill, and a SessionStart hook that bootstraps the environment on first use (requires Python 3.10+ and Rust/cargo for codanna).

## Manual Installation

For use outside Claude Code or to build the vector index manually:

```bash
cd /path/to/mpy-reviewer

# Install all Python dependencies (creates .venv automatically)
uv sync

# codanna for codebase analysis (requires Rust)
cargo install codanna --all-features
```

## Build Index (2-3 hours on CPU, 15-20 min on GPU) ⏳

```bash
uv run python scripts/build_index_resume.py
```

**Check progress:**
```bash
tail -f index_build.log
# Or while running in background:
watch 'ps aux | grep build_index | grep -v grep'
```

## Try It Out (after index is built)

### Example 1: Review a Local Change

```bash
# Create a sample diff
cat > sample.patch << 'EOF'
--- a/py/gc.c
+++ b/py/gc.c
@@ -100,6 +100,10 @@ void gc_collect(void) {
     int i;
     for (i = 0; i < num_blocks; i++) {
+        // Allocate memory without checking
+        void *ptr = malloc(size);
+        if (!ptr) continue;
+
         mark_block(blocks[i]);
     }
 }
EOF

# Get review context
uv run mpy-reviewer review --diff sample.patch

# Get full prompt for Claude
uv run mpy-reviewer review --diff sample.patch --output prompt
```

### Example 2: Review a GitHub PR

```bash
# Review PR by number
uv run mpy-reviewer review --pr 12345 --output prompt
```

### Example 3: Advanced Options

```bash
# Include codebase context
uv run mpy-reviewer review --diff sample.patch --codebase

# Use cross-encoder re-ranking (slower, more accurate)
uv run mpy-reviewer review --diff sample.patch --rerank

# Both combined (best quality)
uv run mpy-reviewer review --diff sample.patch --codebase --rerank --output prompt

# Get structured output
uv run mpy-reviewer review --diff sample.patch --output json | jq '.review_examples[0]'
```

## Use with Claude Code

### As a Skill

After installing the skill (see "Claude Code Skill Setup" below), ask Claude to review your code:

```
Can you review my current branch?
Can you /mpy-review the current branch?

Can you review commit ca65d543?

Can you review my changes to py/gc.c?
```

**Note:** You ask Claude to use the skill - you don't invoke `/mpy-review` directly.

### As Python Module

```python
from rag.retriever import get_retriever
from rag.prompt_builder import build_prompt

# Get similar reviews
retriever = get_retriever()
examples = retriever.get_similar_reviews(diff_text, top_k=8)

# Build prompt for Claude
prompt = build_prompt(diff_text, examples)
print(prompt)
```

## Search for Specific Reviews

```bash
# Search by keyword
uv run mpy-reviewer search "memory leak"
uv run mpy-reviewer search "null pointer"

# Filter by domain
uv run mpy-reviewer search "API design" --domain api_design
uv run mpy-reviewer search "edge cases" --domain correctness

# Filter by severity
uv run mpy-reviewer search "blocking issue" --severity blocking
uv run mpy-reviewer search "code style" --severity nitpick

# Show only style examples
uv run mpy-reviewer search "function naming" --style-only
```

## Common Tasks

### Find All Reviews on Memory Issues

```bash
uv run mpy-reviewer review --diff code.patch --domain memory --top-k 15
```

### Find Blocking Issues Pattern

```bash
uv run mpy-reviewer search "common error pattern" --severity blocking --domain correctness
```

### Get Just the Code Examples

```bash
uv run mpy-reviewer review --diff code.patch --output json | \
  jq '.review_examples[] | {domain, severity, body}'
```

### Generate Full Review Prompt

```bash
uv run mpy-reviewer review --diff code.patch \
  --codebase \
  --rerank \
  --output prompt > review_prompt.txt

# Then use with Claude API or paste into Claude Code
```

## Evaluate System Quality

### Build a Test Dataset

```bash
# Create evaluation dataset with 20 samples
uv run mpy-reviewer eval build-dataset --count 20 --output eval/dataset.json

# Stratified by domain (balanced coverage)
uv run mpy-reviewer eval build-dataset --count 50 --stratify domain
```

### Measure Retrieval Quality

```bash
# Run evaluation
uv run mpy-reviewer eval retrieval --dataset eval/dataset.json --output eval/results

# View results
uv run mpy-reviewer eval metrics --results-dir eval/results
```

Expected metrics (on CPU-based search):
- **MRR**: 0.6-0.8 (higher is better)
- **NDCG@10**: 0.7-0.9
- **Recall@10**: 0.8-0.95

## Troubleshooting

### "Index not found" Error

```bash
uv run mpy-reviewer stats

# If index doesn't exist:
uv run python scripts/build_index_resume.py
```

### Models Won't Download

```bash
# Check internet connection
ping huggingface.co

# Clear cache and try again
rm -rf ~/.cache/huggingface
uv run mpy-reviewer stats
```

### Running Out of Memory

The index builder uses batch_size=4 with periodic GC by default. If still out of memory, edit the constants in `scripts/build_index_resume.py`.

### Re-ranking is Slow

Re-ranking takes 5-10 seconds on CPU. Options:

```bash
# Run without re-ranking (faster)
uv run mpy-reviewer review --diff code.patch

# Or use on GPU (1-2 seconds)
# (if GPU is available and torch CUDA is installed)
```

## Performance Tips

| Want | Command |
|------|---------|
| **Fastest** | `uv run mpy-reviewer review --diff code.patch` |
| **Balanced** | `uv run mpy-reviewer review --diff code.patch --codebase` |
| **Best Quality** | `uv run mpy-reviewer review --diff code.patch --codebase --rerank` |
| **Full Prompt** | `uv run mpy-reviewer review --diff code.patch --codebase --rerank --output prompt` |

## System Statistics

```bash
uv run mpy-reviewer stats
```

Should show:
- Index exists: Yes
- Number of records: 19,465
- Index size: ~80 MB

## Next Steps

1. **Review Real Code**: Try on actual MicroPython PRs
2. **Integrate with Claude**: Use the prompt output with Claude API
3. **Evaluate**: Build evaluation dataset and measure quality
4. **Customize**: Modify prompts or add filters
5. **Deploy**: Set up as ongoing review assistance

## Documentation

For more details, see:

| Document | Contents |
|----------|----------|
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development setup, repository structure, schema reference |
| [docs/DATA_PIPELINE.md](docs/DATA_PIPELINE.md) | Data collection, categorization, and indexing pipeline |
| [CLAUDE.md](CLAUDE.md) | Full project context for AI agents |

## Getting Help

```bash
# Show all commands
uv run mpy-reviewer --help

# Show command-specific help
uv run mpy-reviewer review --help
uv run mpy-reviewer search --help
uv run mpy-reviewer eval --help

# Check installation
uv run python -c "import rag; print('OK')"
```

---

**Next**: Build the index with `uv run python scripts/build_index_resume.py` and try the examples above!
