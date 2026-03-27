"""MCP server for MicroPython issue triage.

Provides persistent access to the issue triage database with warm model loading.
Tools are designed for iterative use during a triage session -- call search_issues
multiple times with different queries, drill into specific issues, etc.
"""

import json
import logging
import os
import subprocess
import sys
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
        "MicroPython issue triage system. Use triage_issue as the primary entry "
        "point for triaging GitHub issues. Use search_issues for targeted queries "
        "to find related issues by topic, component, or port."
    ),
)

# --- Idle timeout for shared SSE mode ---
#
# Activity-based timeout: the server shuts down when no tool calls have
# occurred for _IDLE_TIMEOUT seconds, regardless of connected clients.
# Proxy processes are stateless -- if the server exits, new requests spawn
# a fresh one via _run_direct() fallback.

_IDLE_TIMEOUT = int(os.environ.get("MPY_REVIEWER_IDLE_TIMEOUT", "1800"))  # 30 min default
_idle_timer: threading.Timer | None = None
_idle_lock = threading.Lock()
_idle_enabled = False  # Set to True only for SSE transport (not stdio/bot)


def _touch_activity() -> None:
    """Reset the idle shutdown timer on any tool call."""
    global _idle_timer
    if not _idle_enabled:
        return
    with _idle_lock:
        if _idle_timer is not None:
            _idle_timer.cancel()
        _idle_timer = threading.Timer(_IDLE_TIMEOUT, _idle_shutdown)
        _idle_timer.daemon = True
        _idle_timer.start()


def _idle_shutdown() -> None:
    """Shut down the server after idle timeout."""
    logger.info("Idle timeout (%ds) reached, shutting down", _IDLE_TIMEOUT)
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


def _serialize_results(results: list, max_body: int = 2000) -> list:
    """Strip vector field and truncate large bodies for JSON transport."""
    clean = []
    for r in results:
        entry = {k: v for k, v in r.items() if k != "vector"}
        if "body" in entry and entry["body"] and len(entry["body"]) > max_body:
            entry["body"] = entry["body"][:max_body] + "..."
        clean.append(entry)
    return clean


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
    # Bot tools live in bot.mcp_tools. Registered only for the standalone
    # deployment entry point.
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

        # Reset idle timer on each tool call
        from fastmcp.server.middleware import Middleware

        class ActivityTracker(Middleware):
            async def on_call_tool(self, context, call_next):
                _touch_activity()
                return await call_next(context)

        mcp.add_middleware(ActivityTracker())

    mcp.run(transport=args.transport, **kwargs)
