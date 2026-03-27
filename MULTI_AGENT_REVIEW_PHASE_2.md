# Multi-Agent Review - Phase 2: Create post-review CLI Script

**Part of:** MULTI_AGENT_REVIEW_PLAN.md
**Phase:** 2 of 5
**Estimated Time:** 2-3 hours

## Goal

Create a standalone Python CLI script that accepts validated review findings
as JSON and posts a GitHub PR review with summary body + inline comments.
Replaces the `post_review` MCP tool from `bot/mcp_tools.py`. The script is
called by the validation agent (bot path) or by the interactive skill.

## Prerequisites

- [ ] Phase 1 completed (prompt files exist)
- [ ] Read `bot/mcp_tools.py` lines 88-192 (`post_review()` function)
- [ ] Read `bot/mcp_tools.py` lines 195-438 (CI tools for reference)
- [ ] Understand GitHub PR review API:
  `POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews`

## Files to Create

### `scripts/post-review.py` (in mpy-rules)

**Location:** `~/claude-mpy-marketplace/plugins/mpy-rules/scripts/post-review.py`

**CLI interface:**
```bash
# Read findings from file
post-review --repo micropython/micropython --pr 12345 \
  --findings findings.json --token-file /var/run/token/github_token

# Read findings from stdin
cat findings.json | post-review --repo micropython/micropython --pr 12345

# With explicit diff for line validation
post-review --repo micropython/micropython --pr 12345 \
  --findings findings.json --diff pr.diff
```

**Arguments:**
- `--repo` (required): GitHub repository slug (owner/name)
- `--pr` (required): PR number
- `--findings` (optional): path to JSON findings file (default: stdin)
- `--diff` (optional): path to diff file for line range validation
- `--token-file` (optional): path to file containing GitHub token
- `--token` (optional): GitHub token directly (env `GITHUB_TOKEN` as fallback)
- `--dry-run` (optional): print what would be posted without posting
- `--head-sha` (optional): pin review to specific commit

**Input JSON format:**
```json
{
  "summary": "Review summary text (markdown)",
  "findings": [
    {
      "file": "py/gc.c",
      "line": 42,
      "side": "RIGHT",
      "severity": "blocking",
      "title": "Missing NULL check",
      "body": "Comment text (markdown)",
      "status": "KEEP"
    }
  ]
}
```

Only findings with `status: "KEEP"` are posted. `QUESTIONABLE` findings are
posted with a `[Questionable]` prefix. `INVALID` findings are skipped.

**Behavior:**

1. Parse and validate input JSON
2. If `--diff` provided, validate each finding's line is within the diff
   range for its file. Report specific errors:
   ```json
   {"error": "line_out_of_range", "file": "py/gc.c", "line": 42,
    "valid_range": [10, 38], "message": "line 42 outside diff range for py/gc.c, valid range 10-38"}
   ```
3. Build review body from summary + finding count by severity
4. Build comments array from findings
5. POST to GitHub API: create review with `event: "COMMENT"`
6. Handle 422 errors (comments outside diff): retry with body-only review,
   report rejected comments in output
7. Output result JSON to stdout:
   ```json
   {"review_id": 12345, "comment_count": 8, "rejected_comments": []}
   ```
   or on error:
   ```json
   {"error": "auth_failed", "message": "GitHub token is invalid or expired"}
   ```

**Error handling:**
- Exit 0 on success (JSON result on stdout)
- Exit 1 on validation error (JSON error on stdout, human message on stderr)
- Exit 2 on GitHub API error (JSON error on stdout)
- All errors are structured JSON so the calling agent can parse and act on them

**Auth:**
- GitHub App installation token (from `--token-file` or `--token` or
  `GITHUB_TOKEN` env var)
- Uses `urllib.request` (no external dependencies) or `gh api` as fallback

## Codebase Patterns to Follow

**Pattern: post_review() from bot/mcp_tools.py (lines 88-192)**
- Deletes stale PENDING reviews before creating new one
- Creates review with `event: "COMMENT"` and `comments` array
- On 422: retries without inline comments, reports rejected ones
- Returns structured dict with review_id, comment_count, or error

**Pattern: annotate_diff() from bot/prompt.py (lines 206-248)**
- Parses unified diff to determine valid line ranges per file
- Maps hunk headers `@@ -L,N +R,M @@` to line number ranges
- This logic is needed for the `--diff` line validation feature

**Pattern: structured error output from rag/verifier.py**
- JSON on stdout for machine parsing
- Human-readable on stderr for debugging
- Non-zero exit codes for different failure categories

## Integration Points

- Called by the validation agent via Bash tool in both bot and interactive paths
- The bot's Python orchestrator may also call it directly after collecting
  validated findings (bypassing the agent for the posting step)
- Must work standalone (no imports from mpy-reviewer or rag packages)
- No MCP dependency -- pure CLI with GitHub REST API calls

## Implementation Guidance

- Use `click` for CLI argument parsing (consistent with mpy-reviewer scripts)
- Use `urllib.request` for GitHub API calls (no requests dependency needed)
- The diff line validation logic can be extracted from `bot/prompt.py`
  `annotate_diff()` -- parse hunk headers to build {file: (start, end)} map
- Keep the script self-contained: no imports from rag/ or bot/ packages
- Add a shebang and make executable: `#!/usr/bin/env python3`

## Testing Strategy

**What to Test:**
- JSON input parsing (valid, malformed, missing fields)
- Line range validation against a sample diff
- GitHub API call construction (mock the HTTP request)
- 422 retry logic (mock the 422 response)
- Error output format (structured JSON on stdout)
- Dry-run mode (no HTTP calls, print what would be posted)
- Auth resolution order: --token-file > --token > GITHUB_TOKEN env

**How to Test:**
- Unit tests with mocked HTTP responses
- Manual test: `--dry-run` against a real PR to verify output format
- Integration test: post to a test PR on a fork

**Success Criteria:**
- [ ] Script runs standalone with no mpy-reviewer dependencies
- [ ] Accepts findings JSON from file or stdin
- [ ] Validates line ranges when --diff provided
- [ ] Posts review with inline comments to GitHub
- [ ] Handles 422 gracefully (retry without comments)
- [ ] Structured JSON output on success and failure
- [ ] --dry-run mode works
- [ ] Error messages are specific enough for an agent to correct and retry

## Risks and Mitigations

- **Risk:** GitHub API rate limiting during testing
  - **Mitigation:** Use --dry-run for development, test against fork

- **Risk:** Comment line number mapping differs between GitHub API and diff format
  - **Mitigation:** Study GitHub's pull review API docs carefully -- the `line`
    field uses the diff's new-file line number, `side: RIGHT` for additions

## Next Steps

After completing this phase:
1. Test with `--dry-run` against a real PR
2. Proceed to MULTI_AGENT_REVIEW_PHASE_3.md (interactive skill rewrite)
