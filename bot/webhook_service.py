"""GitHub webhook receiver for /review trigger commands.

Runs as a Starlette ASGI app. Receives issue_comment events from GitHub,
validates signatures, authorizes users, and enqueues review requests.
"""

import asyncio
import json
import logging
from collections import OrderedDict

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from bot.auth import verify_webhook_signature, is_authorized
from bot.config import get_bot_config, BotConfig
from bot.github_api import github_request
from bot.github_app import GitHubAppAuth
from bot.review_queue import ReviewQueue, ReviewRequest

logger = logging.getLogger(__name__)

MAX_PAYLOAD_BYTES = 5_000_000  # 5MB, generous for GitHub webhooks
MAX_FAILURE_RETRIES = 3
_MAX_TRACKED_FAILURES = 1000


async def webhook_handler(request: Request) -> Response:
    """Handle incoming GitHub webhook events."""
    config = getattr(request.app.state, "config", None)
    auth = getattr(request.app.state, "auth", None)
    queue = getattr(request.app.state, "queue", None)
    if config is None or queue is None:
        return JSONResponse({"error": "not initialized"}, status_code=503)

    # Fast-path: reject obviously oversized payloads before reading body.
    # This check alone is insufficient — clients can omit Content-Length.
    content_length = request.headers.get("content-length", "")
    try:
        if content_length and int(content_length) > MAX_PAYLOAD_BYTES:
            return JSONResponse({"error": "payload too large"}, status_code=413)
    except ValueError:
        pass

    # Definitive size check after full body read. Starlette buffers the
    # entire body for request.body(). This is inherent to HMAC verification
    # (we need the complete body to compute the signature). Protection against
    # oversized bodies relies on the Content-Length fast-path above and
    # uvicorn's --limit-concurrency for concurrent connection limits.
    body = await request.body()
    if len(body) > MAX_PAYLOAD_BYTES:
        return JSONResponse({"error": "payload too large"}, status_code=413)
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not verify_webhook_signature(body, signature, config.github_app.webhook_secret):
        logger.warning("Invalid webhook signature")
        return JSONResponse({"error": "invalid signature"}, status_code=401)

    event_type = request.headers.get("X-GitHub-Event", "")
    if event_type != "issue_comment":
        return JSONResponse({"status": "ok"})

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    # Only handle new comments
    if payload.get("action") != "created":
        return JSONResponse({"status": "ok"})

    comment_body = payload.get("comment", {}).get("body", "").strip()
    # Exact match intentional — only "/review", not "/review please" etc.
    if comment_body != "/review":
        return JSONResponse({"status": "ok"})

    # Must be on a PR (issue_comment fires for both issues and PRs)
    issue = payload.get("issue", {})
    if "pull_request" not in issue:
        return JSONResponse({"status": "ok"})

    # Authorization check
    username = payload.get("comment", {}).get("user", {}).get("login", "")
    repo_full = payload.get("repository", {}).get("full_name", "")
    if not repo_full or "/" not in repo_full:
        logger.warning("Missing or malformed repository.full_name: %r", repo_full)
        return JSONResponse({"status": "ignored", "reason": "invalid repo"})
    repo_owner, repo_name = repo_full.split("/", 1)

    if repo_full != config.target.repo:
        logger.warning("Webhook for non-target repo %s (target: %s)", repo_full, config.target.repo)
        return JSONResponse({"status": "ignored", "reason": "wrong repo"})

    token = auth.get_token() if auth else None
    if not is_authorized(
        username, repo_owner, repo_name,
        allowlist=config.authorization.allowlist,
        token=token,
    ):
        logger.info("Unauthorized /review from %s", username)
        return JSONResponse({"status": "ignored", "reason": "unauthorized"})

    comment_id = payload.get("comment", {}).get("id", 0)
    pr_number = issue.get("number", 0)
    if not pr_number:
        logger.warning("Missing PR number in webhook payload")
        return JSONResponse({"status": "ignored", "reason": "missing pr_number"})

    # Add eyes reaction
    try:
        await asyncio.to_thread(
            github_request,
            "POST",
            f"/repos/{repo_owner}/{repo_name}/issues/comments/{comment_id}/reactions",
            {"content": "eyes"},
            token=token,
        )
    except Exception as e:
        logger.warning("Failed to add eyes reaction: %s", e)

    # head_sha may be empty if the PR API call fails here.
    # The orchestrator re-fetches PR metadata and prefers the fresh SHA.
    # Enqueuing with empty SHA is intentional — it allows the review to
    # proceed once the transient API failure resolves.
    head_sha = ""
    try:
        pr_data = await asyncio.to_thread(
            github_request,
            "GET",
            f"/repos/{repo_owner}/{repo_name}/pulls/{pr_number}",
            token=token,
        )
        head_sha = pr_data.get("head", {}).get("sha", "")
    except Exception as e:
        logger.warning("Failed to get PR head SHA: %s", e)

    review_request = ReviewRequest(
        pr_number=pr_number,
        comment_id=comment_id,
        repo_owner=repo_owner,
        repo_name=repo_name,
        requester=username,
        head_sha=head_sha,
    )

    await queue.enqueue(review_request)

    return JSONResponse({
        "status": "queued",
        "pr_number": pr_number,
    })


async def health_handler(request: Request) -> Response:
    """Health check endpoint."""
    return JSONResponse({"status": "ok"})


routes = [
    Route("/webhook", webhook_handler, methods=["POST"]),
    Route("/health", health_handler, methods=["GET"]),
]


def create_app(config: BotConfig | None = None) -> Starlette:
    """Create the Starlette ASGI app.

    Args:
        config: Bot config. If None, loads from env/default path.
    """
    if config is None:
        config = get_bot_config()

    async def lifespan(app):
        # Import here to avoid circular imports at module level
        from bot.orchestrator import run_review

        auth = GitHubAppAuth(
            app_id=config.github_app.app_id,
            private_key_pem=config.github_app.get_private_key_pem,  # callable, not called
            installation_id=config.github_app.installation_id,
        )
        # Force initial token refresh
        auth.get_token()

        # Per-app failure counter — no cross-app leakage, no test isolation fixture needed.
        failure_counts: OrderedDict[str, int] = OrderedDict()

        async def _handler(req: ReviewRequest) -> bool:
            return await run_review(req, config, auth=auth)

        async def _on_success(req: ReviewRequest) -> None:
            failure_counts.pop(f"pr-{req.pr_number}", None)
            try:
                token = auth.get_token()
                await asyncio.to_thread(
                    github_request, "POST",
                    f"/repos/{req.repo_owner}/{req.repo_name}"
                    f"/issues/comments/{req.comment_id}/reactions",
                    {"content": "+1"}, token=token,
                )
            except Exception as e:
                logger.warning("Failed to add success reaction: %s", e)

        async def _on_failure(req: ReviewRequest, err: Exception | None) -> None:
            from bot.orchestrator import DiffTooLargeError

            try:
                token = auth.get_token()
            except Exception as e:
                logger.error("Token refresh failed in failure handler: %s", e)
                return  # Can't post reactions/comments without a token

            try:
                await asyncio.to_thread(
                    github_request, "POST",
                    f"/repos/{req.repo_owner}/{req.repo_name}"
                    f"/issues/comments/{req.comment_id}/reactions",
                    {"content": "confused"}, token=token,
                )
            except Exception as e:
                logger.warning("Failed to add failure reaction: %s", e)

            # Safety: no await between read, increment, and write. The single-threaded
            # asyncio event loop guarantees no interleaving. Do NOT add any await
            # between the next three lines.
            retry_key = f"pr-{req.pr_number}"
            failure_counts[retry_key] = failure_counts.get(retry_key, 0) + 1
            failure_counts.move_to_end(retry_key)
            if len(failure_counts) > _MAX_TRACKED_FAILURES:
                failure_counts.popitem(last=False)

            if isinstance(err, DiffTooLargeError):
                body = "Diff is too large for automated review. Please split into smaller PRs."
            elif failure_counts[retry_key] <= MAX_FAILURE_RETRIES:
                if err:
                    # Log internal details (not posted to GitHub)
                    logger.error("Review failed for PR #%d: %s", req.pr_number, err)
                body = "Review failed. Retry with `/review`."
            else:
                logger.warning(
                    "Suppressing failure comment for PR #%d (retry count %d)",
                    req.pr_number, failure_counts[retry_key],
                )
                return  # suppressed

            try:
                await asyncio.to_thread(
                    github_request, "POST",
                    f"/repos/{req.repo_owner}/{req.repo_name}"
                    f"/issues/{req.pr_number}/comments",
                    {"body": body}, token=token,
                )
            except Exception as e:
                logger.warning("Failed to post failure comment: %s", e)

        queue = ReviewQueue(
            handler=_handler,
            on_success=_on_success,
            on_failure=_on_failure,
        )

        app.state.config = config
        app.state.auth = auth
        app.state.queue = queue
        app.state.failure_counts = failure_counts

        worker_task = asyncio.create_task(queue.start_worker())
        logger.info("Webhook service started")
        yield
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        logger.info("Webhook service shutting down")

    return Starlette(routes=routes, lifespan=lifespan)


def main():
    """Entry point for running the webhook service."""
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    config = get_bot_config()
    app = create_app(config)
    uvicorn.run(app, host=config.server.host, port=config.server.port)


if __name__ == "__main__":
    main()
