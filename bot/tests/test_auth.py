"""Tests for bot.auth."""

import hashlib
import hmac
import urllib.error
from io import BytesIO
from unittest.mock import patch

import pytest

from bot.auth import verify_webhook_signature, is_authorized, _collab_cache


@pytest.fixture(autouse=True)
def _clear_collab_cache():
    """Isolate collaborator cache between tests."""
    _collab_cache.clear()
    yield
    _collab_cache.clear()


def test_valid_signature():
    secret = "test-secret"
    payload = b"hello world"
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    signature = f"sha256={digest}"
    assert verify_webhook_signature(payload, signature, secret) is True


def test_invalid_signature():
    secret = "test-secret"
    payload = b"hello world"
    signature = "sha256=0000000000000000000000000000000000000000000000000000000000000000"
    assert verify_webhook_signature(payload, signature, secret) is False


def test_missing_sha256_prefix():
    secret = "test-secret"
    payload = b"hello world"
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(payload, digest, secret) is False


def test_empty_signature():
    assert verify_webhook_signature(b"payload", "", "secret") is False


def test_empty_secret_returns_false():
    assert verify_webhook_signature(b"payload", "sha256=abc", "") is False


def test_authorized_on_allowlist():
    """Username in allowlist returns True without API call."""
    with patch("bot.auth.github_request") as mock_req:
        result = is_authorized("alice", "owner", "repo", allowlist=["alice"], token="tok")
        assert result is True
        mock_req.assert_not_called()


def test_authorized_as_collaborator():
    """Non-allowlisted user authorized via collaborator check (204 = None response)."""
    with patch("bot.auth.github_request", return_value=None):
        assert is_authorized("bob", "owner", "repo", allowlist=[], token="tok") is True


def test_unauthorized_not_collaborator():
    """Non-collaborator (404) returns False."""
    err = urllib.error.HTTPError(
        url="", code=404, msg="Not Found", hdrs=None, fp=BytesIO(b""),
    )
    with patch("bot.auth.github_request", side_effect=err):
        assert is_authorized("eve", "owner", "repo", allowlist=[], token="tok") is False


def test_unauthorized_api_error():
    """Server error (500) returns False."""
    err = urllib.error.HTTPError(
        url="", code=500, msg="Server Error", hdrs=None, fp=BytesIO(b""),
    )
    with patch("bot.auth.github_request", side_effect=err):
        assert is_authorized("eve", "owner", "repo", allowlist=[], token="tok") is False


def test_authorized_allowlist_none():
    """allowlist=None falls through to collaborator check."""
    with patch("bot.auth.github_request", return_value=None):
        assert is_authorized("bob", "o", "r", allowlist=None, token="tok") is True


def test_collab_cache_avoids_repeat_api_call():
    """Second call for same user hits cache, not the API."""
    with patch("bot.auth.github_request", return_value=None) as mock_req:
        assert is_authorized("alice", "o", "r", token="tok") is True
        assert is_authorized("alice", "o", "r", token="tok") is True
        mock_req.assert_called_once()


def test_collab_cache_does_not_cache_rate_limit():
    """403 rate-limit responses are not cached."""
    err = urllib.error.HTTPError(
        url="", code=403, msg="Forbidden", hdrs=None, fp=BytesIO(b""),
    )
    with patch("bot.auth.github_request", side_effect=err):
        assert is_authorized("eve", "o", "r", token="tok") is False
    assert "o/r/eve" not in _collab_cache
