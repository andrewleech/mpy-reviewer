"""Tests for bot.github_api."""

import json
import os
import tempfile
import urllib.error
from io import BytesIO
from unittest.mock import patch, MagicMock

import pytest

from bot.github_api import github_request, _read_token


def _mock_response(body: str = "", status: int = 200):
    """Create a mock urllib response."""
    resp = MagicMock()
    resp.read.return_value = body.encode()
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_github_request_get():
    resp = _mock_response('{"id": 1}')
    with patch("bot.github_api.urllib.request.urlopen", return_value=resp):
        result = github_request("GET", "/repos/o/r", token="tok")
    assert result == {"id": 1}


def test_github_request_post_with_body():
    resp = _mock_response('{"id": 2}')
    with patch("bot.github_api.urllib.request.urlopen", return_value=resp) as mock_open:
        result = github_request("POST", "/test", body={"key": "val"}, token="tok")
    assert result == {"id": 2}
    req = mock_open.call_args[0][0]
    assert req.data == json.dumps({"key": "val"}).encode()
    assert req.get_header("Content-type") == "application/json"


def test_github_request_empty_response():
    resp = _mock_response("")
    with patch("bot.github_api.urllib.request.urlopen", return_value=resp):
        result = github_request("DELETE", "/test", token="tok")
    assert result is None


def test_github_request_no_token_raises():
    with patch("bot.github_api._read_token", return_value=None):
        with pytest.raises(RuntimeError, match="No GitHub token"):
            github_request("GET", "/test")


def test_github_request_http_error():
    err = urllib.error.HTTPError(
        url="https://api.github.com/test",
        code=422,
        msg="Unprocessable",
        hdrs=None,
        fp=BytesIO(b"error details"),
    )
    with patch("bot.github_api.urllib.request.urlopen", side_effect=err):
        with pytest.raises(urllib.error.HTTPError):
            github_request("POST", "/test", token="tok")


def test_read_token_file_not_found():
    with patch.dict(os.environ, {"GITHUB_TOKEN_FILE": "/nonexistent/path"}):
        assert _read_token() is None


def test_read_token_from_file():
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".token") as f:
        f.write("test-token-value")
        path = f.name
    try:
        with patch.dict(os.environ, {"GITHUB_TOKEN_FILE": path}):
            assert _read_token() == "test-token-value"
    finally:
        os.unlink(path)


def test_github_request_raw_mode():
    resp = _mock_response("raw diff content here")
    with patch("bot.github_api.urllib.request.urlopen", return_value=resp):
        result = github_request("GET", "/test", token="tok", raw=True)
    assert result == "raw diff content here"
    assert isinstance(result, str)


def test_github_request_custom_accept():
    resp = _mock_response("diff output")
    with patch("bot.github_api.urllib.request.urlopen", return_value=resp) as mock_open:
        github_request(
            "GET", "/test", token="tok",
            accept="application/vnd.github.diff", raw=True,
        )
    req = mock_open.call_args[0][0]
    assert req.get_header("Accept") == "application/vnd.github.diff"


def test_github_request_url_error():
    err = urllib.error.URLError("DNS lookup failed")
    with patch("bot.github_api.urllib.request.urlopen", side_effect=err):
        with pytest.raises(urllib.error.URLError):
            github_request("GET", "/test", token="tok")
