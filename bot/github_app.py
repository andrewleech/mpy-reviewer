"""GitHub App authentication: JWT generation and installation token lifecycle."""

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone

import jwt

from bot.github_api import DEFAULT_TOKEN_FILE

logger = logging.getLogger(__name__)


def generate_jwt(app_id: int, private_key_pem: str) -> str:
    """Generate a GitHub App JWT (RS256, 10-minute expiry).

    Args:
        app_id: GitHub App ID.
        private_key_pem: RSA private key in PEM format.

    Returns:
        Signed JWT string.
    """

    now = int(time.time())
    payload = {
        "iat": now - 60,  # 60s clock skew allowance
        "exp": now + (10 * 60),  # 10 minute expiry
        "iss": str(app_id),
    }
    return jwt.encode(payload, private_key_pem, algorithm="RS256")


def get_installation_token(
    jwt_token: str, installation_id: int
) -> tuple[str, datetime]:
    """Exchange a JWT for an installation access token.

    Args:
        jwt_token: GitHub App JWT.
        installation_id: GitHub App installation ID.

    Returns:
        (token, expires_at) tuple.
    """
    url = (
        f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    )
    req = urllib.request.Request(url, data=b"{}", method="POST")
    req.add_header("Authorization", f"Bearer {jwt_token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()[:200] if e.fp else ""
        raise RuntimeError(
            f"Failed to get installation token (HTTP {e.code}): {error_body}"
        ) from e
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"Failed to connect to GitHub API: {e}") from e

    token = data["token"]
    expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
    return token, expires_at


class GitHubAppAuth:
    """Manages GitHub App installation token with auto-refresh.

    Caches the installation token and refreshes it when within 5 minutes
    of expiry. Writes the token to GITHUB_TOKEN_FILE so the MCP server
    can read it on each API call.
    """

    def __init__(
        self,
        app_id: int,
        private_key_pem: str | Callable[[], str],
        installation_id: int,
        token_file: str | None = None,
    ):
        self.app_id = app_id
        if callable(private_key_pem):
            self._get_pem = private_key_pem
        else:
            self._get_pem = lambda pem=private_key_pem: pem
        self.installation_id = installation_id
        self.token_file = token_file or os.environ.get(
            "GITHUB_TOKEN_FILE", DEFAULT_TOKEN_FILE
        )
        self._token: str | None = None
        self._expires_at: datetime | None = None
        self._refresh_lock = threading.Lock()

    def get_token(self) -> str:
        """Get a valid installation token, refreshing if needed."""
        if self._needs_refresh():
            with self._refresh_lock:
                if self._needs_refresh():  # double-check after acquiring lock
                    self._refresh()
        return self._token

    def _needs_refresh(self) -> bool:
        if self._token is None or self._expires_at is None:
            return True
        now = datetime.now(timezone.utc)
        # Refresh if within 5 minutes of expiry
        remaining = (self._expires_at - now).total_seconds()
        return remaining < 300

    def _refresh(self) -> None:
        """Generate a new JWT and exchange it for an installation token."""
        logger.info("Refreshing GitHub App installation token")
        for attempt in range(2):
            try:
                jwt_token = generate_jwt(self.app_id, self._get_pem())
                self._token, self._expires_at = get_installation_token(
                    jwt_token, self.installation_id
                )
                break
            except Exception as e:
                if attempt == 0:
                    logger.warning("Token refresh failed, retrying in 1s: %s", e)
                    time.sleep(1)
                else:
                    raise
        try:
            self._write_token_file()
        except OSError as e:
            logger.error(
                "Token refreshed in memory but file write to %s failed: %s. "
                "MCP server will not authenticate until next successful write.",
                self.token_file, e,
            )
        logger.info(
            "Token refreshed, expires at %s", self._expires_at.isoformat()
        )

    def _write_token_file(self) -> None:
        """Write token to the shared file for MCP server to read.

        No fsync before rename — token-share is tmpfs so durability is moot.
        """
        tmp_path = self.token_file + ".tmp"
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(self._token)
        os.replace(tmp_path, self.token_file)
