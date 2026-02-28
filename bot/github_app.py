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


def fetch_app_slug(app_id: int, private_key_pem: str) -> str:
    """Fetch the GitHub App slug via GET /app using JWT auth.

    Args:
        app_id: GitHub App ID.
        private_key_pem: RSA private key in PEM format.

    Returns:
        The app slug (e.g. "my-review-bot").
    """
    jwt_token = generate_jwt(app_id, private_key_pem)
    url = "https://api.github.com/app"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {jwt_token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()[:200] if e.fp else ""
        raise RuntimeError(
            f"Failed to fetch app info (HTTP {e.code}): {error_body}"
        ) from e
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"Failed to connect to GitHub API: {e}") from e

    slug = data.get("slug", "")
    if not slug:
        raise RuntimeError("GitHub App response missing 'slug' field")
    return slug


class GitHubAppAuth:
    """Manages GitHub App installation tokens with auto-refresh.

    Caches tokens per installation_id and refreshes each independently
    when within 5 minutes of expiry. Writes the latest token to
    GITHUB_TOKEN_FILE so the MCP server can read it on each API call.

    The shared token file is safe because ReviewQueue serializes reviews:
    only one review runs at a time, so the file always holds the token
    for the currently-active installation.
    """

    def __init__(
        self,
        app_id: int,
        private_key_pem: str | Callable[[], str],
        token_file: str | None = None,
    ):
        self.app_id = app_id
        if callable(private_key_pem):
            self._get_pem = private_key_pem
        else:
            self._get_pem = lambda pem=private_key_pem: pem
        self.token_file = token_file or os.environ.get(
            "GITHUB_TOKEN_FILE", DEFAULT_TOKEN_FILE
        )
        self._tokens: dict[int, tuple[str, datetime]] = {}
        self._refresh_lock = threading.Lock()

    def get_token(self, installation_id: int) -> str:
        """Get a valid installation token, refreshing if needed."""
        if self._needs_refresh(installation_id):
            with self._refresh_lock:
                if self._needs_refresh(installation_id):
                    self._refresh(installation_id)
        return self._tokens[installation_id][0]

    def _needs_refresh(self, installation_id: int) -> bool:
        entry = self._tokens.get(installation_id)
        if entry is None:
            return True
        _, expires_at = entry
        now = datetime.now(timezone.utc)
        # Refresh if within 5 minutes of expiry
        remaining = (expires_at - now).total_seconds()
        return remaining < 300

    def _refresh(self, installation_id: int) -> None:
        """Generate a new JWT and exchange it for an installation token."""
        logger.info("Refreshing GitHub App token for installation %d", installation_id)
        for attempt in range(2):
            try:
                jwt_token = generate_jwt(self.app_id, self._get_pem())
                token, expires_at = get_installation_token(
                    jwt_token, installation_id
                )
                self._tokens[installation_id] = (token, expires_at)
                break
            except Exception as e:
                if attempt == 0:
                    logger.warning("Token refresh failed, retrying in 1s: %s", e)
                    time.sleep(1)
                else:
                    raise
        try:
            self._write_token_file(self._tokens[installation_id][0])
        except OSError as e:
            logger.error(
                "Token refreshed in memory but file write to %s failed: %s. "
                "MCP server will not authenticate until next successful write.",
                self.token_file, e,
            )
        logger.info(
            "Token refreshed for installation %d, expires at %s",
            installation_id, self._tokens[installation_id][1].isoformat(),
        )

    def _write_token_file(self, token: str) -> None:
        """Write token to the shared file for MCP server to read.

        No fsync before rename — token-share is tmpfs so durability is moot.
        """
        tmp_path = self.token_file + ".tmp"
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(token)
        os.replace(tmp_path, self.token_file)
