"""Tests for bot.review_queue."""

import asyncio

import pytest

from bot.review_queue import ReviewQueue, ReviewRequest
from bot.tests.conftest import make_review_request


@pytest.mark.asyncio
async def test_enqueue_and_process():
    results = []

    async def handler(req):
        results.append(req.pr_number)
        return True

    q = ReviewQueue(handler=handler)
    task = asyncio.create_task(q.start_worker())
    await q.enqueue(make_review_request(pr_number=1))
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert results == [1]


@pytest.mark.asyncio
async def test_serial_processing():
    order = []

    async def handler(req):
        order.append(req.pr_number)
        await asyncio.sleep(0.01)
        return True

    q = ReviewQueue(handler=handler)
    task = asyncio.create_task(q.start_worker())
    await q.enqueue(make_review_request(pr_number=1))
    await q.enqueue(make_review_request(pr_number=2))
    await asyncio.sleep(0.2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert order == [1, 2]


@pytest.mark.asyncio
async def test_cancel_restart_same_pr():
    handler_entered = asyncio.Event()
    cancelled = False
    call_count = 0

    async def slow_handler(req):
        nonlocal cancelled, call_count
        call_count += 1
        if call_count == 1:
            handler_entered.set()
            try:
                await asyncio.sleep(10)
                return True
            except asyncio.CancelledError:
                cancelled = True
                raise
        # Second invocation returns immediately
        return True

    q = ReviewQueue(handler=slow_handler)
    task = asyncio.create_task(q.start_worker())
    await q.enqueue(make_review_request(pr_number=1))
    await handler_entered.wait()
    # Re-enqueue same PR should cancel in-progress
    await q.enqueue(make_review_request(pr_number=1))
    await asyncio.sleep(0.3)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert cancelled


@pytest.mark.asyncio
async def test_dedup_queued_entries():
    results = []

    async def handler(req):
        results.append(req.pr_number)
        await asyncio.sleep(0.05)
        return True

    q = ReviewQueue(handler=handler)
    # Don't start worker yet, just enqueue
    await q.enqueue(make_review_request(pr_number=1))
    await q.enqueue(make_review_request(pr_number=2))
    await q.enqueue(make_review_request(pr_number=1))  # duplicate of PR 1
    # Queue should have PR 2 and PR 1 (deduped)
    assert q._queue.qsize() == 2


@pytest.mark.asyncio
async def test_success_callback():
    success_prs = []

    async def handler(req):
        return True

    async def on_success(req):
        success_prs.append(req.pr_number)

    q = ReviewQueue(handler=handler, on_success=on_success)
    task = asyncio.create_task(q.start_worker())
    await q.enqueue(make_review_request(pr_number=1))
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert success_prs == [1]


@pytest.mark.asyncio
async def test_failure_callback_on_false():
    failures = []

    async def handler(req):
        return False

    async def on_failure(req, err):
        failures.append((req.pr_number, err))

    q = ReviewQueue(handler=handler, on_failure=on_failure)
    task = asyncio.create_task(q.start_worker())
    await q.enqueue(make_review_request(pr_number=1))
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert len(failures) == 1
    assert failures[0] == (1, None)


@pytest.mark.asyncio
async def test_failure_callback_on_exception():
    failures = []

    async def handler(req):
        raise RuntimeError("boom")

    async def on_failure(req, err):
        failures.append((req.pr_number, str(err)))

    q = ReviewQueue(handler=handler, on_failure=on_failure)
    task = asyncio.create_task(q.start_worker())
    await q.enqueue(make_review_request(pr_number=1))
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert len(failures) == 1
    assert failures[0] == (1, "boom")


@pytest.mark.asyncio
async def test_queue_maxsize():
    """Full queue drops oldest entry."""
    async def slow_handler(req):
        await asyncio.sleep(10)
        return True

    q = ReviewQueue(handler=slow_handler)
    # Fill the queue (maxsize=100)
    for i in range(100):
        q._queue.put_nowait(make_review_request(pr_number=i + 1000))
    assert q._queue.full()
    # Enqueue should drop oldest and succeed
    await q.enqueue(make_review_request(pr_number=9999))
    assert q._queue.qsize() == 100
