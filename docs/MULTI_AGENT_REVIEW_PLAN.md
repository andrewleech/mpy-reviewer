# Multi-Agent Review Implementation Plan

**Spec Source:** MULTI_AGENT_REVIEW_SPEC.md
**Complexity Assessment:** Complex
**Estimated Phases:** 5
**Generated:** 2026-03-27

## Overview

Replace the RAG-driven single-pass review pipeline with a multi-agent
architecture. Four domain-focused review agents run in parallel, followed by a
validation agent that consolidates and verifies findings. Review knowledge is
delivered via static rules (`development-patterns.md`) rather than runtime
embedding search. The same prompt files are shared between the GitHub bot
(spawns `claude -p` subprocesses) and the interactive Claude Code skill
(spawns Agent subagents).

## Codebase Analysis

### Current Architecture

The review pipeline has two entry points:

1. **Bot path**: `bot/orchestrator.py:run_review()` assembles prompts via
   `bot/prompt.py`, generates MCP config pointing to the shared SSE server,
   and spawns a single `claude -p` subprocess. That subprocess uses MCP tools
   (`review_diff`, `verify_findings`, `post_review`) to complete the review.

2. **Interactive path**: `skills/review/SKILL.md` instructs Claude to call
   MCP tools (`review_diff`/`review_pr`) or fall back to the CLI
   (`uv run mpy-reviewer review`). Both paths hit the same RAG retriever.

Both paths depend on:
- `rag/prompt_builder.py` -- STYLE_GUIDE (lines 32-100) and REVIEW_GUIDANCE
  (lines 104-146), plus prompt assembly
- `rag/retriever.py` -- hybrid dense+FTS search via CodeRankEmbed embeddings
- `rag/verifier.py` -- parallel `claude -p` subprocess spawning with
  asyncio.Semaphore (the pattern to replicate)
- `mcp_server.py` -- FastMCP server with review, triage, and bot tools
- `mcp_proxy.py` -- stdio-to-SSE proxy for shared model loading

### Integration Points

- `bot/orchestrator.py` -- Needs rewrite of `run_review()` to spawn
  domain agents directly instead of delegating to MCP
- `bot/prompt.py` -- STYLE_GUIDE/REVIEW_GUIDANCE imports from
  `rag.prompt_builder` need to move to file reads from submodule
- `bot/mcp_tools.py` -- `post_review()`, `get_check_runs()`,
  `get_check_run_annotations()`, `get_workflow_run_log()` need to become
  CLI scripts or stay bot-internal
- `mcp_server.py` -- Review tools (review_diff, review_pr, verify_findings,
  search_reviews, find_style_examples, get_review_stats, get_pr_review_history)
  to be removed; triage tools (triage_issue, search_issues) to remain
- `skills/review/SKILL.md` -- Complete rewrite for multi-agent orchestration

### Existing Patterns to Follow

- **Multi-subprocess spawning**: `rag/verifier.py` uses
  `asyncio.Semaphore(4)` + `asyncio.gather(*coros, return_exceptions=True)`
  for bounded parallel `claude -p` invocations. Each subprocess gets
  `--output-format json`, `--json-schema`, `--allowedTools`,
  `--dangerously-skip-permissions`.

- **Rule file delivery**: `mpy-rules/scripts/setup-rules.sh` copies canonical
  rule files to `~/.claude/mpy-rules/` and symlinks into `.claude/rules/` for
  MicroPython repos. New prompt files should follow this pattern.

- **/review-branch skill**: Multi-agent orchestration with 4-5 parallel agents
  launched via Agent tool with `model='opus'`. Each agent reads
  `shared-context.md` + dimension-specific prompt. Validation agent does a
  second pass annotating findings as KEEP/QUESTIONABLE/INVALID.

### Potential Challenges

- **Bot subprocess environment**: Each `claude -p` subprocess needs codanna
  MCP access. The bot Docker container must have codanna installed and the
  MicroPython checkout available at a known path.

- **Prompt size management**: The diff + development-patterns.md + style guide +
  domain criteria may be large for big PRs. Need to handle gracefully
  (truncation or splitting).

- **JSON output parsing**: Domain agents must produce structured JSON findings.
  Need a schema and robust parsing with fallback for malformed output.

- **Submodule sync**: The bot's mpy-rules submodule must be kept in sync with
  the plugin repo. CI or deployment scripts should update it.

## Phase Overview

### Phase 1: Create Prompt Files in mpy-rules
**Goal:** Extract STYLE_GUIDE and REVIEW_GUIDANCE from rag/prompt_builder.py
into standalone markdown files. Create the 4 domain agent prompts, the shared
context, and the validation agent prompt.
**Details:** See MULTI_AGENT_REVIEW_PHASE_1.md

### Phase 2: Create post-review CLI Script
**Goal:** Replace the `post_review` MCP tool with a standalone Python CLI
script that accepts findings as JSON and posts a GitHub PR review.
**Details:** See MULTI_AGENT_REVIEW_PHASE_2.md

### Phase 3: Rewrite Interactive Skill
**Goal:** Replace the RAG-based SKILL.md with a multi-agent orchestration
skill that launches domain agents in parallel and validates findings.
**Details:** See MULTI_AGENT_REVIEW_PHASE_3.md

### Phase 4: Rewrite Bot Orchestrator
**Goal:** Replace `run_review()` to spawn parallel `claude -p` domain agents
and a validation agent, then post results via the CLI script.
**Details:** See MULTI_AGENT_REVIEW_PHASE_4.md

### Phase 5: RAG Retirement and Documentation
**Goal:** Remove review tools from MCP server, document RAG tooling for
future maintenance, add submodule reference, update plugin version.
**Details:** See MULTI_AGENT_REVIEW_PHASE_5.md

## Testing Approach

### Unit Tests
- post-review.py: mock GitHub API responses, test line validation logic,
  test error message formatting, test JSON input parsing
- Bot orchestrator: mock subprocess spawning, test finding collection and
  consolidation, test error handling for agent failures

### Integration Tests
- Bot path: run orchestrator against a known PR with mocked claude -p output,
  verify the full flow from diff to posted review
- Interactive path: trigger /mpy-review in a Claude Code session, verify
  agents spawn and findings are presented

### Manual Testing
- Review the same PR with both old and new pipelines, compare finding quality
- Test bot Docker deployment with updated orchestrator
- Test plugin installation in fresh Claude Code session

## Success Criteria

- [ ] 6 prompt files exist in mpy-rules/prompts/ (shared-context, 4 domain, validation)
- [ ] post-review.py CLI works standalone with GitHub App token auth
- [ ] /mpy-review skill launches 4 parallel agents + validation in Claude Code
- [ ] Bot orchestrator spawns 5 claude -p subprocesses and posts review
- [ ] MCP server has no review tools, only triage tools remain
- [ ] RAG tooling documented in rag/README.md
- [ ] mpy-rules submodule added to mpy-reviewer repo
- [ ] Plugin version bumped, marketplace entry updated

## Next Steps

1. Read this plan and the original spec (MULTI_AGENT_REVIEW_SPEC.md)
2. Start with Phase 1: MULTI_AGENT_REVIEW_PHASE_1.md
3. After each phase, test before proceeding to next phase
