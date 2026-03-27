# Multi-Agent Review - Phase 1: Create Prompt Files

**Part of:** MULTI_AGENT_REVIEW_PLAN.md
**Phase:** 1 of 5
**Estimated Time:** 2-3 hours

## Goal

Create the 6 prompt files that define the review agents' behavior. Extract the
existing STYLE_GUIDE and REVIEW_GUIDANCE from `rag/prompt_builder.py` into
standalone markdown. Write 4 domain agent prompts and 1 validation agent
prompt, all tailored to MicroPython review patterns.

## Prerequisites

- [ ] Spec file read: MULTI_AGENT_REVIEW_SPEC.md
- [ ] Main plan reviewed: MULTI_AGENT_REVIEW_PLAN.md
- [ ] Read `rag/prompt_builder.py` lines 32-146 (STYLE_GUIDE + REVIEW_GUIDANCE)
- [ ] Read `development-patterns.md` in mpy-rules to understand the rules
- [ ] Read /review-branch prompts for structural reference:
  - `~/.claude/plugins/cache/planet-innovation-marketplace/software/1.1.0/skills/review-branch/prompts/shared-context.md`
  - `~/.claude/plugins/cache/planet-innovation-marketplace/software/1.1.0/skills/review-branch/prompts/finding-validation.md`
  - `~/.claude/plugins/cache/planet-innovation-marketplace/software/1.1.0/skills/review-branch/prompts/architecture.md`

## Files to Create

All files go in `~/claude-mpy-marketplace/plugins/mpy-rules/prompts/`:

### `shared-context.md`

Combine the review stance, style guide, and review guidance into one file that
every agent reads first. Source content from:

- `rag/prompt_builder.py` STYLE_GUIDE constant (lines 32-100) -- voice, tone,
  brevity metrics, opening patterns, anti-patterns, severity markers, technical
  patterns
- `rag/prompt_builder.py` REVIEW_GUIDANCE constant (lines 104-146) -- project
  values, pre-review checks (CODECONVENTIONS.md, PR template, PR size),
  metadata usage, suggestion blocks
- /review-branch `shared-context.md` for structural reference -- the "review
  stance" framing (critical review, simplicity over cleverness, question
  abstractions)

Key adaptations from /review-branch:
- Replace generic "Principal Software Engineer" stance with MicroPython-specific
  values: code quality, small binary size, runtime efficiency
- Add instruction to read `development-patterns.md` rules file (already loaded
  in `.claude/rules/` for interactive, passed explicitly for bot)
- Add instruction to read `CODECONVENTIONS.md` at the MicroPython repo root
- Include the diff annotation format (L/R line numbers) from `bot/prompt.py`
  `annotate_diff()` -- agents need to know how to cite line numbers
- Include structured finding output format (JSON schema) used by all agents

**Finding JSON schema** (used by all domain agents):
```json
{
  "file": "path/to/file.c",
  "line": 42,
  "severity": "blocking|suggestion|nitpick",
  "title": "Short title",
  "description": "Detailed description with code references",
  "recommendation": "What should change",
  "diff_hunk": "relevant hunk context"
}
```

### `correctness-safety.md`

Agent 1 criteria. Reference the Correctness and Error Handling sections of
`development-patterns.md` for the specific patterns to check. Add:

- "Before reviewing, explore the codebase around changed files to understand
  interrupt handler patterns, timeout logic, and macro conventions"
- Specific checks from the spec: macro parenthesization, ISR context, NULL
  guards, overflow, interrupt handler conflicts, tick counter arithmetic,
  errno constants, soft reset state, scheduler atomicity
- Output format: structured findings per shared-context.md schema

Model after /review-branch `architecture.md` structure:
1. "Before reviewing" exploration instructions
2. "Review the diff for" criteria list
3. Output format with severity, title, file:line, commit hash, description,
   existing convention, recommendation

### `resource-constraints.md`

Agent 2 criteria. Reference Memory and Code Size + Performance sections of
`development-patterns.md`. Add:

- "Before reviewing, check the code size impact of changes by examining
  build configuration and understanding which ports are affected"
- Specific checks: MP_OBJ_NEW_SMALL_INT, m_new/m_del, struct packing,
  const for flash data, qstr minimization, hot path allocations,
  loop-invariant hoisting, benchmark expectations
- Emphasis: every byte counts on embedded -- quantify impact where possible

### `api-portability.md`

Agent 3 criteria. Reference API Design + Portability sections of
`development-patterns.md`. Add:

- "Before reviewing, check how similar APIs are implemented across other
  ports to verify naming and behavior consistency"
- Specific checks: CPython compatibility, cross-port naming, HAL abstraction,
  ABI stability, mp_obj_get_array, mp_obj_is_true, wrapper class avoidance,
  board config directness, unimplemented method handling

### `conventions-completeness.md`

Agent 4 criteria. Reference Documentation + Build System + Testing sections of
`development-patterns.md`, plus commit message rules from `core.md`. Add:

- "Before reviewing, read CODECONVENTIONS.md and
  .github/pull_request_template.md from the MicroPython repo root"
- Specific checks: CODECONVENTIONS.md compliance, commit message format
  (subject regex `^[^!]+: [A-Z]+.+ .+\.$`, max 72 chars, component prefix
  rules, Signed-off-by, body line length), PR template sections, MIT license
  headers, documentation accuracy, test coverage, cosmetic/functional
  separation, generated files in $(BUILD)/, offline builds, no redundant
  config defaults
- Commit message accuracy: verify the subject line description matches the
  actual changes in the diff

### `finding-validation.md`

Validation agent criteria. Combine /review-branch validation approach with
codebase verification. The agent receives:
- All findings from all 4 domain agents (concatenated)
- The full diff
- Tool access: Read, Glob, Grep, codanna

Validation steps (in order):
1. **Correctness**: Read cited file:line, verify finding describes something
   in the diff. Mark INVALID if not.
2. **Deduplication**: Merge findings from different agents targeting same
   location with same concern. Keep the more detailed one.
3. **Convention check**: For style/naming findings, read 3-5 adjacent files
   to verify whether the code matches or deviates from project convention.
   If it matches convention, mark INVALID.
4. **Relevance**: Remove findings that restate obvious trade-offs without
   concrete risk. Remove findings about pre-existing code not in the diff.
5. **Flip-flop detection**: Flag findings where the recommendation would
   create an equally valid opposite finding. Mark QUESTIONABLE.
6. **Cross-agent contradiction**: When agents recommend opposite actions,
   keep stronger justification, mark other QUESTIONABLE or INVALID.
7. **Severity calibration**: Adjust severity based on cross-agent consensus
   and codebase evidence.

Output format per finding:
```
[KEEP|QUESTIONABLE|INVALID] [SEVERITY] **Title** -- file:line
Description (preserved verbatim from original agent).
Validation note: <reasoning, 1-2 sentences>
```

End with summary: `Validation: N KEEP, N QUESTIONABLE, N INVALID out of N total`

## Integration Points

- The `shared-context.md` replaces the role that `bot/prompt.py:build_system_prompt()`
  and `rag/prompt_builder.py` STYLE_GUIDE/REVIEW_GUIDANCE currently play
- Domain prompts replace the single-pass review approach where one agent did
  everything guided by RAG examples
- Validation prompt replaces both `verify_findings` (per-finding subprocess
  spawning) and the consolidation step

## Testing Strategy

**What to Test:**
- Read each prompt file and verify it's self-contained (no dangling references
  to MCP tools or RAG database)
- Verify shared-context.md includes all content from STYLE_GUIDE and
  REVIEW_GUIDANCE (nothing lost in extraction)
- Verify each domain prompt covers its spec section completely
- Verify validation prompt covers all 7 steps

**How to Test:**
- Manual review: diff the STYLE_GUIDE/REVIEW_GUIDANCE constants against
  shared-context.md to ensure nothing was dropped
- Dry run: in a Claude Code session in a MicroPython repo, manually read
  each prompt file and verify it makes sense as agent instructions

**Success Criteria:**
- [ ] 6 files created in mpy-rules/prompts/
- [ ] shared-context.md contains all STYLE_GUIDE and REVIEW_GUIDANCE content
- [ ] Each domain prompt references development-patterns.md sections
- [ ] Each domain prompt has "before reviewing" codebase exploration instructions
- [ ] Finding JSON schema is consistent across all domain prompts
- [ ] Validation prompt covers all 7 verification steps
- [ ] No references to MCP tools, RAG database, or embedding model

## Risks and Mitigations

- **Risk:** Prompt files too long, consuming too much agent context
  - **Mitigation:** Keep each domain prompt under 2KB. Shared context under 4KB.
    The development-patterns.md (7KB) is loaded separately as a rules file.

- **Risk:** Style guide loses nuance in extraction
  - **Mitigation:** Diff the extracted version against the original constants
    to verify completeness before moving to Phase 2.

## Next Steps

After completing this phase:
1. Review all 6 prompt files for completeness and consistency
2. Proceed to MULTI_AGENT_REVIEW_PHASE_2.md (post-review CLI script)
