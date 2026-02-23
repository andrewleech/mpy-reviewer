"""Thin HTTP client for GitHub REST API.

Uses urllib.request to avoid adding a requests dependency.
Reads auth token from a file path (env var GITHUB_TOKEN_FILE) on each call,
so the webhook service can rotate the token without restarting the MCP server.
"""

import json
import logging
import os
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

DEFAULT_TOKEN_FILE = "/var/run/token/github_token"
GITHUB_API_BASE = "https://api.github.com"


def _read_token() -> str | None:
    """Read GitHub token from file path in GITHUB_TOKEN_FILE env var."""
    token_file = os.environ.get("GITHUB_TOKEN_FILE", DEFAULT_TOKEN_FILE)
    try:
        with open(token_file) as f:
            token = f.read().strip()
            return token or None
    except OSError:
        logger.debug("Cannot read token file: %s", token_file)
        return None


def github_request(
    method: str,
    endpoint: str,
    body: dict | None = None,
    token: str | None = None,
    accept: str = "application/vnd.github+json",
    raw: bool = False,
) -> dict | str | None:
    """Make an authenticated GitHub REST API request.

    Args:
        method: HTTP method (GET, POST, PUT, DELETE, PATCH).
        endpoint: API endpoint path (e.g. "/repos/owner/repo/pulls/1/reviews").
        body: Optional JSON body for POST/PUT/PATCH requests.
        token: Override token. If None, reads from GITHUB_TOKEN_FILE.
        accept: Accept header value.
        raw: If True, return the raw response body as a string.

    Returns:
        Parsed JSON response body, raw string, or None if the response body is empty.

    Raises:
        urllib.error.HTTPError: On non-2xx response.
        RuntimeError: If no token is available.
    """
    if token is None:
        token = _read_token()
    if token is None:
        raise RuntimeError(
            f"No GitHub token available. Set GITHUB_TOKEN_FILE env var "
            f"or write token to {DEFAULT_TOKEN_FILE}"
        )

    url = f"{GITHUB_API_BASE}{endpoint}"
    data = json.dumps(body).encode() if body else None

    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", accept)
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data:
        req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_body = resp.read().decode()
            if raw:
                return resp_body
            if resp_body:
                return json.loads(resp_body)
            return None
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()[:200] if e.fp else ""
        logger.error(
            "GitHub API error: %s %s -> %d: %s",
            method, endpoint, e.code, error_body,
        )
        raise
    except urllib.error.URLError as e:
        logger.error("GitHub API connection error: %s %s -> %s", method, endpoint, e)
        raise
