"""Issue triage MCP tools for the bot deployment.

Registered alongside review-posting tools when MPY_REVIEWER_BOT_MODE is set.
"""

import logging
import os
import tomllib
import urllib.error

logger = logging.getLogger(__name__)


def _load_target_repos() -> set[str]:
    """Load target repos from bot.toml (via BOT_CONFIG_PATH) or env var fallback."""
    config_path = os.environ.get("BOT_CONFIG_PATH")
    if config_path:
        try:
            with open(config_path, "rb") as f:
                raw = tomllib.load(f)
            target = raw.get("target", {})
            repos = target.get("repos") or target.get("repo")
            if isinstance(repos, str):
                repos = [repos]
            if repos:
                return set(repos)
        except (FileNotFoundError, PermissionError, tomllib.TOMLDecodeError) as e:
            logger.warning("Failed to read target repos from %s: %s", config_path, e)
    raw = os.environ.get("BOT_TARGET_REPOS", "micropython/micropython")
    return {r.strip() for r in raw.split(",") if r.strip()}


def register_triage_bot_tools(mcp):
    """Register triage tools for the bot deployment."""
    try:
        from bot import github_api as _github_api
    except ImportError:
        return

    if not os.environ.get("MPY_REVIEWER_BOT_MODE"):
        return

    target_repos = _load_target_repos()

    def _check_repo(owner: str, repo: str):
        full = f"{owner}/{repo}"
        if full not in target_repos:
            raise ValueError(f"Repository {full} not in target repos")

    @mcp.tool()
    def add_issue_labels(
        owner: str,
        repo: str,
        issue_number: int,
        labels: list[str],
    ) -> dict:
        """Add labels to a GitHub issue.

        Args:
            owner: Repository owner (e.g. "micropython").
            repo: Repository name (e.g. "micropython").
            issue_number: Issue number.
            labels: List of label names to add.

        Returns:
            Dict with 'labels_added' count or 'error'.
        """
        _check_repo(owner, repo)

        from triage.labels import VALID_LABELS
        invalid = [l for l in labels if l not in VALID_LABELS]
        if invalid:
            return {"error": f"Invalid labels: {invalid}. Valid: {sorted(VALID_LABELS)}"}

        try:
            _github_api.github_request(
                "POST",
                f"/repos/{owner}/{repo}/issues/{issue_number}/labels",
                {"labels": labels},
            )
            logger.info("Added labels %s to issue #%d", labels, issue_number)
            return {"labels_added": len(labels)}
        except urllib.error.HTTPError as e:
            error_body = e.read().decode()[:500] if e.fp else ""
            logger.warning("add_issue_labels failed (HTTP %d): %s", e.code, error_body)
            return {"error": f"HTTP {e.code}: {error_body or e.reason}"}
        except urllib.error.URLError as e:
            return {"error": f"Network error: {e.reason}"}

    @mcp.tool()
    def post_issue_comment(
        owner: str,
        repo: str,
        issue_number: int,
        body: str,
    ) -> dict:
        """Post a comment on a GitHub issue.

        Args:
            owner: Repository owner (e.g. "micropython").
            repo: Repository name (e.g. "micropython").
            issue_number: Issue number.
            body: Comment body text (markdown).

        Returns:
            Dict with 'comment_id' or 'error'.
        """
        _check_repo(owner, repo)

        try:
            result = _github_api.github_request(
                "POST",
                f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
                {"body": body},
            )
            logger.info("Posted triage comment on issue #%d", issue_number)
            return {"comment_id": result["id"]}
        except urllib.error.HTTPError as e:
            error_body = e.read().decode()[:500] if e.fp else ""
            logger.warning("post_issue_comment failed (HTTP %d): %s", e.code, error_body)
            return {"error": f"HTTP {e.code}: {error_body or e.reason}"}
        except urllib.error.URLError as e:
            return {"error": f"Network error: {e.reason}"}
