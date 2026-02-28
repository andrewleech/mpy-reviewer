"""Tests for bot.github_app."""

import json
import os
import stat
import tempfile
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

from bot.github_app import generate_jwt, get_installation_token, GitHubAppAuth


# Generate a valid RSA key at import time (test-only, not for production)
def _generate_test_rsa_key() -> str:
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

_TEST_RSA_PEM = _generate_test_rsa_key()


def test_generate_jwt_structure():
    """JWT contains iss, iat, exp claims."""
    import jwt as pyjwt
    token = generate_jwt(123, _TEST_RSA_PEM)
    # Decode without verification (we don't have the public key handy)
    decoded = pyjwt.decode(token, options={"verify_signature": False}, algorithms=["RS256"])
    assert decoded["iss"] == "123"
    assert "iat" in decoded
    assert "exp" in decoded
    assert decoded["exp"] > decoded["iat"]


def test_needs_refresh_no_token():
    auth = GitHubAppAuth(
        app_id=1, private_key_pem=_TEST_RSA_PEM,
    )
    assert auth._needs_refresh(1) is True


def test_needs_refresh_expired():
    auth = GitHubAppAuth(
        app_id=1, private_key_pem=_TEST_RSA_PEM,
    )
    auth._tokens[1] = ("tok", datetime.now(timezone.utc) + timedelta(minutes=1))
    assert auth._needs_refresh(1) is True  # Within 5 min window


def test_needs_refresh_valid():
    auth = GitHubAppAuth(
        app_id=1, private_key_pem=_TEST_RSA_PEM,
    )
    auth._tokens[1] = ("tok", datetime.now(timezone.utc) + timedelta(minutes=30))
    assert auth._needs_refresh(1) is False


def test_write_token_file_permissions():
    with tempfile.NamedTemporaryFile(delete=False) as f:
        path = f.name
    try:
        auth = GitHubAppAuth(
            app_id=1, private_key_pem=_TEST_RSA_PEM,
            token_file=path,
        )
        auth._write_token_file("secret-token")
        mode = os.stat(path).st_mode
        assert stat.S_IMODE(mode) == 0o600
        with open(path) as f:
            assert f.read() == "secret-token"
    finally:
        os.unlink(path)


def test_write_token_file_atomic():
    with tempfile.NamedTemporaryFile(delete=False) as f:
        path = f.name
    try:
        auth = GitHubAppAuth(
            app_id=1, private_key_pem=_TEST_RSA_PEM,
            token_file=path,
        )
        auth._write_token_file("secret-token")
        # No .tmp file should remain
        assert not os.path.exists(path + ".tmp")
    finally:
        os.unlink(path)


def test_get_installation_token_success():
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "token": "ghs_test", "expires_at": "2026-01-01T00:00:00Z"
    }).encode()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("bot.github_app.urllib.request.urlopen", return_value=mock_resp):
        token, expires = get_installation_token("jwt", 123)
    assert token == "ghs_test"
    assert expires.year == 2026


def test_get_token_calls_refresh():
    auth = GitHubAppAuth(
        app_id=1, private_key_pem=_TEST_RSA_PEM,
        token_file="/dev/null",
    )
    with patch("bot.github_app.get_installation_token") as mock:
        mock.return_value = ("fresh-token", datetime.now(timezone.utc) + timedelta(hours=1))
        result = auth.get_token(1)
    assert result == "fresh-token"
    mock.assert_called_once()


def test_refresh_retries_on_transient_failure():
    auth = GitHubAppAuth(
        app_id=1, private_key_pem=_TEST_RSA_PEM,
        token_file="/dev/null",
    )
    call_count = 0

    def mock_get_token(jwt_tok, inst_id):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("transient")
        return ("tok", datetime.now(timezone.utc) + timedelta(hours=1))

    with patch("bot.github_app.get_installation_token", side_effect=mock_get_token):
        auth._refresh(1)
    assert auth._tokens[1][0] == "tok"
    assert call_count == 2


def test_refresh_raises_after_retry_exhaustion():
    """Both retry attempts fail — exception propagates."""
    auth = GitHubAppAuth(
        app_id=1, private_key_pem=_TEST_RSA_PEM,
        token_file="/dev/null",
    )
    with patch("bot.github_app.get_installation_token",
               side_effect=RuntimeError("persistent failure")):
        with pytest.raises(RuntimeError, match="persistent failure"):
            auth._refresh(1)


def test_per_installation_token_cache():
    """Separate installations get separate cached tokens."""
    auth = GitHubAppAuth(
        app_id=1, private_key_pem=_TEST_RSA_PEM,
        token_file="/dev/null",
    )
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    call_log = []

    def mock_get_token(jwt_tok, inst_id):
        call_log.append(inst_id)
        return (f"tok-{inst_id}", expires)

    with patch("bot.github_app.get_installation_token", side_effect=mock_get_token):
        t1 = auth.get_token(100)
        t2 = auth.get_token(200)
        # Second call for same installation should use cache
        t1b = auth.get_token(100)

    assert t1 == "tok-100"
    assert t2 == "tok-200"
    assert t1b == "tok-100"
    assert call_log == [100, 200]  # No third call — cached
