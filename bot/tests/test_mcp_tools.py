"""Tests for bot.mcp_tools — CI inspection tools."""

import io
import os
import urllib.error
import zipfile
from io import BytesIO
from unittest.mock import patch, MagicMock

import pytest


# The tools are registered dynamically via register_bot_tools(), so we
# instantiate a real FastMCP and register tools against it, then call
# the underlying functions directly.

@pytest.fixture(scope="module")
def ci_tools():
    """Register bot tools and return a dict of {name: callable}."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("test")
    env = {
        "MPY_REVIEWER_BOT_MODE": "1",
        "BOT_TARGET_REPO": "micropython/micropython",
    }
    with patch.dict(os.environ, env):
        from bot.mcp_tools import register_bot_tools
        register_bot_tools(mcp)

    # Extract tool functions by name from the MCP instance
    tools = {}
    for tool in mcp._tool_manager._tools.values():
        tools[tool.name] = tool.fn
    return tools


def _make_check_run(name="build", status="completed", conclusion="failure",
                    run_id=100, details_url="", app_slug="github-actions"):
    return {
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "id": run_id,
        "html_url": f"https://github.com/micropython/micropython/runs/{run_id}",
        "output": {"title": f"{name} result", "summary": "some summary"},
        "details_url": details_url or f"https://github.com/micropython/micropython/actions/runs/999/job/{run_id}",
        "app": {"slug": app_slug},
    }


def _make_zip_log(job_name="build", steps=None):
    """Create an in-memory ZIP archive mimicking GitHub Actions log format."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        if steps is None:
            steps = {"1_setup.txt": "setup done\n", "2_run.txt": "error: fail\n"}
        for step_name, content in steps.items():
            zf.writestr(f"{job_name}/{step_name}", content)
    return buf.getvalue()


# --- get_check_runs ---

class TestGetCheckRuns:
    def test_basic(self, ci_tools):
        run = _make_check_run()
        resp = {"total_count": 1, "check_runs": [run]}
        with patch("bot.github_api.github_request", return_value=resp):
            result = ci_tools["get_check_runs"]("micropython", "micropython", "abc123")
        assert result["total_count"] == 1
        assert result["check_runs"][0]["name"] == "build"
        assert result["check_runs"][0]["conclusion"] == "failure"
        assert result["check_runs"][0]["check_run_id"] == 100

    def test_extracts_workflow_run_id(self, ci_tools):
        run = _make_check_run(
            details_url="https://github.com/micropython/micropython/actions/runs/42/job/100"
        )
        resp = {"total_count": 1, "check_runs": [run]}
        with patch("bot.github_api.github_request", return_value=resp):
            result = ci_tools["get_check_runs"]("micropython", "micropython", "abc")
        assert result["check_runs"][0]["workflow_run_id"] == 42

    def test_no_workflow_run_id_for_non_actions_app(self, ci_tools):
        run = _make_check_run(app_slug="codecov")
        resp = {"total_count": 1, "check_runs": [run]}
        with patch("bot.github_api.github_request", return_value=resp):
            result = ci_tools["get_check_runs"]("micropython", "micropython", "abc")
        assert "workflow_run_id" not in result["check_runs"][0]

    def test_pagination(self, ci_tools):
        page1 = {"total_count": 101, "check_runs": [_make_check_run(name=f"j{i}") for i in range(100)]}
        page2 = {"total_count": 101, "check_runs": [_make_check_run(name="last")]}
        with patch("bot.github_api.github_request", side_effect=[page1, page2]):
            result = ci_tools["get_check_runs"]("micropython", "micropython", "abc")
        assert result["total_count"] == 101

    def test_403_returns_error(self, ci_tools):
        err = urllib.error.HTTPError("", 403, "Forbidden", None, BytesIO(b""))
        with patch("bot.github_api.github_request", side_effect=err):
            result = ci_tools["get_check_runs"]("micropython", "micropython", "abc")
        assert "error" in result
        assert result["total_count"] == 0

    def test_repo_check(self, ci_tools):
        with pytest.raises(ValueError, match="does not match"):
            ci_tools["get_check_runs"]("evil", "repo", "abc")


# --- get_check_run_annotations ---

class TestGetCheckRunAnnotations:
    def test_basic(self, ci_tools):
        annotations = [
            {
                "path": "ports/esp32/main.c",
                "start_line": 12,
                "end_line": 12,
                "annotation_level": "failure",
                "message": "unused import `os`",
                "title": "ruff",
            }
        ]
        with patch("bot.github_api.github_request", return_value=annotations):
            result = ci_tools["get_check_run_annotations"]("micropython", "micropython", 100)
        assert result["count"] == 1
        assert result["annotations"][0]["path"] == "ports/esp32/main.c"
        assert result["annotations"][0]["start_line"] == 12
        assert result["annotations"][0]["message"] == "unused import `os`"

    def test_caps_at_100(self, ci_tools):
        annotations = [{"path": f"f{i}.c", "start_line": i, "end_line": i,
                         "annotation_level": "warning", "message": f"warn {i}", "title": "lint"}
                        for i in range(100)]
        # First page returns 100, second would return more but cap stops it
        with patch("bot.github_api.github_request", return_value=annotations):
            result = ci_tools["get_check_run_annotations"]("micropython", "micropython", 100)
        assert result["count"] == 100

    def test_empty(self, ci_tools):
        with patch("bot.github_api.github_request", return_value=[]):
            result = ci_tools["get_check_run_annotations"]("micropython", "micropython", 100)
        assert result["count"] == 0
        assert result["annotations"] == []

    def test_403_returns_error(self, ci_tools):
        err = urllib.error.HTTPError("", 403, "Forbidden", None, BytesIO(b""))
        with patch("bot.github_api.github_request", side_effect=err):
            result = ci_tools["get_check_run_annotations"]("micropython", "micropython", 100)
        assert "error" in result
        assert result["count"] == 0


# --- get_workflow_run_log ---

class TestGetWorkflowRunLog:
    def test_basic(self, ci_tools):
        zip_data = _make_zip_log("build", {
            "1_setup.txt": "setting up\n",
            "2_run.txt": "compiling...\nerror: undefined reference\n",
        })
        with patch("bot.github_api.github_request_binary", return_value=zip_data):
            result = ci_tools["get_workflow_run_log"]("micropython", "micropython", 42)
        assert result["job_name"] == "build"
        assert "undefined reference" in result["log"]

    def test_job_name_filter(self, ci_tools):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("build/1_run.txt", "build output\n")
            zf.writestr("test/1_run.txt", "test output\n")
        with patch("bot.github_api.github_request_binary", return_value=buf.getvalue()):
            result = ci_tools["get_workflow_run_log"]("micropython", "micropython", 42, job_name="test")
        assert result["job_name"] == "test"
        assert "test output" in result["log"]
        assert "build output" not in result["log"]

    def test_strips_timestamps(self, ci_tools):
        zip_data = _make_zip_log("build", {
            "1_run.txt": "2026-01-15T10:30:45.1234567Z error: fail\n",
        })
        with patch("bot.github_api.github_request_binary", return_value=zip_data):
            result = ci_tools["get_workflow_run_log"]("micropython", "micropython", 42)
        assert "2026-01-15" not in result["log"]
        assert "error: fail" in result["log"]

    def test_strips_ansi_escapes(self, ci_tools):
        zip_data = _make_zip_log("build", {
            "1_run.txt": "\x1b[31merror\x1b[0m: something\n",
        })
        with patch("bot.github_api.github_request_binary", return_value=zip_data):
            result = ci_tools["get_workflow_run_log"]("micropython", "micropython", 42)
        assert "\x1b" not in result["log"]
        assert "error: something" in result["log"]

    def test_tail_lines_truncation(self, ci_tools):
        lines = "\n".join(f"line {i}" for i in range(500))
        zip_data = _make_zip_log("build", {"1_run.txt": lines})
        with patch("bot.github_api.github_request_binary", return_value=zip_data):
            result = ci_tools["get_workflow_run_log"]("micropython", "micropython", 42, tail_lines=10)
        assert result["truncated"] is True
        # Should have the last 10 lines
        assert "line 499" in result["log"]
        assert "line 0" not in result["log"]

    def test_tail_lines_capped_at_500(self, ci_tools):
        lines = "\n".join(f"line {i}" for i in range(1000))
        zip_data = _make_zip_log("build", {"1_run.txt": lines})
        with patch("bot.github_api.github_request_binary", return_value=zip_data):
            result = ci_tools["get_workflow_run_log"]("micropython", "micropython", 42, tail_lines=9999)
        assert result["truncated"] is True
        # line 999 present, line 0 not (would need 1000 lines)
        assert "line 999" in result["log"]

    def test_403_returns_error(self, ci_tools):
        err = urllib.error.HTTPError("", 403, "Forbidden", None, BytesIO(b""))
        with patch("bot.github_api.github_request_binary", side_effect=err):
            result = ci_tools["get_workflow_run_log"]("micropython", "micropython", 42)
        assert "error" in result
        assert "permission" in result["error"].lower()

    def test_410_expired_logs(self, ci_tools):
        err = urllib.error.HTTPError("", 410, "Gone", None, BytesIO(b""))
        with patch("bot.github_api.github_request_binary", side_effect=err):
            result = ci_tools["get_workflow_run_log"]("micropython", "micropython", 42)
        assert "expired" in result["error"].lower()

    def test_bad_zip(self, ci_tools):
        with patch("bot.github_api.github_request_binary", return_value=b"not a zip"):
            result = ci_tools["get_workflow_run_log"]("micropython", "micropython", 42)
        assert "error" in result
        assert "ZIP" in result["error"]
