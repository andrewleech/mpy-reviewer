"""Review orchestration — spawns claude -p per review.

Handles git checkout updates, MCP config generation, subprocess management,
and timeout enforcement.
"""

import asyncio
import fcntl
import json
import logging
import os
import tempfile
import urllib.error

from bot.config import BotConfig
from bot.github_api import github_request
from bot.github_app import GitHubAppAuth
from bot.prompt import build_system_prompt, build_user_message
from bot.review_queue import ReviewRequest

logger = logging.getLogger(__name__)

MAX_DIFF_CHARS = 1_000_000
_CHECKOUT_LOCK = os.path.join(tempfile.gettempdir(), "mpy-checkout.lock")


def _get_mpy_checkout() -> str:
    """Return MicroPython checkout path from env. Evaluated per-call."""
    return os.environ.get("MPY_CHECKOUT", "/workspace/micropython")


class DiffTooLargeError(Exception):
    """Raised when PR diff exceeds MAX_DIFF_CHARS."""


async def run_review(
    request: ReviewRequest, config: BotConfig, auth: GitHubAppAuth | None = None,
) -> bool:
    """Execute a full review cycle for a PR.

    1. Update MicroPython checkout to PR head
    2. Build system prompt and user message
    3. Spawn claude -p with MCP config
    4. Wait for completion (with timeout)

    Args:
        request: The review request from the queue.
        config: Bot configuration.
        auth: GitHub App authentication (optional).

    Returns:
        True on success, False on failure.
    """
    token = auth.get_token() if auth else None

    # Re-fetch PR metadata — title/body may have changed since webhook receipt.
    try:
        pr_data = await asyncio.to_thread(
            github_request,
            "GET",
            f"/repos/{request.repo_owner}/{request.repo_name}/pulls/{request.pr_number}",
            token=token,
        )
    except Exception as e:
        logger.error("Failed to fetch PR #%d metadata: %s", request.pr_number, e)
        return False

    pr_title = pr_data.get("title", "")
    pr_body = pr_data.get("body", "") or ""
    head_sha = pr_data.get("head", {}).get("sha", "") or request.head_sha

    if not head_sha:
        logger.error("No head SHA available for PR #%d", request.pr_number)
        return False
    # Fetch the diff
    diff_text = await _fetch_pr_diff(
        request.repo_owner, request.repo_name, request.pr_number, token
    )
    if not diff_text:
        logger.error("Empty diff for PR #%d", request.pr_number)
        return False

    if len(diff_text) > MAX_DIFF_CHARS:
        raise DiffTooLargeError(
            f"Diff for PR #{request.pr_number} exceeds {MAX_DIFF_CHARS:,} chars "
            f"({len(diff_text):,} chars). Split into smaller PRs."
        )

    # Update checkout
    checkout_ok = await _update_checkout(request.pr_number, head_sha)
    if not checkout_ok:
        logger.error("Checkout failed for PR #%d, proceeding with current HEAD", request.pr_number)

    # Build prompts
    system_prompt = build_system_prompt(
        additional_system_prompt=config.prompt.additional_system_prompt,
        top_k=config.review.top_k,
        include_codebase=config.review.include_codebase,
    )

    user_message = build_user_message(
        diff_text=diff_text,
        pr_number=request.pr_number,
        pr_title=pr_title,
        pr_body=pr_body,
        repo_owner=request.repo_owner,
        repo_name=request.repo_name,
        head_sha=head_sha,
    )

    # Write temporary MCP config for claude -p
    mcp_config = _build_mcp_config(config)
    mcp_config_path = _write_temp_json(mcp_config, prefix="mcp-config-")

    # System prompt is passed as a CLI argument. It contains review guidelines
    # and the additional_system_prompt from config — no credentials or tokens.
    # /proc visibility is mitigated by pid:private in docker-compose.yml.
    # If running without PID isolation, write to a temp file and pass via
    # --system-prompt-file (requires Claude CLI support).
    cmd = [
        "claude", "-p",
        "--model", config.review.model,
        "--output-format", "text",
        "--dangerously-skip-permissions",
        "--system-prompt", system_prompt,
        "--mcp-config", mcp_config_path,
        "--allowedTools",
        ",".join([
            "mcp__mpy-reviewer__review_pr",
            "mcp__mpy-reviewer__review_diff",
            "mcp__mpy-reviewer__search_reviews",
            "mcp__mpy-reviewer__find_style_examples",
            "mcp__mpy-reviewer__get_review_stats",
            "mcp__mpy-reviewer__get_pr_review_history",
            "mcp__mpy-reviewer__create_review",
            "mcp__mpy-reviewer__add_review_comment",
            "mcp__mpy-reviewer__submit_review",
            "Read", "Glob", "Grep",
        ]),
    ]

    # Set up environment
    env = os.environ.copy()
    if config.auth.claude_oauth_path:
        env["CLAUDE_CONFIG_DIR"] = config.auth.claude_oauth_path

    logger.info(
        "Spawning claude -p for PR #%d (model=%s, timeout=%ds)",
        request.pr_number, config.review.model, config.review.timeout_seconds,
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=_get_mpy_checkout(),
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=user_message.encode()),
            timeout=config.review.timeout_seconds,
        )

        if proc.returncode != 0:
            logger.error(
                "claude -p failed for PR #%d (rc=%d): %s",
                request.pr_number, proc.returncode, stderr.decode()[:1000],
            )
            return False

        logger.info(
            "claude -p completed for PR #%d (rc=%d, stdout=%d bytes)",
            request.pr_number, proc.returncode, len(stdout),
        )
        return True

    except asyncio.TimeoutError:
        logger.error(
            "claude -p timed out for PR #%d after %ds",
            request.pr_number, config.review.timeout_seconds,
        )
        try:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        except Exception as e:
            logger.debug("Subprocess cleanup after timeout: %s", e)
        return False
    finally:
        # Clean up temp file
        try:
            os.unlink(mcp_config_path)
        except OSError:
            pass


async def _fetch_pr_diff(
    owner: str, repo: str, pr_number: int, token: str | None
) -> str:
    """Fetch the PR diff via GitHub API."""
    def _do_fetch() -> str:
        try:
            return github_request(
                "GET",
                f"/repos/{owner}/{repo}/pulls/{pr_number}",
                token=token,
                accept="application/vnd.github.diff",
                raw=True,
            ) or ""
        except urllib.error.HTTPError as e:
            if e.code == 403:
                logger.error("Rate limited fetching diff for PR #%d", pr_number)
            elif e.code == 404:
                logger.error("PR #%d not found", pr_number)
            else:
                logger.error("Failed to fetch diff for PR #%d: HTTP %d", pr_number, e.code)
            return ""
        except urllib.error.URLError as e:
            logger.error("Network error fetching diff for PR #%d: %s", pr_number, e)
            return ""
    return await asyncio.to_thread(_do_fetch)


async def _update_checkout(pr_number: int, head_sha: str) -> bool:
    """Update the shared MicroPython checkout to the PR's head commit.

    Returns True on success, False on failure.
    The ReviewQueue serializes reviews, so concurrent checkouts are not expected.
    The flock is defense-in-depth against future parallel workers or manual
    CLI invocations sharing the same checkout directory.

    The MCP server shares this volume. File reads during review are safe because
    the claude -p subprocess (which calls MCP tools) is only spawned after
    checkout completes. Do not run MCP reads concurrently with checkout.
    """
    mpy_checkout = _get_mpy_checkout()
    if not os.path.isdir(os.path.join(mpy_checkout, ".git")):
        logger.warning("MicroPython checkout not found at %s", mpy_checkout)
        return False

    # os.open is a fast syscall — acceptable on the event loop thread.
    lock_fd = os.open(_CHECKOUT_LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        await asyncio.to_thread(fcntl.flock, lock_fd, fcntl.LOCK_EX)

        async def _run_git(*args: str, timeout: int = 120) -> bool:
            proc = await asyncio.create_subprocess_exec(
                "git", *args,
                cwd=mpy_checkout,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                logger.error("git %s timed out after %ds", args[0], timeout)
                return False
            if proc.returncode != 0:
                logger.error(
                    "git %s failed (rc=%d): %s",
                    args[0], proc.returncode, stderr.decode()[:200],
                )
                return False
            return True

        try:
            if not await _run_git("checkout", "--", "."):
                return False
            if not await _run_git("clean", "-fd", "-e", ".codanna/"):
                return False
            if not await _run_git("fetch", "origin", f"refs/pull/{pr_number}/head"):
                return False
            if not await _run_git("checkout", "--detach", "FETCH_HEAD"):
                return False

            # Verify checkout landed on expected SHA
            proc = await asyncio.create_subprocess_exec(
                "git", "rev-parse", "HEAD", cwd=mpy_checkout,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            except asyncio.TimeoutError:
                proc.kill()
                logger.error("git rev-parse HEAD timed out")
                return False
            actual_sha = stdout.decode().strip()
            if actual_sha != head_sha:
                logger.warning(
                    "Checkout SHA mismatch for PR #%d: expected %s, got %s",
                    pr_number, head_sha[:8], actual_sha[:8],
                )
                return False
        except Exception as e:
            logger.warning("Failed to update checkout for PR #%d: %s", pr_number, e)
            return False
    finally:
        # Synchronous unlock + close — fast syscalls, no event loop concern.
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)

    logger.info("Checkout updated to PR #%d (%s)", pr_number, head_sha[:8])
    return True


def _build_mcp_config(config: BotConfig) -> dict:
    """Build the MCP client config JSON for claude -p."""
    return {
        "mcpServers": {
            "mpy-reviewer": {
                "command": "python",
                "args": ["mcp_server.py"],
                "cwd": "/app",
                "env": {
                    "GITHUB_TOKEN_FILE": os.environ.get(
                        "GITHUB_TOKEN_FILE", "/var/run/token/github_token"
                    ),
                    "MPY_CHECKOUT": os.environ.get(
                        "MPY_CHECKOUT", "/workspace/micropython"
                    ),
                    "MPY_REVIEWER_BOT_MODE": "1",
                },
            }
        }
    }


def _write_temp_json(data: dict, prefix: str = "mcp-") -> str:
    """Write a dict as JSON to a temp file, return the path."""
    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".json")
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    return path
