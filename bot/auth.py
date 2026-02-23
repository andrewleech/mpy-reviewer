"""Webhook signature verification and user authorization."""

import hashlib
import hmac
import logging
import time
import urllib.error

from bot.github_api import github_request

logger = logging.getLogger(__name__)

_collab_cache: dict[str, tuple[bool, float]] = {}
_COLLAB_CACHE_TTL = 300  # 5 minutes


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify a GitHub webhook HMAC-SHA256 signature.

    Args:
        payload: Raw request body bytes.
        signature: Value of the X-Hub-Signature-256 header (sha256=...).
        secret: Webhook secret from config.

    Returns:
        True if the signature is valid.
    """
    if not secret:
        return False
    if not signature.startswith("sha256="):
        return False
    expected = hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    received = signature[len("sha256="):]
    return hmac.compare_digest(expected, received)


def is_authorized(
    username: str,
    owner: str,
    repo: str,
    allowlist: list[str] | None = None,
    token: str | None = None,
) -> bool:
    """Check if a user is authorized to trigger reviews.

    A user is authorized if they are:
    1. On the config allowlist, OR
    2. A collaborator on the target repository

    Args:
        username: GitHub username.
        owner: Repository owner.
        repo: Repository name.
        allowlist: Usernames that are always authorized.
        token: GitHub token for API calls.

    Returns:
        True if the user is authorized.
    """
    if allowlist and username in allowlist:
        return True

    cache_key = f"{owner}/{repo}/{username}"
    cached = _collab_cache.get(cache_key)
    if cached and (time.monotonic() - cached[1]) < _COLLAB_CACHE_TTL:
        return cached[0]

    # Check if the user is a repo collaborator (204 = yes, 404 = no)
    try:
        github_request(
            "GET",
            f"/repos/{owner}/{repo}/collaborators/{username}",
            token=token,
        )
        result = True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            result = False
        elif e.code == 403:
            # Rate-limited — fail closed, don't cache transient state.
            logger.warning("Rate limited checking collaborator status for %s", username)
            return False
        else:
            logger.warning("Collaborator check failed for %s: HTTP %d", username, e.code)
            return False
    except urllib.error.URLError as e:
        logger.warning("Network error checking collaborator status for %s: %s", username, e)
        return False

    _collab_cache[cache_key] = (result, time.monotonic())
    return result
