# Production-Quality Dual RAG System for dpgeorge-Style Code Review

## Objective

Build a high-quality retrieval system that combines:
1. **Review RAG** - Retrieve relevant dpgeorge review examples from 18,614 categorized comments
2. **Codebase RAG** - Retrieve relevant MicroPython source context for code being reviewed

Enable a frontier model (Claude) to generate accurate, dpgeorge-style code reviews by providing rich contextual examples and codebase knowledge.

---

## System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Review Request                                │
│  (PR diff, file paths, commit message)                              │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Query Processing                                │
│  - Extract code patterns, identifiers, domains                      │
│  - Generate multiple query variants                                  │
│  - Identify relevant metadata filters                                │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                              ▼
┌────────────────────────────┐    ┌────────────────────────────┐
│      Review RAG            │    │      Codebase RAG          │
│                            │    │                            │
│  Stage 1: Sparse+Dense     │    │  Stage 1: Codanna Index    │
│  Stage 2: Metadata Filter  │    │  Stage 2: Symbol/Caller    │
│  Stage 3: Cross-Encoder    │    │  Stage 3: Context Expand   │
│  Stage 4: Diversity        │    │  Stage 4: Hierarchy Rank   │
└────────────────────────────┘    └────────────────────────────┘
                    │                              │
                    └──────────────┬──────────────┘
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Result Fusion                                   │
│  - Reciprocal Rank Fusion (RRF) or learned weights                  │
│  - Context budget allocation                                         │
│  - Deduplication and diversity enforcement                          │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Prompt Assembly                                 │
│  - Style guide (dpgeorge patterns)                                  │
│  - Retrieved review examples (5-10)                                  │
│  - Retrieved codebase context (relevant definitions)                │
│  - Code diff to review                                               │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Frontier Model (Claude)                         │
│  Generate review in dpgeorge style                                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Component 1: Review RAG (dpgeorge Comments)

### 1.1 Embedding Strategy

**Primary Embeddings (Dense)**:
- Model: `jinaai/jina-embeddings-v2-base-code` (local, Hugging Face)
- Why: 8K context for large diffs, specialized for 30 programming languages
- Dimension: 768
- VRAM: ~650MB (can also run on CPU)

**Chunking Strategy**:
```
For each review comment:
  Chunk A (Primary): comment_body only
  Chunk B (Contextual): comment_body + diff_hunk (code context)
  Chunk C (Rich): comment_body + diff_hunk + theme + keywords

Store all three with shared metadata, query against appropriate chunk type
```

**Sparse Index (BM25)**:
- Index: comment_body + keywords + theme
- Purpose: Exact keyword matching (function names, error messages)
- Why: Dense embeddings can miss exact matches

### 1.2 Metadata Schema for Filtering

```json
{
  "comment_id": "integer",
  "comment_type": "enum[review_comment, issue_comment, review]",
  "domain": "enum[12 domains]",
  "severity": "enum[blocking, suggestion, nitpick]",
  "component": "enum[py_core, extmod, port_specific, ...]",
  "language_context": "enum[c_code, python_code, documentation, ...]",
  "code_construct": "enum[function, macro, class, ...]",
  "concern_type": "enum[correctness, style, performance, ...]",
  "feedback_type": "enum[question, suggestion, requirement, ...]",
  "is_style_example": "boolean",
  "is_pattern": "boolean",
  "has_code_suggestion": "boolean",
  "port": "string|null",
  "subsystem": "string|null",
  "keywords": "array[string]",
  "body_length": "integer",
  "diff_length": "integer"
}
```

### 1.3 Multi-Stage Retrieval Pipeline

```
Stage 1: Initial Retrieval (Hybrid)
  ├─ Dense: Top 100 by embedding similarity
  ├─ Sparse: Top 100 by BM25 score
  └─ Merge: Reciprocal Rank Fusion → Top 50

Stage 2: Metadata Filtering
  ├─ Hard filters: language_context, component (if determinable)
  ├─ Soft boost: domain match (+0.2), severity match (+0.1)
  └─ Result: Top 30

Stage 3: Cross-Encoder Re-ranking
  ├─ Model: ms-marco-MiniLM-L-12-v2 or BGE-reranker-large
  ├─ Input: (query, comment+context) pairs
  └─ Result: Top 15

Stage 4: Diversity & Quality Selection
  ├─ MMR (Maximal Marginal Relevance) for diversity
  ├─ Prefer is_style_example=true
  ├─ Balance severity distribution
  └─ Final: 5-10 examples
```

### 1.4 Query Expansion

For each review request, generate multiple query variants:
```python
queries = [
    original_query,                           # Raw diff/code
    extract_function_signatures(query),       # "def foo(x, y):" patterns
    extract_error_patterns(query),            # Common error patterns
    domain_specific_query(inferred_domain),   # "memory safety in C"
    concern_query(inferred_concern),          # "correctness of loop bounds"
]
```

---

## Component 2: Codebase RAG (MicroPython Source)

### 2.1 Codanna Index Enhancement

**Initial Setup**:
```bash
cd /home/corona/mpy/review
codanna init
codanna index . --progress
```

**Custom Configuration** (`.codanna/settings.toml`):
```toml
[index]
include = ["py/**", "extmod/**", "ports/**", "shared/**", "lib/**"]
exclude = ["**/build/**", "**/.git/**", "**/test*/**"]
max_file_size = 100000

[embedding]
model = "code-specific"  # If available
chunk_size = 1500
overlap = 200
```

### 2.2 Hierarchical Code Indexing

**Level 1: File-Level**
- Summary embedding per file
- Key exports, imports, dependencies

**Level 2: Symbol-Level**
- Functions, classes, macros, structs
- Full signature + docstring/comment

**Level 3: Definition-Level**
- Struct/enum definitions with all fields
- Macro expansions

**Relationship Graph**:
```
Using codanna tools:
  - find_callers: What calls this function
  - get_calls: What this function calls
  - analyze_impact: Change radius
  - find_symbol: Exact lookup

Build adjacency for:
  - Include relationships (header → source)
  - Call graph (function → function)
  - Type dependencies (struct uses → struct definition)
```

### 2.3 Context Expansion Strategy

When reviewing code in file `X`:
```
1. Direct context: Lines ±50 around changed code
2. Same-file context: Function boundaries, related definitions
3. Header context: Included headers' relevant definitions
4. Caller context: Functions that call modified code
5. Pattern context: Similar patterns elsewhere in codebase
```

### 2.4 Code-Aware Query Generation

For a diff being reviewed:
```python
def generate_codebase_queries(diff):
    queries = []

    # Extract identifiers
    identifiers = extract_identifiers(diff)  # mp_obj_t, gc_alloc, etc.
    for ident in identifiers:
        queries.append(f"definition of {ident}")

    # Extract includes
    includes = extract_includes(diff)  # #include "obj.h"
    for inc in includes:
        queries.append(f"contents of {inc}")

    # Extract patterns
    patterns = extract_code_patterns(diff)  # MP_DEFINE_CONST_*, etc.
    for pat in patterns:
        queries.append(f"usage pattern {pat}")

    return queries
```

---

## Component 3: Result Fusion & Prompt Assembly

### 3.1 Fusion Strategy

**Reciprocal Rank Fusion (RRF)**:
```python
def rrf_score(rankings, k=60):
    scores = defaultdict(float)
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            scores[item] += 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: -x[1])
```

**Weighted Combination**:
```python
final_score = (
    0.4 * review_relevance +
    0.3 * codebase_relevance +
    0.2 * metadata_match +
    0.1 * style_example_bonus
)
```

### 3.2 Context Budget Allocation

Total budget: ~15K tokens for retrieval

```
Review Examples:
  - 5-8 comments × 500-800 tokens = 3-6K tokens
  - Prioritize: blocking > suggestion > nitpick
  - Ensure diversity: different domains/concerns

Codebase Context:
  - Relevant definitions: 2-4K tokens
  - Include chains: 1-2K tokens
  - Similar patterns: 1-2K tokens

Style Guide (static):
  - dpgeorge patterns summary: 1K tokens
  - Feedback type examples: 500 tokens
```

### 3.3 Final Prompt Structure

```markdown
# dpgeorge Review Style Guide
[Static content about communication patterns, severity calibration]

# Relevant Past Reviews by dpgeorge
## Example 1: [domain] - [severity]
File: {path}
Code context:
```diff
{diff_hunk}
```
dpgeorge's comment:
> {comment_body}
---
[Repeat for 5-8 examples]

# MicroPython Codebase Context
## Relevant Definitions
{retrieved_definitions}

## Related Patterns in Codebase
{similar_code_patterns}

# Code to Review
PR: #{pr_number} - {title}
Files changed: {file_list}

```diff
{full_diff}
```

# Your Task
Review this code in dpgeorge's style. Consider:
- Correctness (logic bugs, edge cases)
- Code style (MicroPython conventions)
- Memory efficiency (embedded constraints)
- API design (if public interfaces affected)

Provide feedback with appropriate severity levels.
```

---

## Component 4: Vector Store & Infrastructure

### 4.1 Vector Store Selection

**Recommended: Qdrant** (local, production-grade)
- Hybrid search (dense + sparse) built-in
- Payload filtering (our metadata)
- MMR support
- Quantization for efficiency
- REST + gRPC APIs

**Alternative: Weaviate**
- GraphQL API
- Hybrid search
- Better for complex filtering

### 4.2 Deployment Architecture

```
┌─────────────────────────────────────────────┐
│              Local Machine                   │
├─────────────────────────────────────────────┤
│  LanceDB (embedded, no server)              │
│    - Table: dpgeorge_reviews (~40-80 MB)    │
│    - Data: ./data/lance/                    │
│    - Portable: copy dir or Git LFS          │
│                                             │
│  Codanna Service                            │
│    - MCP server (already running)           │
│    - Index: /home/corona/mpy/review         │
│                                             │
│  Python CLI (mpy-review-rag)                │
│    - Orchestrates retrieval pipeline        │
│    - Assembles prompts                      │
│                                             │
│  Claude Code / API                          │
│    - Consumes assembled context             │
│    - Generates reviews                      │
└─────────────────────────────────────────────┘
```

### 4.3 Embedding Pipeline

```python
# Pseudo-code for indexing

import lancedb
from transformers import AutoModel, AutoTokenizer
import torch
import sqlite3
import pyarrow as pa

# Initialize Jina embeddings
model = AutoModel.from_pretrained("jinaai/jina-embeddings-v2-base-code", trust_remote_code=True)
tokenizer = AutoTokenizer.from_pretrained("jinaai/jina-embeddings-v2-base-code")

# Move to GPU if available
device = "cuda" if torch.cuda.is_available() else "cpu"
model = model.to(device)

def embed(texts: list[str]) -> list[list[float]]:
    """Embed texts using Jina v2 Base Code (8K context)."""
    inputs = tokenizer(texts, padding=True, truncation=True, max_length=8192, return_tensors="pt")
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        outputs = model(**inputs)
    # Mean pooling
    embeddings = outputs.last_hidden_state.mean(dim=1)
    return embeddings.cpu().numpy().tolist()

# Initialize LanceDB (local, no server needed)
db = lancedb.connect("./data/lance")

# Prepare data for indexing
conn = sqlite3.connect("dpgeorge_reviews.db")
records = []

for comment in get_all_comments(conn):
    # Dense embedding (can handle up to 8K tokens = ~27K chars)
    text = f"{comment['body']}\n\nCode context:\n{comment['diff_hunk']}"
    vector = embed([text])[0]

    records.append({
        "id": comment['id'],
        "vector": vector,
        "body": comment['body'],
        "diff_hunk": comment['diff_hunk'],
        "domain": comment['domain'],
        "severity": comment['severity'],
        "component": comment['component'],
        "language_context": comment['language_context'],
        "code_construct": comment['code_construct'],
        "is_style_example": comment['is_style_example'],
        "keywords": comment['keywords'],
        # ... all metadata fields
    })

# Create table with all records (LanceDB handles indexing automatically)
table = db.create_table("dpgeorge_reviews", records, mode="overwrite")

# Optional: Create IVF-PQ index for larger datasets (not needed at 18K scale)
# table.create_index(metric="cosine", num_partitions=16, num_sub_vectors=48)

# For full-text search (hybrid), create FTS index
table.create_fts_index("body", replace=True)
```

**Portability**: The `./data/lance/` directory can be:
- Copied directly to another machine
- Committed to Git LFS
- Uploaded to S3/cloud storage

---

## Component 5: Evaluation Framework

### 5.1 Retrieval Quality Metrics

**Offline Evaluation**:
- Recall@K: Do we retrieve relevant examples?
- Precision@K: Are retrieved examples relevant?
- MRR (Mean Reciprocal Rank): Is the best example ranked high?
- NDCG: Graded relevance scoring

**Test Set Construction**:
```python
# Sample 100 PRs with known dpgeorge reviews
# For each PR:
#   - Input: PR diff (excluding dpgeorge's review)
#   - Ground truth: dpgeorge's actual review
#   - Evaluate: Can we retrieve similar past reviews?
```

### 5.2 Generation Quality Metrics

**Automatic**:
- BLEU/ROUGE against actual dpgeorge reviews (weak signal)
- Domain/severity classification accuracy
- Code suggestion presence when warranted

**Human Evaluation**:
- Blind comparison: Generated vs actual dpgeorge review
- Style match scoring (1-5 scale)
- Technical accuracy assessment
- Actionability of feedback

### 5.3 A/B Testing Framework

```
Configurations to test:
A. Dense only (baseline)
B. Dense + Sparse hybrid
C. Dense + Sparse + Cross-encoder
D. Full pipeline with metadata filtering

For each:
- Measure retrieval latency
- Measure retrieval quality
- Measure generation quality
- Track context token usage
```

---

## Implementation Phases

### Phase 1: Infrastructure Setup
- [ ] Install and configure Qdrant (Docker)
- [ ] Index MicroPython with Codanna
- [ ] Set up embedding pipeline (OpenAI or local)
- [ ] Create review collection schema

### Phase 2: Review RAG Implementation
- [ ] Export reviews from SQLite to Qdrant
- [ ] Implement hybrid retrieval (dense + BM25)
- [ ] Add metadata filtering
- [ ] Implement cross-encoder re-ranking
- [ ] Add diversity selection (MMR)

### Phase 3: Codebase RAG Implementation
- [ ] Verify Codanna index quality
- [ ] Implement context expansion logic
- [ ] Build code-aware query generation
- [ ] Integrate with Codanna MCP tools

### Phase 4: Integration & Fusion
- [ ] Implement RRF fusion
- [ ] Build prompt assembly pipeline
- [ ] Context budget management
- [ ] End-to-end testing

### Phase 5: Evaluation & Tuning
- [ ] Build evaluation dataset
- [ ] Implement metrics collection
- [ ] Run A/B experiments
- [ ] Tune parameters based on results

### Phase 6: Production Hardening
- [ ] Error handling and fallbacks
- [ ] Caching layer
- [ ] Monitoring and logging
- [ ] Documentation

---

## Design Decisions (Confirmed)

1. **Embedding Model**: Jina Embeddings v2 Base Code (local, 8K context, 30 programming languages)
2. **Vector Store**: LanceDB (local, Git LFS portable, no external services)
3. **Evaluation**: Rigorous with real data only (no synthetic test cases)
4. **Integration**: CLI tool + SKILL.md for Claude Code integration

### Vector Store Rationale

- **Portability**: Native Lance format designed for Git/cloud storage
- **Size**: 40-80 MB for 18,614 embeddings (columnar compression)
- **Setup**: Single `pip install lancedb`, no Docker required
- **Transfer**: Copy data directory or commit to Git LFS
- **Performance**: Same query latency (~5-20ms) as Qdrant at this scale
- **Hybrid search**: Supports dense + sparse (full-text) search

### Embedding Model Rationale

After research comparing OpenAI, Voyage, and local models:

- **Context Length**: 8K tokens handles most diffs (up to ~27K chars); OpenAI limited to ~2.3K tokens
- **Code Specialization**: Jina v2 Base Code supports 30 programming languages including C/Python
- **Performance**: ~90% accuracy on code retrieval vs ~88% for OpenAI general-purpose
- **Cost**: Free after initial setup (no API costs for re-indexing)
- **Model**: `jinaai/jina-embeddings-v2-base-code` from Hugging Face
- **Dimensions**: 768
- **VRAM**: ~650MB (can run on CPU with slower inference)

---

## Component 6: CLI Tool & Skill Integration

### 6.1 CLI Tool Design

```bash
# Primary commands
mpy-review-rag index          # Build/update vector indices
mpy-review-rag search <query> # Test retrieval quality
mpy-review-rag review <diff>  # Generate review context for a diff
mpy-review-rag eval           # Run evaluation suite

# Examples
mpy-review-rag review --pr 12345                    # Review a PR by number
mpy-review-rag review --diff /path/to/file.diff    # Review a diff file
mpy-review-rag review --stdin                       # Read diff from stdin
mpy-review-rag search "memory allocation in gc"    # Test semantic search
```

**Output Modes**:
```bash
--output context    # Output retrieval context only (for manual review)
--output prompt     # Output full assembled prompt
--output json       # Structured JSON for programmatic use
```

### 6.2 Skill Integration

Create `/home/corona/.claude/skills/dpgeorge-review.md`:

```markdown
---
name: dpgeorge-review
description: Generate code reviews in dpgeorge's style using RAG-augmented context
---

# dpgeorge Review Skill

Use this skill when reviewing MicroPython code or PRs. It retrieves relevant
past reviews by dpgeorge and MicroPython codebase context to help generate
accurate, style-consistent reviews.

## Usage

When the user asks to review code or a PR:

1. Get the diff content (from PR number, file, or clipboard)
2. Run the RAG retrieval:
   ```bash
   mpy-review-rag review --pr <number> --output prompt
   ```
3. The output contains:
   - Relevant past dpgeorge reviews
   - Related MicroPython source context
   - Style guidelines
4. Use this context to generate the review

## Example Invocations

- "Review PR #16234 in dpgeorge style"
- "Review this diff like dpgeorge would"
- "/dpgeorge-review 16234"

## Output Interpretation

The tool outputs structured context with:
- `review_examples`: Past reviews with similar code patterns
- `codebase_context`: Relevant MicroPython definitions
- `style_guide`: dpgeorge's review patterns
- `metadata`: Retrieval quality signals
```

### 6.3 Skill Workflow

```
User: "Review PR #16234"
      ↓
Claude Code invokes skill
      ↓
Skill runs: mpy-review-rag review --pr 16234 --output prompt
      ↓
Tool retrieves:
  - 8 relevant past reviews (4.2K tokens)
  - Related mp_obj_* definitions (2.1K tokens)
  - Header context for modified files (1.8K tokens)
      ↓
Claude generates review using retrieved context
      ↓
User sees dpgeorge-style review with proper severity, domain awareness
```

---

## Component 7: Real-Data Evaluation Framework

### 7.1 Evaluation Dataset Construction

**Source**: Actual PRs with dpgeorge reviews from the database

**Dataset Structure**:
```python
# For each test case:
{
    "pr_number": 12345,
    "pr_title": "py/objstr: Add splitlines method",
    "diff": "<full PR diff>",
    "files_changed": ["py/objstr.c", "py/objstr.h"],

    # Ground truth: dpgeorge's actual reviews on this PR
    "dpgeorge_reviews": [
        {
            "comment_id": 789,
            "body": "This should handle the universal newlines case...",
            "file": "py/objstr.c",
            "line": 245,
            "severity": "suggestion",
            "domain": "correctness"
        },
        # ... more reviews
    ],

    # For retrieval evaluation: which past reviews SHOULD be retrieved?
    "relevant_past_reviews": [
        # Comment IDs from OTHER PRs that address similar issues
        # (manually curated or heuristically matched)
    ]
}
```

### 7.2 Dataset Sampling Strategy

**Selection Criteria** (ensure diversity):
```python
# Sample 100 PRs ensuring coverage of:
- All 12 domains (8-10 per domain)
- All 3 severity levels
- Multiple components (py_core, extmod, ports)
- Various file types (C, Python, docs)
- Different PR sizes (small, medium, large diffs)
- Recent PRs (2023-2024) and older PRs
```

**Exclusion**:
```python
# Exclude from test set:
- PRs where dpgeorge was the author (reviewing own code)
- PRs with only "Merged in..." process comments
- PRs with < 2 substantive review comments
```

### 7.3 Retrieval Metrics

**Metrics to Track**:
```python
# For each test PR, given the diff as query:

recall_at_k = {
    5: "% of relevant past reviews in top 5",
    10: "% of relevant past reviews in top 10",
    20: "% of relevant past reviews in top 20"
}

precision_at_k = {
    5: "% of top 5 that are relevant",
    10: "% of top 10 that are relevant"
}

mrr = "1/rank of first relevant result"

ndcg = "Graded relevance with position discount"

domain_accuracy = "% where retrieved domain matches actual review domain"
severity_calibration = "Distribution match between retrieved and actual"
```

### 7.4 Generation Quality Metrics

**Automatic (Weak Signal)**:
```python
# Compare generated review to actual dpgeorge review
- Concern overlap: Did we identify the same issues?
- Severity match: Is our severity calibration similar?
- Domain match: Did we focus on the right domain?
```

**Human Evaluation (Strong Signal)**:
```python
# Blind A/B comparison
# Evaluator sees: PR diff + two reviews (one generated, one actual)
# Evaluator rates:
- Which is more technically accurate? (1-5)
- Which is more actionable? (1-5)
- Which better matches dpgeorge's style? (1-5)
- Can you tell which is generated? (yes/no)
```

### 7.5 Evaluation Pipeline

```bash
# Build evaluation dataset
mpy-review-rag eval build-dataset --output eval/dataset.json

# Run retrieval evaluation
mpy-review-rag eval retrieval --dataset eval/dataset.json --output eval/retrieval_results.json

# Generate reviews for test set
mpy-review-rag eval generate --dataset eval/dataset.json --output eval/generated_reviews.json

# Compute metrics
mpy-review-rag eval metrics --results eval/retrieval_results.json

# Human evaluation interface (optional)
mpy-review-rag eval human --dataset eval/dataset.json --generated eval/generated_reviews.json
```

---

## Files to Create/Modify

```
/home/corona/mpy/dpgeorge-review-db/
├── rag/
│   ├── __init__.py
│   ├── config.py              # Configuration (Qdrant URL, model paths, device)
│   ├── embeddings.py          # Jina v2 Base Code local embedding
│   ├── indexer.py             # Build Qdrant indices from SQLite
│   ├── retriever.py           # Multi-stage hybrid retrieval
│   ├── reranker.py            # Cross-encoder re-ranking
│   ├── codebase.py            # Codanna integration for codebase RAG
│   ├── fusion.py              # RRF fusion of review + codebase results
│   ├── prompt_builder.py      # Assemble final prompt with context budget
│   ├── evaluator.py           # Retrieval quality metrics
│   └── cli.py                 # Click-based CLI (dpgeorge-rag)
├── eval/
│   ├── build_dataset.py       # Sample PRs for evaluation set
│   ├── compute_metrics.py     # Recall@k, MRR, NDCG calculations
│   └── dataset.json           # 100 real PR test cases
├── data/
│   └── lance/                 # LanceDB data (portable, Git LFS compatible)
├── requirements.txt           # transformers, torch, lancedb, click, etc.
├── pyproject.toml             # Package configuration
└── tests/
    ├── test_retrieval.py
    ├── test_fusion.py
    └── test_prompt_builder.py

/home/corona/.claude/skills/
└── dpgeorge-review.md         # Skill definition for Claude Code

/home/corona/mpy/review/
└── .codanna/                  # Codanna index (to be built)
    ├── settings.toml
    └── index/
```

---

## Revised Implementation Phases

### Phase 1: Infrastructure (Day 1)
- [ ] Create project structure (`/home/corona/mpy/dpgeorge-review-db/rag/`)
- [ ] Install dependencies (`pip install lancedb transformers torch click`)
- [ ] Download Jina model (`jinaai/jina-embeddings-v2-base-code`)
- [ ] Build Codanna index for MicroPython (`codanna index`)

### Phase 2: Review RAG Core (Days 2-3)
- [ ] Implement `embeddings.py` - Jina v2 Base Code with batching and GPU/CPU support
- [ ] Implement `indexer.py` - Export reviews to LanceDB with all metadata + FTS index
- [ ] Implement `retriever.py` - Hybrid search (dense + full-text)
- [ ] Add metadata filtering support
- [ ] Basic CLI for testing (`mpy-review-rag search`)

### Phase 3: Codebase RAG Integration (Day 4)
- [ ] Implement `codebase.py` - Wrap Codanna MCP tools
- [ ] Build query generation from diffs (extract identifiers, patterns)
- [ ] Context expansion (headers, callers, related code)
- [ ] Test codebase retrieval quality

### Phase 4: Cross-Encoder Re-ranking (Day 5)
- [ ] Implement `reranker.py` - BGE-reranker or ms-marco model
- [ ] Integrate into retrieval pipeline
- [ ] Add MMR diversity selection
- [ ] Tune re-ranking weights

### Phase 5: Fusion & Prompt Assembly (Day 6)
- [ ] Implement `fusion.py` - RRF combination
- [ ] Implement `prompt_builder.py` - Context budget management
- [ ] Build style guide extraction from database
- [ ] End-to-end CLI (`mpy-review-rag review`)

### Phase 6: Evaluation Framework (Days 7-8)
- [ ] Build evaluation dataset (100 real PRs)
- [ ] Implement retrieval metrics (recall@k, MRR, NDCG)
- [ ] Run baseline evaluation
- [ ] Tune parameters based on metrics

### Phase 7: Skill Integration & Polish (Day 9)
- [ ] Create `/home/corona/.claude/skills/dpgeorge-review.md`
- [ ] Test skill invocation from Claude Code
- [ ] Error handling and edge cases
- [ ] Documentation

### Phase 8: Iteration & Tuning (Ongoing)
- [ ] Analyze failure cases
- [ ] Adjust retrieval weights, chunk strategies
- [ ] Add caching for common queries
- [ ] Monitor and improve
