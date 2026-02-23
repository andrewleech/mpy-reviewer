"""Review-posting MCP tools for the bot deployment.

Extracted from mcp_server.py to eliminate the bidirectional dependency
between the mcp_server and bot packages.
"""

import os


def register_bot_tools(mcp):
    """Register bot tools if bot package is available and bot mode is enabled.

    SECURITY: These tools post reviews to GitHub using the shared installation
    token. The MCP HTTP endpoint intentionally has no application-level auth.
    It relies on Docker network isolation — the mcp-server container is only
    reachable within the bot-internal network. The webhook container is the
    sole client. Do not expose port 9090 outside the Docker network.
    """
    try:
        from bot.github_api import github_request
    except ImportError:
        return

    if not os.environ.get("MPY_REVIEWER_BOT_MODE"):
        return

    target_repo = os.environ.get("BOT_TARGET_REPO", "micropython/micropython")

    def _check_repo(owner: str, repo: str):
        """Reject requests targeting repos other than the configured target."""
        if f"{owner}/{repo}" != target_repo:
            raise ValueError(
                f"Repository {owner}/{repo} does not match "
                f"target repo {target_repo}"
            )

    @mcp.tool()
    def create_review(
        owner: str,
        repo: str,
        pr_number: int,
        commit_sha: str | None = None,
    ) -> dict:
        """Create a pending review on a GitHub PR.

        Creates a PENDING review that can accumulate inline comments before
        being submitted. Use add_review_comment to attach comments, then
        submit_review to make everything visible.

        Args:
            owner: Repository owner (e.g. "micropython").
            repo: Repository name (e.g. "micropython").
            pr_number: Pull request number.
            commit_sha: Optional commit SHA to pin the review to.

        Returns:
            Dict with 'review_id'.
        """
        _check_repo(owner, repo)
        body = {"commit_id": commit_sha} if commit_sha else None
        result = github_request(
            "POST", f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews", body
        )
        return {"review_id": result["id"]}

    @mcp.tool()
    def add_review_comment(
        owner: str,
        repo: str,
        pr_number: int,
        review_id: int,
        path: str,
        body: str,
        line: int | None = None,
        side: str = "RIGHT",
    ) -> dict:
        """Add an inline comment to a pending GitHub PR review.

        Args:
            owner: Repository owner.
            repo: Repository name.
            pr_number: Pull request number.
            review_id: Review ID from create_review.
            path: File path relative to repo root.
            body: Comment text.
            line: Line number in the diff. If None, attaches to the file.
            side: "RIGHT" (new/added, default) or "LEFT" (old/deleted).

        Returns:
            Dict with 'comment_id'.
        """
        _check_repo(owner, repo)
        payload = {"path": path, "body": body, "side": side}
        if line is not None:
            payload["line"] = line
        result = github_request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews/{review_id}/comments",
            payload,
        )
        return {"comment_id": result["id"]}

    @mcp.tool()
    def submit_review(
        owner: str,
        repo: str,
        pr_number: int,
        review_id: int,
        body: str,
        event: str = "COMMENT",
    ) -> dict:
        """Submit a pending review, making all comments visible.

        Args:
            owner: Repository owner.
            repo: Repository name.
            pr_number: Pull request number.
            review_id: Review ID from create_review.
            body: Review summary text.
            event: Review event — only "COMMENT" is permitted.

        Returns:
            Dict with 'status'.
        """
        _check_repo(owner, repo)
        if event != "COMMENT":
            raise ValueError(
                f"Only 'COMMENT' event is permitted, got '{event}'"
            )
        github_request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews/{review_id}/events",
            {"body": body, "event": event},
        )
        return {"status": "submitted"}
