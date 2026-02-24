"""Graph-aware context expansion for review retrieval.

Provides relational post-processing:
- Reply chain reconstruction (in_reply_to_id traversal)
- PR sibling expansion (other high-severity comments from same PR)
- File-level review aggregation across PRs
"""

import sqlite3
import logging
from typing import List, Dict, Any, Optional
from collections import defaultdict

from .config import get_config

logger = logging.getLogger(__name__)


def _get_connection() -> sqlite3.Connection:
    config = get_config()
    conn = sqlite3.connect(config.sqlite_db_path)
    conn.row_factory = sqlite3.Row
    return conn


def expand_reply_chain(
    comment_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> List[Dict[str, Any]]:
    """Follow in_reply_to_id links to reconstruct a conversation thread.

    Walks both up (to the root) and down (to all descendants) to get
    the full thread containing this comment.

    Args:
        comment_id: Starting comment ID.
        conn: Optional database connection (created if not provided).

    Returns:
        List of comments in chronological order forming the thread.
    """
    close_conn = conn is None
    if conn is None:
        conn = _get_connection()

    try:
        # Walk up to find the root of the thread
        root_id = comment_id
        visited = {root_id}
        while True:
            row = conn.execute(
                "SELECT in_reply_to_id FROM review_comments WHERE id = ?",
                (root_id,),
            ).fetchone()
            if row is None or row["in_reply_to_id"] is None:
                break
            parent_id = row["in_reply_to_id"]
            if parent_id in visited:
                break  # cycle guard
            visited.add(parent_id)
            root_id = parent_id

        # Now collect the full thread starting from root
        thread = []
        queue = [root_id]
        seen = set()

        while queue:
            cid = queue.pop(0)
            if cid in seen:
                continue
            seen.add(cid)

            row = conn.execute(
                """SELECT id, pr_number, body, path, line, diff_hunk,
                          created_at, in_reply_to_id
                   FROM review_comments WHERE id = ?""",
                (cid,),
            ).fetchone()

            if row is None:
                continue

            thread.append(dict(row))

            # Find children
            children = conn.execute(
                "SELECT id FROM review_comments WHERE in_reply_to_id = ?",
                (cid,),
            ).fetchall()
            for child in children:
                queue.append(child["id"])

        # Sort chronologically
        thread.sort(key=lambda x: x.get("created_at", ""))

        return thread

    finally:
        if close_conn:
            conn.close()


def expand_pr_context(
    pr_number: int,
    conn: Optional[sqlite3.Connection] = None,
    max_siblings: int = 5,
    min_severity: str = "suggestion",
    repo: str = "micropython/micropython",
) -> List[Dict[str, Any]]:
    """Get other review comments from the same PR.

    Useful for understanding review priorities in a session.
    Prioritizes blocking > suggestion comments.

    Args:
        pr_number: PR number.
        conn: Optional database connection.
        max_siblings: Maximum sibling comments to return.
        min_severity: Minimum severity to include ("blocking" or "suggestion").
        repo: GitHub repository slug.

    Returns:
        List of sibling comments with categorization metadata.
    """
    close_conn = conn is None
    if conn is None:
        conn = _get_connection()

    severity_filter = "('blocking')" if min_severity == "blocking" else "('blocking', 'suggestion')"

    try:
        rows = conn.execute(
            f"""SELECT rc.id, rc.body, rc.path, rc.diff_hunk, rc.created_at,
                       cc.severity, cc.theme, d.name as domain
                FROM review_comments rc
                JOIN comment_categories cc
                    ON rc.id = cc.comment_id AND cc.comment_type = 'review_comment'
                LEFT JOIN domains d ON cc.domain_id = d.id
                WHERE rc.pr_number = ?
                  AND rc.repo = ?
                  AND cc.severity IN {severity_filter}
                  AND cc.theme != 'FAILED_CATEGORIZATION'
                ORDER BY
                    CASE cc.severity WHEN 'blocking' THEN 0 ELSE 1 END,
                    rc.created_at
                LIMIT ?""",
            (pr_number, repo, max_siblings),
        ).fetchall()

        return [dict(r) for r in rows]

    finally:
        if close_conn:
            conn.close()


def get_file_review_summary(
    file_path: str,
    conn: Optional[sqlite3.Connection] = None,
    max_prs: int = 20,
    repo: str = "micropython/micropython",
) -> Dict[str, Any]:
    """Aggregate review themes for a specific file across all PRs.

    Useful for queries like "what gets flagged in py/mpconfig.h?"

    Args:
        file_path: File path (as stored in review_comments.path).
        conn: Optional database connection.
        max_prs: Maximum number of PRs to aggregate across.
        repo: GitHub repository slug.

    Returns:
        Dict with theme_counts, severity_counts, domain_counts, sample_comments,
        and total_comments.
    """
    close_conn = conn is None
    if conn is None:
        conn = _get_connection()

    try:
        rows = conn.execute(
            """SELECT rc.id, rc.pr_number, rc.body, rc.created_at,
                      cc.severity, cc.theme, d.name as domain
               FROM review_comments rc
               JOIN comment_categories cc
                   ON rc.id = cc.comment_id AND cc.comment_type = 'review_comment'
               LEFT JOIN domains d ON cc.domain_id = d.id
               WHERE rc.path = ?
                 AND rc.repo = ?
                 AND cc.theme != 'FAILED_CATEGORIZATION'
                 AND rc.pr_number IN (
                     SELECT DISTINCT pr_number FROM review_comments
                     WHERE path = ? AND repo = ?
                     ORDER BY pr_number DESC LIMIT ?
                 )
               ORDER BY rc.created_at DESC""",
            (file_path, repo, file_path, repo, max_prs),
        ).fetchall()

        if not rows:
            return {
                "file_path": file_path,
                "total_comments": 0,
                "pr_count": 0,
            }

        domain_counts = defaultdict(int)
        severity_counts = defaultdict(int)
        theme_counts = defaultdict(int)
        pr_numbers = set()
        samples = []

        for row in rows:
            row_dict = dict(row)
            domain_counts[row_dict.get("domain", "unknown")] += 1
            severity_counts[row_dict.get("severity", "unknown")] += 1
            theme = row_dict.get("theme", "")
            if theme:
                theme_counts[theme] += 1
            pr_numbers.add(row_dict["pr_number"])

            if len(samples) < 5:
                samples.append({
                    "pr_number": row_dict["pr_number"],
                    "body": row_dict["body"][:300] if row_dict["body"] else "",
                    "severity": row_dict.get("severity"),
                    "domain": row_dict.get("domain"),
                })

        return {
            "file_path": file_path,
            "total_comments": len(rows),
            "pr_count": len(pr_numbers),
            "domain_counts": dict(
                sorted(domain_counts.items(), key=lambda x: -x[1])
            ),
            "severity_counts": dict(
                sorted(severity_counts.items(), key=lambda x: -x[1])
            ),
            "top_themes": dict(
                sorted(theme_counts.items(), key=lambda x: -x[1])[:10]
            ),
            "sample_comments": samples,
        }

    finally:
        if close_conn:
            conn.close()


def get_pr_review_context(
    pr_number: int,
    max_comments: int = 20,
    conn: Optional[sqlite3.Connection] = None,
    repo: str = "micropython/micropython",
) -> Dict[str, Any]:
    """Get full review history for a PR, organized as threads.

    This is the main entry point for the get_pr_review_history MCP tool.

    Args:
        pr_number: GitHub PR number.
        max_comments: Maximum total comments to return.
        conn: Optional database connection.
        repo: GitHub repository slug.

    Returns:
        Dict with 'pr_info', 'threads' (grouped conversations), 'standalone'
        (comments not in threads), and 'review_verdicts'.
    """
    close_conn = conn is None
    if conn is None:
        conn = _get_connection()

    try:
        # PR metadata
        pr_row = conn.execute(
            "SELECT number, title, author, state, created_at, merged_at FROM prs WHERE number = ? AND repo = ?",
            (pr_number, repo),
        ).fetchone()

        pr_info = dict(pr_row) if pr_row else {"number": pr_number}

        # All review comments for this PR
        review_comments = conn.execute(
            """SELECT id, body, path, line, diff_hunk, created_at, in_reply_to_id
               FROM review_comments
               WHERE pr_number = ? AND repo = ?
               ORDER BY created_at""",
            (pr_number, repo),
        ).fetchall()
        review_comments = [dict(r) for r in review_comments]

        # Issue comments
        issue_comments = conn.execute(
            """SELECT id, body, created_at
               FROM issue_comments
               WHERE pr_number = ? AND repo = ?
               ORDER BY created_at""",
            (pr_number, repo),
        ).fetchall()
        issue_comments = [dict(r) for r in issue_comments]

        # Review verdicts
        verdicts = conn.execute(
            """SELECT id, state, body, created_at
               FROM reviews
               WHERE pr_number = ? AND repo = ? AND body IS NOT NULL AND body != ''
               ORDER BY created_at""",
            (pr_number, repo),
        ).fetchall()
        verdicts = [dict(r) for r in verdicts]

        # Group review comments into threads
        threads, standalone = _group_into_threads(review_comments)

        # Truncate to max_comments
        total = sum(len(t) for t in threads) + len(standalone) + len(issue_comments) + len(verdicts)
        if total > max_comments:
            # Prioritize threads and verdicts, trim standalone and issue comments
            standalone = standalone[:max(1, max_comments // 4)]
            issue_comments = issue_comments[:max(1, max_comments // 4)]

        return {
            "pr_info": pr_info,
            "threads": threads,
            "standalone": standalone[:max_comments],
            "issue_comments": issue_comments[:max_comments],
            "review_verdicts": verdicts,
            "comment_count": total,
        }

    finally:
        if close_conn:
            conn.close()


def _group_into_threads(
    comments: List[Dict[str, Any]],
) -> tuple:
    """Group comments into reply threads and standalone comments.

    Returns:
        (threads, standalone) where threads is a list of lists (each a
        conversation thread) and standalone is a list of comments with
        no reply chain.
    """
    # Build parent→children map
    children_map = defaultdict(list)
    comment_map = {c["id"]: c for c in comments}
    has_parent = set()

    for c in comments:
        parent_id = c.get("in_reply_to_id")
        if parent_id is not None:
            children_map[parent_id].append(c["id"])
            has_parent.add(c["id"])

    # Find thread roots (comments that are parents but not children)
    roots = []
    for c in comments:
        if c["id"] in children_map and c["id"] not in has_parent:
            roots.append(c["id"])

    # Build threads via BFS from each root
    threads = []
    in_thread = set()

    for root_id in roots:
        thread = []
        queue = [root_id]
        while queue:
            cid = queue.pop(0)
            if cid in in_thread or cid not in comment_map:
                continue
            in_thread.add(cid)
            thread.append(comment_map[cid])
            for child_id in children_map.get(cid, []):
                queue.append(child_id)

        if thread:
            thread.sort(key=lambda x: x.get("created_at", ""))
            threads.append(thread)

    # Standalone: comments not in any thread
    standalone = [c for c in comments if c["id"] not in in_thread]

    return threads, standalone


def expand_results_with_threads(
    results: List[Dict[str, Any]],
    conn: Optional[sqlite3.Connection] = None,
    max_thread_len: int = 3,
) -> List[Dict[str, Any]]:
    """Post-process retrieval results to attach thread context.

    For each result that is part of a reply chain, attach the thread
    as metadata. This is called from the retriever after MMR selection.

    Args:
        results: Retrieved review results.
        conn: Optional database connection.
        max_thread_len: Maximum thread messages to attach per result.

    Returns:
        Results with 'thread' metadata attached where applicable.
    """
    close_conn = conn is None
    if conn is None:
        conn = _get_connection()

    try:
        for result in results:
            comment_id = result.get("comment_id")
            comment_type = result.get("comment_type")

            if comment_type != "review_comment" or not comment_id:
                continue

            # Check if this comment is part of a thread
            row = conn.execute(
                "SELECT in_reply_to_id FROM review_comments WHERE id = ?",
                (comment_id,),
            ).fetchone()

            if row is None:
                continue

            has_parent = row["in_reply_to_id"] is not None
            has_children = conn.execute(
                "SELECT 1 FROM review_comments WHERE in_reply_to_id = ? LIMIT 1",
                (comment_id,),
            ).fetchone() is not None

            if has_parent or has_children:
                thread = expand_reply_chain(comment_id, conn)
                # Trim to max length, keeping the current comment and neighbors
                if len(thread) > max_thread_len:
                    # Find the current comment's position
                    idx = next(
                        (i for i, t in enumerate(thread) if t["id"] == comment_id),
                        0,
                    )
                    start = max(0, idx - max_thread_len // 2)
                    thread = thread[start : start + max_thread_len]

                # Note: database only contains the lead maintainer's comments.
                # Thread may have gaps where the other participant's
                # messages were (they are not stored).
                result["thread"] = [
                    {
                        "id": t["id"],
                        "body": t["body"][:300] if t["body"] else "",
                        "created_at": t.get("created_at"),
                    }
                    for t in thread
                    if t["id"] != comment_id  # exclude self
                ]

        return results

    finally:
        if close_conn:
            conn.close()
