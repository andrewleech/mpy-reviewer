#!/usr/bin/env python3
"""
Collect dpgeorge's PR review comments from a MicroPython repository.

Uses the GitHub CLI (gh) for authentication and API access.
Supports resume from checkpoint and incremental updates.
"""

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from collect_utils import (
    REVIEWER, DB_PATH, REQUEST_DELAY, gh_api, init_db, get_sync_state,
    set_sync_state, search_in_range
)


def get_collected_pr_numbers(conn, repo):
    """Get set of PR numbers already collected for this repo."""
    cursor = conn.execute("SELECT number FROM prs WHERE repo = ?", (repo,))
    return {row[0] for row in cursor.fetchall()}


def search_prs_with_comments(repo, since=None):
    """Search for PRs that dpgeorge has commented on.

    Uses date ranges to work around GitHub's 1000 result limit.
    """
    base_query = f"repo:{repo} is:pr commenter:{REVIEWER}"

    if since:
        # Incremental sync - single query should be under 1000 results
        print(f"  Searching for PRs updated since {since}...")
        return search_in_range(base_query, f"updated:>={since}")

    # Full sync - query by year to get all results
    all_prs = set()
    current_year = datetime.now().year

    # MicroPython project started ~2013
    for year in range(2013, current_year + 1):
        date_range = f"created:{year}-01-01..{year}-12-31"
        print(f"  Searching PRs from {year}...")
        year_prs = search_in_range(base_query, date_range)
        print(f"    Found {len(year_prs)} PRs from {year}")
        all_prs.update(year_prs)
        time.sleep(REQUEST_DELAY)

    return list(all_prs)


def fetch_pr_details(repo, pr_number):
    """Fetch full PR details."""
    endpoint = f"repos/{repo}/pulls/{pr_number}"
    return gh_api(endpoint)


def fetch_review_comments(repo, pr_number):
    """Fetch review comments (inline code comments) for a PR."""
    endpoint = f"repos/{repo}/pulls/{pr_number}/comments"
    comments = gh_api(endpoint, paginate=True) or []
    # Filter to dpgeorge's comments
    return [c for c in comments if c.get("user", {}).get("login") == REVIEWER]


def fetch_issue_comments(repo, pr_number):
    """Fetch issue comments (general discussion) for a PR."""
    endpoint = f"repos/{repo}/issues/{pr_number}/comments"
    comments = gh_api(endpoint, paginate=True) or []
    # Filter to dpgeorge's comments
    return [c for c in comments if c.get("user", {}).get("login") == REVIEWER]


def fetch_reviews(repo, pr_number):
    """Fetch reviews (APPROVED/CHANGES_REQUESTED) for a PR."""
    endpoint = f"repos/{repo}/pulls/{pr_number}/reviews"
    reviews = gh_api(endpoint, paginate=True) or []
    # Filter to dpgeorge's reviews
    return [r for r in reviews if r.get("user", {}).get("login") == REVIEWER]


def store_pr(conn, repo, pr):
    """Store PR details in database."""
    conn.execute("""
        INSERT OR REPLACE INTO prs
        (id, number, repo, title, body, author, state, created_at, merged_at, closed_at,
         changed_files, commits, additions, deletions, base_branch)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        pr["id"],
        pr["number"],
        repo,
        pr["title"],
        pr["body"],
        pr["user"]["login"],
        pr["state"],
        pr["created_at"],
        pr.get("merged_at"),
        pr.get("closed_at"),
        pr.get("changed_files"),
        pr.get("commits"),
        pr.get("additions"),
        pr.get("deletions"),
        pr.get("base", {}).get("ref"),
    ))


def store_review_comments(conn, repo, pr_number, comments):
    """Store review comments in database."""
    for c in comments:
        conn.execute("""
            INSERT OR REPLACE INTO review_comments
            (id, pr_number, repo, body, path, line, original_line, diff_hunk,
             created_at, updated_at, in_reply_to_id, commit_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            c["id"],
            pr_number,
            repo,
            c["body"],
            c.get("path"),
            c.get("line"),
            c.get("original_line"),
            c.get("diff_hunk"),
            c["created_at"],
            c.get("updated_at"),
            c.get("in_reply_to_id"),
            c.get("commit_id"),
        ))


def store_issue_comments(conn, repo, pr_number, comments):
    """Store issue comments in database."""
    for c in comments:
        conn.execute("""
            INSERT OR REPLACE INTO issue_comments
            (id, pr_number, repo, body, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            c["id"],
            pr_number,
            repo,
            c["body"],
            c["created_at"],
            c.get("updated_at"),
        ))


def store_reviews(conn, repo, pr_number, reviews):
    """Store reviews in database."""
    for r in reviews:
        conn.execute("""
            INSERT OR REPLACE INTO reviews
            (id, pr_number, repo, state, body, created_at, commit_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            r["id"],
            pr_number,
            repo,
            r["state"],
            r.get("body"),
            r["submitted_at"],
            r.get("commit_id"),
        ))


def collect_pr(conn, repo, pr_number):
    """Collect all data for a single PR."""
    # Fetch PR details
    pr = fetch_pr_details(repo, pr_number)
    if pr is None:
        print(f"    Failed to fetch PR #{pr_number}", file=sys.stderr)
        return False

    time.sleep(REQUEST_DELAY)

    # Fetch comments
    review_comments = fetch_review_comments(repo, pr_number)
    time.sleep(REQUEST_DELAY)

    issue_comments = fetch_issue_comments(repo, pr_number)
    time.sleep(REQUEST_DELAY)

    reviews = fetch_reviews(repo, pr_number)
    time.sleep(REQUEST_DELAY)

    # Store everything
    store_pr(conn, repo, pr)
    store_review_comments(conn, repo, pr_number, review_comments)
    store_issue_comments(conn, repo, pr_number, issue_comments)
    store_reviews(conn, repo, pr_number, reviews)
    conn.commit()

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Collect dpgeorge's PR review comments from a GitHub repository."
    )
    parser.add_argument(
        "--repo",
        default="micropython/micropython",
        help="GitHub repository (default: micropython/micropython)",
    )
    args = parser.parse_args()
    repo = args.repo

    print(f"Initializing database at {DB_PATH}")
    conn = init_db()

    # Repo-scoped sync state keys
    sync_key = f"last_sync:{repo}"
    checkpoint_key = f"checkpoint_pr:{repo}"

    # Check for incremental mode
    last_sync = get_sync_state(conn, sync_key)
    collected_prs = get_collected_pr_numbers(conn, repo)

    if last_sync:
        print(f"Incremental sync for {repo} from {last_sync}")
        print(f"Already have {len(collected_prs)} PRs in database for {repo}")
    else:
        print(f"Full collection for {repo} (no previous sync)")

    # Find PRs to collect
    print(f"\nSearching for PRs commented by {REVIEWER} on {repo}...")
    pr_numbers = search_prs_with_comments(repo, since=last_sync)
    print(f"Found {len(pr_numbers)} PRs total")

    # Filter out already collected (for full sync)
    if not last_sync:
        pr_numbers = [n for n in pr_numbers if n not in collected_prs]
        print(f"{len(pr_numbers)} PRs to collect (excluding already collected)")

    # Estimate time
    api_calls_per_pr = 4  # PR details + review comments + issue comments + reviews
    total_calls = len(pr_numbers) * api_calls_per_pr
    estimated_hours = (total_calls * REQUEST_DELAY) / 3600
    print(f"Estimated time: {estimated_hours:.1f} hours ({total_calls} API calls)")

    # Collect PRs
    start_time = datetime.now()
    for i, pr_number in enumerate(pr_numbers):
        elapsed = datetime.now() - start_time
        rate = (i + 1) / max(elapsed.total_seconds(), 1) * 3600

        print(f"[{i+1}/{len(pr_numbers)}] PR #{pr_number} ({rate:.0f} PRs/hour)")

        success = collect_pr(conn, repo, pr_number)
        if not success:
            print(f"  Skipping PR #{pr_number}")
            continue

        # Update checkpoint periodically
        if (i + 1) % 10 == 0:
            set_sync_state(conn, checkpoint_key, str(pr_number))

    # Update sync timestamp
    set_sync_state(conn, sync_key, datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    # Print summary
    cursor = conn.execute("SELECT repo, COUNT(*) FROM prs GROUP BY repo")
    print(f"\nCollection complete!")
    for row in cursor:
        print(f"  PRs ({row[0]}): {row[1]}")

    cursor = conn.execute("SELECT COUNT(*) FROM review_comments WHERE repo = ?", (repo,))
    total_review_comments = cursor.fetchone()[0]

    cursor = conn.execute("SELECT COUNT(*) FROM issue_comments WHERE repo = ?", (repo,))
    total_issue_comments = cursor.fetchone()[0]

    cursor = conn.execute("SELECT COUNT(*) FROM reviews WHERE repo = ?", (repo,))
    total_reviews = cursor.fetchone()[0]

    print(f"  Review comments ({repo}): {total_review_comments}")
    print(f"  Issue comments ({repo}): {total_issue_comments}")
    print(f"  Reviews ({repo}): {total_reviews}")

    conn.close()


if __name__ == "__main__":
    main()
