# Multi-Agent Review - Phase 3: Rewrite Interactive Skill

**Part of:** MULTI_AGENT_REVIEW_PLAN.md
**Phase:** 3 of 5
**Estimated Time:** 2-3 hours

## Goal

Replace the RAG-based `skills/review/SKILL.md` in mpy-rules with a
multi-agent orchestration skill. The new skill launches 4 domain agents in
parallel via the Agent tool, collects findings, spawns a validation agent,
and presents results to the user.

## Prerequisites

- [ ] Phase 1 completed (prompt files in mpy-rules/prompts/)
- [ ] Phase 2 completed (post-review.py CLI works)
- [ ] Read /review-branch SKILL.md for orchestration patterns:
  `~/.claude/plugins/cache/planet-innovation-marketplace/software/1.1.0/skills/review-branch/SKILL.md`

## Files to Create

### `skills/review/SKILL.md` (in mpy-rules, replaces existing)

**Location:** `~/claude-mpy-marketplace/plugins/mpy-rules/skills/review/SKILL.md`

This file defines the interactive review workflow. It replaces the current
SKILL.md that lives in mpy-reviewer.

**Frontmatter:**
```yaml
---
name: mpy-review
description: Review MicroPython code changes using domain-focused agents.
  Invoke when user mentions reviewing code, wants feedback on MicroPython
  PRs/commits/diffs, or asks for code review.
---
```

**Orchestration workflow (modeled on /review-branch SKILL.md):**

**STEP 1: Detect context and gather diff**

Parse user request to determine what to review:
- "review my current branch" -> `git diff main`
- "review commit abc123" -> `git show abc123`
- "review PR 12345" -> `gh pr diff 12345`
- "review my changes to py/gc.c" -> `git diff main -- py/gc.c`

Gather metadata:
- Changed files list (`git diff --stat`)
- Commit log (`git log --oneline <base>..HEAD`)
- PR title/body if reviewing a PR
- Save full diff to temp file for agent reference

Detect MicroPython repo (check for `py/mpconfig.h`). If not in a
MicroPython repo, abort with clear message.

**STEP 2: Launch parallel review agents**

Resolve prompt directory: `${CLAUDE_PLUGIN_ROOT}/prompts` (or
`~/.claude/mpy-rules/` canonical path as fallback).

Read and verify all 5 prompt files exist:
- `shared-context.md`
- `correctness-safety.md`
- `resource-constraints.md`
- `api-portability.md`
- `conventions-completeness.md`

Launch 4 agents in a SINGLE Agent tool call (parallel execution).
Each agent receives:

1. Runtime context: base branch, changed files, commit log, diff file path,
   PR metadata if available
2. Read directives: "Read the following files before reviewing:
   `<prompt_dir>/shared-context.md` and `<prompt_dir>/<domain>.md`
   and `<rules_dir>/development-patterns.md`"
3. Codebase access: Read, Glob, Grep on the MicroPython repo, codanna MCP
4. The diff (either inline for small diffs or file path for large ones)
5. Output instruction: "Return findings as a JSON array"

Always specify `model='opus'` for review agents.

**STEP 3: Collect and validate findings**

Wait for all 4 agents to complete. Parse JSON findings from each.
Concatenate all findings with a `dimension` tag added to each
(correctness_safety, resource_constraints, api_portability,
conventions_completeness).

Launch 1 validation agent (separate Agent call to preserve orchestrator
context). The validation agent receives:
- All concatenated findings
- The full diff
- Read directive: `<prompt_dir>/finding-validation.md` and
  `<prompt_dir>/shared-context.md` and
  `<rules_dir>/development-patterns.md`
- Codebase access: Read, Glob, Grep, codanna

Always specify `model='opus'` for the validation agent.

**STEP 4: Present results**

Parse validation output. Build console summary:
- Validation stats (N KEEP, N QUESTIONABLE, N INVALID)
- All validated findings sorted by severity (blocking > suggestion > nitpick)
- QUESTIONABLE findings tagged with `[QUESTIONABLE]` and validation note
- INVALID findings omitted

Write full report to `/tmp/MPY_REVIEW_<timestamp>.md` with:
- Summary section
- Findings grouped by dimension
- Action items sorted by severity

Display merge readiness:
- READY -- no blocking findings
- READY WITH WARNINGS -- blocking findings are all QUESTIONABLE
- NOT READY -- confirmed blocking findings

**STEP 5: User next steps**

Offer options:
1. **Triage** -- walk through each finding, user decides include/skip/defer
2. **Plan all** -- include all KEEP + QUESTIONABLE findings
3. **Post to GitHub** -- if reviewing a PR, offer to post via post-review.py

If posting: assemble findings JSON, call post-review.py via Bash tool with
appropriate arguments.

## Files to Modify

### Remove old skill from mpy-reviewer

The old `skills/review/SKILL.md` at `~/mpy/dpgeorge-review-db/skills/review/`
is no longer needed once the mpy-rules skill is active. It can be deleted or
kept as a reference with a note that it's superseded.

## Codebase Patterns to Follow

**Pattern: /review-branch SKILL.md orchestration**
- Step-by-step workflow with clear phases
- Prompt directory resolution with verification
- Parallel agent launch in single tool call
- Validation as separate agent
- Console summary with severity-sorted findings
- Triage vs Plan All user choice
- Plan file generation -> EnterPlanMode

**Key differences from /review-branch:**
- MicroPython-specific: checks for py/mpconfig.h, reads CODECONVENTIONS.md
- 4 agents instead of 5 (no plan alignment agent -- could add later)
- Findings use MicroPython severity terms (blocking/suggestion/nitpick)
  instead of generic (CRITICAL/WARNING/INFO)
- Post-to-GitHub option via post-review.py CLI
- Development patterns loaded from rules/ directory

## Implementation Guidance

- Keep the SKILL.md focused on orchestration logic, not review criteria
  (that lives in the prompt files)
- The skill reads prompt files at runtime -- it does not inline their content
- Use `${CLAUDE_PLUGIN_ROOT}/prompts/` to reference prompt files
- For codanna access, agents need the codanna MCP -- the SessionStart hook
  already installs it
- Large diffs should be written to a temp file and the path passed to agents
  rather than inlining the full diff in each agent's prompt

## Testing Strategy

**What to Test:**
- Skill triggers on review-related user requests
- Correct diff generation for branches, commits, PRs, file-specific reviews
- All 4 agents spawn in parallel
- Validation agent runs after domain agents complete
- Findings are correctly parsed and presented
- Post-to-GitHub option works via post-review.py

**How to Test:**
- In a MicroPython repo, ask Claude to review current changes
- Verify agents spawn (check for parallel Agent tool calls in output)
- Verify findings are presented with correct severity sorting
- Test post-to-GitHub on a fork PR with --dry-run

**Success Criteria:**
- [ ] SKILL.md frontmatter has name: mpy-review
- [ ] Skill detects MicroPython repo correctly
- [ ] 4 domain agents launch in parallel
- [ ] Validation agent runs as separate agent
- [ ] Findings presented in severity order
- [ ] QUESTIONABLE findings are tagged
- [ ] Report written to /tmp/
- [ ] Post-to-GitHub option available for PR reviews

## Risks and Mitigations

- **Risk:** Agent tool may not support `model='opus'` parameter in all contexts
  - **Mitigation:** Test in actual Claude Code session; fall back to default
    model if parameter not supported

- **Risk:** Prompt file paths differ between plugin install and development
  - **Mitigation:** Use `${CLAUDE_PLUGIN_ROOT}` with fallback to
    `~/.claude/mpy-rules/` canonical path

## Next Steps

After completing this phase:
1. Test the full interactive flow in a MicroPython repo
2. Proceed to MULTI_AGENT_REVIEW_PHASE_4.md (bot orchestrator rewrite)
