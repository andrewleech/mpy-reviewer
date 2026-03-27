# Multi-Agent Review - Phase 4: Rewrite Bot Orchestrator

**Part of:** MULTI_AGENT_REVIEW_PLAN.md
**Phase:** 4 of 5
**Estimated Time:** 3-4 hours

## Goal

Rewrite `bot/orchestrator.py:run_review()` to spawn parallel `claude -p`
domain agents (sonnet) and a validation agent (opus) directly, replacing the
single-pass MCP-dependent approach. The bot posts results via `post-review.py`
CLI. No MCP server dependency for the review pipeline.

## Prerequisites

- [ ] Phase 1 completed (prompt files in mpy-rules submodule)
- [ ] Phase 2 completed (post-review.py CLI works)
- [ ] Phase 3 completed (interactive skill tested)
- [ ] Read `rag/verifier.py` for the subprocess spawning pattern
- [ ] Read current `bot/orchestrator.py` for checkout/diff/error handling

## Files to Modify

### `bot/orchestrator.py`

**Replace `run_review()` with multi-agent flow:**

The outer shell stays the same: PR metadata fetch, diff fetch, checkout update,
error handling, and reporting. The inner review logic changes completely.

**Current flow (to remove):**
1. Build system prompt via `bot/prompt.py`
2. Generate MCP config pointing to shared SSE server
3. Spawn single `claude -p` with MCP tools
4. That subprocess does everything (review_diff, verify_findings, post_review)

**New flow:**
1. Load prompt files from mpy-rules submodule path
2. Build per-agent prompts (shared-context + domain criteria + diff + metadata)
3. Spawn 4 `claude -p` domain agents in parallel (sonnet)
4. Collect JSON findings from each agent's stdout
5. Concatenate and tag findings by dimension
6. Spawn 1 `claude -p` validation agent (opus) with all findings + diff
7. Collect validated findings from stdout
8. Call `post-review.py` CLI to post to GitHub
9. Handle CI inspection (optional, can be a 6th agent or post-processing)

**Subprocess spawning pattern** (from `rag/verifier.py`):
```python
sem = asyncio.Semaphore(4)

async def _run_domain_agent(domain: str, prompt: str, diff_path: str) -> list[dict]:
    async with sem:
        cmd = [
            "claude", "-p",
            "--model", "sonnet",
            "--output-format", "json",
            "--json-schema", json.dumps(FINDINGS_SCHEMA),
            "--dangerously-skip-permissions",
            "--system-prompt", system_prompt,
            "--allowedTools", "Read,Glob,Grep",
        ]
        # ... spawn subprocess, pass user prompt via stdin, parse JSON output
```

**Key changes from current orchestrator:**
- No MCP config generation (`_build_mcp_config()` no longer needed for review)
- No single `claude -p` with MCP tools -- replaced by 5 focused subprocesses
- Prompt assembly reads from submodule files instead of importing from
  `rag.prompt_builder`
- `post-review.py` CLI replaces `post_review` MCP tool
- Each domain agent gets `--allowedTools Read,Glob,Grep` (plus codanna MCP
  if available in the Docker container)
- Validation agent gets the same tools

**Prompt assembly:**

For each domain agent, the system prompt is built by concatenating:
1. `mpy-rules/prompts/shared-context.md` (read from submodule)
2. `mpy-rules/rules/development-patterns.md` (read from submodule)

The user message contains:
1. The domain-specific criteria (from `mpy-rules/prompts/<domain>.md`)
2. PR metadata (title, body, commit messages)
3. The annotated diff (using `annotate_diff()` from `bot/prompt.py`)
4. Security delimiters around untrusted PR content

For the validation agent, the system prompt is:
1. `mpy-rules/prompts/shared-context.md`
2. `mpy-rules/prompts/finding-validation.md`

The user message contains:
1. All findings from domain agents (JSON array)
2. The annotated diff

**Error handling:**

If a domain agent fails (timeout, crash, malformed output):
- Log the failure
- Continue with findings from successful agents
- Include a note in the review summary: "N/4 review dimensions completed"

If the validation agent fails:
- Fall back to unvalidated findings (all treated as KEEP)
- Include a note: "Findings not cross-validated"

If post-review.py fails:
- Parse the JSON error from stderr
- If line_out_of_range: the orchestrator can retry without inline comments
- If auth_failed: raise ReviewError with appropriate user_message
- If other: log and raise generic ReviewError

### `bot/prompt.py`

**Changes:**
- Remove `build_system_prompt()` -- no longer needed (prompts read from files)
- Keep `build_user_message()` -- still needed for wrapping PR content
- Keep `annotate_diff()` -- still needed for line number annotation
- Keep `_sanitize_untrusted()` -- still needed for security
- Remove the lazy import of `rag.prompt_builder` (STYLE_GUIDE, REVIEW_GUIDANCE)
- The REVIEW_GUIDANCE and STYLE_GUIDE constants can be removed from
  `rag/prompt_builder.py` once this phase is complete (they live in
  `mpy-rules/prompts/shared-context.md` now)

### `bot/tests/test_orchestrator.py`

**Update tests:**
- Test multi-agent spawning (mock subprocess, verify 4 domain + 1 validation)
- Test finding collection and concatenation
- Test fallback when agents fail
- Test post-review.py invocation
- Remove tests that reference MCP config generation

### `bot/tests/test_prompt.py`

**Update tests:**
- Remove `test_system_prompt_includes_style_guide` (no more system prompt)
- Keep tests for `annotate_diff()` and `build_user_message()`

## Codebase Patterns to Follow

**Pattern: verifier.py subprocess management**
- `asyncio.Semaphore(MAX_PARALLEL)` for bounded concurrency
- `asyncio.gather(*coros, return_exceptions=True)` for parallel execution
- `asyncio.create_subprocess_exec` with stdout/stderr PIPE
- `asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)` for timeout
- Structured JSON output via `--output-format json --json-schema`
- Graceful handling of timeouts and non-zero exit codes

**Pattern: bot/orchestrator.py error hierarchy**
- `ReviewError` base class with `user_message` attribute
- Subclasses: `DiffTooLargeError`, `PromptTooLongError`, `RateLimitedError`,
  `ReviewTimeoutError`, `MetadataFetchError`, `EmptyDiffError`, `DiffFetchError`
- These are preserved -- the multi-agent flow raises the same errors

**Pattern: checkout management**
- `_update_checkout()` with flock serialization, fork detection, temporary
  remote management -- all preserved as-is

## Integration Points

- Reads prompt files from `mpy-rules/` submodule (path resolved via
  config or env var, default: `<repo_root>/mpy-rules/`)
- Calls `post-review.py` from the submodule's `scripts/` directory
- Docker container needs: claude CLI, codanna (optional), Python, git, gh
- The MicroPython checkout at `MPY_CHECKOUT` is passed as `cwd` to each
  `claude -p` subprocess

## Implementation Guidance

- Factor the multi-agent spawning into a separate function
  `_run_review_agents()` that returns consolidated findings. This keeps
  `run_review()` clean and testable.
- Factor the validation step into `_run_validation_agent()` similarly.
- Factor the posting step into `_post_review()` that calls the CLI script.
- The prompt file loading can be a helper that reads files from the submodule
  path and caches them (they don't change during a review).
- For codanna MCP access in Docker, the bot Dockerfile may need to configure
  a codanna MCP server. If codanna is not available, agents still work --
  they just can't do semantic code search (Read/Glob/Grep are sufficient
  for most verification).

## CI Inspection

The current flow has CI inspection as part of the single agent's workflow
(system prompt includes CI section, agent calls get_check_runs etc.). In the
new flow, CI inspection can be:

Option A: A 5th domain agent focused on CI (adds latency but is clean)
Option B: Post-processing in Python after the review (faster, but less smart)
Option C: Part of the conventions-completeness agent's scope (already has
  PR template and commit message checking)

Recommend Option C for now -- the conventions agent can be instructed to check
CI status via `gh` CLI calls if it has Bash access.

## Testing Strategy

**What to Test:**
- Multi-agent spawning: verify 4 domain + 1 validation subprocess calls
- Finding collection: mock agent output, verify JSON parsing
- Agent failure handling: mock timeout/crash for one agent, verify others proceed
- Validation failure handling: mock validation agent failure, verify fallback
- Post-review invocation: mock CLI call, verify arguments
- Full pipeline: mock all subprocesses, verify end-to-end flow
- Error propagation: verify ReviewError subclasses still work

**How to Test:**
- Unit tests with mocked `asyncio.create_subprocess_exec`
- Integration test: run against a real PR with `--dry-run` on post-review.py
- Docker test: rebuild containers, trigger webhook on test PR

**Success Criteria:**
- [ ] `run_review()` spawns 4 domain agents in parallel
- [ ] Domain agents use sonnet model
- [ ] Validation agent uses opus model
- [ ] Findings collected as JSON from each agent
- [ ] Failed agents don't block the review
- [ ] post-review.py called with correct arguments
- [ ] No MCP dependency in the review pipeline
- [ ] All existing bot tests pass (updated for new flow)
- [ ] ReviewError hierarchy still works

## Risks and Mitigations

- **Risk:** 5 subprocess spawns is more expensive than 1 (current)
  - **Mitigation:** Domain agents use sonnet (cheaper). The 4 domain agents
    run in parallel so wall-clock time may be similar. The validation agent
    is the only opus call.

- **Risk:** JSON output parsing from `claude -p` may be unreliable
  - **Mitigation:** Use `--json-schema` to enforce structure. Add robust
    parsing with fallback to empty findings list on malformed output.

- **Risk:** codanna not available in Docker container
  - **Mitigation:** Make codanna optional. Agents work with Read/Glob/Grep
    alone. Add codanna to Dockerfile as a non-blocking enhancement.

## Next Steps

After completing this phase:
1. Run full bot test against a test PR
2. Rebuild Docker containers and verify webhook flow
3. Proceed to MULTI_AGENT_REVIEW_PHASE_5.md (RAG retirement and cleanup)
