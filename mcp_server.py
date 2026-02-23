"""MCP server for MicroPython review RAG system.

Provides persistent access to the review database with warm model loading.
Tools are designed for iterative use during a review session — call search_reviews
multiple times with different queries, drill into PR history, etc.
"""

import json
import logging
import os
import subprocess
import sys

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


@mcp.tool()
def review_diff(
    diff_text: str,
    top_k: int = 8,
    include_codebase: bool = False,
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

    Returns:
        Markdown orchestration prompt (~5-8K chars) with a summary table
        of temp files, the style guide, and workflow instructions.
    """
    retriever = _get_retriever()
    builder = _get_builder()

    files_changed = _extract_files_from_diff(diff_text)

    results = retriever.get_similar_reviews(
        diff_text, top_k=top_k, diff_files=files_changed,
    )

    codebase_context = None
    if include_codebase:
        try:
            from rag.codebase import get_codebase_retriever
            codebase_context = get_codebase_retriever().get_context_for_diff(
                diff_text, top_k=5,
            )
        except Exception as e:
            logger.warning(f"Codebase context failed: {e}")

    _temp_dir, file_infos = builder.write_example_files(results)

    prompt = builder.build_orchestration_prompt(
        file_infos=file_infos,
        files_changed=files_changed,
        codebase_context=codebase_context,
    )

    return prompt


@mcp.tool()
def review_pr(
    pr_number: int,
    top_k: int = 8,
    include_codebase: bool = False,
) -> str:
    """Review a GitHub PR by number using historical MicroPython review patterns.

    Fetches the PR diff from micropython/micropython via gh CLI, then
    retrieves relevant past review examples and writes them to temp files.

    Args:
        pr_number: GitHub PR number from micropython/micropython.
        top_k: Number of review examples to retrieve (default 8).
        include_codebase: Include MicroPython codebase context (slower).

    Returns:
        Markdown orchestration prompt with file paths and style guide.
    """
    result = subprocess.run(
        ["gh", "pr", "diff", str(pr_number), "--repo", "micropython/micropython"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return json.dumps({"error": f"Failed to fetch PR diff: {result.stderr.strip()}"})

    diff_text = result.stdout
    if not diff_text.strip():
        return json.dumps({"error": f"PR #{pr_number} has an empty diff"})

    retriever = _get_retriever()
    builder = _get_builder()

    files_changed = _extract_files_from_diff(diff_text)

    results = retriever.get_similar_reviews(
        diff_text, top_k=top_k, diff_files=files_changed,
    )

    codebase_context = None
    if include_codebase:
        try:
            from rag.codebase import get_codebase_retriever
            codebase_context = get_codebase_retriever().get_context_for_diff(
                diff_text, top_k=5,
            )
        except Exception as e:
            logger.warning(f"Codebase context failed: {e}")

    _temp_dir, file_infos = builder.write_example_files(results)

    return builder.build_orchestration_prompt(
        file_infos=file_infos,
        files_changed=files_changed,
        pr_number=pr_number,
        codebase_context=codebase_context,
    )


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
    from rag.indexer import index_stats
    return index_stats()


@mcp.tool()
def get_pr_review_history(
    pr_number: int,
    max_comments: int = 20,
) -> dict:
    """Get full review history for a specific PR.

    Retrieves all review comments, issue comments, and review verdicts
    for a PR, organized as conversation threads where possible.

    Args:
        pr_number: GitHub PR number.
        max_comments: Maximum comments to return (default 20).

    Returns:
        Dict with 'threads' (grouped by reply chain), 'pr_info', and 'comment_count'.
    """
    from rag.graph_expander import get_pr_review_context
    return get_pr_review_context(pr_number, max_comments=max_comments)


if __name__ == "__main__":
    # Bot review-posting tools live in bot.mcp_tools. Registered only for
    # the standalone deployment entry point. Plugin/library imports get the
    # base mcp object without review-posting tools.
    try:
        from bot.mcp_tools import register_bot_tools
        register_bot_tools(mcp)
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

    mcp.run(transport=args.transport, **kwargs)
