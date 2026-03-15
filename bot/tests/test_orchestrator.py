"""Tests for bot.orchestrator."""

import asyncio
import json
import os
import urllib.error
from contextlib import contextmanager
from io import BytesIO
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from bot.orchestrator import (
    run_review, _fetch_pr_diff, _update_checkout, _build_mcp_config,
    _write_temp_json, _classify_claude_failure, MAX_DIFF_CHARS,
    ReviewError, DiffTooLargeError, DiffFetchError, PromptTooLongError,
    RateLimitedError, ReviewTimeoutError, MetadataFetchError, EmptyDiffError,
)
from bot.tests.conftest import make_review_request


def _make_config():
    """Create a minimal BotConfig mock."""
    config = MagicMock()
    config.review.model = "sonnet"
    config.review.timeout_seconds = 10
    config.review.top_k = 8
    config.review.include_codebase = False
    config.review.check_ci = True
    config.prompt.additional_system_prompt = ""
    config.auth.claude_oauth_path = ""
    config.mcp.url = "http://localhost:9090"
    return config


@contextmanager
def _mock_run_review_env(diff="diff", checkout_ok=True, proc_returncode=0,
                         proc_stdout=b"output", proc_stderr=b""):
    """Common mock stack for run_review tests (metadata, diff, checkout, subprocess, temp, unlink)."""
    mock_proc = MagicMock()
    mock_proc.returncode = proc_returncode

    async def comm(input=None):
        return proc_stdout, proc_stderr
    mock_proc.communicate = comm

    with patch("bot.orchestrator.github_request",
               return_value={"title": "t", "body": "b", "head": {"sha": "abc"}}):
        with patch("bot.orchestrator._fetch_pr_diff",
                   new_callable=AsyncMock, return_value=diff):
            with patch("bot.orchestrator._update_checkout",
                       new_callable=AsyncMock, return_value=checkout_ok):
                with patch("asyncio.create_subprocess_exec",
                           return_value=mock_proc):
                    with patch("bot.orchestrator._write_temp_json",
                               return_value="/tmp/f.json"):
                        with patch("os.unlink"):
                            yield mock_proc


@pytest.mark.asyncio
async def test_fetch_pr_diff_uses_github_request():
    """Verifies _fetch_pr_diff uses github_request with raw=True."""
    with patch("bot.orchestrator.github_request", return_value="diff content") as mock:
        result = await _fetch_pr_diff("owner", "repo", 1, "tok")
    assert result == "diff content"
    mock.assert_called_once_with(
        "GET", "/repos/owner/repo/pulls/1",
        token="tok",
        accept="application/vnd.github.diff",
        raw=True,
    )


@pytest.mark.asyncio
async def test_run_review_empty_diff():
    req = make_review_request()
    config = _make_config()
    auth = MagicMock()
    auth.get_token.return_value = "tok"

    with patch("bot.orchestrator.github_request", return_value={"title": "t", "body": "b", "head": {"sha": "abc"}}):
        with patch("bot.orchestrator._fetch_pr_diff", new_callable=AsyncMock, return_value=""):
            with pytest.raises(EmptyDiffError):
                await run_review(req, config, auth=auth)


@pytest.mark.asyncio
async def test_run_review_diff_fetch_failure():
    """Raises DiffFetchError when diff fetch returns None (HTTP/network error)."""
    req = make_review_request()
    config = _make_config()
    auth = MagicMock()
    auth.get_token.return_value = "tok"

    with patch("bot.orchestrator.github_request", return_value={"title": "t", "body": "b", "head": {"sha": "abc"}}):
        with patch("bot.orchestrator._fetch_pr_diff", new_callable=AsyncMock, return_value=None):
            with pytest.raises(DiffFetchError):
                await run_review(req, config, auth=auth)


@pytest.mark.asyncio
async def test_run_review_diff_too_large():
    req = make_review_request()
    config = _make_config()
    auth = MagicMock()
    auth.get_token.return_value = "tok"

    big_diff = "x" * (MAX_DIFF_CHARS + 1)
    with patch("bot.orchestrator.github_request", return_value={"title": "t", "body": "b", "head": {"sha": "abc"}}):
        with patch("bot.orchestrator._fetch_pr_diff", new_callable=AsyncMock, return_value=big_diff):
            with pytest.raises(DiffTooLargeError):
                await run_review(req, config, auth=auth)


@pytest.mark.asyncio
async def test_update_checkout_checks_return_codes():
    """Returns False when git fetch fails."""
    with patch("os.path.isdir", return_value=True):
        # Mock subprocess: first two succeed, third (fetch) fails
        call_count = 0
        async def mock_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            proc = MagicMock()
            proc.returncode = 0 if call_count <= 2 else 1
            async def communicate():
                return b"", b"fetch error"
            proc.communicate = communicate
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            result = await _update_checkout(1, "abc123", "micropython", "micropython")
    assert result is False


@pytest.mark.asyncio
async def test_update_checkout_detached_head():
    """Verifies checkout uses --detach FETCH_HEAD."""
    git_calls = []

    with patch("os.path.isdir", return_value=True):
        async def mock_exec(*args, **kwargs):
            git_calls.append(args)
            proc = MagicMock()
            proc.returncode = 0
            async def communicate():
                # rev-parse HEAD returns the expected SHA
                if "rev-parse" in args:
                    return b"abc12345\n", b""
                # remote get-url returns origin URL
                if "get-url" in args:
                    return b"https://github.com/micropython/micropython.git\n", b""
                return b"", b""
            proc.communicate = communicate
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            result = await _update_checkout(1, "abc12345", "micropython", "micropython")

    assert result is True
    # Second-to-last git call should be checkout --detach FETCH_HEAD
    # (last is rev-parse HEAD for SHA verification)
    detach_call = git_calls[-2]
    assert "checkout" in detach_call
    assert "--detach" in detach_call
    assert "FETCH_HEAD" in detach_call


@pytest.mark.asyncio
async def test_run_review_success():
    """Happy path: subprocess completes with rc=0."""
    auth = MagicMock()
    auth.get_token.return_value = "tok"

    with _mock_run_review_env():
        assert await run_review(make_review_request(), _make_config(), auth=auth) is True


@pytest.mark.asyncio
async def test_run_review_timeout():
    """Timeout path: process terminated then killed."""
    config = _make_config()
    config.review.timeout_seconds = 0.01
    auth = MagicMock()
    auth.get_token.return_value = "tok"

    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.terminate = MagicMock()
    mock_proc.kill = MagicMock()

    async def hang(input=None):
        await asyncio.sleep(100)
    mock_proc.communicate = hang

    with patch("bot.orchestrator.github_request", return_value={"title": "t", "body": "b", "head": {"sha": "abc"}}):
        with patch("bot.orchestrator._fetch_pr_diff", new_callable=AsyncMock, return_value="diff"):
            with patch("bot.orchestrator._update_checkout", new_callable=AsyncMock, return_value=True):
                with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                    with patch("bot.orchestrator._write_temp_json", return_value="/tmp/f.json"):
                        with patch("os.unlink"):
                            with pytest.raises(ReviewTimeoutError):
                                await run_review(make_review_request(), config, auth=auth)
    mock_proc.terminate.assert_called_once()


@pytest.mark.asyncio
async def test_run_review_pr_fetch_failure():
    """Raises MetadataFetchError when PR metadata fetch fails."""
    auth = MagicMock()
    auth.get_token.return_value = "tok"

    with patch("bot.orchestrator.github_request", side_effect=RuntimeError("API down")):
        with pytest.raises(MetadataFetchError):
            await run_review(make_review_request(), _make_config(), auth=auth)


@pytest.mark.asyncio
async def test_run_review_no_head_sha():
    """Raises MetadataFetchError when no head SHA is available."""
    auth = MagicMock()
    auth.get_token.return_value = "tok"

    with patch("bot.orchestrator.github_request", return_value={"title": "t", "body": "b", "head": {"sha": ""}}):
        with pytest.raises(MetadataFetchError):
            await run_review(make_review_request(head_sha=""), _make_config(), auth=auth)


def test_build_mcp_config():
    config = _make_config()
    result = _build_mcp_config(config)
    assert "mcpServers" in result
    assert "mpy-reviewer" in result["mcpServers"]
    assert result["mcpServers"]["mpy-reviewer"]["type"] == "sse"
    assert result["mcpServers"]["mpy-reviewer"]["url"] == "http://localhost:9090/sse"


def test_write_temp_json():
    path = _write_temp_json({"key": "val"})
    try:
        with open(path) as f:
            assert json.loads(f.read()) == {"key": "val"}
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_run_review_auth_none():
    """auth=None passes token=None; github_request reads from file."""
    with _mock_run_review_env():
        assert await run_review(make_review_request(), _make_config(), auth=None) is True


@pytest.mark.asyncio
async def test_fetch_pr_diff_403():
    err = urllib.error.HTTPError("", 403, "Forbidden", None, BytesIO(b""))
    with patch("bot.orchestrator.github_request", side_effect=err):
        assert await _fetch_pr_diff("o", "r", 1, "tok") is None


@pytest.mark.asyncio
async def test_fetch_pr_diff_404():
    err = urllib.error.HTTPError("", 404, "Not Found", None, BytesIO(b""))
    with patch("bot.orchestrator.github_request", side_effect=err):
        assert await _fetch_pr_diff("o", "r", 1, "tok") is None


@pytest.mark.asyncio
async def test_fetch_pr_diff_500():
    err = urllib.error.HTTPError("", 500, "Server Error", None, BytesIO(b""))
    with patch("bot.orchestrator.github_request", side_effect=err):
        assert await _fetch_pr_diff("o", "r", 1, "tok") is None


@pytest.mark.asyncio
async def test_fetch_pr_diff_url_error():
    """Returns None on network error."""
    err = urllib.error.URLError("Connection refused")
    with patch("bot.orchestrator.github_request", side_effect=err):
        assert await _fetch_pr_diff("o", "r", 1, "tok") is None


@pytest.mark.asyncio
async def test_update_checkout_no_git_dir():
    """Returns False when .git directory doesn't exist."""
    with patch("os.path.isdir", return_value=False):
        assert await _update_checkout(1, "abc", "micropython", "micropython") is False


@pytest.mark.asyncio
async def test_run_review_subprocess_failure():
    """Raises ReviewError when claude -p exits non-zero."""
    auth = MagicMock()
    auth.get_token.return_value = "tok"

    with _mock_run_review_env(proc_returncode=1, proc_stdout=b"", proc_stderr=b"error output"):
        with pytest.raises(ReviewError):
            await run_review(make_review_request(), _make_config(), auth=auth)


@pytest.mark.asyncio
async def test_run_review_subprocess_prompt_too_long():
    """Raises PromptTooLongError when claude -p reports prompt is too long."""
    auth = MagicMock()
    auth.get_token.return_value = "tok"

    with _mock_run_review_env(proc_returncode=1, proc_stdout=b"", proc_stderr=b"prompt is too long"):
        with pytest.raises(PromptTooLongError):
            await run_review(make_review_request(), _make_config(), auth=auth)


@pytest.mark.asyncio
async def test_run_review_subprocess_rate_limited():
    """Raises RateLimitedError when claude -p reports rate limit."""
    auth = MagicMock()
    auth.get_token.return_value = "tok"

    with _mock_run_review_env(proc_returncode=1, proc_stdout=b"", proc_stderr=b"rate limit exceeded"):
        with pytest.raises(RateLimitedError):
            await run_review(make_review_request(), _make_config(), auth=auth)


@pytest.mark.asyncio
async def test_update_checkout_sha_mismatch():
    """Returns False when checked-out SHA differs from expected."""
    with patch("os.path.isdir", return_value=True):
        async def mock_exec(*args, **kwargs):
            proc = MagicMock()
            proc.returncode = 0
            async def communicate():
                if "rev-parse" in args:
                    return b"different_sha\n", b""
                return b"", b""
            proc.communicate = communicate
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            result = await _update_checkout(1, "expected_sha", "micropython", "micropython")
    assert result is False


@pytest.mark.asyncio
async def test_update_checkout_fork_adds_remote():
    """For fork repos, adds a temporary remote, fetches, then removes it."""
    git_calls = []

    with patch("os.path.isdir", return_value=True):
        async def mock_exec(*args, **kwargs):
            git_calls.append(args)
            proc = MagicMock()
            proc.returncode = 0
            async def communicate():
                if "rev-parse" in args:
                    return b"abc12345\n", b""
                if "get-url" in args:
                    return b"https://github.com/micropython/micropython.git\n", b""
                return b"", b""
            proc.communicate = communicate
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            result = await _update_checkout(1, "abc12345", "andrewleech", "micropython")

    assert result is True
    # Should have added a fork remote
    add_calls = [c for c in git_calls if "remote" in c and "add" in c]
    assert len(add_calls) == 1
    assert "_fork_andrewleech" in add_calls[0]
    assert "https://github.com/andrewleech/micropython.git" in add_calls[0]
    # Should have fetched from the fork remote
    fetch_calls = [c for c in git_calls if "fetch" in c and "_fork_andrewleech" in c]
    assert len(fetch_calls) == 1
    # Should have cleaned up the fork remote (in finally block)
    remove_calls = [c for c in git_calls if "remote" in c and "remove" in c and "_fork_andrewleech" in c]
    assert len(remove_calls) >= 1


@pytest.mark.asyncio
async def test_run_review_allowed_tools_include_ci():
    """Verify CI tools are in the --allowedTools list."""
    auth = MagicMock()
    auth.get_token.return_value = "tok"
    captured_cmd = None

    with _mock_run_review_env() as mock_proc:
        async def capture_exec(*args, **kwargs):
            nonlocal captured_cmd
            captured_cmd = args
            return mock_proc
        with patch("asyncio.create_subprocess_exec", side_effect=capture_exec):
            await run_review(make_review_request(), _make_config(), auth=auth)

    assert captured_cmd is not None
    # Find the --allowedTools argument value
    cmd_list = list(captured_cmd)
    idx = cmd_list.index("--allowedTools")
    tools_str = cmd_list[idx + 1]
    assert "mcp__mpy-reviewer__get_check_runs" in tools_str
    assert "mcp__mpy-reviewer__get_check_run_annotations" in tools_str
    assert "mcp__mpy-reviewer__get_workflow_run_log" in tools_str


@pytest.mark.asyncio
async def test_run_review_allowed_tools_include_verify():
    """Verify verify_findings is in the --allowedTools list."""
    auth = MagicMock()
    auth.get_token.return_value = "tok"
    captured_cmd = None

    with _mock_run_review_env() as mock_proc:
        async def capture_exec(*args, **kwargs):
            nonlocal captured_cmd
            captured_cmd = args
            return mock_proc
        with patch("asyncio.create_subprocess_exec", side_effect=capture_exec):
            await run_review(make_review_request(), _make_config(), auth=auth)

    assert captured_cmd is not None
    cmd_list = list(captured_cmd)
    idx = cmd_list.index("--allowedTools")
    tools_str = cmd_list[idx + 1]
    assert "mcp__mpy-reviewer__verify_findings" in tools_str


# --- _classify_claude_failure tests ---


def test_classify_prompt_too_long():
    err = _classify_claude_failure("error: prompt is too long for model", 1)
    assert isinstance(err, PromptTooLongError)
    assert "context limit" in err.user_message


def test_classify_rate_limit():
    err = _classify_claude_failure("rate limit exceeded, please retry", 1)
    assert isinstance(err, RateLimitedError)
    assert "rate-limited" in err.user_message


def test_classify_429():
    err = _classify_claude_failure("http error 429 too many requests", 1)
    assert isinstance(err, RateLimitedError)


def test_classify_status_429():
    err = _classify_claude_failure("http error status: 429", 1)
    assert isinstance(err, RateLimitedError)


def test_classify_429_too_many():
    err = _classify_claude_failure("error 429 too many requests", 1)
    assert isinstance(err, RateLimitedError)


def test_classify_429_substring_no_false_positive():
    """Bare '429' inside a larger number should not trigger RateLimitedError."""
    err = _classify_claude_failure("processed 4290 tokens in batch", 1)
    assert type(err) is ReviewError


def test_classify_combined_stderr_stdout():
    """Trigger phrase in stdout with unrelated stderr still matches."""
    err = _classify_claude_failure("some warnings here\nprompt is too long for model", 1)
    assert isinstance(err, PromptTooLongError)


def test_classify_generic_failure():
    err = _classify_claude_failure("some unknown error", 1)
    assert type(err) is ReviewError
    assert "rc=1" in str(err)


# --- ReviewError hierarchy tests ---


def test_review_error_is_exception():
    assert issubclass(ReviewError, Exception)


def test_all_subclasses_have_user_message():
    for cls in [DiffTooLargeError, DiffFetchError, PromptTooLongError,
                RateLimitedError, ReviewTimeoutError, MetadataFetchError,
                EmptyDiffError]:
        assert issubclass(cls, ReviewError)
        err = cls("internal detail")
        assert err.user_message  # non-empty
        assert "internal detail" not in err.user_message


def test_review_error_custom_user_message():
    err = ReviewError("internal", user_message="custom message")
    assert err.user_message == "custom message"
