"""MCP server for MicroPython review RAG system.

Provides persistent access to the review database with warm model loading.
Tools are designed for iterative use during a review session — call search_reviews
multiple times with different queries, drill into PR history, etc.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time

from fastmcp import FastMCP

# Configure logging to stderr so it doesn't interfere with stdio transport
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

mcp = FastMCP(
    "mpy-reviewer",
    instructions=(
        "MicroPython code review RAG system backed by 18,614 categorized review "
        "comments. Use review_diff or review_pr as "
        "the primary entry point for code review. Use search_reviews for targeted "
        "follow-up queries during a review (e.g. searching for memory allocation "
        "patterns, error handling examples). Use find_style_examples to calibrate "
        "tone. Use get_pr_review_history to see full review threads for a PR."
    ),
)

# --- Idle timeout for shared SSE mode ---
#
# Tracks both tool-call activity AND active SSE connections. The server
# shuts down only when the idle timeout expires AND there are zero active
# connections. This prevents killing the server while a session is
# connected but the user is thinking/reading.

_IDLE_TIMEOUT = int(os.environ.get("MPY_REVIEWER_IDLE_TIMEOUT", "1800"))  # 30 min default
_idle_timer: threading.Timer | None = None
_idle_lock = threading.Lock()
_idle_enabled = False  # Set to True only for SSE transport (not stdio/bot)
_active_connections = 0  # SSE connection count


def _touch_activity() -> None:
    """Reset the idle shutdown timer on any tool call or connection change."""
    global _idle_timer
    if not _idle_enabled:
        return
    with _idle_lock:
        if _idle_timer is not None:
            _idle_timer.cancel()
        _idle_timer = threading.Timer(_IDLE_TIMEOUT, _idle_shutdown)
        _idle_timer.daemon = True
        _idle_timer.start()


def _connection_opened() -> None:
    """Track a new SSE connection."""
    global _active_connections
    with _idle_lock:
        _active_connections += 1
    _touch_activity()
    logger.info("SSE connection opened (active: %d)", _active_connections)


def _connection_closed() -> None:
    """Track an SSE connection closing."""
    global _active_connections
    with _idle_lock:
        _active_connections = max(0, _active_connections - 1)
    _touch_activity()
    logger.info("SSE connection closed (active: %d)", _active_connections)


def _idle_shutdown() -> None:
    """Shut down the server after idle timeout, if no active connections."""
    with _idle_lock:
        if _active_connections > 0:
            # Still have connected clients — restart the timer
            logger.info("Idle timeout reached but %d connections active, deferring",
                        _active_connections)
    if _active_connections > 0:
        _touch_activity()
        return

    logger.info("Idle timeout (%ds) reached with 0 connections, shutting down", _IDLE_TIMEOUT)
    from pathlib import Path
    lock_file = Path.home() / ".cache" / "mpy-reviewer" / "server.lock"
    try:
        lock_file.unlink(missing_ok=True)
    except OSError:
        pass
    os._exit(0)


def _start_idle_timer() -> None:
    """Enable and start the idle timer (called once at SSE server startup)."""
    global _idle_enabled
    _idle_enabled = True
    _touch_activity()


# Lazy-loaded singletons — survive across tool calls within a session
_retriever = None
_builder = None


def _get_retriever():
    global _retriever
    if _retriever is None:
        from rag.retriever import ReviewRetriever
        _retriever = ReviewRetriever()
        # Force eager load of embedder and connection so first query is warm
        _ = _retriever.embedder
        _ = _retriever.conn
        logger.info("Retriever initialized (model warm)")
    return _retriever


def _get_builder():
    global _builder
    if _builder is None:
        from rag.prompt_builder import PromptBuilder
        _builder = PromptBuilder()
    return _builder


def _serialize_results(results: list, max_body: int = 2000) -> list:
    """Strip vector field and truncate large bodies for JSON transport."""
    clean = []
    for r in results:
        entry = {k: v for k, v in r.items() if k != "vector"}
        if "body" in entry and entry["body"] and len(entry["body"]) > max_body:
            entry["body"] = entry["body"][:max_body] + "..."
        clean.append(entry)
    return clean


def _extract_files_from_diff(diff_text: str) -> list:
    """Extract file paths from unified diff text."""
    from rag.codebase import extract_diff_file_paths
    return extract_diff_file_paths(diff_text)


def _make_review_tmpdir() -> str:
    """Create a temp directory for review example files.

    Uses MPY_REVIEW_TMPDIR as the parent if set (shared volume in Docker),
    otherwise falls back to the system default.
    """
    base = os.environ.get("MPY_REVIEW_TMPDIR")
    return tempfile.mkdtemp(prefix="mpy-review-", dir=base)


@mcp.tool()
def review_diff(
    diff_text: str,
    top_k: int = 8,
    include_codebase: bool = False,
    commit_messages: list[str] | None = None,
    pr_title: str | None = None,
    pr_body: str | None = None,
) -> str:
    """Review a code diff using historical MicroPython review patterns.

    Primary entry point for code review. Accepts raw unified diff text,
    retrieves relevant past review examples, writes each example to a
    temp file, and returns a compact orchestration prompt with file paths.

    The calling agent already has the diff in context so it is not echoed
    back. Example files contain full diff_hunks and thread context with
    no truncation.

    Args:
        diff_text: Unified diff text to review.
        top_k: Number of review examples to retrieve (default 8).
        include_codebase: Include MicroPython codebase context (slower).
        commit_messages: Optional list of commit messages for context.
        pr_title: Optional PR title for context.
        pr_body: Optional PR description/body for context.

    Returns:
        Markdown orchestration prompt (~5-8K chars) with a summary table
        of temp files, the style guide, and workflow instructions.
    """
    _touch_activity()
    t0 = time.monotonic()
    logger.info("review_diff: starting (top_k=%d, include_codebase=%s, diff_len=%d)",
                top_k, include_codebase, len(diff_text))

    retriever = _get_retriever()
    builder = _get_builder()
    logger.info("review_diff: retriever/builder ready (%.1fs)", time.monotonic() - t0)

    files_changed = _extract_files_from_diff(diff_text)
    logger.info("review_diff: %d files in diff (%.1fs)", len(files_changed), time.monotonic() - t0)

    results = retriever.get_similar_reviews(
        diff_text, top_k=top_k, diff_files=files_changed,
    )
    logger.info("review_diff: retrieval returned %d results (%.1fs)",
                len(results), time.monotonic() - t0)

    codebase_context = None
    if include_codebase:
        try:
            from rag.codebase import get_codebase_retriever
            codebase_context = get_codebase_retriever().get_context_for_diff(
                diff_text, top_k=5,
            )
            logger.info("review_diff: codebase context loaded (%.1fs)", time.monotonic() - t0)
        except Exception as e:
            logger.warning(f"review_diff: codebase context failed (%.1fs): {e}",
                           time.monotonic() - t0)

    temp_dir = _make_review_tmpdir()
    _temp_dir, file_infos = builder.write_example_files(results, temp_dir=temp_dir)
    logger.info("review_diff: wrote %d example files to %s (%.1fs)",
                len(file_infos), temp_dir, time.monotonic() - t0)

    prompt = builder.build_orchestration_prompt(
        file_infos=file_infos,
        files_changed=files_changed,
        commit_messages=commit_messages,
        pr_title=pr_title,
        pr_body=pr_body,
        codebase_context=codebase_context,
    )

    logger.info("review_diff: complete (%.1fs)", time.monotonic() - t0)
    return prompt


@mcp.tool()
def review_pr(
    pr_number: int,
    repo: str = "micropython/micropython",
    top_k: int = 8,
    include_codebase: bool = False,
) -> str:
    """Review a GitHub PR by number using historical MicroPython review patterns.

    Fetches the PR diff via gh CLI, then retrieves relevant past review
    examples and writes them to temp files.

    Args:
        pr_number: GitHub PR number.
        repo: GitHub repository slug (default: micropython/micropython).
        top_k: Number of review examples to retrieve (default 8).
        include_codebase: Include MicroPython codebase context (slower).

    Returns:
        Markdown orchestration prompt with file paths and style guide.
    """
    _touch_activity()
    t0 = time.monotonic()
    logger.info("review_pr: starting PR #%d (top_k=%d, include_codebase=%s)",
                pr_number, top_k, include_codebase)

    result = subprocess.run(
        ["gh", "pr", "diff", str(pr_number), "--repo", repo],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error("review_pr: gh pr diff failed: %s", result.stderr.strip())
        return json.dumps({"error": f"Failed to fetch PR diff: {result.stderr.strip()}"})

    diff_text = result.stdout
    if not diff_text.strip():
        return json.dumps({"error": f"PR #{pr_number} has an empty diff"})

    logger.info("review_pr: fetched diff (%d chars, %.1fs)",
                len(diff_text), time.monotonic() - t0)

    # Fetch PR metadata (title, body, commit messages)
    pr_title = None
    pr_body = None
    commit_messages = None
    try:
        meta_result = subprocess.run(
            ["gh", "pr", "view", str(pr_number), "--repo", repo,
             "--json", "title,body,commits"],
            capture_output=True, text=True,
        )
        if meta_result.returncode == 0:
            meta = json.loads(meta_result.stdout)
            pr_title = meta.get("title")
            pr_body = meta.get("body")
            commits = meta.get("commits", [])
            if commits:
                commit_messages = [
                    c.get("messageHeadline", "") for c in commits
                    if c.get("messageHeadline")
                ]
            logger.info("review_pr: fetched metadata (%.1fs)", time.monotonic() - t0)
    except Exception as e:
        logger.warning("review_pr: metadata fetch failed: %s", e)

    retriever = _get_retriever()
    builder = _get_builder()
    logger.info("review_pr: retriever/builder ready (%.1fs)", time.monotonic() - t0)

    files_changed = _extract_files_from_diff(diff_text)
    logger.info("review_pr: %d files in diff (%.1fs)", len(files_changed), time.monotonic() - t0)

    results = retriever.get_similar_reviews(
        diff_text, top_k=top_k, diff_files=files_changed,
    )
    logger.info("review_pr: retrieval returned %d results (%.1fs)",
                len(results), time.monotonic() - t0)

    codebase_context = None
    if include_codebase:
        try:
            from rag.codebase import get_codebase_retriever
            codebase_context = get_codebase_retriever().get_context_for_diff(
                diff_text, top_k=5,
            )
            logger.info("review_pr: codebase context loaded (%.1fs)", time.monotonic() - t0)
        except Exception as e:
            logger.warning("review_pr: codebase context failed (%.1fs): %s",
                           time.monotonic() - t0, e)

    temp_dir = _make_review_tmpdir()
    _temp_dir, file_infos = builder.write_example_files(results, temp_dir=temp_dir)
    logger.info("review_pr: wrote %d example files to %s (%.1fs)",
                len(file_infos), temp_dir, time.monotonic() - t0)

    prompt = builder.build_orchestration_prompt(
        file_infos=file_infos,
        files_changed=files_changed,
        pr_number=pr_number,
        pr_title=pr_title,
        pr_body=pr_body,
        commit_messages=commit_messages,
        codebase_context=codebase_context,
    )

    logger.info("review_pr: complete (%.1fs)", time.monotonic() - t0)
    return prompt


@mcp.tool()
def search_reviews(
    query: str,
    top_k: int = 10,
    domain: str | None = None,
    severity: str | None = None,
    component: str | None = None,
    language_context: str | None = None,
) -> dict:
    """Search review comments by semantic similarity with optional filters.

    Use for targeted follow-up queries during a review session. For example,
    after reviewing a diff, search for "memory allocation gc" to find specific
    patterns flagged around garbage collection.

    Filterable domains: correctness, code_style, api_design, memory, performance,
    portability, documentation, testing, security, architecture, build_system.

    Filterable severities: blocking, suggestion, nitpick.

    Filterable components: py_core, extmod, port_specific, drivers, tools, tests,
    docs, build_system.

    Args:
        query: Natural language search query.
        top_k: Number of results (default 10).
        domain: Filter by review domain.
        severity: Filter by severity level.
        component: Filter by codebase component.
        language_context: Filter by language (c_code, python_code, etc.).

    Returns:
        Dict with 'results' list and 'count'.
    """
    _touch_activity()
    retriever = _get_retriever()
    results = retriever.search_with_filters(
        query,
        domain=domain,
        severity=severity,
        component=component,
        language_context=language_context,
        top_k=top_k,
    )

    return {
        "results": _serialize_results(results),
        "count": len(results),
        "query": query,
        "filters": {
            k: v for k, v in {
                "domain": domain,
                "severity": severity,
                "component": component,
                "language_context": language_context,
            }.items() if v is not None
        },
    }


@mcp.tool()
def find_style_examples(
    query: str = "",
    top_k: int = 10,
) -> dict:
    """Find review comments that exemplify the lead maintainer's communication style.

    Filtered to comments marked as style examples during categorization.
    Use to calibrate tone and phrasing when generating reviews.

    Args:
        query: Optional search query to focus style examples (default: broad).
        top_k: Number of results (default 10).

    Returns:
        Dict with 'results' list and 'count'.
    """
    _touch_activity()
    retriever = _get_retriever()

    if query:
        results = retriever.search_with_filters(
            query, is_style_example=True, top_k=top_k,
        )
    else:
        # Broad style example retrieval — use a generic query
        results = retriever.search_with_filters(
            "code review feedback suggestion", is_style_example=True, top_k=top_k,
        )

    return {
        "results": _serialize_results(results),
        "count": len(results),
    }


@mcp.tool()
def get_review_stats() -> dict:
    """Get statistics about the review database index.

    Returns record count, domain distribution, and other index metadata.
    Use to verify the system is operational.

    Returns:
        Dict with index statistics.
    """
    _touch_activity()
    from rag.indexer import index_stats
    return index_stats()


@mcp.tool()
def get_pr_review_history(
    pr_number: int,
    repo: str = "micropython/micropython",
    max_comments: int = 20,
) -> dict:
    """Get full review history for a specific PR.

    Retrieves all review comments, issue comments, and review verdicts
    for a PR, organized as conversation threads where possible.

    Args:
        pr_number: GitHub PR number.
        repo: GitHub repository slug (default: micropython/micropython).
        max_comments: Maximum comments to return (default 20).

    Returns:
        Dict with 'threads' (grouped by reply chain), 'pr_info', and 'comment_count'.
    """
    _touch_activity()
    from rag.graph_expander import get_pr_review_context
    return get_pr_review_context(pr_number, max_comments=max_comments, repo=repo)


@mcp.tool()
async def verify_findings(
    findings: list[dict],
    diff_text: str,
    pr_number: int | None = None,
    repo: str = "micropython/micropython",
) -> str:
    """Cross-check review findings against the actual codebase.

    Each finding is verified independently by a dedicated claude -p subprocess
    with access to codanna, the filesystem, gh CLI, and historical review
    precedent from the RAG database.

    Call this after generating structured findings from a review_diff/review_pr
    session. Findings that are false positives (e.g. pattern matches existing
    convention) are flagged so the caller can drop or adjust them.

    Args:
        findings: JSON array of structured findings. Each must have:
            file (str), line (int), severity (str), description (str),
            diff_hunk (str).
        diff_text: The full unified diff being reviewed.
        pr_number: Optional PR number for GitHub context.
        repo: Repository slug (default: micropython/micropython).

    Returns:
        Markdown orchestration prompt with verdict summary table and
        paths to per-finding verdict files under /tmp/mpy-verify-*/.
    """
    _touch_activity()
    t0 = time.monotonic()
    logger.info(
        "verify_findings: starting (%d findings, pr=%s)",
        len(findings), pr_number,
    )

    from rag.verifier import REQUIRED_FINDING_FIELDS, MAX_FINDINGS, verify_all_findings

    # Validate findings count
    if len(findings) > MAX_FINDINGS:
        return (
            f"Error: too many findings ({len(findings)}). "
            f"Maximum is {MAX_FINDINGS}. Prioritize the most important findings."
        )

    # Validate finding fields
    for i, f in enumerate(findings):
        missing = [k for k in REQUIRED_FINDING_FIELDS if k not in f]
        if missing:
            return (
                f"Error: finding #{i} is missing required fields: {', '.join(missing)}. "
                f"Each finding must have: {', '.join(REQUIRED_FINDING_FIELDS)}"
            )

    retriever = _get_retriever()

    # Determine cwd (MicroPython checkout)
    # CLAUDE_PROJECT_DIR is set by Claude Code to the user's project directory
    cwd = (
        os.environ.get("MPY_CHECKOUT")
        or os.environ.get("CLAUDE_PROJECT_DIR")
        or "/workspace/micropython"
    )

    # Build env
    env = os.environ.copy()
    config_dir = os.environ.get("MPY_REVIEWER_CLAUDE_CONFIG_DIR")
    if config_dir:
        env["CLAUDE_CONFIG_DIR"] = config_dir

    prompt, file_infos = await verify_all_findings(
        findings=findings,
        diff_text=diff_text,
        pr_number=pr_number,
        repo=repo,
        retriever=retriever,
        cwd=cwd,
        env=env,
    )

    logger.info(
        "verify_findings: complete (%d verdicts, %.1fs)",
        len(file_infos), time.monotonic() - t0,
    )
    return prompt


# --- Issue triage tools ---

_triage_retriever = None
_triage_builder = None


def _get_triage_retriever():
    global _triage_retriever
    if _triage_retriever is None:
        from triage.retriever import IssueRetriever
        _triage_retriever = IssueRetriever()
        _ = _triage_retriever.embedder
        _ = _triage_retriever.conn
        logger.info("Triage retriever initialized")
    return _triage_retriever


def _get_triage_builder():
    global _triage_builder
    if _triage_builder is None:
        from triage.prompt_builder import TriagePromptBuilder
        _triage_builder = TriagePromptBuilder()
    return _triage_builder


@mcp.tool()
def triage_issue(
    issue_number: int,
    repo: str = "micropython/micropython",
    top_k: int = 5,
    include_codebase: bool = False,
) -> str:
    """Triage a GitHub issue using similar issues, closing refs, and review patterns.

    Primary entry point for issue triage. Fetches the issue, finds similar
    issues and closing references, optionally searches the codebase, and
    returns an orchestration prompt for triage assessment.

    Args:
        issue_number: GitHub issue number.
        repo: GitHub repository slug (default: micropython/micropython).
        top_k: Number of similar issues to retrieve (default 5).
        include_codebase: Include MicroPython codebase context (slower).

    Returns:
        Markdown triage prompt with similar issues, closing refs, and style guide.
    """
    _touch_activity()
    t0 = time.monotonic()
    logger.info("triage_issue: starting #%d (top_k=%d, include_codebase=%s)",
                issue_number, top_k, include_codebase)

    retriever = _get_triage_retriever()
    builder = _get_triage_builder()

    # Fetch issue from DB
    issue = retriever.get_issue(issue_number, repo)
    if issue is None:
        # Try fetching from GitHub
        issue_data = _fetch_github_issue(issue_number, repo)
        if issue_data is None:
            return json.dumps({"error": f"Issue #{issue_number} not found in DB or GitHub"})
        issue = issue_data

    title = issue.get("title", "")
    body = issue.get("body", "") or ""
    state = issue.get("state", "open")
    labels_raw = issue.get("labels", "[]")
    if isinstance(labels_raw, str):
        try:
            labels = json.loads(labels_raw)
        except (json.JSONDecodeError, TypeError):
            labels = []
    elif isinstance(labels_raw, list):
        labels = labels_raw
    else:
        labels = []

    logger.info("triage_issue: issue fetched (%.1fs)", time.monotonic() - t0)

    # Find similar issues
    query_text = f"{title}\n\n{body}"
    similar = retriever.find_potential_duplicates(title, body, top_k=top_k)
    # Exclude the issue itself from results
    similar = [s for s in similar if s.get("issue_number") != issue_number or s.get("repo") != repo]
    logger.info("triage_issue: %d similar issues found (%.1fs)",
                len(similar), time.monotonic() - t0)

    # Check closing refs
    closing_refs = retriever.check_closing_refs(issue_number, repo)
    logger.info("triage_issue: %d closing refs found (%.1fs)",
                len(closing_refs), time.monotonic() - t0)

    # Related review comments
    related_reviews = retriever.find_related_reviews(query_text, top_k=5)
    logger.info("triage_issue: %d related reviews found (%.1fs)",
                len(related_reviews), time.monotonic() - t0)

    # Codebase context
    codebase_context = None
    if include_codebase:
        try:
            from rag.codebase import get_codebase_retriever
            codebase_context = get_codebase_retriever().get_context_for_diff(
                query_text, top_k=5,
            )
            logger.info("triage_issue: codebase context loaded (%.1fs)",
                        time.monotonic() - t0)
        except Exception as e:
            logger.warning("triage_issue: codebase context failed: %s", e)

    # Build triage prompt
    from triage.prompt_builder import TriageContext
    context = TriageContext(
        issue_number=issue_number,
        issue_title=title,
        issue_body=body,
        issue_labels=labels,
        issue_state=state,
        issue_repo=repo,
        similar_issues=similar,
        related_reviews=related_reviews,
        closing_refs=closing_refs,
        codebase_context=codebase_context,
    )

    prompt = builder.build_triage_prompt(context)
    logger.info("triage_issue: complete (%.1fs)", time.monotonic() - t0)
    return prompt


@mcp.tool()
def search_issues(
    query: str,
    top_k: int = 10,
    state: str | None = None,
    component: str | None = None,
    port: str | None = None,
) -> dict:
    """Search indexed issues by semantic similarity with optional filters.

    Use for finding issues related to a topic or code area.

    Args:
        query: Natural language search query.
        top_k: Number of results (default 10).
        state: Filter by issue state (open, closed).
        component: Filter by component.
        port: Filter by port.

    Returns:
        Dict with 'results' list and 'count'.
    """
    _touch_activity()
    retriever = _get_triage_retriever()
    results = retriever.search_similar_issues(
        query, top_k=top_k, state=state, component=component, port=port,
    )

    return {
        "results": _serialize_results(results),
        "count": len(results),
        "query": query,
        "filters": {
            k: v for k, v in {
                "state": state,
                "component": component,
                "port": port,
            }.items() if v is not None
        },
    }


def _fetch_github_issue(issue_number: int, repo: str) -> dict | None:
    """Fetch an issue from GitHub when not in DB."""
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{repo}/issues/{issue_number}"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        labels = [l["name"] for l in data.get("labels", [])]
        return {
            "number": data["number"],
            "title": data.get("title", ""),
            "body": data.get("body", ""),
            "state": data.get("state", "open"),
            "labels": json.dumps(labels),
            "author": data.get("user", {}).get("login", ""),
            "created_at": data.get("created_at", ""),
            "closed_at": data.get("closed_at"),
            "comments_count": data.get("comments", 0),
        }
    except Exception:
        return None


if __name__ == "__main__":
    # Bot review-posting tools live in bot.mcp_tools. Registered only for
    # the standalone deployment entry point. Plugin/library imports get the
    # base mcp object without review-posting tools.
    try:
        from bot.mcp_tools import register_bot_tools
        register_bot_tools(mcp)
    except ImportError:
        pass

    try:
        from triage.mcp_tools import register_triage_bot_tools
        register_triage_bot_tools(mcp)
    except ImportError:
        pass

    import argparse

    parser = argparse.ArgumentParser(description="MicroPython Review MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="MCP transport protocol (default: stdio)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="HTTP bind address")
    parser.add_argument("--port", type=int, default=8080, help="HTTP port")
    args = parser.parse_args()

    kwargs = {}
    if args.transport != "stdio":
        kwargs["host"] = args.host
        kwargs["port"] = args.port

    # Enable idle timeout for SSE transport (shared server mode),
    # unless bot mode is active (bot manages its own lifecycle).
    if args.transport != "stdio" and not os.environ.get("MPY_REVIEWER_BOT_MODE"):
        _start_idle_timer()
        logger.info("Idle timeout enabled: %ds", _IDLE_TIMEOUT)

        # Add middleware to track client connections via MCP initialize/message
        from fastmcp.server.middleware import Middleware

        class ConnectionTracker(Middleware):
            """Track MCP client sessions for idle timeout."""
            _sessions: set = set()

            async def on_initialize(self, context, call_next):
                session_id = id(context)
                ConnectionTracker._sessions.add(session_id)
                _connection_opened()
                return await call_next(context)

            async def on_call_tool(self, context, call_next):
                _touch_activity()
                return await call_next(context)

        mcp.add_middleware(ConnectionTracker())

    mcp.run(transport=args.transport, **kwargs)
