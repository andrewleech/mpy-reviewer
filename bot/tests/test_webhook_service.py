"""Tests for bot.webhook_service."""

import asyncio
import hashlib
import hmac
import json
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from bot.webhook_service import create_app, MAX_FAILURE_RETRIES
from bot.config import BotConfig, _build_config
from bot.review_queue import ReviewQueue, ReviewRequest


def _make_config() -> BotConfig:
    return _build_config({
        "github_app": {
            "app_id": 1,
            "webhook_secret": "test-secret",
            "private_key": "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----",
        },
        "authorization": {"allowlist": ["allowed-user"]},
        "review": {"model": "sonnet", "timeout_seconds": 60},
    })


def _sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _make_payload(
    action="created",
    comment_body="/review",
    username="allowed-user",
    is_pr=True,
    repo_full="micropython/micropython",
):
    issue = {"number": 42}
    if is_pr:
        issue["pull_request"] = {"url": "..."}
    return {
        "action": action,
        "comment": {
            "id": 999,
            "body": comment_body,
            "user": {"login": username},
        },
        "issue": issue,
        "repository": {"full_name": repo_full},
        "installation": {"id": 123},
    }


@pytest.fixture
def app():
    """App with mocked auth/queue — tests webhook_handler paths in isolation."""
    config = _make_config()
    with patch("bot.webhook_service.GitHubAppAuth") as MockAuth:
        mock_auth = MagicMock()
        mock_auth.get_token.return_value = "test-token"
        MockAuth.return_value = mock_auth
        with patch("bot.webhook_service.fetch_app_slug", return_value="test-bot"):
            with patch("bot.webhook_service.ReviewQueue") as MockQueue:
                mock_queue = MagicMock()
                mock_queue.enqueue = AsyncMock()
                mock_queue.start_worker = AsyncMock()
                MockQueue.return_value = mock_queue
                app = create_app(config)
                yield app, mock_queue


def _post_webhook(client, payload, secret="test-secret", event="issue_comment"):
    body = json.dumps(payload).encode()
    sig = _sign(body, secret)
    return client.post(
        "/webhook",
        content=body,
        headers={
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": event,
            "Content-Type": "application/json",
        },
    )


def test_health_endpoint(app):
    app_instance, _ = app
    with TestClient(app_instance) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_invalid_signature(app):
    app_instance, _ = app
    with TestClient(app_instance) as client:
        payload = _make_payload()
        body = json.dumps(payload).encode()
        resp = client.post(
            "/webhook",
            content=body,
            headers={
                "X-Hub-Signature-256": "sha256=bad",
                "X-GitHub-Event": "issue_comment",
            },
        )
    assert resp.status_code == 401


def test_non_issue_comment_event(app):
    app_instance, _ = app
    with TestClient(app_instance) as client:
        resp = _post_webhook(client, _make_payload(), event="push")
    assert resp.status_code == 200


def test_non_created_action(app):
    app_instance, _ = app
    with TestClient(app_instance) as client:
        resp = _post_webhook(client, _make_payload(action="deleted"))
    assert resp.status_code == 200


def test_non_review_comment(app):
    app_instance, _ = app
    with TestClient(app_instance) as client:
        resp = _post_webhook(client, _make_payload(comment_body="just a comment"))
    assert resp.status_code == 200


def test_issue_not_pr(app):
    app_instance, _ = app
    with TestClient(app_instance) as client:
        resp = _post_webhook(client, _make_payload(is_pr=False))
    assert resp.status_code == 200


def test_unauthorized_user(app):
    app_instance, _ = app
    with TestClient(app_instance) as client:
        with patch("bot.webhook_service.is_authorized", return_value=False):
            resp = _post_webhook(client, _make_payload(username="evil"))
    assert resp.status_code == 200
    assert resp.json().get("reason") == "unauthorized"


def test_valid_review_queued(app):
    app_instance, mock_queue = app
    with TestClient(app_instance) as client:
        with patch("bot.webhook_service.is_authorized", return_value=True):
            with patch("bot.webhook_service.github_request"):
                resp = _post_webhook(client, _make_payload())
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    mock_queue.enqueue.assert_called_once()
    req = mock_queue.enqueue.call_args[0][0]
    assert req.installation_id == 123


def test_missing_installation_key(app):
    """Payload without installation key still queues (token=None path)."""
    app_instance, mock_queue = app
    payload = _make_payload()
    del payload["installation"]
    with TestClient(app_instance) as client:
        with patch("bot.webhook_service.is_authorized", return_value=True):
            with patch("bot.webhook_service.github_request"):
                resp = _post_webhook(client, payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    req = mock_queue.enqueue.call_args[0][0]
    assert req.installation_id == 0


def test_invalid_json_body(app):
    app_instance, _ = app
    with TestClient(app_instance) as client:
        body = b"not json"
        sig = _sign(body, "test-secret")
        resp = client.post(
            "/webhook",
            content=body,
            headers={
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "issue_comment",
            },
        )
    assert resp.status_code == 400


def test_empty_repo_full_name(app):
    app_instance, _ = app
    with TestClient(app_instance) as client:
        payload = _make_payload(repo_full="")
        with patch("bot.webhook_service.is_authorized", return_value=True):
            resp = _post_webhook(client, payload)
    # Should be handled before auth check since repo_full comes first...
    # Actually looking at the code flow: sig check -> event check -> action check ->
    # comment body check -> PR check -> then repo_full validation
    # So with empty repo_full it should return "ignored"
    assert resp.status_code == 200
    assert resp.json().get("reason") == "invalid repo"


def test_payload_too_large(app):
    app_instance, _ = app
    with TestClient(app_instance) as client:
        resp = client.post(
            "/webhook",
            content=b"x",
            headers={
                "Content-Length": "999999999",
                "X-Hub-Signature-256": "sha256=bad",
                "X-GitHub-Event": "issue_comment",
            },
        )
    assert resp.status_code == 413


@pytest.fixture
def callback_app():
    """App with real lifespan — tests on_success/on_failure callbacks."""
    config = _make_config()
    with patch("bot.webhook_service.GitHubAppAuth") as MockAuth:
        mock_auth = MagicMock()
        mock_auth.get_token.return_value = "tok"
        MockAuth.return_value = mock_auth
        with patch("bot.webhook_service.fetch_app_slug", return_value="test-bot"):
            with patch("bot.webhook_service.ReviewQueue") as _:
                app_inst = create_app(config)
            with patch("bot.orchestrator.run_review", new_callable=AsyncMock):
                with TestClient(app_inst) as client:
                    yield app_inst, client


@pytest.mark.asyncio
async def test_on_failure_does_not_leak_error_details(callback_app):
    """Failure comment must not contain internal error details."""
    app_inst, _ = callback_app
    posted_comments = []

    def mock_github_request(method, endpoint, body=None, token=None, **kw):
        if method == "POST" and "/comments" in endpoint and body and "body" in body:
            posted_comments.append(body["body"])
        return None

    queue = app_inst.state.queue
    req = ReviewRequest(
        pr_number=99, comment_id=100,
        repo_owner="o", repo_name="r",
        requester="u", head_sha="abc",
    )
    with patch("bot.webhook_service.github_request", side_effect=mock_github_request):
        await queue.on_failure(req, RuntimeError("secret internal traceback"))

    assert len(posted_comments) == 1
    assert "secret internal traceback" not in posted_comments[0]
    assert "Retry with `/review`" in posted_comments[0]


@pytest.mark.asyncio
async def test_on_failure_suppresses_after_max_retries(callback_app):
    """After MAX_FAILURE_RETRIES, no more comments are posted."""
    app_inst, _ = callback_app
    posted_comments = []

    def mock_github_request(method, endpoint, body=None, token=None, **kw):
        if method == "POST" and "/comments" in endpoint and body and "body" in body:
            posted_comments.append(body["body"])
        return None

    queue = app_inst.state.queue
    req = ReviewRequest(
        pr_number=98, comment_id=100,
        repo_owner="o", repo_name="r",
        requester="u", head_sha="abc",
    )
    app_inst.state.failure_counts["pr-98"] = MAX_FAILURE_RETRIES + 1
    with patch("bot.webhook_service.github_request", side_effect=mock_github_request):
        await queue.on_failure(req, RuntimeError("err"))

    # No comment should be posted since we exceeded max retries
    assert len(posted_comments) == 0


@pytest.mark.asyncio
async def test_on_success_resets_failure_count(callback_app):
    """Success clears the failure counter for the PR."""
    app_inst, _ = callback_app

    queue = app_inst.state.queue
    app_inst.state.failure_counts["pr-97"] = 2
    req = ReviewRequest(
        pr_number=97, comment_id=100,
        repo_owner="o", repo_name="r",
        requester="u", head_sha="abc",
    )
    with patch("bot.webhook_service.github_request", return_value=None):
        await queue.on_success(req)

    assert "pr-97" not in app_inst.state.failure_counts


def test_payload_too_large_no_content_length(app):
    """Large body without Content-Length header still rejected."""
    app_instance, _ = app
    with TestClient(app_instance) as client:
        big_body = b"x" * (5_000_001)
        sig = _sign(big_body, "test-secret")
        resp = client.post(
            "/webhook",
            content=big_body,
            headers={
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "issue_comment",
            },
        )
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_on_failure_diff_too_large_uses_fixed_message(callback_app):
    """DiffTooLargeError posts a generic message, not the raw exception."""
    from bot.orchestrator import DiffTooLargeError

    app_inst, _ = callback_app
    posted = []

    def mock_gr(method, endpoint, body=None, token=None, **kw):
        if method == "POST" and "/comments" in endpoint and body and "body" in body:
            posted.append(body["body"])
        return None

    req = ReviewRequest(
        pr_number=96, comment_id=100,
        repo_owner="o", repo_name="r",
        requester="u", head_sha="abc",
    )
    with patch("bot.webhook_service.github_request", side_effect=mock_gr):
        await app_inst.state.queue.on_failure(
            req, DiffTooLargeError("Diff exceeds 1,000,000 chars (2,000,000)")
        )
    assert len(posted) == 1
    assert "1,000,000" not in posted[0]
    assert "too large" in posted[0].lower()


def test_wrong_repo_rejected(app):
    """Webhook for non-target repo returns 'wrong repo'."""
    app_instance, _ = app
    with TestClient(app_instance) as client:
        with patch("bot.webhook_service.is_authorized", return_value=True):
            resp = _post_webhook(client, _make_payload(repo_full="other/repo"))
    assert resp.status_code == 200
    assert resp.json().get("reason") == "wrong repo"


@pytest.mark.asyncio
async def test_on_failure_tolerates_reaction_failure(callback_app):
    """Failure comment still posted when reaction API call fails."""
    app_inst, _ = callback_app
    posted = []

    def mock_gr(method, endpoint, body=None, token=None, **kw):
        if method == "POST" and "/reactions" in endpoint:
            raise RuntimeError("reaction API down")
        if method == "POST" and "/comments" in endpoint and body and "body" in body:
            posted.append(body["body"])
        return None

    req = ReviewRequest(
        pr_number=94, comment_id=100,
        repo_owner="o", repo_name="r",
        requester="u", head_sha="abc",
    )
    with patch("bot.webhook_service.github_request", side_effect=mock_gr):
        await app_inst.state.queue.on_failure(req, RuntimeError("err"))
    assert len(posted) == 1


@pytest.mark.asyncio
async def test_on_failure_token_refresh_failure(callback_app):
    """Early return when auth.get_token() raises — no reaction or comment posted."""
    app_inst, _ = callback_app
    app_inst.state.auth.get_token.side_effect = RuntimeError("token refresh failed")
    posted = []

    def mock_gr(method, endpoint, body=None, token=None, **kw):
        if method == "POST":
            posted.append(endpoint)
        return None

    req = ReviewRequest(
        pr_number=93, comment_id=100,
        repo_owner="o", repo_name="r",
        requester="u", head_sha="abc",
    )
    with patch("bot.webhook_service.github_request", side_effect=mock_gr):
        await app_inst.state.queue.on_failure(req, RuntimeError("err"))
    assert len(posted) == 0


@pytest.mark.asyncio
async def test_on_success_tolerates_reaction_failure(callback_app):
    """Failure counter still cleared when reaction API call fails."""
    app_inst, _ = callback_app
    app_inst.state.failure_counts["pr-95"] = 2
    req = ReviewRequest(
        pr_number=95, comment_id=100,
        repo_owner="o", repo_name="r",
        requester="u", head_sha="abc",
    )
    with patch("bot.webhook_service.github_request",
               side_effect=RuntimeError("reaction API down")):
        await app_inst.state.queue.on_success(req)
    assert "pr-95" not in app_inst.state.failure_counts


# --- review_requested (pull_request event) tests ---


def _make_pr_payload(
    action="review_requested",
    reviewer_login="test-bot[bot]",
    pr_number=42,
    head_sha="abc123",
    sender="allowed-user",
    repo_full="micropython/micropython",
):
    payload = {
        "action": action,
        "pull_request": {
            "number": pr_number,
            "head": {"sha": head_sha},
        },
        "sender": {"login": sender},
        "repository": {"full_name": repo_full},
        "installation": {"id": 123},
    }
    if reviewer_login is not None:
        payload["requested_reviewer"] = {"login": reviewer_login}
    return payload


def test_review_requested_queued(app):
    app_instance, mock_queue = app
    with TestClient(app_instance) as client:
        resp = _post_webhook(
            client, _make_pr_payload(), event="pull_request",
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    mock_queue.enqueue.assert_called_once()
    req = mock_queue.enqueue.call_args[0][0]
    assert req.comment_id == 0
    assert req.pr_number == 42


def test_review_requested_wrong_reviewer_ignored(app):
    app_instance, mock_queue = app
    with TestClient(app_instance) as client:
        resp = _post_webhook(
            client,
            _make_pr_payload(reviewer_login="someone-else"),
            event="pull_request",
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    mock_queue.enqueue.assert_not_called()


def test_review_requested_wrong_repo_ignored(app):
    app_instance, mock_queue = app
    with TestClient(app_instance) as client:
        resp = _post_webhook(
            client,
            _make_pr_payload(repo_full="other/repo"),
            event="pull_request",
        )
    assert resp.status_code == 200
    assert resp.json().get("reason") == "wrong repo"
    mock_queue.enqueue.assert_not_called()


def test_review_requested_non_review_action_ignored(app):
    app_instance, mock_queue = app
    with TestClient(app_instance) as client:
        resp = _post_webhook(
            client,
            _make_pr_payload(action="opened"),
            event="pull_request",
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    mock_queue.enqueue.assert_not_called()


def test_review_requested_team_request_ignored(app):
    """Team review requests (no requested_reviewer) are ignored."""
    app_instance, mock_queue = app
    payload = _make_pr_payload(reviewer_login=None)
    # Remove requested_reviewer, add requested_team instead
    payload.pop("requested_reviewer", None)
    payload["requested_team"] = {"name": "some-team"}
    with TestClient(app_instance) as client:
        resp = _post_webhook(client, payload, event="pull_request")
    assert resp.status_code == 200
    mock_queue.enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_on_success_skips_reaction_when_no_comment(callback_app):
    """Success callback with comment_id=0 skips reaction, clears failure count."""
    app_inst, _ = callback_app
    app_inst.state.failure_counts["pr-91"] = 2
    api_calls = []

    def mock_gr(method, endpoint, body=None, token=None, **kw):
        api_calls.append((method, endpoint))
        return None

    req = ReviewRequest(
        pr_number=91, comment_id=0,
        repo_owner="o", repo_name="r",
        requester="u", head_sha="abc",
    )
    with patch("bot.webhook_service.github_request", side_effect=mock_gr):
        await app_inst.state.queue.on_success(req)
    assert "pr-91" not in app_inst.state.failure_counts
    assert len(api_calls) == 0  # No reaction API call


@pytest.mark.asyncio
async def test_on_failure_skips_reaction_but_posts_comment_when_no_comment_id(callback_app):
    """Failure callback with comment_id=0 skips reaction but still posts PR comment."""
    app_inst, _ = callback_app
    api_calls = []

    def mock_gr(method, endpoint, body=None, token=None, **kw):
        api_calls.append((method, endpoint))
        return None

    req = ReviewRequest(
        pr_number=90, comment_id=0,
        repo_owner="o", repo_name="r",
        requester="u", head_sha="abc",
    )
    with patch("bot.webhook_service.github_request", side_effect=mock_gr):
        await app_inst.state.queue.on_failure(req, RuntimeError("err"))
    # No reaction call, but comment should be posted
    reaction_calls = [c for c in api_calls if "/reactions" in c[1]]
    comment_calls = [c for c in api_calls if "/comments" in c[1]]
    assert len(reaction_calls) == 0
    assert len(comment_calls) == 1
