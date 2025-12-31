---
name: dpgeorge-review
description: Semantic search and retrieval system for dpgeorge's MicroPython code review patterns. Use to find relevant past reviews, generate review context for PRs/diffs, or search for specific feedback patterns. Provides AI-assisted code review matching dpgeorge's technical standards and communication style.
---

# dpgeorge Review RAG Skill

## Description

A retrieval-augmented generation (RAG) system providing access to 18,614 categorized code review comments from Damien George (dpgeorge) on the MicroPython project. Use this skill to:

- Find relevant past reviews for new code changes
- Generate review context with examples in dpgeorge's style
- Search for specific feedback patterns (memory, API design, portability, etc.)
- Understand MicroPython review standards and conventions

## Prerequisites

The dpgeorge-review system must be installed and indexed before using this skill.

### One-Time Setup

1. **Install the package:**
   ```bash
   cd /home/anl/mpy/dpgeorge-review-db
   python3 -m venv venv
   source venv/bin/activate
   pip install -e .
   ```

2. **Build the vector index** (takes ~5 hours on CPU):
   ```bash
   source venv/bin/activate
   python scripts/build_index_resume.py
   ```

3. **Verify installation:**
   ```bash
   source venv/bin/activate
   mpy-review-rag stats
   ```

   Should show:
   - Index exists: True
   - Number of records: 18,614

### Installing the Skill

1. **Create skill directory:**
   ```bash
   mkdir -p ~/.claude/skills/dpgeorge-review
   ```

2. **Link or copy the SKILL.md:**
   ```bash
   ln -s /home/anl/mpy/dpgeorge-review-db/skill/SKILL.md \
         ~/.claude/skills/dpgeorge-review/SKILL.md
   ```

3. **Verify skill is available:**
   ```bash
   # In Claude Code, the skill should be available as /dpgeorge-review
   ```

## Usage

### Basic Review Context Generation

Generate review context for a code diff:

```bash
# From a diff file
/dpgeorge-review review --diff path/to/changes.patch

# From a GitHub PR
/dpgeorge-review review --pr 12345

# From stdin
git diff | /dpgeorge-review review --stdin
```

### Advanced Review Options

```bash
# Include codebase context (definitions, similar patterns)
/dpgeorge-review review --diff changes.patch --codebase

# Use cross-encoder re-ranking for better relevance (slower)
/dpgeorge-review review --diff changes.patch --rerank

# Get more examples
/dpgeorge-review review --diff changes.patch -k 15

# Full prompt for AI review (best quality, slowest)
/dpgeorge-review review --diff changes.patch --codebase --rerank --output prompt

# JSON output for programmatic use
/dpgeorge-review review --diff changes.patch --output json
```

### Search for Specific Patterns

Find similar reviews by semantic search:

```bash
# Search by topic
/dpgeorge-review search "memory allocation error handling"
/dpgeorge-review search "null pointer dereference"
/dpgeorge-review search "function naming conventions"

# Filter by domain
/dpgeorge-review search "API design" --domain api_design
/dpgeorge-review search "edge cases" --domain correctness
/dpgeorge-review search "performance" --domain performance

# Filter by severity
/dpgeorge-review search "blocking issue" --severity blocking
/dpgeorge-review search "style issue" --severity nitpick

# Filter by component
/dpgeorge-review search "GPIO config" --component port_specific
/dpgeorge-review search "GC issue" --component py_core

# Get more results
/dpgeorge-review search "memory leak" -k 20

# Only show style examples
/dpgeorge-review search "variable naming" --style-only

# JSON output
/dpgeorge-review search "error handling" --json
```

### Index Management

```bash
# Show index statistics
/dpgeorge-review stats

# Rebuild index (if needed)
/dpgeorge-review index --force

# Build with specific batch size (memory-constrained systems)
/dpgeorge-review index --force --batch-size 4
```

### Evaluation

```bash
# Build evaluation dataset
/dpgeorge-review eval build-dataset --count 50 --stratify domain --output eval/dataset.json

# Run retrieval evaluation
/dpgeorge-review eval retrieval --dataset eval/dataset.json --output eval/results

# View evaluation metrics
/dpgeorge-review eval metrics --results-dir eval/results
```

## Output Formats

### Context Output (default)

Provides formatted review examples with diff context:

```markdown
# Relevant Past Reviews by dpgeorge

## Example 1: correctness - blocking
​```diff
- old code
+ new code
​```

dpgeorge's comment:
> This will cause a null pointer dereference...

---
```

### Prompt Output

Full prompt ready to paste into an AI model for code review:

- Style guide (dpgeorge's review principles)
- 5-10 relevant review examples with context
- Codebase context (if --codebase used)
- Code to review
- Task instructions

### JSON Output

Structured data for programmatic use:

```json
{
  "review_examples": [
    {
      "comment_id": 12345,
      "body": "comment text",
      "diff_hunk": "diff context",
      "domain": "correctness",
      "severity": "blocking",
      "score": 0.8
    }
  ],
  "codebase_context": {...},
  "query_length": 1234
}
```

## Filters and Categories

### Domains (13 categories)

- `code_style` - Formatting, naming conventions
- `correctness` - Logic bugs, edge cases
- `api_design` - Public interfaces, usability
- `memory` - Memory management, leaks
- `performance` - Speed, efficiency
- `portability` - Cross-platform compatibility
- `documentation` - Comments, docs
- `testing` - Test coverage, quality
- `security` - Security vulnerabilities
- `architecture` - Design patterns, structure
- `build_system` - Makefiles, configuration
- `error_handling` - Error paths, recovery

### Severities

- `blocking` - Must fix before merge
- `suggestion` - Recommended improvement
- `nitpick` - Minor style/preference

### Components

- `py_core` - Core Python runtime (py/)
- `extmod` - Extended modules (extmod/)
- `port_specific` - Port implementations (ports/)
- `drivers` - Hardware drivers (drivers/)
- `tools` - Build/development tools (tools/)
- `tests` - Test suite (tests/)
- `docs` - Documentation (docs/)
- `build_system` - Build configuration
- `examples` - Example code

## Performance

### First Query
- ~2-3 seconds (model loading)

### Subsequent Queries
- Dense search only: ~0.5-1 second
- With re-ranking: +5-10 seconds (CPU), +1-2 seconds (GPU)
- With codebase context: +2-3 seconds

### Tips for Speed
```bash
# Fastest (skip re-ranking)
/dpgeorge-review review --diff file.patch

# Balanced
/dpgeorge-review review --diff file.patch --codebase

# Best quality (slowest)
/dpgeorge-review review --diff file.patch --codebase --rerank
```

## Common Workflows

### 1. Review a Local Branch

```bash
# Generate diff for current branch
git diff main > my_changes.patch

# Get review context
/dpgeorge-review review --diff my_changes.patch --codebase --output prompt > review_context.txt

# Use the context to inform your AI-assisted review
```

### 2. Review a GitHub PR

```bash
# Get review examples for a PR
/dpgeorge-review review --pr 12345 --codebase --rerank --output prompt

# The output can be pasted into an AI model for review generation
```

### 3. Find Examples of Specific Feedback

```bash
# Find all memory-related blocking issues
/dpgeorge-review search "memory allocation" --domain memory --severity blocking -k 20

# Find port-specific API design suggestions
/dpgeorge-review search "GPIO API" --component port_specific --domain api_design
```

### 4. Learn dpgeorge's Style

```bash
# Find style-heavy examples
/dpgeorge-review search "code style" --style-only -k 30

# Search for communication patterns
/dpgeorge-review search "function naming" --style-only
/dpgeorge-review search "comment style" --style-only
```

## Troubleshooting

### "Index not found" Error

```bash
# Verify index exists
source /home/anl/mpy/dpgeorge-review-db/venv/bin/activate
/dpgeorge-review stats

# If not, build it
cd /home/anl/mpy/dpgeorge-review-db
python scripts/build_index_resume.py
```

### Slow Performance

```bash
# Don't use --rerank for faster results
/dpgeorge-review review --diff file.patch

# Or reduce top-k
/dpgeorge-review review --diff file.patch -k 5
```

### Memory Issues

```bash
# If indexing fails, reduce batch size
cd /home/anl/mpy/dpgeorge-review-db
source venv/bin/activate
python scripts/build_index_resume.py  # Uses batch_size=4 by default
```

### Command Not Found

Ensure virtual environment is activated:

```bash
source /home/anl/mpy/dpgeorge-review-db/venv/bin/activate
which mpy-review-rag  # Should show venv path
```

Or use full path:
```bash
/home/anl/mpy/dpgeorge-review-db/venv/bin/mpy-review-rag review --diff file.patch
```

## Data Statistics

- **Total records**: 18,614 categorized review comments
- **Source PRs**: 5,542 (2013-2025)
- **Review comments**: 6,842 (inline code feedback)
- **Issue comments**: 11,379 (PR discussion)
- **Review verdicts**: 4,584

### Distribution

**By Domain:**
- Correctness: 21.2%
- Code Style: 17.3%
- API Design: 12.7%
- Documentation: 11.5%
- Architecture: 11.3%

**By Severity:**
- Suggestion: 57.9%
- Nitpick: 28.5%
- Blocking: 13.6%

**By Component:**
- Port-specific: 32.4%
- Core Python: 31.9%
- Extended modules: 9.8%

## Technical Details

### Models Used

- **Embeddings**: jinaai/jina-embeddings-v2-base-code (768-dim, 8K context)
- **Re-ranker**: BAAI/bge-reranker-large (cross-encoder)

### Search Pipeline

1. **Query Processing**: Extract identifiers and patterns
2. **Hybrid Retrieval**: Dense (embedding) + Sparse (BM25) search
3. **Fusion**: Reciprocal Rank Fusion (RRF)
4. **Filtering**: Domain, severity, component filters
5. **Re-ranking** (optional): Cross-encoder scoring
6. **Diversity**: MMR selection for balanced results

### Database

- **Storage**: SQLite (source) + LanceDB (vector index)
- **Size**: 28MB SQLite + 1.4GB LanceDB
- **Location**: /home/anl/mpy/dpgeorge-review-db/data/

## Examples

### Example 1: Review a Diff File

```bash
$ /dpgeorge-review review --diff my_changes.patch --codebase
# Relevant Past Reviews by dpgeorge

## Example 1: correctness - blocking
​```diff
+void *ptr = malloc(size);
+use(ptr);
​```

dpgeorge's comment:
> Need to check if malloc returns NULL before using ptr.

---

## Example 2: code_style - suggestion
...
```

### Example 2: Search for API Design Patterns

```bash
$ /dpgeorge-review search "constructor arguments" --domain api_design -k 5
--- Result 1 ---
Domain: api_design | Severity: suggestion
Score: 0.8543

Better to have constructor arguments with sensible defaults rather than
requiring a separate init() call...
```

### Example 3: Generate Full Review Prompt

```bash
$ /dpgeorge-review review --diff my_changes.patch --codebase --rerank --output prompt > review.txt

# The review.txt now contains:
# - dpgeorge's review style guide
# - 8 relevant review examples with diff context
# - MicroPython codebase context (definitions, patterns)
# - Your code to review
# - Task instructions for the AI model
```

## Integration with AI Review

The most common workflow is:

1. Generate review context with this skill
2. Pass the context to an AI model (Claude, GPT, etc.)
3. The AI reviews the code using dpgeorge's patterns

Example:
```bash
# Get context
/dpgeorge-review review --pr 12345 --codebase --rerank --output prompt > context.txt

# Now paste context.txt into Claude Code or API
# The AI will review the PR in dpgeorge's style
```

## Version and Updates

- **Database**: Built from micropython/micropython through 2025-01
- **Index**: 18,614 records
- **To update**: Re-run data collection and indexing scripts in the project repository

## Support

For issues, see:
- `/home/anl/mpy/dpgeorge-review-db/README.md` - Project overview
- `/home/anl/mpy/dpgeorge-review-db/CLAUDE.md` - Development guide
- `/home/anl/mpy/dpgeorge-review-db/QUICKSTART.md` - Quick start guide
