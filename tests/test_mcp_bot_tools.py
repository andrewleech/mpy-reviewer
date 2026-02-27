"""Tests for bot.mcp_tools — review-posting tool registration and guards."""

import os
from unittest.mock import patch, MagicMock

import pytest


BOT_TOOL_NAMES = {"post_review", "get_check_runs", "get_check_run_annotations",
                  "get_workflow_run_log"}


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
    """FastMCP instance with bot tools registered and a mock github_api module.

    Returns (tools_dict, mock_github_api_module). Set return values on
    mock_github_api_module.github_request for the tools to use.

    post_review calls _delete_pending_reviews (GET) then creates the review
    (POST). Use side_effect to return different values per call:
        mock_api.github_request.side_effect = [[], {"id": 42}]
    """
    from fastmcp import FastMCP

    os.environ["MPY_REVIEWER_BOT_MODE"] = "1"
    test_mcp = FastMCP("test")
    mock_github_api = MagicMock()
    # `from bot import github_api` resolves via sys.modules["bot"].github_api,
    # so the bot mock's github_api attr must be our mock_github_api.
    mock_bot = MagicMock(github_api=mock_github_api)
    with patch.dict("sys.modules", {
        "bot": mock_bot,
        "bot.github_api": mock_github_api,
    }):
        from bot.mcp_tools import register_bot_tools
        register_bot_tools(test_mcp)
    tools = test_mcp._tool_manager._tools
    return tools, mock_github_api


def test_bot_tools_skipped_without_env_var():
    """Bot tools are not registered when MPY_REVIEWER_BOT_MODE is unset."""
    from fastmcp import FastMCP
    from bot.mcp_tools import register_bot_tools

    test_mcp = FastMCP("test")
    tools_before = _get_tool_names(test_mcp)
    register_bot_tools(test_mcp)
    tools_after = _get_tool_names(test_mcp)

    new_tools = tools_after - tools_before
    assert not BOT_TOOL_NAMES.intersection(new_tools)


def test_bot_tools_skipped_when_bot_package_missing():
    """Bot tools are not registered when bot.github_api is not importable."""
    import sys
    import bot as bot_pkg
    from fastmcp import FastMCP
    from bot.mcp_tools import register_bot_tools

    os.environ["MPY_REVIEWER_BOT_MODE"] = "1"
    test_mcp = FastMCP("test")
    tools_before = _get_tool_names(test_mcp)

    # Remove bot.github_api from both sys.modules and the bot package's
    # namespace so `from bot import github_api` fails at call time.
    saved_mod = sys.modules.pop("bot.github_api", None)
    saved_attr = getattr(bot_pkg, "github_api", None)
    if hasattr(bot_pkg, "github_api"):
        delattr(bot_pkg, "github_api")
    try:
        with patch.dict("sys.modules", {"bot.github_api": None}):
            register_bot_tools(test_mcp)
    finally:
        if saved_mod is not None:
            sys.modules["bot.github_api"] = saved_mod
        if saved_attr is not None:
            bot_pkg.github_api = saved_attr

    tools_after = _get_tool_names(test_mcp)
    new_tools = tools_after - tools_before
    assert not BOT_TOOL_NAMES.intersection(new_tools)


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
    try:
        from bot.github_api import github_request  # noqa: F401
        bot_available = True
    except ImportError:
        bot_available = False

    if bot_available:
        assert BOT_TOOL_NAMES.issubset(new_tools)
    else:
        assert not BOT_TOOL_NAMES.intersection(new_tools)


def test_check_repo_rejects_wrong_repo(bot_mcp):
    """post_review raises ValueError for non-target repo."""
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
    assert "post_review" in tools

    with pytest.raises(ValueError, match="does not match"):
        tools["post_review"].fn(
            owner="wrong", repo="repo", pr_number=1,
            body="test",
        )


def test_check_repo_accepts_target_repo(bot_mcp):
    """Default target repo (micropython/micropython) passes the repo check."""
    tools, mock_api = bot_mcp
    assert "post_review" in tools

    # GET for pending reviews, then POST for the review
    mock_api.github_request.side_effect = [[], {"id": 99}]
    result = tools["post_review"].fn(
        owner="micropython", repo="micropython", pr_number=1,
        body="test",
    )
    assert "review_id" in result


def test_post_review_success(bot_mcp):
    """post_review returns review_id and comment_count from GitHub API."""
    tools, mock_api = bot_mcp
    # GET pending reviews → empty list, POST review → created
    mock_api.github_request.side_effect = [[], {"id": 42}]
    assert "post_review" in tools

    result = tools["post_review"].fn(
        owner="micropython", repo="micropython", pr_number=1,
        body="looks good",
    )
    assert result == {"review_id": 42, "comment_count": 0}


def test_post_review_with_comments(bot_mcp):
    """post_review passes inline comments and reports count."""
    tools, mock_api = bot_mcp
    mock_api.github_request.side_effect = [[], {"id": 55}]

    comments = [
        {"path": "py/gc.c", "line": 10, "side": "RIGHT", "body": "Missing null check."},
        {"path": "py/obj.h", "line": 5, "side": "RIGHT", "body": "Use `void`."},
    ]
    result = tools["post_review"].fn(
        owner="micropython", repo="micropython", pr_number=1,
        body="summary", comments=comments,
    )
    assert result["review_id"] == 55
    assert result["comment_count"] == 2


def test_post_review_strips_extra_comment_fields(bot_mcp):
    """post_review strips fields the GitHub API doesn't accept."""
    tools, mock_api = bot_mcp
    mock_api.github_request.side_effect = [[], {"id": 1}]

    comments = [
        {"path": "f.c", "line": 1, "side": "RIGHT", "body": "fix",
         "suggestion": "corrected", "extra_field": True},
    ]
    tools["post_review"].fn(
        owner="micropython", repo="micropython", pr_number=1,
        body="summary", comments=comments,
    )
    # Inspect the payload sent to github_request
    call_args = mock_api.github_request.call_args_list
    # Last call is the POST for the review (first call is GET for pending reviews)
    post_call = [c for c in call_args if c[0][0] == "POST"][-1]
    sent_comments = post_call[0][2].get("comments", [])
    assert len(sent_comments) == 1
    assert "suggestion" not in sent_comments[0]
    assert "extra_field" not in sent_comments[0]


def test_post_review_always_uses_comment_event(bot_mcp):
    """post_review always submits with event='COMMENT' (hardcoded)."""
    tools, mock_api = bot_mcp
    mock_api.github_request.side_effect = [[], {"id": 1}]

    tools["post_review"].fn(
        owner="micropython", repo="micropython", pr_number=1,
        body="test",
    )
    post_call = [c for c in mock_api.github_request.call_args_list if c[0][0] == "POST"][-1]
    payload = post_call[0][2]
    assert payload["event"] == "COMMENT"
