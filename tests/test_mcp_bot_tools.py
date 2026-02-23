"""Tests for bot.mcp_tools — review-posting tool registration and guards."""

import os
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(autouse=True)
def _clean_env():
    """Ensure bot-related env vars are unset before/after each test."""
    saved = {}
    for key in ("MPY_REVIEWER_BOT_MODE", "BOT_TARGET_REPO"):
        saved[key] = os.environ.pop(key, None)
    yield
    for key, val in saved.items():
        if val is not None:
            os.environ[key] = val
        else:
            os.environ.pop(key, None)


def _get_tool_names(mcp_instance):
    """Extract registered tool names from a FastMCP instance."""
    return set(mcp_instance._tool_manager._tools.keys())


@pytest.fixture
def bot_mcp():
    """FastMCP instance with bot tools registered and a mock github_request."""
    from fastmcp import FastMCP

    os.environ["MPY_REVIEWER_BOT_MODE"] = "1"
    test_mcp = FastMCP("test")
    mock_github_request = MagicMock()
    with patch.dict("sys.modules", {
        "bot": MagicMock(),
        "bot.github_api": MagicMock(github_request=mock_github_request),
    }):
        from bot.mcp_tools import register_bot_tools
        register_bot_tools(test_mcp)
    tools = test_mcp._tool_manager._tools
    return tools, mock_github_request


def test_bot_tools_skipped_without_env_var():
    """Bot tools are not registered when MPY_REVIEWER_BOT_MODE is unset."""
    from fastmcp import FastMCP
    from bot.mcp_tools import register_bot_tools

    test_mcp = FastMCP("test")
    tools_before = _get_tool_names(test_mcp)
    register_bot_tools(test_mcp)
    tools_after = _get_tool_names(test_mcp)

    new_tools = tools_after - tools_before
    bot_tool_names = {"create_review", "add_review_comment", "submit_review"}
    assert not bot_tool_names.intersection(new_tools)


def test_bot_tools_skipped_when_bot_package_missing():
    """Bot tools are not registered when bot package is not importable."""
    from fastmcp import FastMCP
    import builtins

    real_import = builtins.__import__

    def _block_bot(name, *args, **kwargs):
        if name == "bot.github_api":
            raise ImportError("no bot package")
        return real_import(name, *args, **kwargs)

    os.environ["MPY_REVIEWER_BOT_MODE"] = "1"
    test_mcp = FastMCP("test")
    tools_before = _get_tool_names(test_mcp)

    with patch.object(builtins, "__import__", side_effect=_block_bot):
        from bot.mcp_tools import register_bot_tools
        register_bot_tools(test_mcp)

    tools_after = _get_tool_names(test_mcp)
    new_tools = tools_after - tools_before
    bot_tool_names = {"create_review", "add_review_comment", "submit_review"}
    assert not bot_tool_names.intersection(new_tools)


def test_bot_tools_registered_with_env_var():
    """Bot tools ARE registered when MPY_REVIEWER_BOT_MODE is set and bot package exists."""
    from fastmcp import FastMCP
    from bot.mcp_tools import register_bot_tools

    os.environ["MPY_REVIEWER_BOT_MODE"] = "1"
    test_mcp = FastMCP("test")
    tools_before = _get_tool_names(test_mcp)
    register_bot_tools(test_mcp)
    tools_after = _get_tool_names(test_mcp)

    new_tools = tools_after - tools_before
    bot_tool_names = {"create_review", "add_review_comment", "submit_review"}
    try:
        from bot.github_api import github_request  # noqa: F401
        bot_available = True
    except ImportError:
        bot_available = False

    if bot_available:
        assert bot_tool_names.issubset(new_tools)
    else:
        assert not bot_tool_names.intersection(new_tools)


def test_check_repo_rejects_wrong_repo(bot_mcp):
    """_check_repo raises ValueError for non-target repo."""
    os.environ["BOT_TARGET_REPO"] = "test/repo"
    # Re-register with new target repo
    from fastmcp import FastMCP
    test_mcp = FastMCP("test")
    mock_github_request = MagicMock()
    with patch.dict("sys.modules", {
        "bot": MagicMock(),
        "bot.github_api": MagicMock(github_request=mock_github_request),
    }):
        from bot.mcp_tools import register_bot_tools
        register_bot_tools(test_mcp)
    tools = test_mcp._tool_manager._tools
    assert "submit_review" in tools

    with pytest.raises(ValueError, match="does not match"):
        tools["submit_review"].fn(
            owner="wrong", repo="repo", pr_number=1,
            review_id=1, body="test", event="COMMENT",
        )


def test_check_repo_accepts_target_repo(bot_mcp):
    """Default target repo passes the repo check (fails on event instead)."""
    tools, _ = bot_mcp
    assert "submit_review" in tools

    with pytest.raises(ValueError, match="Only 'COMMENT'"):
        tools["submit_review"].fn(
            owner="micropython", repo="micropython", pr_number=1,
            review_id=1, body="test", event="APPROVE",
        )


def test_submit_review_rejects_non_comment_event(bot_mcp):
    """submit_review raises ValueError for non-COMMENT events."""
    tools, _ = bot_mcp
    assert "submit_review" in tools

    for bad_event in ("APPROVE", "REQUEST_CHANGES", "DISMISS"):
        with pytest.raises(ValueError, match="Only 'COMMENT'"):
            tools["submit_review"].fn(
                owner="micropython", repo="micropython", pr_number=1,
                review_id=1, body="test", event=bad_event,
            )


def test_create_review_success(bot_mcp):
    """create_review returns review_id from GitHub API."""
    tools, mock_github_request = bot_mcp
    mock_github_request.return_value = {"id": 42}
    assert "create_review" in tools

    result = tools["create_review"].fn(
        owner="micropython", repo="micropython", pr_number=1,
    )
    assert result == {"review_id": 42}
    mock_github_request.assert_called_once()


def test_create_review_no_commit_sha_sends_none(bot_mcp):
    """create_review sends body=None when commit_sha is omitted."""
    tools, mock_github_request = bot_mcp
    mock_github_request.return_value = {"id": 1}

    tools["create_review"].fn(
        owner="micropython", repo="micropython", pr_number=1,
    )
    mock_github_request.assert_called_once_with(
        "POST", "/repos/micropython/micropython/pulls/1/reviews", None,
    )


def test_submit_review_accepts_comment_event(bot_mcp):
    """submit_review succeeds with event='COMMENT'."""
    tools, mock_github_request = bot_mcp
    mock_github_request.return_value = {}
    assert "submit_review" in tools

    result = tools["submit_review"].fn(
        owner="micropython", repo="micropython", pr_number=1,
        review_id=1, body="test", event="COMMENT",
    )
    assert result == {"status": "submitted"}
    mock_github_request.assert_called_once_with(
        "POST",
        "/repos/micropython/micropython/pulls/1/reviews/1/events",
        {"body": "test", "event": "COMMENT"},
    )
