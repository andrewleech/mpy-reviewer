"""Serial review queue with cancel-restart support."""

import asyncio
import logging
from dataclasses import dataclass
from collections.abc import Callable, Awaitable

logger = logging.getLogger(__name__)


@dataclass
class ReviewRequest:
    """A queued review request."""

    pr_number: int
    comment_id: int
    repo_owner: str
    repo_name: str
    requester: str
    head_sha: str
    installation_id: int = 0


@dataclass
class TriageRequest:
    """A queued triage request."""

    issue_number: int
    comment_id: int
    repo_owner: str
    repo_name: str
    requester: str
    installation_id: int = 0


class ReviewQueue:
    """Processes review requests serially with cancel-restart for same-PR duplicates.

    The handler callable returns True on success, False on non-exceptional failure.
    It may also raise exceptions — these are caught by the worker and routed to
    on_failure with the exception instance. DiffTooLargeError is the primary
    typed exception used for user-facing error messages.

    Usage:
        queue = ReviewQueue(handler=run_review_func)
        asyncio.create_task(queue.start_worker())
        await queue.enqueue(request)
    """

    def __init__(
        self,
        handler: Callable[[ReviewRequest], Awaitable[bool]],
        on_success: Callable[[ReviewRequest], Awaitable[None]] | None = None,
        on_failure: Callable[[ReviewRequest, Exception | None], Awaitable[None]] | None = None,
    ):
        self.handler = handler
        self.on_success = on_success
        self.on_failure = on_failure
        self._queue: asyncio.Queue[ReviewRequest] = asyncio.Queue(maxsize=100)
        self._current_pr: int | None = None
        self._current_task: asyncio.Task | None = None

    async def enqueue(self, request: ReviewRequest) -> None:
        """Add a review request to the queue.

        If a review is in progress for the same PR, it will be cancelled
        when the worker picks up this new request.
        """
        # If the same PR is currently being reviewed, cancel it immediately
        if (
            self._current_pr == request.pr_number
            and self._current_task is not None
            and not self._current_task.done()
        ):
            logger.info(
                "Cancelling in-progress review for PR #%d (new request)",
                request.pr_number,
            )
            self._current_task.cancel()

        # Deduplicate: remove any queued entries for the same PR.
        # Safety: no await between drain and re-insert, so no other coroutine
        # can observe the partially-drained queue in single-threaded asyncio.
        existing = []
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                self._queue.task_done()
                existing.append(item)
            except asyncio.QueueEmpty:
                break
        for item in existing:
            if item.pr_number != request.pr_number:
                self._queue.put_nowait(item)

        if self._queue.full():
            try:
                dropped = self._queue.get_nowait()
                self._queue.task_done()
                logger.warning(
                    "Review queue full, dropping PR #%d to make room",
                    dropped.pr_number,
                )
            except asyncio.QueueEmpty:
                pass

        await self._queue.put(request)
        logger.info(
            "Enqueued review for PR #%d (queue depth: %d)",
            request.pr_number,
            self._queue.qsize(),
        )

    async def start_worker(self) -> None:
        """Worker loop — processes one review at a time."""
        logger.info("Review queue worker started")
        while True:
            request = await self._queue.get()
            logger.info(
                "Processing review for PR #%d (requested by %s)",
                request.pr_number,
                request.requester,
            )
            self._current_pr = request.pr_number

            try:
                # Wrap handler in a task so we can cancel it
                task = asyncio.create_task(self.handler(request))
                self._current_task = task
                success = await task
                if success and self.on_success:
                    await self.on_success(request)
                elif not success and self.on_failure:
                    await self.on_failure(request, None)
            except asyncio.CancelledError:
                logger.info(
                    "Review for PR #%d was cancelled", request.pr_number
                )
            except Exception as e:
                logger.exception(
                    "Review for PR #%d failed: %s", request.pr_number, e
                )
                if self.on_failure:
                    await self.on_failure(request, e)
            finally:
                self._current_pr = None
                self._current_task = None
                self._queue.task_done()
