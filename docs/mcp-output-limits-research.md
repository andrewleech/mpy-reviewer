# MCP Tool Output Limits in Claude Code

Research date: 2026-02-21

## 1. Maximum Output Size for MCP Tool Results

### Default Limit: 25,000 tokens

The official Claude Code documentation states:

> "The default maximum is 25,000 tokens"

Source: [Claude Code MCP Docs](https://code.claude.com/docs/en/mcp)

### Warning Threshold: 10,000 tokens

Claude Code displays a warning when any single MCP tool output exceeds 10,000
tokens. The warning reads something like:

```
Warning: Large MCP response (~25.1k tokens), this can fill up context quickly
```

### Error When Exceeded

When the limit is hard-exceeded, the error message follows this pattern:

```
Error: MCP tool "<tool_name>" response (N tokens) exceeds maximum allowed
tokens (25000). Please use pagination, filtering, or limit parameters to
reduce the response size.
```

In the user's case, a 198,098-character response was rejected. Characters and
tokens are not 1:1 -- roughly 4 characters per token is typical, so ~198k
characters would be approximately ~50k tokens, well above the 25k default.

### Configuring the Limit

Set the `MAX_MCP_OUTPUT_TOKENS` environment variable before launching Claude Code:

```bash
# Increase to 50k tokens
MAX_MCP_OUTPUT_TOKENS=50000 claude

# Or export for the session
export MAX_MCP_OUTPUT_TOKENS=50000
```

This can also be set in `settings.json` via the `env` field.

### Behavior When Exceeded

Based on multiple sources, there are two enforcement mechanisms depending on
version and configuration:

1. **Hard rejection**: The tool result is discarded and an error message is
   shown to the model, instructing it to use pagination/filtering.
2. **Truncation with marker**: Some sources (DeepWiki analysis of claude-code
   source) report that outputs exceeding the limit are "automatically truncated
   with a persistence marker." This may apply to the terminal display rather
   than the model context.

The hard rejection behavior is the one observed in practice when the limit is
significantly exceeded.

### Note on the MCP Specification

The MCP specification itself (revision 2025-06-18) does **not** define any
size limit for tool results. The 25,000-token limit is imposed by Claude Code
as the MCP client, not by the protocol.

Source: [MCP Tools Specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)

---

## 2. Best Practices for MCP Servers Returning Large Results

### Strategy 1: Server-Side Truncation and Summarization

The most reliable approach. The MCP server itself should enforce output size
limits and return concise results.

**For RAG systems specifically:**
- Return only the top-K most relevant results, not all candidates
- Include only the most relevant snippet from each result, not full documents
- Provide metadata (score, source, category) alongside truncated body text
- Set a character/token budget and truncate individual results to fit

**Implementation pattern:**
```python
MAX_RESULT_CHARS = 80000  # ~20k tokens, safe margin under 25k limit

def format_results(results, max_chars=MAX_RESULT_CHARS):
    output = []
    remaining = max_chars
    for r in results:
        entry = format_single_result(r)
        if len(entry) > remaining:
            entry = truncate_with_marker(entry, remaining)
        output.append(entry)
        remaining -= len(entry)
        if remaining <= 0:
            output.append(f"[{len(results) - len(output)} more results truncated]")
            break
    return "\n\n".join(output)
```

### Strategy 2: Tiered Data Access (Summary + Detail)

Implement separate tools where one returns lightweight summaries and another
retrieves full details by ID.

**Pattern:**
- `search_reviews(query, top_k=10)` -- returns brief summaries with IDs
- `get_review_detail(comment_id)` -- returns full text for a specific comment

This lets the model iterate: search first, then fetch details for the most
relevant hits. Total context consumed is lower because only the interesting
results are expanded.

Source: [GitHub Community Discussion #169224](https://github.com/orgs/community/discussions/169224)

### Strategy 3: Cursor-Based Pagination

MCP natively supports cursor-based pagination. The server returns a page of
results plus an opaque `nextCursor` token. The client passes the cursor back
to get the next page.

**Key characteristics:**
- Cursor is an opaque string (often Base64-encoded state)
- Page size is determined by the server and may vary
- Supported on `resources/list`, `prompts/list`, `tools/list`
- For tool results, pagination must be implemented in the tool's own schema
  (MCP pagination spec applies to listing operations, not tool call results)

**For tool call results**, pagination must be a tool parameter:

```python
@mcp.tool()
def search_reviews(query: str, top_k: int = 10, cursor: str = None) -> dict:
    """Search review database. Returns paginated results."""
    results, next_cursor = do_search(query, top_k, cursor)
    response = {"results": results}
    if next_cursor:
        response["next_cursor"] = next_cursor
        response["note"] = "More results available. Call again with cursor parameter."
    return response
```

**Caveat:** Models sometimes ignore pagination cues. Adding explicit
instructions in the tool description helps:

> "Results are paginated. If `next_cursor` is present, call this tool again
> with `cursor=<value>` to get more results."

Source: [MCP Pagination Specification](https://modelcontextprotocol.info/specification/draft/server/utilities/pagination/)

### Strategy 4: Resource Links Instead of Inline Content

MCP tool results can return `resource_link` content types instead of embedding
large data inline. The link provides a URI that the client can optionally fetch.

```json
{
  "type": "resource_link",
  "uri": "file:///tmp/review-context-abc123.md",
  "name": "Full review context",
  "description": "Complete review context with 45 similar reviews",
  "mimeType": "text/markdown"
}
```

This avoids the token limit entirely for the tool result itself, though the
resource content still consumes context when fetched.

### Strategy 5: Field Filtering and Response Simplification

Remove fields that provide no analytical value to the model:

- Strip UI-oriented fields (icon URLs, animation URLs)
- Replace complex nested objects with flat references (e.g., full address
  objects become simple address hashes)
- Truncate long string fields (e.g., diff hunks to first 512 chars)
- Exclude fields the model won't use for the current task

Source: [Blockscout MCP Optimization Guide](https://www.blog.blockscout.com/mcp-explained-part-2-optimizations/)

### Strategy 6: Adaptive Budget Allocation

For RAG specifically, allocate a character budget across results and adaptively
truncate:

```
Total budget: 80,000 chars
Per-result budget: 80,000 / top_k
```

If some results are shorter than their budget, redistribute the surplus to
longer results. This maximizes information density within the limit.

---

## 3. How Claude Code Skills Interact with MCP Tools

### Skills Run in the Main Session Context (by default)

When Claude loads a skill (either automatically or via `/skill-name`), the
skill's instructions are injected into the current conversation context. The
skill runs inline -- it does not spawn a separate process or agent.

MCP tools that are available to the main session are also available when a
skill is active. The skill's `allowed-tools` frontmatter can restrict which
tools are accessible, but it cannot grant access to tools the session doesn't
have.

### Skills with `context: fork`

When a skill has `context: fork` in its frontmatter, it runs in a **forked
subagent context**. This subagent:

- Gets a fresh conversation context (no access to parent conversation history)
- Receives the skill content as its prompt
- Has access to MCP tools (subject to `allowed-tools` restrictions)
- Uses the `agent` field to determine execution environment (model, tools)
- Returns a summary to the parent session when complete

### Subagents with Preloaded Skills

When a subagent is spawned with `skills` in its configuration, the full skill
content is injected at startup (not just the metadata). The subagent has access
to MCP tools available to the parent session.

### Practical Implication for MCP RAG Tools

When a skill calls an MCP tool, the tool result goes into the **skill's
execution context** (which is the main session context unless `context: fork`
is set). The 25k token limit applies regardless of whether the call originates
from a skill or from the main conversation.

If a skill with `context: fork` calls an MCP tool, the result goes into the
subagent's context. The same 25k limit applies, but the subagent has a fresh
context window, so there's more room for large results. The subagent then
summarizes its findings back to the parent.

Source: [Claude Code Skills Documentation](https://code.claude.com/docs/en/skills)
Source: [Understanding Claude Code Full Stack](https://alexop.dev/posts/understanding-claude-code-full-stack/)

---

## 4. Recommended Patterns for RAG MCP Tools

### Pattern A: Truncated Inline Results (Simplest)

The MCP server enforces a hard character limit on its output. Each search
result is truncated to fit within the budget.

**Pros:** Simple to implement, works with all clients.
**Cons:** May lose important context from truncated results.

```python
@mcp.tool()
def search_reviews(query: str, top_k: int = 8) -> str:
    results = retriever.search(query, top_k=top_k)
    return format_results(results, max_chars=80000)
```

### Pattern B: Two-Phase Retrieval (Recommended for RAG)

Phase 1 returns compact summaries. Phase 2 fetches full context for selected
results.

**Tool 1: `search_reviews`**
- Input: query, filters, top_k
- Output: List of {id, score, theme, severity, snippet (200 chars)}
- Size: ~5k tokens for 10 results

**Tool 2: `get_review_detail`**
- Input: comment_id
- Output: Full comment body, diff hunk, thread context, PR metadata
- Size: ~1-3k tokens per result

**Tool 3: `get_review_context`** (optional)
- Input: list of comment_ids
- Output: Batched full context for multiple comments
- Size: Budget-controlled, truncates to fit

This lets Claude search broadly, assess relevance from summaries, then fetch
only what it needs. Total context consumed is typically lower than returning
everything upfront.

### Pattern C: Write-to-File + Reference (for very large contexts)

The MCP server writes full context to a temporary file and returns only the
file path and a summary.

```python
@mcp.tool()
def generate_review_prompt(diff: str) -> str:
    results = retriever.search(diff, top_k=20)
    full_context = build_full_prompt(results)

    # Write to temp file
    path = f"/tmp/review-context-{uuid4().hex[:8]}.md"
    Path(path).write_text(full_context)

    # Return summary + file reference
    summary = summarize_results(results)
    return f"""## Review Context Summary
{summary}

Full context ({len(results)} reviews, {len(full_context)} chars) written to:
{path}

Use the Read tool to access the full context if needed.
"""
```

**Pros:** No token limit issues, full context preserved.
**Cons:** Requires the model to make a follow-up Read tool call, which it may
or may not do. Also consumes context when the file is read.

### Pattern D: Pre-Built Prompt with Budget (Current mpy-reviewer approach)

The server assembles a complete review prompt, but enforces a token budget.
Results are ranked by relevance and included until the budget is exhausted.

This is the approach currently used by the mpy-reviewer MCP server. The main
risk is exceeding the 25k limit when the review prompt (instruction text +
style guide + retrieved examples + diff context) grows too large.

**Mitigation options:**
1. Set `MAX_MCP_OUTPUT_TOKENS=50000` in the MCP server config or user env
2. Reduce the number of retrieved examples (top_k=5 instead of 8)
3. Truncate individual review examples more aggressively
4. Split the prompt into multiple tool calls (style guide in one, examples
   in another, instructions in a third)

---

## 5. Recommendations for mpy-reviewer

Given the current architecture (MCP server returning assembled review prompts):

### Immediate Fix

Set a character budget in the MCP server's `review_diff` and `review_pr` tools.
A safe budget is ~80,000 characters (~20k tokens), leaving headroom under the
25k default limit. Truncate individual review examples to fit.

### Better Architecture

Refactor into multiple tools:

1. **`search_reviews`** -- returns compact results with IDs and scores
2. **`get_review_detail`** -- returns full context for a specific comment
3. **`get_style_guide`** -- returns the generated style guide (fixed size)
4. **`review_diff`** -- returns review instructions + the most relevant 3-5
   examples (budget-controlled), referencing `search_reviews` for more

This reduces average context consumption while letting Claude fetch more
detail when needed.

### User-Side Workaround

If server changes aren't immediate, users can increase the limit:

```bash
export MAX_MCP_OUTPUT_TOKENS=100000
claude
```

Or in `.claude/settings.json`:

```json
{
  "env": {
    "MAX_MCP_OUTPUT_TOKENS": "100000"
  }
}
```

Note: increasing the limit doesn't solve the context consumption problem --
large tool results still eat into the context window. It just prevents the
hard error.

---

## Sources

- [Claude Code MCP Documentation](https://code.claude.com/docs/en/mcp) -- Official docs, confirms 25k default and MAX_MCP_OUTPUT_TOKENS variable
- [Claude Code Skills Documentation](https://code.claude.com/docs/en/skills) -- Skills architecture, allowed-tools, context: fork
- [MCP Tools Specification (2025-06-18)](https://modelcontextprotocol.io/specification/2025-06-18/server/tools) -- Protocol spec, no size limit defined
- [MCP Pagination Specification](https://modelcontextprotocol.info/specification/draft/server/utilities/pagination/) -- Cursor-based pagination
- [GitHub Issue #9152: MCP Image Token Limit](https://github.com/anthropics/claude-code/issues/9152) -- 25k limit error message format
- [GitHub Issue #2638: Truncated MCP Responses](https://github.com/anthropics/claude-code/issues/2638) -- Display truncation vs. model context
- [GitHub Issue #7732: MAX_MCP_TOOL_SCHEMA_TOKENS](https://github.com/anthropics/claude-code/issues/7732) -- Schema token management
- [GitHub Community Discussion #169224](https://github.com/orgs/community/discussions/169224) -- Tiered data access patterns
- [DeepWiki: Claude Code Token Limits](https://deepwiki.com/kill136/claude-code-open/14.2-token-limits) -- Source code analysis of limits
- [Blockscout MCP Optimizations](https://www.blog.blockscout.com/mcp-explained-part-2-optimizations/) -- Truncation and pagination patterns
- [Scott Spence: Optimising MCP Context Usage](https://scottspence.com/posts/optimising-mcp-server-context-usage-in-claude-code) -- Tool consolidation, context budgets
- [Understanding Claude Code Full Stack](https://alexop.dev/posts/understanding-claude-code-full-stack/) -- Skills and MCP interaction architecture
