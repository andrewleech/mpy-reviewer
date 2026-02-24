# Round 6 Fix Plan

29 findings (1 critical skipped per prior decision), grouped by fixup commit target.

---

## Fixup 1: `--fixup=e1aef7b7` (mcp_server.py, tests/test_mcp_bot_tools.py)

### #1/#2 [WARNING] Extract bot tools from mcp_server.py into bot/mcp_tools.py

**Files:** `mcp_server.py:326-456` → new `bot/mcp_tools.py`, `tests/test_mcp_bot_tools.py`

The three review-posting tools (`create_review`, `add_review_comment`, `submit_review`) plus `_check_repo` and the env-var/import guard move to `bot/mcp_tools.py`. This eliminates the bidirectional dependency (mcp_server no longer imports from bot) and makes the tools testable without monkey-patching FastMCP internals.

**New file `bot/mcp_tools.py`:**
```python
"""Review-posting MCP tools for the bot deployment."""

import os
from typing import Optional

def register_bot_tools(mcp):
    """Register bot tools if bot package is available and bot mode is enabled.

    (Existing SECURITY docstring moves here)
    """
    try:
        from bot.github_api import github_request
    except ImportError:
        return

    if not os.environ.get("MPY_REVIEWER_BOT_MODE"):
        return

    target_repo = os.environ.get("BOT_TARGET_REPO", "micropython/micropython")

    def _check_repo(owner, repo):
        """Reject requests targeting repos other than the configured target."""
        ...

    @mcp.tool()
    def create_review(...): ...

    @mcp.tool()
    def add_review_comment(...): ...

    @mcp.tool()
    def submit_review(...): ...
```

**Update `mcp_server.py`:**
```python
# Remove _register_bot_tools() entirely (lines 326-455)
# Update __main__ block:
if __name__ == "__main__":
    try:
        from bot.mcp_tools import register_bot_tools
        register_bot_tools(mcp)
    except ImportError:
        pass
    ...
```

**Update `tests/test_mcp_bot_tools.py`:**
Tests import `register_bot_tools` from `bot.mcp_tools` instead of calling `mcp_server._register_bot_tools()`. No more monkey-patching `mcp_server.mcp`.

### #12 [INFO] `create_review` sends empty dict when `commit_sha` is None

**File:** `bot/mcp_tools.py` (after extraction)

```python
# Before
body = {"commit_id": commit_sha} if commit_sha else {}

# After
body = {"commit_id": commit_sha} if commit_sha else None
```

### #13 [INFO] Test boilerplate in test_mcp_bot_tools.py

**File:** `tests/test_mcp_bot_tools.py`

After #1/#2, the tests import from `bot.mcp_tools` directly. Extract the common setup into a fixture:

```python
@pytest.fixture
def bot_mcp():
    """FastMCP instance with bot tools registered."""
    from fastmcp import FastMCP
    os.environ["MPY_REVIEWER_BOT_MODE"] = "1"
    test_mcp = FastMCP("test")
    mock_github_request = MagicMock()
    with patch.dict("sys.modules", {
        "bot": MagicMock(),
        "bot.github_api": MagicMock(github_request=mock_github_request),
    }):
        from bot.mcp_tools import register_bot_tools
        register_bot_tools(test_mcp)
    tools = test_mcp._tool_manager._tools
    return tools, mock_github_request
```

### #14 [INFO] Inconsistent type annotation style

**File:** `mcp_server.py`

Update `mcp_server.py`'s `Optional` imports to PEP 604 style to match `bot/`. The `rag/` package keeps its existing style.

```python
# Before
from typing import Optional
def review_diff(... top_k: int = 8, include_codebase: bool = False) -> str:

# After — remove `from typing import Optional`, use `X | None` for any Optional params
```

---

## Fixup 2: `--fixup=4c03a546` (bot/config.py, bot/github_app.py, bot/tests/)

### #10 [WARNING] TargetConfig properties compute on access

**File:** `bot/config.py:44-54`

Replace cached `_owner`/`_name` with compute-on-access properties. Remove the `__post_init__` caching. Keep the validation.

```python
@dataclass
class TargetConfig:
    repo: str = "micropython/micropython"

    def __post_init__(self):
        if "/" not in self.repo:
            raise ValueError(f"repo must be 'owner/name', got: {self.repo!r}")
        owner, name = self.repo.split("/", 1)
        if not owner or not name:
            raise ValueError(f"repo must be 'owner/name', got: {self.repo!r}")

    @property
    def owner(self) -> str:
        return self.repo.split("/", 1)[0]

    @property
    def name(self) -> str:
        return self.repo.split("/", 1)[1]
```

### #11 [WARNING] Inline key warning → debug

**File:** `bot/config.py:119-122`

```python
# Before
logger.warning(
    "Using inline private_key. Consider private_key_path to reduce exposure."
)

# After
logger.debug(
    "Using inline private_key. Consider private_key_path for production."
)
```

### #19 [WARNING] Test for `_refresh` double failure

**File:** `bot/tests/test_github_app.py`

```python
def test_refresh_raises_after_retry_exhaustion():
    auth = GitHubAppAuth(
        app_id=1, private_key_pem=_TEST_RSA_PEM,
        installation_id=1, token_file="/dev/null",
    )
    with patch("bot.github_app.get_installation_token",
               side_effect=RuntimeError("persistent failure")):
        with pytest.raises(RuntimeError, match="persistent failure"):
            auth._refresh()
```

### #20 [WARNING] Wire `ReviewConfig.top_k` and `include_codebase` into system prompt

**File:** `bot/prompt.py`

The `claude -p` subprocess calls MCP tools with their own `top_k` and `include_codebase` params. Pass the config values as instructions in the system prompt so the model uses them.

```python
def build_system_prompt(
    additional_system_prompt: str = "",
    top_k: int = 8,
    include_codebase: bool = True,
) -> str:
    ...
    # Add to tool workflow section:
    tool_instructions = (
        "## Review Workflow\n"
        "\n"
        f"1. Use the `review_pr` or `review_diff` MCP tool with `top_k={top_k}` "
        f"and `include_codebase={'true' if include_codebase else 'false'}` to retrieve "
        "relevant past review examples from the RAG database.\n"
        ...
    )
```

Update `bot/orchestrator.py` call site:
```python
system_prompt = build_system_prompt(
    additional_system_prompt=config.prompt.additional_system_prompt,
    top_k=config.review.top_k,
    include_codebase=config.review.include_codebase,
)
```

### #30 [INFO] Token write lacks fsync — document

**File:** `bot/github_app.py:140-146`

```python
def _write_token_file(self) -> None:
    """Write token to the shared file for MCP server to read.

    No fsync before rename — token-share is tmpfs so durability is moot.
    """
```

---

## Fixup 3: `--fixup=9bf02e83` (bot/ app logic, tests)

### #3 [WARNING] Document DiffTooLargeError exception contract

**File:** `bot/review_queue.py:32-37`

Add documentation to the handler type alias and the worker:

```python
class ReviewQueue:
    """Processes review requests serially with cancel-restart for same-PR duplicates.

    The handler callable returns True on success, False on non-exceptional failure.
    It may also raise exceptions — these are caught by the worker and routed to
    on_failure with the exception instance. DiffTooLargeError is the primary
    typed exception used for user-facing error messages.
    """
```

### #4 [WARNING] Cache collaborator status with TTL

**File:** `bot/auth.py`

Add a simple TTL cache to `is_authorized` for the collaborator API check:

```python
import time

_collab_cache: dict[str, tuple[bool, float]] = {}
_COLLAB_CACHE_TTL = 300  # 5 minutes

def is_authorized(...) -> bool:
    if allowlist and username in allowlist:
        return True

    cache_key = f"{owner}/{repo}/{username}"
    cached = _collab_cache.get(cache_key)
    if cached and (time.monotonic() - cached[1]) < _COLLAB_CACHE_TTL:
        return cached[0]

    # ... existing collaborator check ...
    result = ...  # True/False from API
    _collab_cache[cache_key] = (result, time.monotonic())
    return result
```

Add test and autouse fixture for cache isolation.

### #5 [INFO] Move `_failure_counts` to app.state

**File:** `bot/webhook_service.py`

Remove module-level `_failure_counts`, `_MAX_TRACKED_FAILURES`. Create inside `lifespan` and attach to `app.state.failure_counts`. Update `_on_success` and `_on_failure` closures to reference `app.state.failure_counts`. Remove the test fixture `_reset_failure_counts` since each `create_app` gets its own dict.

```python
async def lifespan(app):
    ...
    failure_counts: OrderedDict[str, int] = OrderedDict()
    app.state.failure_counts = failure_counts
    ...
```

Update callbacks to use `failure_counts` (closed over from lifespan scope).

Update tests: `_failure_counts` imports become `app_inst.state.failure_counts`.

### #6 [INFO] Clarify flock docstring

**File:** `bot/orchestrator.py:228-232`

```python
async def _update_checkout(pr_number: int, head_sha: str) -> bool:
    """Update the shared MicroPython checkout to the PR's head commit.

    Returns True on success, False on failure.
    The ReviewQueue serializes reviews, so concurrent checkouts are not expected.
    The flock is defense-in-depth against future parallel workers or manual
    CLI invocations sharing the same checkout directory.
    """
```

### #7 [WARNING] Document sync flock unlock as intentional

**File:** `bot/orchestrator.py:240, 299-300`

The `os.open` and `flock` unlock are fast syscalls that won't block the event loop. Document:

```python
    # os.open is a fast syscall — acceptable on the event loop thread.
    lock_fd = os.open(_CHECKOUT_LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        await asyncio.to_thread(fcntl.flock, lock_fd, fcntl.LOCK_EX)
        ...
    finally:
        # Synchronous unlock + close — fast syscalls, no event loop concern.
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
```

### #8 [WARNING] SHA mismatch → warning severity

**File:** `bot/orchestrator.py:290`

```python
# Before
logger.error(
    "Checkout SHA mismatch for PR #%d: expected %s, got %s",

# After
logger.warning(
    "Checkout SHA mismatch for PR #%d: expected %s, got %s",
```

### #9 [WARNING] Clarify `_on_failure` control flow

**File:** `bot/webhook_service.py:229-240`

Restructure to make `body` assignment explicit in each branch:

```python
if isinstance(err, DiffTooLargeError):
    body = "Diff is too large for automated review. Please split into smaller PRs."
elif failure_counts[retry_key] <= MAX_FAILURE_RETRIES:
    if err:
        logger.error("Review failed for PR #%d: %s", req.pr_number, err)
    body = "Review failed. Retry with `/review`."
else:
    logger.warning(
        "Suppressing failure comment for PR #%d (retry count %d)",
        req.pr_number, failure_counts[retry_key],
    )
    return  # suppressed
```

This is already the structure — the `if err:` guard only protects the log, not the `body` assignment. Add a comment:

```python
            if err:
                # Log internal details (not posted to GitHub)
                logger.error("Review failed for PR #%d: %s", req.pr_number, err)
            body = "Review failed. Retry with `/review`."
```

### #15 [WARNING] Test for wrong-repo rejection

**File:** `bot/tests/test_webhook_service.py`

```python
def test_wrong_repo_rejected(app):
    app_instance, _ = app
    with TestClient(app_instance) as client:
        with patch("bot.webhook_service.is_authorized", return_value=True):
            resp = _post_webhook(client, _make_payload(repo_full="other/repo"))
    assert resp.status_code == 200
    assert resp.json().get("reason") == "wrong repo"
```

### #16 [WARNING] Test for _on_failure reaction failure tolerance

**File:** `bot/tests/test_webhook_service.py`

```python
@pytest.mark.asyncio
async def test_on_failure_tolerates_reaction_failure(callback_app):
    """Failure comment still posted when reaction API call fails."""
    app_inst, _ = callback_app
    posted = []
    call_count = 0

    def mock_gr(method, endpoint, body=None, token=None, **kw):
        nonlocal call_count
        call_count += 1
        if method == "POST" and "/reactions" in endpoint:
            raise RuntimeError("reaction API down")
        if method == "POST" and "/comments" in endpoint and body and "body" in body:
            posted.append(body["body"])
        return None

    req = ReviewRequest(...)
    with patch("bot.webhook_service.github_request", side_effect=mock_gr):
        await app_inst.state.queue.on_failure(req, RuntimeError("err"))
    assert len(posted) == 1
```

### #17 [WARNING] Test for _on_failure token refresh failure

**File:** `bot/tests/test_webhook_service.py`

```python
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

    req = ReviewRequest(...)
    with patch("bot.webhook_service.github_request", side_effect=mock_gr):
        await app_inst.state.queue.on_failure(req, RuntimeError("err"))
    assert len(posted) == 0  # Nothing posted due to early return
```

### #18 [WARNING] Test for _on_success reaction failure

**File:** `bot/tests/test_webhook_service.py`

```python
@pytest.mark.asyncio
async def test_on_success_tolerates_reaction_failure(callback_app):
    """Failure counter still cleared when reaction API call fails."""
    app_inst, _ = callback_app
    # Pre-populate failure count
    app_inst.state.failure_counts["pr-95"] = 2
    req = ReviewRequest(pr_number=95, ...)

    with patch("bot.webhook_service.github_request",
               side_effect=RuntimeError("reaction API down")):
        await app_inst.state.queue.on_success(req)
    assert "pr-95" not in app_inst.state.failure_counts
```

Note: This test relies on #5 (move _failure_counts to app.state). If #5 is deferred, use the module-level `_failure_counts` import instead.

### #21 [WARNING] Log dropped PR number in queue overflow

**File:** `bot/review_queue.py:79-82`

```python
# Before
logger.warning("Review queue full (%d), dropping oldest", self._queue.qsize())
try:
    self._queue.get_nowait()
    self._queue.task_done()

# After
try:
    dropped = self._queue.get_nowait()
    self._queue.task_done()
    logger.warning(
        "Review queue full, dropping PR #%d to make room",
        dropped.pr_number,
    )
```

### #22 [INFO] Test for SHA mismatch

**File:** `bot/tests/test_orchestrator.py`

```python
@pytest.mark.asyncio
async def test_update_checkout_sha_mismatch():
    """Returns False when checked-out SHA differs from expected."""
    with patch("os.path.isdir", return_value=True):
        async def mock_exec(*args, **kwargs):
            proc = MagicMock()
            proc.returncode = 0
            async def communicate():
                if "rev-parse" in args:
                    return b"different_sha\n", b""
                return b"", b""
            proc.communicate = communicate
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            result = await _update_checkout(1, "expected_sha")
    assert result is False
```

### #23 [INFO] Document _sanitize_untrusted rationale

**File:** `bot/prompt.py:88-90`

```python
def _sanitize_untrusted(text: str) -> str:
    """Strip fake delimiter tags from untrusted PR content.

    Stripping (vs. escaping) is intentional: these exact strings should never
    appear in legitimate code diffs. Removing them preserves readability while
    preventing delimiter injection. The system prompt's first/last tag rule
    provides a second layer of defense.
    """
    return text.replace("<untrusted-pr-content>", "").replace("</untrusted-pr-content>", "")
```

### #24 [INFO] Remove redundant `pass` from DiffTooLargeError

**File:** `bot/orchestrator.py:33-34`

```python
# Before
class DiffTooLargeError(Exception):
    """Raised when PR diff exceeds MAX_DIFF_CHARS."""
    pass

# After
class DiffTooLargeError(Exception):
    """Raised when PR diff exceeds MAX_DIFF_CHARS."""
```

### #26 [WARNING] Document body-buffering tradeoff

**File:** `bot/webhook_service.py:49-52`

The tradeoff is inherent to HMAC verification (need full body to compute signature). Add comment:

```python
    # Definitive size check after full body read. Starlette buffers the
    # entire body for request.body(). This is inherent to HMAC verification
    # (we need the complete body to compute the signature). Protection against
    # oversized bodies relies on the Content-Length fast-path above and
    # uvicorn's --limit-concurrency for concurrent connection limits.
    body = await request.body()
```

### #27 [WARNING] Document system prompt CLI arg limitation

**File:** `bot/orchestrator.py:114-116`

The existing comment already documents the mitigation. Strengthen to note fallback:

```python
    # System prompt is passed as a CLI argument. It contains review guidelines
    # and the additional_system_prompt from config — no credentials or tokens.
    # /proc visibility is mitigated by pid:private in docker-compose.yml.
    # If running without PID isolation, write to a temp file and pass via
    # --system-prompt-file (requires Claude CLI support).
```

### #28 [WARNING] Document shared volume timing in _update_checkout docstring

Already partly addressed in #6. The updated docstring covers this:

```python
    """Update the shared MicroPython checkout to the PR's head commit.

    Returns True on success, False on failure.
    The ReviewQueue serializes reviews, so concurrent checkouts are not expected.
    The flock is defense-in-depth against future parallel workers or manual
    CLI invocations sharing the same checkout directory.

    The MCP server shares this volume. File reads during review are safe because
    the claude -p subprocess (which calls MCP tools) is only spawned after
    checkout completes. Do not run MCP reads concurrently with checkout.
    """
```

### #29 [INFO] Document near-miss tag handling

Covered by the expanded docstring in #23. The system prompt's first/last tag rule handles near-miss variations since the model is instructed to only trust exact delimiter boundaries.

---

## Finding → Fixup Mapping

| # | Sev | Finding | Fixup |
|---|-----|---------|-------|
| 1 | WARN | Bot tools as closures | 1 |
| 2 | WARN | Bidirectional dependency | 1 (via #1) |
| 3 | WARN | DiffTooLargeError contract | 3 |
| 4 | WARN | No rate limiting on auth | 3 |
| 5 | INFO | _failure_counts module-level | 3 |
| 6 | INFO | flock docstring | 3 |
| 7 | WARN | Mixed sync/async flock | 3 |
| 8 | WARN | SHA mismatch severity | 3 |
| 9 | WARN | _on_failure control flow | 3 |
| 10 | WARN | TargetConfig stale properties | 2 |
| 11 | WARN | Inline key warning level | 2 |
| 12 | INFO | create_review empty dict | 1 |
| 13 | INFO | Test boilerplate | 1 |
| 14 | INFO | Type annotation style | 1 |
| 15 | WARN | No wrong-repo test | 3 |
| 16 | WARN | No reaction failure test | 3 |
| 17 | WARN | No token refresh failure test | 3 |
| 18 | WARN | No success reaction failure test | 3 |
| 19 | WARN | No _refresh double failure test | 2 |
| 20 | WARN | Unused ReviewConfig fields | 2 |
| 21 | WARN | Queue dedup log | 3 |
| 22 | INFO | No SHA mismatch test | 3 |
| 23 | INFO | _sanitize_untrusted rationale | 3 |
| 24 | INFO | Redundant pass | 3 |
| 25 | CRIT | MCP no auth | SKIP |
| 26 | WARN | Body buffering tradeoff | 3 |
| 27 | WARN | System prompt /proc | 3 |
| 28 | WARN | git clean shared volume | 3 |
| 29 | INFO | Near-miss tags | 3 (via #23) |
| 30 | INFO | Token write no fsync | 2 |

---

## Execution

```bash
# Fixup 1
git add mcp_server.py bot/mcp_tools.py tests/test_mcp_bot_tools.py
git commit --fixup=e1aef7b7

# Fixup 2
git add bot/config.py bot/github_app.py bot/prompt.py bot/orchestrator.py \
        bot/tests/test_github_app.py bot/tests/test_prompt.py
git commit --fixup=4c03a546

# Fixup 3
git add bot/auth.py bot/webhook_service.py bot/orchestrator.py \
        bot/prompt.py bot/review_queue.py \
        bot/tests/test_orchestrator.py bot/tests/test_webhook_service.py \
        bot/tests/test_auth.py
git commit --fixup=9bf02e83

# Squash
GIT_SEQUENCE_EDITOR=":" git rebase -i --autosquash origin/main
```

## Verification

```bash
source venv/bin/activate
pytest bot/tests/ tests/ -v
timeout 3 python mcp_server.py --transport stdio < /dev/null
python -c "from bot.config import load_config; print('config OK')"
python -c "from bot.webhook_service import create_app; print('webhook OK')"
```
