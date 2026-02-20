# MicroPython Review Database

A database and analysis system for the MicroPython lead maintainer's code review feedback on the MicroPython repository.

## Project Goal

Create a queryable knowledge base of historical MicroPython PR review patterns and style that can:
1. **Guide AI-assisted PR reviews** - Find relevant past feedback when reviewing new PRs
2. **Learn review patterns** - Identify recurring best practices and common issues
3. **Match writing style** - Replicate the lead maintainer's direct, terse, technical communication style
4. **Provide context-aware guidance** - Search by component, port, subsystem, concern type, etc.

## Why This Matters

When reviewing MicroPython PRs, an AI assistant needs to:
- Apply the same technical standards the lead maintainer uses (memory safety, portability, API design)
- Match the project's coding conventions and patterns
- Communicate in the lead maintainer's characteristic style (direct, technical, no fluff)
- Find relevant precedents for similar code patterns or issues
- Understand domain-specific concerns (embedded systems, microcontrollers, resource constraints)

## Project Status

### Completed
✅ Database schema design and implementation
✅ Data collection script (22,805 comments from 5,542 PRs)
✅ Full data collection (6,842 review comments + 11,379 issue comments + 4,584 reviews)
✅ Enhanced categorization schema design (13 fields)
✅ Manual validation (40 sample categorizations)
✅ Full categorization run (18,614 categorized comments)
✅ Vector index built (sqlite-vec with CodeRankEmbed embeddings)
✅ Semantic search validated and working
✅ CLI tool implementation (`mpy-reviewer`)

### Future Enhancements
- Style guide generation from categorized corpus
- Integration with GitHub Actions for automated review suggestions
- Continuous collection of new reviews

## Data Collection Results

**Repository:** micropython/micropython
**Timeframe:** 2013-2025 (full project history)
**Total PRs analyzed:** 5,542
**Comments collected:** 22,805 total
- Review comments (inline code): 6,842
- Issue comments (PR discussion): 11,379
- Review verdicts: 4,584

**Collection method:** GitHub API via `gh` CLI
**Challenges solved:**
- URL encoding for search queries
- GitHub's 1000-result pagination limit (solved with year-based queries)
- Rate limiting (maintained ~674 PRs/hour)

## Key Findings

### Comment Distribution by Component

```
ports/       43% (2,953 comments)
py/          15% (1,030 comments)
extmod/      11% (734 comments)
docs/         9% (588 comments)
tests/        7% (495 comments)
tools/        4% (307 comments)
other        11% (698 comments)
```

**Insight:** Nearly half of all review feedback is port-specific, highlighting the importance of hardware platform context.

### Most Commented Files

1. `py/mpconfig.h` (64) - Configuration macros
2. `extmod/modbluetooth.c` (59) - Bluetooth module
3. `py/objtype.c` (46) - Type system
4. `ports/mimxrt/Makefile` (42) - Build system
5. `ports/rp2/machine_uart.c` (42) - UART driver

### GitHub Labels in Use

**Ports (15 labels):**
- port-esp32, port-stm32, port-rp2, port-unix, port-zephyr
- port-mimxrt, port-nrf, port-samd, port-renesas-ra, etc.

**Components:**
- extmod, drivers, docs, tests, examples, board-definition

**Change types:**
- bug, enhancement, needs-info, proposed-close

## Categorization Schema Design

After analyzing 40 random samples, we developed a 13-field schema:

### Core Fields
- **domain**: Broad technical category (code_style, memory, error_handling, api_design, performance, portability, documentation, testing, security, architecture, build_system, correctness)
- **theme**: Specific issue or pattern (e.g., "use simpler bool type", "struct alignment")
- **severity**: blocking | suggestion | nitpick
- **is_style_example**: Whether comment demonstrates the lead maintainer's writing style well

### Component Classification
- **component**: Codebase area (py_core, extmod, port_specific, drivers, tools, tests, docs, build_system, examples)
- **port**: Specific port if applicable (esp32, stm32, rp2, unix, etc.) or NULL
- **subsystem**: More specific area (bluetooth, networking, usb, filesystem, uart, gc, vm, compiler, etc.) or NULL

### Technical Context
- **language_context**: c_code, python_code, documentation, makefile, shell_script, yaml
- **code_construct**: What's being discussed (function, macro, struct, typedef, class, module, test_case, documentation_page, build_rule, config_option)
- **concern_type**: Nature of feedback (correctness, safety, api_design, style, performance, portability, maintainability, testing, documentation, security, compatibility)

### Comment Characteristics
- **feedback_type**: How comment is phrased (question, suggestion, requirement, information, praise, merge)
- **is_pattern**: Whether this is a reusable pattern/best practice (true/false)
- **cpython_related**: Mentions CPython compatibility (true/false)
- **has_code_suggestion**: Includes specific code example (true/false)

### Keywords
- **keywords**: JSON array of 2-5 technical terms for text search

## Recurring Patterns Identified

From 40 sample categorizations, **17 patterns** (42%) were reusable across multiple contexts:

### API Design Patterns
1. Use constructor arguments with sensible defaults
2. Use descriptive function names that explain purpose
3. Use MicroPython HAL abstraction functions for consistency
4. Clarify meaning of special values (like 0, -1, NULL)

### Code Style Patterns
5. Prefer bool over int for boolean values
6. Avoid negation in preprocessor conditionals (use positive logic)
7. Avoid goto statements, prefer fall-through logic
8. Wrap macro arguments in parentheses
9. Watch for macro double-evaluation side effects
10. Comment when intentionally discarding return values
11. Extract repeated code to helper functions

### Portability Patterns
12. Consider struct member alignment for cross-platform compatibility
13. Test on multiple platforms before assuming behavior

### Testing Patterns
14. Prefer generic tests that work on all boards over board-specific tests
15. Keep tests focused and separated
16. Ensure comprehensive test coverage before merge

### Documentation Patterns
17. Provide examples rather than just descriptions
18. Reference shared documentation instead of duplicating

## Lead Maintainer's Communication Style

### Characteristics
- **Terse and direct** - no unnecessary words
- **Technical precision** - specific about exactly what's wrong
- **Question-based** - often phrases suggestions as questions
- **Acknowledges uncertainty** - "I think", "Maybe", "Or am I wrong?"
- **Polite but firm** - "Please try to do that"
- **Provides rationale** - explains why a change matters
- **Includes code examples** - shows concrete alternatives

### Example Patterns
```
"this can just be a `bool`"
"Better to not use negation and change the logic to..."
"I think this function should be called X. Is that what it's doing?"
"To avoid labels and goto (which is nice if possible)..."
"Strange that it needs this... even with no optimisation..."
"Ah, I see, I didn't appreciate that..."
"Please use `mp_hal_pin_config(...)`"
```

### Rare Praise
- Usually minimal: "Ok!", "Thanks!", "Good!"
- Sometimes informational: "Thank you! And good to know about..."

## Technical Decision Log

### Database Schema Design

**Decision:** SQLite with relational structure
**Rationale:**
- Portable, no server required
- Complex queries for filtering by multiple dimensions
- Supports full-text search if needed later

**Tables:**
- `prs` - PR metadata (title, author, changed files, additions/deletions)
- `review_comments` - Inline code review comments with diff context
- `issue_comments` - General PR discussion comments
- `reviews` - Review verdicts (APPROVED, CHANGES_REQUESTED)
- `comment_categories` - Categorization metadata (13 fields)
- `domains` - Domain lookup table
- `sync_state` - Checkpoint tracking for resumable operations

### Categorization Approach

**Decision:** Use `claude -p` (headless mode) with JSON schema enforcement
**Rationale:**
- No API key management (uses Claude CLI auth)
- Structured output guaranteed via `--json-schema`
- Batch processing (20 comments per call reduces API overhead)
- Cost control via `--max-budget-usd`
- Uses Haiku model for cost efficiency

**Alternatives considered:**
1. Direct Anthropic API calls - requires API key, more boilerplate
2. Task agents in parallel - more complex, harder to checkpoint
3. Manual categorization - not feasible for 22,805 comments

### Schema Evolution

**Initial schema (4 fields):**
- domain, theme, severity, is_style_example

**Enhanced schema (13 fields):**
- Added component/port/subsystem for location context
- Added language_context/code_construct for technical context
- Added concern_type to capture nature of feedback
- Added feedback_type to distinguish questions/suggestions/requirements
- Added is_pattern flag for reusable patterns
- Added metadata flags (cpython_related, has_code_suggestion)
- Added keywords array for text search

**Rationale:**
- Need more dimensions for effective search when reviewing new PRs
- Original schema too coarse-grained for targeted queries
- Validated on 40 samples - all fields proved useful

### Search Use Cases

The enhanced schema enables queries like:

```sql
-- Find memory safety issues in extmod C code
SELECT * FROM comment_categories
WHERE component = 'extmod'
  AND language_context = 'c_code'
  AND concern_type = 'safety'

-- Get API design patterns for constructor functions
SELECT * FROM comment_categories
WHERE concern_type = 'api_design'
  AND is_pattern = 1
  AND code_construct = 'function'
  AND keywords LIKE '%constructor%'

-- Find port-specific UART driver feedback
SELECT * FROM comment_categories
WHERE subsystem = 'uart'
  AND port IS NOT NULL
  AND severity != 'nitpick'

-- Get best style examples on testing
SELECT * FROM comment_categories
WHERE domain = 'testing'
  AND is_style_example = 1
  AND feedback_type IN ('suggestion', 'requirement')
```

## Data Quality Observations

### Collection Reliability
- **Success rate:** 99.995% (1 HTTP 504 error out of ~22,168 API calls)
- **Missing data:** Reviews without comments (verdicts only)
- **Duplicate handling:** None found (GitHub IDs are unique)

### Comment Quality Distribution
From 40 samples:
- **Substantive technical feedback:** 60%
- **Process/merge comments:** 23%
- **Questions/discussion:** 17%

**Severity distribution:**
- Suggestions: 70%
- Blocking issues: 13%
- Nitpicks: 17%

**Code examples included:** 30%

### Schema Application Results

**Tested:** 40 random comments (mix of review, issue, and verdict comments)
**Success rate:** 100% - all comments categorizable
**Ambiguous fields:** <5% (mostly domain vs concern_type overlap)
**NULL values:** Appropriate (subsystem NULL in 46% of cases for general comments)

## Extending the Database

To add newer review data:

### 1. Collect New Reviews
```bash
source venv/bin/activate
python scripts/collect.py  # Incremental collection
```

### 2. Categorize New Comments
```bash
python scripts/categorize_headless.py  # Uses Claude CLI
```

### 3. Rebuild Vector Index
```bash
python scripts/build_index_resume.py  # Handles resume
```

See `CLAUDE.md` for detailed workflow documentation.

## Usage Examples

### CLI Tool

```bash
# Install the package
pip install -e .

# Show index statistics
mpy-reviewer stats

# Search for relevant reviews (semantic search)
mpy-reviewer search "memory allocation error handling" -k 10

# Search with filters
mpy-reviewer search "GPIO pin configuration" --component port_specific --domain api_design

# Generate review context for a PR
mpy-reviewer review --pr 17321

# Generate review context from a diff file
mpy-reviewer review --diff path/to/changes.diff

# Output as JSON for programmatic use
mpy-reviewer search "type checking" --json
```

### Python API

```python
from rag.retriever import search, find_similar

# Simple semantic search
results = search("memory allocation in C", top_k=10)

# Search with filters
results = search(
    "error handling",
    top_k=10,
    domain="correctness",
    component="py_core",
    severity="blocking"
)

# Find similar reviews for a code diff
diff_text = "..."  # Your diff content
results = find_similar(diff_text, top_k=8)
```

## Repository Structure

```
mpy-reviewer/
├── data/
│   └── reviews.db                   # SQLite database + vec0 index
├── rag/                             # RAG Python package
│   ├── cli.py                       # CLI entry point
│   ├── config.py                    # Configuration management
│   ├── embeddings.py                # CodeRankEmbed embeddings wrapper
│   ├── indexer.py                   # sqlite-vec index builder
│   ├── retriever.py                 # Hybrid search (dense + FTS)
│   ├── reranker.py                  # Cross-encoder re-ranking
│   └── ...                          # Other modules
├── scripts/
│   ├── collect.py                   # Data collection from GitHub
│   ├── categorize_headless.py       # Claude CLI categorization
│   ├── build_index_resume.py        # Resume-capable index builder
│   └── ...                          # Other utility scripts
├── docs/                            # Design docs and notes
├── pyproject.toml                   # Package configuration
├── CLAUDE.md                        # AI agent instructions
└── README.md                        # This file
```

## Technical Notes

### GitHub API Quirks
- Search API returns max 1000 results per query
- Solution: Query by year (2013-2025) to keep each under 1000
- Rate limit: 5000 requests/hour (we run at ~674 PRs/hour)

### Database Design Choices
- Store diff context with review comments for full context
- Keep original GitHub IDs for traceability
- Separate tables for different comment types (review vs issue vs verdict)
- Denormalized categories table for query performance

### Categorization Challenges
- Some comments are purely procedural (merges, closes)
- Determining is_pattern requires understanding broader context
- Domain vs concern_type has some overlap (acceptable)
- Keywords need guidelines for consistency

## Contributing

This is a personal research project for improving AI-assisted code review. The methodology and findings may be useful for similar projects analyzing maintainer feedback patterns.

## License

Data collected from public GitHub repository micropython/micropython.
Scripts and analysis tools: MIT License.

## Contact

Built for use with Claude Code for MicroPython development.
