# Quick Start Guide - MicroPython Review RAG System

Get started with the MicroPython code review assistant in 5 minutes.

## Prerequisites

- Python 3.10+
- 10GB+ disk space
- 4GB+ RAM (8GB+ recommended)

## Installation (5 minutes)

```bash
cd /home/anl/mpy/mpy-reviewer

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
mpy-reviewer index --force --batch-size 32
```

**Check progress:**
```bash
tail -f index_build.log
# Or while running in background:
watch 'ps aux | grep mpy-reviewer | grep index'
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
mpy-reviewer review --diff sample.patch

# Get full prompt for Claude
mpy-reviewer review --diff sample.patch --output prompt
```

### Example 2: Review a GitHub PR

```bash
# Review PR by number
mpy-reviewer review --pr 12345 --output prompt
```

### Example 3: Advanced Options

```bash
# Include codebase context
mpy-reviewer review --diff sample.patch --codebase

# Use cross-encoder re-ranking (slower, more accurate)
mpy-reviewer review --diff sample.patch --rerank

# Both combined (best quality)
mpy-reviewer review --diff sample.patch --codebase --rerank --output prompt

# Get structured output
mpy-reviewer review --diff sample.patch --output json | jq '.review_examples[0]'
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
mpy-reviewer search "memory leak"
mpy-reviewer search "null pointer"

# Filter by domain
mpy-reviewer search "API design" --domain api_design
mpy-reviewer search "edge cases" --domain correctness

# Filter by severity
mpy-reviewer search "blocking issue" --severity blocking
mpy-reviewer search "code style" --severity nitpick

# Show only style examples
mpy-reviewer search "function naming" --style-only
```

## Common Tasks

### Find All Reviews on Memory Issues

```bash
mpy-reviewer review --diff code.patch --domain memory --top-k 15
```

### Find Blocking Issues Pattern

```bash
mpy-reviewer search "common error pattern" --severity blocking --domain correctness
```

### Get Just the Code Examples

```bash
mpy-reviewer review --diff code.patch --output json | \
  jq '.review_examples[] | {domain, severity, body}'
```

### Generate Full Review Prompt

```bash
mpy-reviewer review --diff code.patch \
  --codebase \
  --rerank \
  --output prompt > review_prompt.txt

# Then use with Claude API or paste into Claude Code
```

## Evaluate System Quality

### Build a Test Dataset

```bash
# Create evaluation dataset with 20 samples
mpy-reviewer eval build-dataset --count 20 --output eval/dataset.json

# Stratified by domain (balanced coverage)
mpy-reviewer eval build-dataset --count 50 --stratify domain
```

### Measure Retrieval Quality

```bash
# Run evaluation
mpy-reviewer eval retrieval --dataset eval/dataset.json --output eval/results

# View results
mpy-reviewer eval metrics --results-dir eval/results
```

Expected metrics (on CPU-based search):
- **MRR**: 0.6-0.8 (higher is better)
- **NDCG@10**: 0.7-0.9
- **Recall@10**: 0.8-0.95

## Troubleshooting

### "Index not found" Error

```bash
source venv/bin/activate
mpy-reviewer stats

# If index doesn't exist:
mpy-reviewer index --force
```

### Models Won't Download

```bash
# Check internet connection
ping huggingface.co

# Clear cache and try again
rm -rf ~/.cache/huggingface
mpy-reviewer stats
```

### Running Out of Memory

```bash
# Reduce batch size during indexing
mpy-reviewer index --force --batch-size 8

# Or use CPU-only (if you installed with GPU)
pip install torch --index-url https://download.pytorch.org/whl/cpu
mpy-reviewer index --force --batch-size 16
```

### Re-ranking is Slow

Re-ranking takes 5-10 seconds on CPU. Options:

```bash
# Run without re-ranking (faster)
mpy-reviewer review --diff code.patch

# Or use on GPU (1-2 seconds)
# (if GPU is available and torch CUDA is installed)
```

## Performance Tips

| Want | Command |
|------|---------|
| **Fastest** | `mpy-reviewer review --diff code.patch` |
| **Balanced** | `mpy-reviewer review --diff code.patch --codebase` |
| **Best Quality** | `mpy-reviewer review --diff code.patch --codebase --rerank` |
| **Full Prompt** | `mpy-reviewer review --diff code.patch --codebase --rerank --output prompt` |

## System Statistics

```bash
mpy-reviewer stats
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
mpy-reviewer --help

# Show command-specific help
mpy-reviewer review --help
mpy-reviewer search --help
mpy-reviewer eval --help

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
ln -s /home/anl/mpy/mpy-reviewer/skill/SKILL.md \
      ~/.claude/skills/mpy-review/SKILL.md
```

### 2. Verify Installation

The skill should now be available in Claude Code. Test it by asking Claude:

```
Can you /mpy-review stats
```

This should show the index status (18,614 records).

**Note:** The skill requires the virtual environment and index to be set up first (steps above).

### 3. Usage Examples

Ask Claude to review your code using natural language:

```
# Review your current work
Can you review my current branch?
Can you /mpy-review my uncommitted changes?

# Review specific commit
Can you review commit ca65d543?

# Review specific files
Can you review my changes to py/gc.c?

# Find review examples
Can you find examples of memory allocation reviews?
What has the lead maintainer said about error handling?
```

Claude interprets your request, runs the appropriate git/search commands, and provides review feedback.

See `skill/SKILL.md` for the agent's complete instructions.

---

**Next**: Build the index with `mpy-reviewer index --force` and try the examples above!
