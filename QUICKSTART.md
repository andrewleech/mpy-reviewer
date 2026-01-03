# Quick Start Guide - dpgeorge Review RAG System

Get started with the dpgeorge code review assistant in 5 minutes.

## Prerequisites

- Python 3.10+
- 10GB+ disk space
- 4GB+ RAM (8GB+ recommended)

## Installation (5 minutes)

```bash
cd /home/corona/mpy/dpgeorge-review-db

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install with GPU support (if available)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
pip install -e .

# Or CPU-only (smaller, slower)
pip install -e .
```

## Build Index (2-3 hours on CPU, 15-20 min on GPU) ⏳

```bash
source venv/bin/activate
mpy-review-rag index --force --batch-size 32
```

**Check progress:**
```bash
tail -f index_build.log
# Or while running in background:
watch 'ps aux | grep mpy-review-rag | grep index'
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
mpy-review-rag review --diff sample.patch

# Get full prompt for Claude
mpy-review-rag review --diff sample.patch --output prompt
```

### Example 2: Review a GitHub PR

```bash
# Review PR by number
mpy-review-rag review --pr 12345 --output prompt
```

### Example 3: Advanced Options

```bash
# Include codebase context
mpy-review-rag review --diff sample.patch --codebase

# Use cross-encoder re-ranking (slower, more accurate)
mpy-review-rag review --diff sample.patch --rerank

# Both combined (best quality)
mpy-review-rag review --diff sample.patch --codebase --rerank --output prompt

# Get structured output
mpy-review-rag review --diff sample.patch --output json | jq '.review_examples[0]'
```

## Use with Claude Code

### As a Skill

After installing the skill (see "Claude Code Skill Setup" below), you can use natural language:

```bash
/mpy-review the current branch
/mpy-review commit ca65d543
/mpy-review my changes to py/gc.c
```

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
mpy-review-rag search "memory leak"
mpy-review-rag search "null pointer"

# Filter by domain
mpy-review-rag search "API design" --domain api_design
mpy-review-rag search "edge cases" --domain correctness

# Filter by severity
mpy-review-rag search "blocking issue" --severity blocking
mpy-review-rag search "code style" --severity nitpick

# Show only style examples
mpy-review-rag search "function naming" --style-only
```

## Common Tasks

### Find All Reviews on Memory Issues

```bash
mpy-review-rag review --diff code.patch --domain memory --top-k 15
```

### Find Blocking Issues Pattern

```bash
mpy-review-rag search "common error pattern" --severity blocking --domain correctness
```

### Get Just the Code Examples

```bash
mpy-review-rag review --diff code.patch --output json | \
  jq '.review_examples[] | {domain, severity, body}'
```

### Generate Full Review Prompt

```bash
mpy-review-rag review --diff code.patch \
  --codebase \
  --rerank \
  --output prompt > review_prompt.txt

# Then use with Claude API or paste into Claude Code
```

## Evaluate System Quality

### Build a Test Dataset

```bash
# Create evaluation dataset with 20 samples
mpy-review-rag eval build-dataset --count 20 --output eval/dataset.json

# Stratified by domain (balanced coverage)
mpy-review-rag eval build-dataset --count 50 --stratify domain
```

### Measure Retrieval Quality

```bash
# Run evaluation
mpy-review-rag eval retrieval --dataset eval/dataset.json --output eval/results

# View results
mpy-review-rag eval metrics --results-dir eval/results
```

Expected metrics (on CPU-based search):
- **MRR**: 0.6-0.8 (higher is better)
- **NDCG@10**: 0.7-0.9
- **Recall@10**: 0.8-0.95

## Troubleshooting

### "Index not found" Error

```bash
source venv/bin/activate
mpy-review-rag stats

# If index doesn't exist:
mpy-review-rag index --force
```

### Models Won't Download

```bash
# Check internet connection
ping huggingface.co

# Clear cache and try again
rm -rf ~/.cache/huggingface
mpy-review-rag stats
```

### Running Out of Memory

```bash
# Reduce batch size during indexing
mpy-review-rag index --force --batch-size 8

# Or use CPU-only (if you installed with GPU)
pip install torch --index-url https://download.pytorch.org/whl/cpu
mpy-review-rag index --force --batch-size 16
```

### Re-ranking is Slow

Re-ranking takes 5-10 seconds on CPU. Options:

```bash
# Run without re-ranking (faster)
mpy-review-rag review --diff code.patch

# Or use on GPU (1-2 seconds)
# (if GPU is available and torch CUDA is installed)
```

## Performance Tips

| Want | Command |
|------|---------|
| **Fastest** | `mpy-review-rag review --diff code.patch` |
| **Balanced** | `mpy-review-rag review --diff code.patch --codebase` |
| **Best Quality** | `mpy-review-rag review --diff code.patch --codebase --rerank` |
| **Full Prompt** | `mpy-review-rag review --diff code.patch --codebase --rerank --output prompt` |

## System Statistics

```bash
mpy-review-rag stats
```

Should show:
- Index exists: Yes
- Number of records: 18,614
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
| README_RAG.md | Full architecture and configuration |
| IMPLEMENTATION_PLAN.md | Technical design and component details |
| REVIEW_DATABASE_GUIDE.md | Database schema and data collection |
| DEVELOPMENT_STATUS.md | Current development state |

## Getting Help

```bash
# Show all commands
mpy-review-rag --help

# Show command-specific help
mpy-review-rag review --help
mpy-review-rag search --help
mpy-review-rag eval --help

# Check installation
python3 -c "import rag; print(rag.__version__)"
```

## Claude Code Skill Setup

To use this as a Claude Code skill with natural language:

### 1. Install the Skill

```bash
# Create skill directory
mkdir -p ~/.claude/skills/mpy-review

# Link the SKILL.md file
ln -s /home/anl/mpy/dpgeorge-review-db/skill/SKILL.md \
      ~/.claude/skills/mpy-review/SKILL.md
```

### 2. Verify Installation

The skill should now be available in Claude Code. Test it with:

```bash
/mpy-review stats
```

**Note:** The skill requires the virtual environment and index to be set up first (steps above).

### 3. Usage Examples (Natural Language)

```bash
# Review your current work
/mpy-review the current branch
/mpy-review my uncommitted changes

# Review specific commit
/mpy-review commit ca65d543

# Review specific files
/mpy-review my changes to py/gc.c

# Find review examples
/mpy-review find examples of memory allocation reviews
/mpy-review what has dpgeorge said about error handling

# Get statistics
/mpy-review stats
```

The agent interprets your natural language request and runs the appropriate commands automatically.

See `skill/SKILL.md` for the agent's complete instructions.

---

**Next**: Build the index with `mpy-review-rag index --force` and try the examples above!
