"""Tests for bot.orchestrator."""

import asyncio
import json
import os
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from bot.orchestrator import (
    run_review, _fetch_pr_diff, _update_checkout, _write_temp_file,
    _classify_claude_failure, _parse_validation_output, MAX_DIFF_CHARS,
    DOMAIN_AGENTS,
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


# --- _fetch_pr_diff tests ---


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


# --- run_review early exit tests ---


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
    """Raises DiffFetchError when diff fetch returns None."""
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


# --- _update_checkout tests ---


@pytest.mark.asyncio
async def test_update_checkout_no_git_dir():
    """Returns False when .git directory doesn't exist."""
    with patch("os.path.isdir", return_value=False):
        assert await _update_checkout(1, "abc", "micropython", "micropython") is False


@pytest.mark.asyncio
async def test_update_checkout_checks_return_codes():
    """Returns False when git fetch fails."""
    with patch("os.path.isdir", return_value=True):
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
                if "rev-parse" in args:
                    return b"abc12345\n", b""
                if "get-url" in args:
                    return b"https://github.com/micropython/micropython.git\n", b""
                return b"", b""
            proc.communicate = communicate
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            result = await _update_checkout(1, "abc12345", "micropython", "micropython")

    assert result is True
    detach_call = git_calls[-2]
    assert "checkout" in detach_call
    assert "--detach" in detach_call
    assert "FETCH_HEAD" in detach_call


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
    add_calls = [c for c in git_calls if "remote" in c and "add" in c]
    assert len(add_calls) == 1
    assert "_fork_andrewleech" in add_calls[0]
    fetch_calls = [c for c in git_calls if "fetch" in c and "_fork_andrewleech" in c]
    assert len(fetch_calls) == 1
    remove_calls = [c for c in git_calls if "remote" in c and "remove" in c and "_fork_andrewleech" in c]
    assert len(remove_calls) >= 1


# --- _write_temp_file tests ---


def test_write_temp_file():
    path = _write_temp_file("test content", prefix="test-")
    try:
        with open(path) as f:
            assert f.read() == "test content"
    finally:
        os.unlink(path)


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


# --- _parse_validation_output tests ---


def test_parse_validation_empty_output():
    """Empty validation output treats all findings as KEEP."""
    findings = [{"title": "Test", "file": "a.c", "line": 1, "severity": "blocking"}]
    result = _parse_validation_output("", findings)
    assert len(result) == 1
    assert result[0]["status"] == "KEEP"


def test_parse_validation_keep():
    findings = [{"title": "Missing NULL check", "file": "a.c", "line": 1, "severity": "blocking"}]
    output = "[KEEP] [blocking] **Missing NULL check** -- a.c:1\nDescription.\nValidation note: Verified in code."
    result = _parse_validation_output(output, findings)
    assert result[0]["status"] == "KEEP"


def test_parse_validation_invalid():
    findings = [{"title": "Style issue", "file": "b.c", "line": 5, "severity": "nitpick"}]
    output = "[INVALID] [nitpick] **Style issue** -- b.c:5\nDescription.\nValidation note: Matches convention."
    result = _parse_validation_output(output, findings)
    assert result[0]["status"] == "INVALID"


def test_parse_validation_questionable():
    findings = [{"title": "Extract function", "file": "c.c", "line": 10, "severity": "suggestion"}]
    output = "[QUESTIONABLE] [suggestion] **Extract function** -- c.c:10\nDescription.\nValidation note: Flip-flop risk."
    result = _parse_validation_output(output, findings)
    assert result[0]["status"] == "QUESTIONABLE"
    assert "Flip-flop" in result[0].get("validation_note", "")


def test_parse_validation_multiple():
    findings = [
        {"title": "Bug A", "file": "a.c", "line": 1, "severity": "blocking"},
        {"title": "Style B", "file": "b.c", "line": 2, "severity": "nitpick"},
    ]
    output = (
        "[KEEP] [blocking] **Bug A** -- a.c:1\nReal bug.\nValidation note: Confirmed.\n\n"
        "[INVALID] [nitpick] **Style B** -- b.c:2\nNot relevant.\nValidation note: Matches convention."
    )
    result = _parse_validation_output(output, findings)
    assert result[0]["status"] == "KEEP"
    assert result[1]["status"] == "INVALID"


# --- ReviewError hierarchy tests ---


def test_review_error_is_exception():
    assert issubclass(ReviewError, Exception)


def test_all_subclasses_have_user_message():
    for cls in [DiffTooLargeError, DiffFetchError, PromptTooLongError,
                RateLimitedError, ReviewTimeoutError, MetadataFetchError,
                EmptyDiffError]:
        assert issubclass(cls, ReviewError)
        err = cls("internal detail")
        assert err.user_message
        assert "internal detail" not in err.user_message


def test_review_error_custom_user_message():
    err = ReviewError("internal", user_message="custom message")
    assert err.user_message == "custom message"


# --- Multi-agent constants ---


def test_domain_agents_count():
    """Verify 4 domain agents are configured."""
    assert len(DOMAIN_AGENTS) == 4
    dimensions = [d[0] for d in DOMAIN_AGENTS]
    assert "correctness-safety" in dimensions
    assert "resource-constraints" in dimensions
    assert "api-portability" in dimensions
    assert "conventions-completeness" in dimensions
