# Multi-Agent Review Architecture Specification

## Overview

Replace the RAG-driven single-pass review pipeline with a multi-agent approach
where domain-focused review agents run in parallel, followed by a validation
agent that consolidates and filters findings. The review knowledge previously
extracted at runtime via embedding search is now baked into static rules
(`development-patterns.md`) distilled from ~19.5K categorized review comments.

## Goals

- Remove the embedding model, SQLite-vec database, and MCP proxy from the
  review pipeline's runtime dependencies
- Improve review quality through domain-focused agents that go deep on their
  area rather than one agent covering everything superficially
- Reduce false positives via a validation agent that checks findings against
  the actual codebase and filters noise
- Share prompts and tooling between the GitHub bot and interactive Claude Code
  plugin -- same review logic, different execution mechanisms
- Keep the RAG database and tooling available for future rule extraction and
  analysis, but not as a runtime dependency

## Deployment Contexts

### Bot Path (GitHub webhook)

The Python orchestrator (`bot/orchestrator.py`) manages the outer shell: git
checkout, diff fetching, error handling, and posting results to GitHub. It
spawns `claude -p` subprocesses directly for each review agent.

```
bot/orchestrator.py (Python)
  ├── spawn 4x claude -p domain agents in parallel (sonnet)
  ├── collect structured findings from stdout
  ├── spawn 1x claude -p validation agent (opus)
  ├── collect validated findings
  └── call post-review CLI script to post to GitHub
```

No MCP server involved. Parallelism managed via `asyncio.Semaphore` as the
current `verifier.py` already does.

### Interactive Path (Claude Code plugin/skill)

The Claude Code session acts as orchestrator. It spawns subagents via the
Agent tool.

```
Claude Code session (orchestrator, context preserved)
  ├── spawn 4x Agent subagents in parallel (opus)
  ├── collect structured findings
  ├── spawn 1x Agent validation subagent (opus, separate to preserve context)
  └── present findings to user (triage or plan)
```

Same prompts as the bot path. Different execution mechanism (Agent tool vs
`claude -p` subprocess) and model tier (opus vs sonnet for domain agents).

## Review Dimensions

Four domain-focused agents, each receiving the full diff, development patterns
rules, style guide, and read-only access to the MicroPython checkout.

### Agent 1: Correctness & Safety

- Macro argument parenthesization and type safety
- ISR context verification (RTOS primitives, no allocations in handlers)
- NULL pointer guards, check ordering in compound conditions
- Integer overflow in timer/PWM/tick calculations
- Interrupt handler conflicts with new read/write code
- Tick counter overflow handling (subtraction-based comparison)
- Error handling: specific errno constants, meaningful error sources
- Soft reset heap state, scheduler atomicity

### Agent 2: Resource Constraints

- Code size impact across port builds (bare-arm, minimal, unix, stm32)
- `MP_OBJ_NEW_SMALL_INT()` vs `mp_obj_new_int()` for heap avoidance
- `m_new`/`m_del` usage, GC-scanned memory for external pointers
- Struct packing, `const` for flash-resident data
- Qstr minimization, underscore-prefixed internal constants
- Allocations in hot paths, loop-invariant hoisting
- Performance benchmark expectations

### Agent 3: API & Portability

- CPython compatibility for module signatures and behavior
- Cross-port parameter naming consistency
- Abstraction layers over HAL, no direct HAL calls in extmod/py
- Stable enum values for ABI compatibility
- `mp_obj_get_array()` for sequence flexibility, `mp_obj_is_true()` for booleans
- Avoid unnecessary wrapper classes
- Board config directness (no intermediate config variables)
- Unimplemented methods must raise, not return stubs

### Agent 4: Conventions & Completeness

- `CODECONVENTIONS.md` compliance (formatting, naming, style)
- Commit message format: subject regex, component prefix rules, Signed-off-by,
  body line length, accuracy of description vs actual changes
- PR template compliance (Summary, Testing, Trade-offs sections)
- MIT license headers on new files, copyright attribution
- Documentation accuracy (MicroPython vs CPython behavior)
- Test coverage, hardware testing confirmation
- Cosmetic vs functional change separation
- Generated files in `$(BUILD)/`, offline builds, no redundant config defaults

## Agent Context

Every agent (domain and validation) receives:

1. **Development patterns** -- full `development-patterns.md` from the
   mpy-rules plugin (loaded from `~/.claude/mpy-rules/development-patterns.md`
   or the submodule path)
2. **Style guide** -- tone, brevity, severity markers, opening patterns,
   anti-patterns. Guides both what to look for and how to phrase findings.
3. **Review guidance** -- project values (code quality, small binary size,
   runtime efficiency), pre-review checks, suggestion block format
4. **The diff** -- full unified diff of the PR/branch
5. **PR metadata** -- title, body, commit messages (when available)
6. **Tool access** -- Read, Glob, Grep on the MicroPython checkout + codanna
   MCP for semantic code search

Development patterns and style guide are sourced from the mpy-rules plugin
to inherit updates automatically.

## Model Assignments

| Agent | Bot (GitHub) | Interactive (Claude Code) |
|-------|-------------|--------------------------|
| 4x domain review agents | sonnet | opus |
| 1x validation agent | opus | opus |

## Validation Agent

A single agent that receives all findings from the 4 domain agents plus the
full diff and codebase access. Performs both consolidation and per-finding
verification in one pass.

### Consolidation (cross-agent)

- **Deduplication** -- merge findings from different agents targeting the same
  code location with the same concern
- **Contradiction detection** -- when agents recommend opposite actions for
  the same code, keep the stronger justification, mark the other questionable
- **Flip-flop detection** -- findings where implementing the recommendation
  would create an equally valid finding in the opposite direction
- **Severity calibration** -- adjust severity based on cross-agent consensus

### Per-finding verification (codebase)

- **Correctness check** -- read the cited file and line, verify the finding
  describes something that actually exists in the diff
- **Convention check** -- read 3-5 adjacent files to verify whether the
  reviewed code matches or deviates from project convention
- **Relevance filter** -- remove findings that restate obvious trade-offs
  without concrete risk

### Verdict states

- **KEEP** -- correct, relevant, actionable
- **QUESTIONABLE** -- valid but ambiguous (flip-flop, style call, weak
  contradiction). Included in output with flag and reasoning.
- **INVALID** -- incorrect, irrelevant, or contradicts project convention.
  Removed from output.

### Output format

```
[KEEP|QUESTIONABLE|INVALID] [SEVERITY] **Title** -- file:line -- commit: <hash>
Description.
Validation note: <reasoning, 1-2 sentences>
```

## GitHub Posting (Bot Path)

A Python CLI script (`post-review`) replaces the `post_review` MCP tool.
The validation agent calls it via Bash with structured arguments.

The script:
- Accepts findings as JSON on stdin or via file path
- Authenticates via GitHub App token (from env or token file)
- Validates line numbers are within the diff range
- Posts a single PR review with summary body + inline comments
- Returns structured error messages the agent can act on
  (e.g. "line 42 outside diff range for file.c, valid range 10-38")
- Exits 0 on success, non-zero with JSON error detail on failure

## Repository Structure

### mpy-rules (`~/claude-mpy-marketplace/plugins/mpy-rules/`)

Shared review prompts, rules, skill, and CLI tooling. Delivered as a Claude
Code plugin.

```
mpy-rules/
├── .claude-plugin/
│   └── plugin.json
├── hooks/
│   └── hooks.json                  # SessionStart: setup-rules.sh
├── rules/
│   ├── core.md                     # Build, test, format, commit rules
│   ├── architecture.md             # MicroPython architecture guide
│   ├── pr-workflow.md              # PR description and workflow rules
│   └── development-patterns.md     # Distilled review patterns
├── skills/
│   └── review/
│       └── SKILL.md                # Interactive /mpy-review skill
├── prompts/
│   ├── shared-context.md           # Review stance + style guide + guidance
│   ├── correctness-safety.md       # Agent 1 criteria
│   ├── resource-constraints.md     # Agent 2 criteria
│   ├── api-portability.md          # Agent 3 criteria
│   ├── conventions-completeness.md # Agent 4 criteria
│   └── finding-validation.md       # Validation agent criteria
├── scripts/
│   ├── setup-rules.sh              # Rule file deployment hook
│   └── post-review.py              # GitHub review posting CLI
└── README.md
```

### mpy-reviewer (`~/mpy/dpgeorge-review-db/`)

Bot orchestration, RAG tooling, and triage system.

```
mpy-reviewer/
├── bot/
│   ├── orchestrator.py             # Spawns claude -p agents, manages flow
│   ├── webhook_service.py          # GitHub webhook handler
│   ├── review_queue.py             # Serialized review queue
│   ├── prompt.py                   # Bot-specific prompt assembly (reads from submodule)
│   ├── config/                     # Bot deployment config
│   └── tests/
├── triage/                         # Issue triage system (unchanged)
├── rag/                            # RAG tooling (development/analysis use)
│   ├── README.md                   # Documentation: what it is, how to update
│   ├── embeddings.py
│   ├── retriever.py
│   ├── indexer.py
│   ├── prompt_builder.py           # Legacy prompt builder
│   ├── config.py
│   └── ...
├── scripts/
│   ├── extract_patterns.py         # Cluster analysis -> development-patterns.md
│   ├── collect.py                  # GitHub API data collection
│   ├── categorize_headless.py      # Claude CLI categorization
│   ├── build_index_resume.py       # Vector index builder
│   └── ...
├── data/
│   └── reviews.db                  # SQLite + vec0 database
├── mpy-rules/                      # Git submodule -> mpy-rules repo
├── docs/
│   ├── RAG_ARCHITECTURE.md         # How the RAG system works
│   ├── DATA_PIPELINE.md            # Collection -> categorization -> indexing
│   ├── author_checklist.md         # Raw extract_patterns.py output
│   └── ...
└── pyproject.toml
```

The bot reads prompts from `mpy-rules/` submodule. The plugin delivers them
directly.

## RAG Tooling Documentation

The RAG database and tooling remain in mpy-reviewer but are no longer runtime
dependencies. They serve as the development pipeline for extracting and
updating the static rules. Documentation must cover:

- **What it is** -- 19.5K categorized review comments with 768-dim embeddings,
  13-field categorization schema, hybrid dense+FTS search
- **How it was built** -- 3-stage pipeline: collect (GitHub API) -> categorize
  (Claude CLI) -> index (CodeRankEmbed + sqlite-vec)
- **How to update** -- re-run collection for new PRs, categorize new comments,
  rebuild index, re-run extract_patterns.py to regenerate development-patterns.md
- **How to query** -- CLI (`mpy-reviewer search/stats`), Python API, direct
  SQLite queries
- **Current statistics** -- record counts, domain/severity distributions,
  index metadata

## Migration Path

1. Create prompt files in mpy-rules (shared-context, 4 domain prompts,
   validation prompt)
2. Create post-review.py CLI script in mpy-rules
3. Update SKILL.md in mpy-rules for the multi-agent interactive flow
4. Update bot/orchestrator.py to spawn parallel claude -p agents using
   prompts from submodule
5. Remove review_diff, verify_findings from mcp_server.py
6. Add submodule reference in mpy-reviewer
7. Write RAG documentation (RAG_ARCHITECTURE.md, update DATA_PIPELINE.md)
8. Move RAG-only MCP tools to optional/separate entry point
9. Test both paths end-to-end

## Testing Strategy

- Unit tests for post-review.py (mock GitHub API, test line validation,
  error formatting)
- Integration test: run bot orchestrator against a known PR, verify agent
  spawning and finding collection
- Comparison test: review the same PR with old RAG pipeline and new
  multi-agent pipeline, compare finding quality
- Interactive test: trigger /mpy-review in Claude Code session, verify
  agent spawning via Agent tool and finding presentation
