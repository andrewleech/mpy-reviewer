"""Triage orchestration — spawns claude -p per triage request."""

import asyncio
import json
import logging
import os
import tempfile

from bot.config import BotConfig
from bot.github_api import github_request
from bot.github_app import GitHubAppAuth
from bot.review_queue import TriageRequest

logger = logging.getLogger(__name__)


async def run_triage(
    request: TriageRequest,
    config: BotConfig,
    auth: GitHubAppAuth | None = None,
) -> bool:
    """Execute a triage cycle for an issue.

    1. Fetch issue metadata from GitHub
    2. Build system prompt with triage instructions
    3. Spawn claude -p with MCP config (triage + review tools)
    4. Wait for completion

    Returns:
        True on success, False on failure.
    """
    triage_config = config.triage
    if triage_config is None:
        logger.error("Triage not configured")
        return False

    token = auth.get_token(request.installation_id) if auth else None

    # Fetch issue metadata
    try:
        issue_data = await asyncio.to_thread(
            github_request,
            "GET",
            f"/repos/{request.repo_owner}/{request.repo_name}/issues/{request.issue_number}",
            token=token,
        )
    except Exception as e:
        logger.error("Failed to fetch issue #%d: %s", request.issue_number, e)
        return False

    issue_title = issue_data.get("title", "")
    issue_body = issue_data.get("body", "") or ""
    issue_state = issue_data.get("state", "open")
    issue_labels = [l["name"] for l in issue_data.get("labels", [])]

    # Build system prompt
    system_prompt = _build_triage_system_prompt(
        top_k=triage_config.top_k,
        include_codebase=triage_config.include_codebase,
        additional_system_prompt=config.prompt.additional_system_prompt,
    )

    # Build user message
    user_message = _build_triage_user_message(
        issue_number=request.issue_number,
        issue_title=issue_title,
        issue_body=issue_body,
        issue_state=issue_state,
        issue_labels=issue_labels,
        repo_owner=request.repo_owner,
        repo_name=request.repo_name,
    )

    # Write MCP config
    mcp_config = _build_triage_mcp_config(config)
    mcp_config_path = _write_temp_json(mcp_config)

    cmd = [
        "claude", "-p",
        "--model", triage_config.model,
        "--output-format", "text",
        "--dangerously-skip-permissions",
        "--system-prompt", system_prompt,
        "--mcp-config", mcp_config_path,
        "--allowedTools",
        ",".join([
            "mcp__mpy-reviewer__triage_issue",
            "mcp__mpy-reviewer__search_issues",
            "mcp__mpy-reviewer__search_reviews",
            "mcp__mpy-reviewer__find_style_examples",
            "mcp__mpy-reviewer__get_review_stats",
            "mcp__mpy-reviewer__post_issue_comment",
            "mcp__mpy-reviewer__add_issue_labels",
        ]),
    ]

    env = os.environ.copy()
    if config.auth.claude_oauth_path:
        env["CLAUDE_CONFIG_DIR"] = config.auth.claude_oauth_path

    logger.info(
        "Spawning claude -p for issue #%d triage (model=%s, timeout=%ds)",
        request.issue_number, triage_config.model, triage_config.timeout_seconds,
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=user_message.encode()),
            timeout=triage_config.timeout_seconds,
        )

        stderr_text = stderr.decode(errors="replace")
        if proc.returncode != 0:
            logger.error(
                "claude -p failed for issue #%d triage (rc=%d): %s",
                request.issue_number, proc.returncode, stderr_text[:2000],
            )
            return False

        logger.info(
            "claude -p completed for issue #%d triage (rc=%d, stdout=%d bytes)",
            request.issue_number, proc.returncode, len(stdout),
        )
        if stderr_text.strip():
            logger.info("claude -p stderr for issue #%d:\n%s",
                        request.issue_number, stderr_text[:3000])
        return True

    except asyncio.TimeoutError:
        logger.error(
            "claude -p timed out for issue #%d after %ds",
            request.issue_number, triage_config.timeout_seconds,
        )
        try:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        except Exception:
            pass
        return False
    finally:
        try:
            os.unlink(mcp_config_path)
        except OSError:
            pass


def _build_triage_system_prompt(
    top_k: int = 5,
    include_codebase: bool = True,
    additional_system_prompt: str = "",
) -> str:
    parts = [
        "You are an issue triage bot for the MicroPython project.",
        "Your job is to classify issues, detect duplicates, and draft responses. "
        "Be terse, technical, and direct.",
        "",
        "## Workflow",
        f"1. Call triage_issue with the issue number (top_k={top_k}, "
        f"include_codebase={str(include_codebase).lower()})",
        "2. Analyse the triage context returned",
        "3. If the issue is resolved/duplicate, use add_issue_labels to apply 'proposed-close'",
        "4. Apply component/port/type labels via add_issue_labels",
        "5. Post a triage comment via post_issue_comment",
        "",
        "## Style",
        "- Be terse and technical. No pleasantries.",
        "- Reference specific PRs, issues, and code paths.",
        "- Ask pointed questions when info is missing.",
    ]
    if additional_system_prompt:
        parts.append("")
        parts.append(additional_system_prompt)
    return "\n".join(parts)


def _build_triage_user_message(
    issue_number: int,
    issue_title: str,
    issue_body: str,
    issue_state: str,
    issue_labels: list[str],
    repo_owner: str,
    repo_name: str,
) -> str:
    labels_str = ", ".join(issue_labels) if issue_labels else "(none)"
    return f"""Triage issue #{issue_number} on {repo_owner}/{repo_name}.

Title: {issue_title}
State: {issue_state}
Current labels: {labels_str}

{issue_body}
"""


def _build_triage_mcp_config(config: BotConfig) -> dict:
    return {
        "mcpServers": {
            "mpy-reviewer": {
                "type": "sse",
                "url": f"{config.mcp.url}/sse",
            }
        }
    }


def _write_temp_json(data: dict) -> str:
    fd, path = tempfile.mkstemp(prefix="triage-mcp-", suffix=".json")
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    return path
