"""Review-posting MCP tools for the bot deployment.

Extracted from mcp_server.py to eliminate the bidirectional dependency
between the mcp_server and bot packages.
"""

import io
import logging
import os
import re
import urllib.error
import zipfile

logger = logging.getLogger(__name__)


def register_bot_tools(mcp):
    """Register bot tools if bot package is available and bot mode is enabled.

    SECURITY: These tools post reviews to GitHub using the shared installation
    token. The MCP HTTP endpoint intentionally has no application-level auth.
    It relies on Docker network isolation — the mcp-server container is only
    reachable within the bot-internal network. The webhook container is the
    sole client. Do not expose port 9090 outside the Docker network.
    """
    try:
        from bot import github_api as _github_api
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
            Dict with 'review_id', or 'error' with 'review_id': None on failure.
        """
        _check_repo(owner, repo)
        payload = {"commit_id": commit_sha} if commit_sha else None
        try:
            result = _github_api.github_request(
                "POST",
                f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
                payload,
            )
            return {"review_id": result["id"]}
        except urllib.error.HTTPError as e:
            error_body = e.read().decode()[:500] if e.fp else ""
            if e.code == 422 and "pending review" in error_body.lower():
                # "User can only have one pending review per pull request".
                # Dismiss the stale pending review and create a fresh one.
                logger.warning("Pending review already exists on PR #%d, deleting it", pr_number)
                try:
                    reviews = _github_api.github_request(
                        "GET", f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
                    )
                    for rev in reviews:
                        if rev.get("state") == "PENDING":
                            _github_api.github_request(
                                "DELETE",
                                f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews/{rev['id']}",
                            )
                            logger.info("Deleted stale pending review %d", rev["id"])
                    result = _github_api.github_request(
                        "POST",
                        f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
                        payload,
                    )
                    return {"review_id": result["id"]}
                except (urllib.error.HTTPError, urllib.error.URLError) as retry_err:
                    logger.error("create_review retry failed on PR #%d: %s", pr_number, retry_err)
                    return {"error": f"Retry after stale review cleanup failed: {retry_err}", "review_id": None}
            logger.warning(
                "create_review failed (HTTP %d) on PR #%d: %s",
                e.code, pr_number, error_body,
            )
            return {"error": f"HTTP {e.code}: {error_body or e.reason}", "review_id": None}
        except urllib.error.URLError as e:
            logger.warning("create_review network error on PR #%d: %s", pr_number, e)
            return {"error": f"Network error: {e.reason}", "review_id": None}

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
        try:
            result = _github_api.github_request(
                "POST",
                f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews/{review_id}/comments",
                payload,
            )
            return {"comment_id": result["id"]}
        except urllib.error.HTTPError as e:
            error_body = e.read().decode()[:500] if e.fp else ""
            logger.warning(
                "add_review_comment failed (HTTP %d) on %s line %s: %s",
                e.code, path, line, error_body,
            )
            return {
                "error": f"HTTP {e.code}: {error_body or e.reason}",
                "comment_id": None,
                "failed_path": path,
                "failed_line": line,
                "failed_side": side,
            }
        except urllib.error.URLError as e:
            logger.warning("add_review_comment network error on %s line %s: %s", path, line, e)
            return {
                "error": f"Network error: {e.reason}",
                "comment_id": None,
                "failed_path": path,
                "failed_line": line,
                "failed_side": side,
            }

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
            Dict with 'status', or 'error' with 'status': 'failed' on failure.
        """
        _check_repo(owner, repo)
        if event != "COMMENT":
            raise ValueError(
                f"Only 'COMMENT' event is permitted, got '{event}'"
            )
        try:
            _github_api.github_request(
                "POST",
                f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews/{review_id}/events",
                {"body": body, "event": event},
            )
            return {"status": "submitted"}
        except urllib.error.HTTPError as e:
            error_body = e.read().decode()[:500] if e.fp else ""
            logger.warning(
                "submit_review failed (HTTP %d) on PR #%d review %d: %s",
                e.code, pr_number, review_id, error_body,
            )
            return {"error": f"HTTP {e.code}: {error_body or e.reason}", "status": "failed"}
        except urllib.error.URLError as e:
            logger.warning("submit_review network error on PR #%d review %d: %s", pr_number, review_id, e)
            return {"error": f"Network error: {e.reason}", "status": "failed"}

    @mcp.tool()
    def get_check_runs(
        owner: str,
        repo: str,
        ref: str,
    ) -> dict:
        """Get CI check runs for a commit.

        Lists all check runs (CI jobs) for the given commit ref. Use this
        to see which CI checks passed or failed before drilling into
        annotations or logs.

        Args:
            owner: Repository owner (e.g. "micropython").
            repo: Repository name (e.g. "micropython").
            ref: Commit SHA, branch name, or tag.

        Returns:
            Dict with 'total_count' and 'check_runs' list. Each check run
            has: name, status, conclusion, check_run_id, html_url,
            output_title, output_summary, and workflow_run_id (if from
            GitHub Actions).
        """
        _check_repo(owner, repo)
        try:
            all_runs = []
            page = 1
            max_pages = 10  # Cap at 1000 check runs
            while page <= max_pages:
                result = _github_api.github_request(
                    "GET",
                    f"/repos/{owner}/{repo}/commits/{ref}/check-runs"
                    f"?per_page=100&page={page}",
                )
                runs = result.get("check_runs", [])
                all_runs.extend(runs)
                if len(runs) < 100:
                    break
                page += 1

            check_runs = []
            for run in all_runs:
                entry = {
                    "name": run.get("name", ""),
                    "status": run.get("status", ""),
                    "conclusion": run.get("conclusion"),
                    "check_run_id": run.get("id"),
                    "html_url": run.get("html_url", ""),
                    "output_title": (run.get("output") or {}).get("title"),
                    "output_summary": (run.get("output") or {}).get("summary"),
                }
                # Extract workflow_run_id from GitHub Actions check runs
                app = run.get("app") or {}
                if app.get("slug") == "github-actions":
                    details_url = run.get("details_url", "")
                    # URL format: .../actions/runs/{run_id}/job/{job_id}
                    m = re.search(r"/actions/runs/(\d+)", details_url)
                    if m:
                        entry["workflow_run_id"] = int(m.group(1))
                check_runs.append(entry)

            return {
                "total_count": len(check_runs),
                "check_runs": check_runs,
            }
        except urllib.error.HTTPError as e:
            if e.code == 403:
                return {"error": "Missing 'checks: read' permission on the GitHub App", "total_count": 0, "check_runs": []}
            raise

    @mcp.tool()
    def get_check_run_annotations(
        owner: str,
        repo: str,
        check_run_id: int,
    ) -> dict:
        """Get annotations (structured lint/test findings) for a check run.

        Annotations contain file path, line number, and message — ideal for
        linting tools like ruff or codespell that emit structured output.
        Call this for failed check runs before falling back to raw logs.

        Args:
            owner: Repository owner.
            repo: Repository name.
            check_run_id: Check run ID from get_check_runs.

        Returns:
            Dict with 'annotations' list and 'count'. Each annotation has:
            path, start_line, end_line, annotation_level, message, title.
        """
        _check_repo(owner, repo)
        try:
            all_annotations = []
            page = 1
            cap = 100
            while len(all_annotations) < cap:
                result = _github_api.github_request(
                    "GET",
                    f"/repos/{owner}/{repo}/check-runs/{check_run_id}/annotations"
                    f"?per_page=100&page={page}",
                )
                if not result:
                    break
                for ann in result:
                    all_annotations.append({
                        "path": ann.get("path", ""),
                        "start_line": ann.get("start_line"),
                        "end_line": ann.get("end_line"),
                        "annotation_level": ann.get("annotation_level", ""),
                        "message": ann.get("message", ""),
                        "title": ann.get("title"),
                    })
                    if len(all_annotations) >= cap:
                        break
                if len(result) < 100:
                    break
                page += 1

            return {
                "count": len(all_annotations),
                "annotations": all_annotations,
            }
        except urllib.error.HTTPError as e:
            if e.code == 403:
                return {"error": "Missing 'checks: read' permission on the GitHub App", "count": 0, "annotations": []}
            raise

    @mcp.tool()
    def get_workflow_run_log(
        owner: str,
        repo: str,
        workflow_run_id: int,
        job_name: str | None = None,
        tail_lines: int = 200,
    ) -> dict:
        """Get logs from a GitHub Actions workflow run.

        Downloads the log archive and extracts the relevant job's output.
        Use this as a fallback when get_check_run_annotations returns no
        annotations (e.g. build or test failures that don't emit structured
        output).

        Args:
            owner: Repository owner.
            repo: Repository name.
            workflow_run_id: Workflow run ID from get_check_runs.
            job_name: Job name to extract. If None, returns the first
                job found (alphabetically).
            tail_lines: Number of lines from end of log to return (max 500).

        Returns:
            Dict with 'job_name', 'log' (tail of the log text), and
            'truncated' (whether the log was trimmed).
        """
        _check_repo(owner, repo)
        tail_lines = min(tail_lines, 500)
        max_log_bytes = 50 * 1024  # 50KB hard cap on returned text

        try:
            data = _github_api.github_request_binary(
                f"/repos/{owner}/{repo}/actions/runs/{workflow_run_id}/logs",
            )
        except urllib.error.HTTPError as e:
            if e.code == 403:
                return {"error": "Missing 'actions: read' permission on the GitHub App", "job_name": None, "log": "", "truncated": False}
            if e.code == 410:
                return {"error": "Logs have expired (GitHub retains for 90 days)", "job_name": None, "log": "", "truncated": False}
            raise

        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            return {"error": "Invalid ZIP archive from GitHub", "job_name": None, "log": "", "truncated": False}

        with zf:
            # Find the target log file in the ZIP
            # GitHub Actions logs are structured as: {job_name}/{step_number}_{step_name}.txt
            # Or sometimes just flat files. Job folders are top-level directories.
            names = zf.namelist()
            job_dirs = sorted({n.split("/")[0] for n in names if "/" in n})

            selected_dir = None
            if job_name:
                # Exact or substring match
                for d in job_dirs:
                    if d == job_name or job_name.lower() in d.lower():
                        selected_dir = d
                        break
            if not selected_dir and job_dirs:
                # Pick first directory (only option if no job_name specified)
                selected_dir = job_dirs[0]

            if not selected_dir:
                # Flat archive — concatenate all files
                log_parts = []
                for name in sorted(names):
                    try:
                        log_parts.append(zf.read(name).decode("utf-8", errors="replace"))
                    except (OSError, zipfile.BadZipFile):
                        continue
                raw_log = "\n".join(log_parts)
                selected_job = "(all)"
            else:
                selected_job = selected_dir
                job_files = sorted(n for n in names if n.startswith(selected_dir + "/"))
                log_parts = []
                for name in job_files:
                    try:
                        log_parts.append(zf.read(name).decode("utf-8", errors="replace"))
                    except (OSError, zipfile.BadZipFile):
                        continue
                raw_log = "\n".join(log_parts)

        # Strip GitHub Actions timestamps (YYYY-MM-DDTHH:MM:SS.nnnnnnnZ prefix)
        # and ANSI escape codes
        cleaned_lines = []
        for line in raw_log.splitlines():
            # Strip timestamp prefix
            line = re.sub(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z\s?", "", line)
            # Strip ANSI escapes
            line = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", line)
            cleaned_lines.append(line)

        # Tail and cap
        truncated = len(cleaned_lines) > tail_lines
        tail = cleaned_lines[-tail_lines:]
        log_text = "\n".join(tail)
        if len(log_text) > max_log_bytes:
            log_text = log_text[-max_log_bytes:]
            truncated = True

        return {
            "job_name": selected_job,
            "log": log_text,
            "truncated": truncated,
        }
