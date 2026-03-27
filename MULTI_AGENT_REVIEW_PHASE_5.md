# Multi-Agent Review - Phase 5: RAG Retirement and Documentation

**Part of:** MULTI_AGENT_REVIEW_PLAN.md
**Phase:** 5 of 5
**Estimated Time:** 2-3 hours

## Goal

Remove review tools from the MCP server, document the RAG tooling for future
maintenance, add the mpy-rules submodule reference, and update plugin/marketplace
versions. After this phase, the RAG database is a development/analysis tool
only, not a runtime dependency.

## Prerequisites

- [ ] Phases 1-4 completed and tested
- [ ] Bot review pipeline works without MCP server
- [ ] Interactive skill works without MCP tools

## Files to Modify

### `mcp_server.py`

**Remove review-specific tools:**
- `review_diff()` (lines 154-231)
- `review_pr()` (lines 234-349)
- `search_reviews()` (lines 352-409)
- `find_style_examples()` (lines 412-445)
- `get_review_stats()` (lines 448-460)
- `get_pr_review_history()` (lines 463-484)
- `verify_findings()` (lines 487-571)

**Keep triage tools:**
- `triage_issue()` (lines 599-702)
- `search_issues()` (lines 705-744)

**Remove review-related singletons:**
- `_retriever` and `_get_retriever()` (lines 88-101)
- `_builder` and `_get_builder()` (lines 104-109)

**Keep triage singletons:**
- `_triage_retriever` and `_get_triage_retriever()` (lines 577-588)
- `_triage_builder` and `_get_triage_builder()` (lines 591-597)

**Update server description:**
- Change `instructions` parameter to reference triage only

**Update __main__ block:**
- Keep bot tool registration (bot.mcp_tools still used for triage bot)
- Keep triage tool registration

### `mcp_proxy.py`

The proxy is still needed if the triage tools use the shared retriever
(which loads embeddings). If triage has its own separate database and model,
the proxy could be simplified. For now, keep as-is.

### `.mcp.json`

Update to reflect that the MCP server now only provides triage tools.
Consider whether the plugin should still register an MCP server at all --
if the review skill no longer needs MCP, and triage is separate, the
`.mcp.json` may be better moved to the mpy-reviewer bot repo only.

### `bot/prompt.py`

**Remove dead code:**
- Remove `build_system_prompt()` if Phase 4 eliminated its usage
- Remove the `from rag.prompt_builder import REVIEW_GUIDANCE, STYLE_GUIDE`
  lazy import
- Keep `build_user_message()`, `annotate_diff()`, `_sanitize_untrusted()`

### `rag/prompt_builder.py`

**Preserve but mark as legacy:**
- Add a docstring note: "Legacy prompt builder. STYLE_GUIDE and REVIEW_GUIDANCE
  have been extracted to mpy-rules/prompts/shared-context.md. This module is
  retained for the CLI tool and direct Python API access."
- Keep `STYLE_GUIDE` and `REVIEW_GUIDANCE` constants for backward compatibility
  with the CLI tool (`uv run mpy-reviewer review`)

## Files to Create

### `rag/README.md`

Documentation for the RAG tooling. Must cover:

**What it is:**
- ~19.5K categorized review comments from the MicroPython lead maintainer
- 768-dim CodeRankEmbed embeddings in sqlite-vec virtual table
- 13-field categorization schema (domain, severity, component, theme, etc.)
- Hybrid dense+FTS5 search with heuristic boosting
- Full-text search via FTS5 contentless table

**How it was built (3-stage pipeline):**
1. Collect: `scripts/collect.py` fetches PR metadata and review comments
   from GitHub API. Targets the `dpgeorge` reviewer on
   `micropython/micropython` and `micropython/micropython-lib`.
2. Categorize: `scripts/categorize_headless.py` classifies each comment
   using Claude CLI with a 13-field JSON schema.
3. Index: `scripts/build_index_resume.py` generates CodeRankEmbed embeddings
   and builds the sqlite-vec + FTS5 index. Resume-capable (safe to interrupt).

**How to update:**
```bash
# 1. Collect new reviews (incremental, skips existing)
uv run python scripts/collect.py

# 2. Categorize uncategorized comments
uv run python scripts/categorize_headless.py

# 3. Rebuild index (resume-capable)
uv run python scripts/build_index_resume.py

# 4. Verify
uv run mpy-reviewer stats
```

**How to regenerate development patterns:**
```bash
# Run clustering with LLM distillation
uv run python scripts/extract_patterns.py --output mpy-rules/rules/development-patterns.md

# Or heuristic mode (no Claude CLI needed)
uv run python scripts/extract_patterns.py --skip-llm --output /tmp/patterns_draft.md
```

**How to query:**
```bash
# CLI search
uv run mpy-reviewer search "memory allocation" --domain memory -k 10

# Index statistics
uv run mpy-reviewer stats

# Direct SQL
sqlite3 data/reviews.db "SELECT COUNT(*) FROM comment_categories"
```

**Current statistics** (reference `docs/author_checklist.md` for cluster data):
- Total indexed records: ~19,465
- Repos: micropython/micropython (5,646 PRs), micropython/micropython-lib (252 PRs)
- Domain distribution, severity distribution (reference CLAUDE.md)

### Submodule setup

Add mpy-rules as a git submodule:
```bash
cd ~/mpy/dpgeorge-review-db
git submodule add ../claude-mpy-marketplace/plugins/mpy-rules mpy-rules
# Or if using GitHub:
git submodule add https://github.com/andrewleech/claude-mpy-marketplace.git mpy-rules
```

The bot Dockerfile needs to initialize submodules:
```dockerfile
RUN git submodule update --init
```

### Plugin version updates

**mpy-rules plugin.json:** Bump to 0.4.0 (adds prompts/ directory and
review skill)

**marketplace.json:** Update mpy-rules version to 0.4.0, update description
to mention multi-agent review

**mpy-reviewer plugin.json (if applicable):** Update to reflect that the
review pipeline no longer lives here

### Docker updates

**bot/Dockerfile:**
- Remove: any reference to embedding model download or sqlite-vec for review
  (keep if triage still needs it)
- Add: codanna installation (optional, for agent codebase access)
- Add: submodule initialization
- Keep: claude CLI, gh CLI, git, Python dependencies for bot

**bot/docker-compose.yml:**
- Remove: `hf-cache` volume if no longer needed for review (check triage)
- Keep: mpy-checkout volume, token-share, review-tmp

## Integration Points

- The `rag/` package is still importable for CLI usage and triage
- The `mcp_server.py` still runs for triage tools
- The bot reads prompts from `mpy-rules/` submodule
- The `scripts/extract_patterns.py` outputs to `mpy-rules/` submodule path

## Testing Strategy

**What to Test:**
- MCP server starts with triage tools only (no review tools)
- `uv run mpy-reviewer stats` still works (RAG CLI preserved)
- `uv run mpy-reviewer search` still works
- Bot review pipeline works end-to-end without MCP
- Docker containers build and run
- Triage bot still functions (triage_issue, search_issues via MCP)

**How to Test:**
- Start MCP server, verify only triage tools are listed
- Run CLI commands to verify RAG tooling still functional
- Trigger review webhook on test PR
- Trigger triage webhook on test issue

**Success Criteria:**
- [ ] MCP server has no review tools
- [ ] Triage tools still work via MCP
- [ ] RAG CLI (search, stats) still works
- [ ] rag/README.md documents full pipeline
- [ ] mpy-rules submodule added and bot reads from it
- [ ] Docker containers build and deploy
- [ ] Plugin versions bumped
- [ ] No broken imports or dead code paths

## Risks and Mitigations

- **Risk:** Triage tools share retriever infrastructure with review tools
  - **Mitigation:** Triage has its own `_triage_retriever` singleton.
    Verify it works independently after review retriever is removed.

- **Risk:** Removing review tools breaks existing plugin installations
  - **Mitigation:** Version bump signals breaking change. Document
    migration in changelog.

- **Risk:** Submodule adds complexity to bot deployment
  - **Mitigation:** Simple `git submodule update --init` in Dockerfile.
    Pin to specific commit/tag for stability.

## Next Steps

After completing this phase:
1. Run full end-to-end test of both bot and interactive paths
2. Compare review quality: old RAG pipeline vs new multi-agent pipeline
   on the same PR
3. Monitor first few bot reviews for quality and false positive rate
4. Consider adding CI inspection as a 5th domain agent if needed
