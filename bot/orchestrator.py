"""Review orchestration -- multi-agent review pipeline.

Spawns 4 parallel domain review agents (sonnet) and 1 validation agent (opus)
as claude -p subprocesses. Posts results via post-review.py CLI.
No MCP server dependency for the review pipeline.
"""

import asyncio
import fcntl
import json
import logging
import os
import re
import subprocess
import tempfile
import urllib.error
from pathlib import Path

from bot.config import BotConfig
from bot.github_api import github_request
from bot.github_app import GitHubAppAuth
from bot.prompt import annotate_diff, build_user_message
from bot.review_queue import ReviewRequest

logger = logging.getLogger(__name__)

MAX_DIFF_CHARS = 1_000_000
_CHECKOUT_LOCK = os.path.join(tempfile.gettempdir(), "mpy-checkout.lock")

# Multi-agent review configuration
DOMAIN_MODEL = "sonnet"
VALIDATION_MODEL = "opus"
MAX_PARALLEL_AGENTS = 4
AGENT_TIMEOUT = 300  # Per-agent timeout in seconds
AGENT_BUDGET = "1.00"  # Max budget per domain agent

DOMAIN_AGENTS = [
    ("correctness-safety", "correctness-safety.md"),
    ("resource-constraints", "resource-constraints.md"),
    ("api-portability", "api-portability.md"),
    ("conventions-completeness", "conventions-completeness.md"),
]

# JSON schema for domain agent findings output
FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "line": {"type": "integer"},
                    "side": {"type": "string", "enum": ["RIGHT", "LEFT"]},
                    "severity": {"type": "string", "enum": ["blocking", "suggestion", "nitpick"]},
                    "dimension": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "recommendation": {"type": "string"},
                    "diff_hunk": {"type": "string"},
                    "commit": {"type": "string"},
                },
                "required": ["file", "line", "severity", "title", "description"],
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["findings"],
}


def _get_mpy_checkout() -> str:
    """Return MicroPython checkout path from env. Evaluated per-call."""
    return os.environ.get("MPY_CHECKOUT", "/workspace/micropython")


class ReviewError(Exception):
    """Base class for review failures with user-facing messages."""

    user_message: str = "Review failed due to an unexpected error. Retry with `/review`."

    def __init__(self, message: str | None = None, user_message: str | None = None):
        super().__init__(message or self.user_message)
        if user_message is not None:
            self.user_message = user_message


class DiffTooLargeError(ReviewError):
    """Raised when PR diff exceeds MAX_DIFF_CHARS."""

    user_message = "Diff is too large for automated review. Please split into smaller PRs."


class PromptTooLongError(ReviewError):
    """Raised when the prompt exceeds the model's context limit."""

    user_message = "PR content exceeds the model's context limit. Please split into smaller PRs."


class RateLimitedError(ReviewError):
    """Raised when the API returns a rate limit error."""

    user_message = "Review is temporarily rate-limited. Retry with `/review` in a few minutes."


class ReviewTimeoutError(ReviewError):
    """Raised when the review subprocess times out."""

    user_message = "Review timed out. The PR may be too complex for a single pass. Retry with `/review`."


class MetadataFetchError(ReviewError):
    """Raised when PR metadata cannot be fetched."""

    user_message = "Could not fetch PR metadata from GitHub. Retry with `/review`."


class EmptyDiffError(ReviewError):
    """Raised when the PR diff is empty."""

    user_message = "PR has an empty diff — nothing to review."


class DiffFetchError(ReviewError):
    """Raised when the PR diff cannot be fetched from GitHub."""

    user_message = "Could not fetch PR diff from GitHub. Retry with `/review`."


def _get_prompts_dir() -> Path:
    """Return the path to review prompt files.

    Looks for mpy-rules submodule first, then falls back to env var.
    """
    # Submodule path relative to this repo
    repo_root = Path(__file__).parent.parent
    submodule = repo_root / "mpy-rules-repo" / "plugins" / "mpy-rules" / "prompts"
    if submodule.is_dir():
        return submodule

    # Env var override
    env_path = os.environ.get("MPY_REVIEW_PROMPTS_DIR")
    if env_path:
        p = Path(env_path)
        if p.is_dir():
            return p

    # Canonical plugin location
    canonical = Path.home() / ".claude" / "mpy-rules"
    if canonical.is_dir():
        return canonical

    raise ReviewError(
        "Cannot find review prompt files. Set MPY_REVIEW_PROMPTS_DIR or "
        "initialize the mpy-rules submodule.",
        user_message="Review system misconfigured -- prompt files not found.",
    )


def _get_rules_dir() -> Path:
    """Return the path to rules files (development-patterns.md etc.)."""
    repo_root = Path(__file__).parent.parent
    submodule = repo_root / "mpy-rules-repo" / "plugins" / "mpy-rules" / "rules"
    if submodule.is_dir():
        return submodule
    canonical = Path.home() / ".claude" / "mpy-rules"
    if canonical.is_dir():
        return canonical
    return _get_prompts_dir().parent / "rules"


def _get_post_review_script() -> Path:
    """Return the path to the post-review.py CLI script."""
    repo_root = Path(__file__).parent.parent
    submodule = repo_root / "mpy-rules-repo" / "plugins" / "mpy-rules" / "scripts" / "post-review.py"
    if submodule.is_file():
        return submodule
    env_path = os.environ.get("MPY_POST_REVIEW_SCRIPT")
    if env_path:
        return Path(env_path)
    raise ReviewError(
        "Cannot find post-review.py script.",
        user_message="Review system misconfigured -- post-review script not found.",
    )


def _load_prompt_file(path: Path) -> str:
    """Read a prompt file, raising ReviewError if missing."""
    try:
        return path.read_text()
    except FileNotFoundError:
        raise ReviewError(f"Missing prompt file: {path}")


async def _run_domain_agent(
    dimension: str,
    prompt_file: str,
    system_prompt: str,
    user_message: str,
    env: dict,
    cwd: str,
    timeout: int = AGENT_TIMEOUT,
) -> list[dict]:
    """Spawn a single domain review agent as a claude -p subprocess.

    Returns a list of finding dicts. On failure, returns empty list.
    """
    cmd = [
        "claude", "-p",
        "--model", DOMAIN_MODEL,
        "--output-format", "json",
        "--json-schema", json.dumps(FINDINGS_SCHEMA),
        "--dangerously-skip-permissions",
        "--system-prompt", system_prompt,
        "--allowedTools", "Read,Glob,Grep",
        "--max-budget-usd", AGENT_BUDGET,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=cwd,
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=user_message.encode()),
            timeout=timeout,
        )

        if proc.returncode != 0:
            logger.error(
                "Domain agent %s failed (rc=%d): %s",
                dimension, proc.returncode, stderr.decode(errors="replace")[:500],
            )
            return []

        # Parse structured JSON output
        try:
            output = json.loads(stdout.decode())
        except json.JSONDecodeError:
            logger.error("Bad JSON from domain agent %s", dimension)
            return []

        # Extract findings from structured_output wrapper
        structured = output
        if isinstance(output, dict) and "structured_output" in output:
            structured = output["structured_output"]

        findings = []
        if isinstance(structured, dict):
            findings = structured.get("findings", [])
        elif isinstance(structured, list):
            findings = structured

        # Tag each finding with its dimension
        for f in findings:
            if isinstance(f, dict):
                f.setdefault("dimension", dimension)

        logger.info("Domain agent %s returned %d findings", dimension, len(findings))
        return findings

    except asyncio.TimeoutError:
        logger.error("Domain agent %s timed out after %ds", dimension, timeout)
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        return []
    except Exception as e:
        logger.error("Domain agent %s error: %s", dimension, e)
        return []


async def _run_validation_agent(
    system_prompt: str,
    user_message: str,
    env: dict,
    cwd: str,
    timeout: int = AGENT_TIMEOUT * 2,
) -> str:
    """Spawn the validation agent. Returns raw text output."""
    cmd = [
        "claude", "-p",
        "--model", VALIDATION_MODEL,
        "--output-format", "text",
        "--dangerously-skip-permissions",
        "--system-prompt", system_prompt,
        "--allowedTools", "Read,Glob,Grep",
        "--max-budget-usd", "2.00",
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=cwd,
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=user_message.encode()),
            timeout=timeout,
        )

        if proc.returncode != 0:
            logger.error(
                "Validation agent failed (rc=%d): %s",
                proc.returncode, stderr.decode(errors="replace")[:500],
            )
            return ""

        return stdout.decode(errors="replace")

    except asyncio.TimeoutError:
        logger.error("Validation agent timed out after %ds", timeout)
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        return ""
    except Exception as e:
        logger.error("Validation agent error: %s", e)
        return ""


async def _post_review_via_cli(
    findings_json: dict,
    repo_owner: str,
    repo_name: str,
    pr_number: int,
    head_sha: str,
    diff_path: str | None = None,
    token: str | None = None,
) -> dict:
    """Post review via post-review.py CLI script."""
    script = _get_post_review_script()

    cmd = [
        "python3", str(script),
        "--repo", f"{repo_owner}/{repo_name}",
        "--pr", str(pr_number),
    ]
    if head_sha:
        cmd.extend(["--head-sha", head_sha])
    if diff_path:
        cmd.extend(["--diff", diff_path])
    if token:
        cmd.extend(["--token", token])
    else:
        token_file = os.environ.get("GITHUB_TOKEN_FILE")
        if token_file:
            cmd.extend(["--token-file", token_file])

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            input=json.dumps(findings_json),
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            logger.error("post-review.py failed (rc=%d): %s",
                         result.returncode, result.stderr[:500])
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return {"error": f"post-review.py failed (rc={result.returncode})"}

        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return {"error": "post-review.py timed out"}
    except Exception as e:
        return {"error": f"post-review.py error: {e}"}


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
        True on success.

    Raises:
        ReviewError: On any expected failure (subclass indicates cause).
    """
    token = auth.get_token(request.installation_id) if auth else None

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
        raise MetadataFetchError(
            f"Failed to fetch PR #{request.pr_number} metadata: {e}"
        ) from e

    pr_title = pr_data.get("title", "")
    pr_body = pr_data.get("body", "") or ""
    head_sha = pr_data.get("head", {}).get("sha", "") or request.head_sha

    if not head_sha:
        logger.error("No head SHA available for PR #%d", request.pr_number)
        raise MetadataFetchError(
            f"No head SHA available for PR #{request.pr_number}"
        )
    # Fetch the diff — returns None on fetch failure, "" on genuinely empty diff.
    diff_text = await _fetch_pr_diff(
        request.repo_owner, request.repo_name, request.pr_number, token
    )
    if diff_text is None:
        logger.error("Failed to fetch diff for PR #%d", request.pr_number)
        raise DiffFetchError(f"Failed to fetch diff for PR #{request.pr_number}")
    if not diff_text:
        logger.error("Empty diff for PR #%d", request.pr_number)
        raise EmptyDiffError(f"Empty diff for PR #{request.pr_number}")

    if len(diff_text) > MAX_DIFF_CHARS:
        raise DiffTooLargeError(
            f"Diff for PR #{request.pr_number} exceeds {MAX_DIFF_CHARS:,} chars "
            f"({len(diff_text):,} chars). Split into smaller PRs."
        )

    # Update checkout
    checkout_ok = await _update_checkout(
        request.pr_number, head_sha, request.repo_owner, request.repo_name,
    )
    if not checkout_ok:
        logger.error("Checkout failed for PR #%d, proceeding with current HEAD", request.pr_number)

    # Load prompt files
    prompts_dir = _get_prompts_dir()
    rules_dir = _get_rules_dir()
    shared_context = _load_prompt_file(prompts_dir / "shared-context.md")
    dev_patterns = _load_prompt_file(rules_dir / "development-patterns.md")
    validation_prompt = _load_prompt_file(prompts_dir / "finding-validation.md")

    # Annotate diff with L/R line numbers for agent reference
    annotated_diff = annotate_diff(diff_text)

    # Build the user message with PR metadata and annotated diff
    user_msg = build_user_message(
        diff_text=diff_text,
        pr_number=request.pr_number,
        pr_title=pr_title,
        pr_body=pr_body,
        repo_owner=request.repo_owner,
        repo_name=request.repo_name,
        head_sha=head_sha,
    )

    # Write diff to temp file for agent file reads
    diff_path = _write_temp_file(annotated_diff, prefix="mpy-diff-", suffix=".patch")

    try:
        return await _run_multi_agent_review(
            request, config, token, diff_text, pr_title, pr_body, head_sha,
            shared_context, dev_patterns, validation_prompt, prompts_dir,
            user_msg, diff_path,
        )
    finally:
        try:
            os.unlink(diff_path)
        except OSError:
            pass


async def _run_multi_agent_review(
    request: ReviewRequest,
    config: BotConfig,
    token: str | None,
    diff_text: str,
    pr_title: str,
    pr_body: str,
    head_sha: str,
    shared_context: str,
    dev_patterns: str,
    validation_prompt: str,
    prompts_dir: Path,
    user_msg: str,
    diff_path: str,
) -> bool:
    """Run the multi-agent review pipeline and post results."""
    # Set up environment for all agents
    env = os.environ.copy()
    if config.auth.claude_oauth_path:
        env["CLAUDE_CONFIG_DIR"] = config.auth.claude_oauth_path

    mpy_checkout = _get_mpy_checkout()

    # --- Phase 1: Spawn domain agents in parallel ---
    logger.info(
        "Spawning %d domain review agents for PR #%d",
        len(DOMAIN_AGENTS), request.pr_number,
    )

    sem = asyncio.Semaphore(MAX_PARALLEL_AGENTS)

    async def _guarded_domain_agent(dimension: str, prompt_file: str) -> list[dict]:
        async with sem:
            domain_criteria = _load_prompt_file(prompts_dir / prompt_file)
            system = shared_context + "\n\n" + dev_patterns
            user = (
                f"# Review Dimension: {dimension}\n\n"
                f"{domain_criteria}\n\n"
                f"# PR Under Review\n\n"
                f"Full diff file: {diff_path}\n\n"
                f"{user_msg}"
            )
            return await _run_domain_agent(
                dimension, prompt_file, system, user, env, mpy_checkout,
            )

    coros = [
        _guarded_domain_agent(dim, pfile) for dim, pfile in DOMAIN_AGENTS
    ]
    results = await asyncio.gather(*coros, return_exceptions=True)

    # Collect findings from all agents
    all_findings = []
    agents_succeeded = 0
    for i, result in enumerate(results):
        dim_name = DOMAIN_AGENTS[i][0]
        if isinstance(result, Exception):
            logger.error("Domain agent %s raised: %s", dim_name, result)
        elif isinstance(result, list):
            all_findings.extend(result)
            agents_succeeded += 1
        else:
            agents_succeeded += 1

    logger.info(
        "Domain agents: %d/%d succeeded, %d total findings for PR #%d",
        agents_succeeded, len(DOMAIN_AGENTS), len(all_findings), request.pr_number,
    )

    if not all_findings:
        logger.warning("No findings from any domain agent for PR #%d", request.pr_number)
        # Post a clean review
        post_result = await _post_review_via_cli(
            {"summary": "No issues found.", "findings": []},
            request.repo_owner, request.repo_name, request.pr_number,
            head_sha, diff_path, token,
        )
        logger.info("Posted clean review for PR #%d: %s", request.pr_number, post_result)
        return True

    # --- Phase 2: Spawn validation agent ---
    logger.info(
        "Spawning validation agent for PR #%d (%d findings to validate)",
        request.pr_number, len(all_findings),
    )

    validation_system = shared_context + "\n\n" + dev_patterns + "\n\n" + validation_prompt
    validation_user = (
        "# Raw Findings from Review Agents\n\n"
        f"```json\n{json.dumps(all_findings, indent=2)}\n```\n\n"
        f"# Review Context\n\n"
        f"Full diff file: {diff_path}\n\n"
        f"{user_msg}"
    )

    validation_output = await _run_validation_agent(
        validation_system, validation_user, env, mpy_checkout,
    )

    # Parse validation output to extract KEEP/QUESTIONABLE findings
    # The validation agent returns text with [KEEP], [QUESTIONABLE], [INVALID] markers
    validated_findings = _parse_validation_output(validation_output, all_findings)

    logger.info(
        "Validation: %d KEEP, %d QUESTIONABLE, %d INVALID for PR #%d",
        sum(1 for f in validated_findings if f.get("status") == "KEEP"),
        sum(1 for f in validated_findings if f.get("status") == "QUESTIONABLE"),
        sum(1 for f in validated_findings if f.get("status") == "INVALID"),
        request.pr_number,
    )

    # Build summary
    blocking = sum(1 for f in validated_findings
                   if f.get("status") in ("KEEP", "QUESTIONABLE") and f.get("severity") == "blocking")
    suggestion = sum(1 for f in validated_findings
                     if f.get("status") in ("KEEP", "QUESTIONABLE") and f.get("severity") == "suggestion")
    nitpick = sum(1 for f in validated_findings
                  if f.get("status") in ("KEEP", "QUESTIONABLE") and f.get("severity") == "nitpick")

    summary_parts = []
    if blocking:
        summary_parts.append(f"{blocking} blocking")
    if suggestion:
        summary_parts.append(f"{suggestion} suggestion")
    if nitpick:
        summary_parts.append(f"{nitpick} nitpick")
    summary = f"Review of PR #{request.pr_number}: {', '.join(summary_parts) or 'no issues found'}."
    if agents_succeeded < len(DOMAIN_AGENTS):
        summary += f" ({agents_succeeded}/{len(DOMAIN_AGENTS)} review dimensions completed.)"

    # --- Phase 3: Post review ---
    post_payload = {
        "summary": summary,
        "findings": validated_findings,
    }

    post_result = await _post_review_via_cli(
        post_payload, request.repo_owner, request.repo_name,
        request.pr_number, head_sha, diff_path, token,
    )

    if "error" in post_result:
        logger.error("Failed to post review for PR #%d: %s",
                      request.pr_number, post_result["error"])
        raise ReviewError(
            f"Failed to post review: {post_result['error']}",
            user_message="Review completed but could not post to GitHub. Retry with `/review`.",
        )

    logger.info(
        "Review posted for PR #%d: review_id=%s, %d comments",
        request.pr_number, post_result.get("review_id"), post_result.get("comment_count", 0),
    )

    return True


_RATE_LIMIT_RE = re.compile(r"rate.?limit|status[:\s]+429|\b429\b.*too many", re.IGNORECASE)


def _classify_claude_failure(combined_output: str, returncode: int) -> ReviewError:
    """Map claude -p failure output to a typed ReviewError."""
    if "prompt is too long" in combined_output:
        return PromptTooLongError(f"claude -p failed: prompt is too long (rc={returncode})")
    if _RATE_LIMIT_RE.search(combined_output):
        return RateLimitedError(f"claude -p failed: rate limited (rc={returncode})")
    return ReviewError(f"claude -p failed (rc={returncode})")


async def _fetch_pr_diff(
    owner: str, repo: str, pr_number: int, token: str | None
) -> str | None:
    """Fetch the PR diff via GitHub API.

    Returns the diff text, empty string if the PR has no changes, or None on
    fetch failure (HTTP error, network error).
    """
    def _do_fetch() -> str | None:
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
            return None
        except urllib.error.URLError as e:
            logger.error("Network error fetching diff for PR #%d: %s", pr_number, e)
            return None
    return await asyncio.to_thread(_do_fetch)


async def _update_checkout(
    pr_number: int, head_sha: str, repo_owner: str, repo_name: str,
) -> bool:
    """Update the shared MicroPython checkout to the PR's head commit.

    For fork repos (where repo_owner/repo_name differs from origin), a
    temporary remote is added to fetch the PR ref, then removed after checkout.

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

        # Determine whether this PR lives on origin or a fork.
        # Read origin URL to compare against the request's repo.
        is_fork = False
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "remote", "get-url", "origin", cwd=mpy_checkout,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            origin_url = stdout_bytes.decode().strip().lower()
            repo_slug = f"{repo_owner}/{repo_name}".lower()
            if repo_slug not in origin_url:
                is_fork = True
        except Exception:
            pass  # Assume not a fork if we can't determine

        fork_remote = f"_fork_{repo_owner}" if is_fork else None

        try:
            if not await _run_git("checkout", "--", "."):
                return False
            if not await _run_git("clean", "-fd", "-e", ".codanna/"):
                return False

            if is_fork:
                fork_url = f"https://github.com/{repo_owner}/{repo_name}.git"
                # Add temporary remote for the fork
                await _run_git("remote", "remove", fork_remote)  # ignore failure
                if not await _run_git("remote", "add", fork_remote, fork_url):
                    return False
                if not await _run_git(
                    "fetch", fork_remote, f"refs/pull/{pr_number}/head",
                ):
                    return False
            else:
                if not await _run_git(
                    "fetch", "origin", f"refs/pull/{pr_number}/head",
                ):
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
            # Clean up temporary fork remote
            if fork_remote:
                await _run_git("remote", "remove", fork_remote)
    finally:
        # Synchronous unlock + close — fast syscalls, no event loop concern.
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)

    logger.info("Checkout updated to PR #%d (%s)", pr_number, head_sha[:8])
    return True


def _write_temp_file(content: str, prefix: str = "mpy-", suffix: str = ".txt") -> str:
    """Write text content to a temp file, return the path."""
    fd, path = tempfile.mkstemp(prefix=prefix, suffix=suffix)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


def _parse_validation_output(
    validation_text: str, original_findings: list[dict],
) -> list[dict]:
    """Parse validation agent text output into annotated findings.

    The validation agent returns text with [KEEP], [QUESTIONABLE], [INVALID]
    markers per finding. This parser extracts the verdict for each finding.

    Falls back to treating all original findings as KEEP if parsing fails.
    """
    if not validation_text.strip():
        # Validation agent failed -- treat all findings as unvalidated KEEP
        logger.warning("Empty validation output, treating all findings as KEEP")
        for f in original_findings:
            f["status"] = "KEEP"
        return original_findings

    # Try to match each finding from the original list to a verdict in the output
    validated = []

    for f in original_findings:
        title = f.get("title", "")
        file_ref = f.get("file", "")

        # Search for this finding in the validation output
        # Default to KEEP if not found (fail-open, but logged)
        status = "KEEP"

        # Find the position of this finding's title in the validation text
        title_pos = validation_text.find(title)
        if title_pos == -1 and file_ref:
            # Try finding by file reference
            title_pos = validation_text.find(file_ref)

        if title_pos >= 0:
            # Look backwards from the title for the nearest verdict marker
            preceding = validation_text[:title_pos].upper()
            # Find the last verdict marker before this title
            keep_pos = preceding.rfind("[KEEP]")
            quest_pos = preceding.rfind("[QUESTIONABLE]")
            invalid_pos = preceding.rfind("[INVALID]")

            latest = max(keep_pos, quest_pos, invalid_pos)
            if latest >= 0:
                if latest == invalid_pos:
                    status = "INVALID"
                elif latest == quest_pos:
                    status = "QUESTIONABLE"
                else:
                    status = "KEEP"

        if title_pos < 0:
            logger.warning(
                "Validation output missing finding: %s (%s), defaulting to KEEP",
                title[:50], file_ref,
            )

        finding = dict(f)
        finding["status"] = status

        # Extract validation note if present
        if title_pos >= 0:
            after_title = validation_text[title_pos:]
            note_match = re.search(
                r"[Vv]alidation note:\s*(.+?)(?:\n\n|\n\[|$)",
                after_title, re.DOTALL,
            )
            if note_match:
                finding["validation_note"] = note_match.group(1).strip()

        validated.append(finding)

    return validated
