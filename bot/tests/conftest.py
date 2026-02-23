"""Shared test fixtures for bot tests."""

from bot.review_queue import ReviewRequest


# Helper function (not a fixture). Imported directly by test modules.
def make_review_request(**kwargs) -> ReviewRequest:
    """Create a ReviewRequest with sensible defaults."""
    defaults = dict(
        pr_number=1,
        comment_id=100,
        repo_owner="micropython",
        repo_name="micropython",
        requester="user",
        head_sha="abcdef1234567890",
    )
    defaults.update(kwargs)
    return ReviewRequest(**defaults)
