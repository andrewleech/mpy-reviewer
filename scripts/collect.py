#!/usr/bin/env python3
"""
Collect dpgeorge's PR review comments from micropython/micropython.

Uses the GitHub CLI (gh) for authentication and API access.
Supports resume from checkpoint and incremental updates.
"""

import json
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

REPO = "micropython/micropython"
REVIEWER = "dpgeorge"
DB_PATH = Path(__file__).parent.parent / "data" / "reviews.db"
SCHEMA_PATH = Path(__file__).parent.parent / "schema.sql"

# Rate limiting
REQUESTS_PER_HOUR = 5000
REQUEST_DELAY = 3600 / REQUESTS_PER_HOUR  # ~0.72 seconds


def gh_api(endpoint, paginate=False):
    """Call GitHub API via gh CLI."""
    cmd = ["gh", "api", "-H", "Accept: application/vnd.github+json"]
    if paginate:
        cmd.append("--paginate")
    cmd.append(endpoint)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"API error: {result.stderr}", file=sys.stderr)
        return None

    if not result.stdout.strip():
        return [] if paginate else None

    # Handle paginated results (multiple JSON arrays concatenated)
    if paginate:
        # gh --paginate concatenates JSON arrays, need to parse carefully
        data = []
        decoder = json.JSONDecoder()
        text = result.stdout.strip()
        pos = 0
        while pos < len(text):
            try:
                obj, end = decoder.raw_decode(text, pos)
                if isinstance(obj, list):
                    data.extend(obj)
                else:
                    data.append(obj)
                pos = end
                # Skip whitespace
                while pos < len(text) and text[pos] in ' \t\n\r':
                    pos += 1
            except json.JSONDecodeError:
                break
        return data

    return json.loads(result.stdout)


def init_db():
    """Initialize the database with schema."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.commit()
    return conn


def get_sync_state(conn, key):
    """Get sync state value."""
    cursor = conn.execute("SELECT value FROM sync_state WHERE key = ?", (key,))
    row = cursor.fetchone()
    return row[0] if row else None


def set_sync_state(conn, key, value):
    """Set sync state value."""
    conn.execute(
        "INSERT OR REPLACE INTO sync_state (key, value) VALUES (?, ?)",
        (key, value)
    )
    conn.commit()


def get_collected_pr_numbers(conn):
    """Get set of PR numbers already collected."""
    cursor = conn.execute("SELECT number FROM prs")
    return {row[0] for row in cursor.fetchall()}


def search_prs_in_range(base_query, date_range=None):
    """Search for PRs with optional date range, handling pagination."""
    query = base_query
    if date_range:
        query += f" {date_range}"

    prs = []
    page = 1
    per_page = 100

    while True:
        endpoint = f"search/issues?q={quote(query)}&per_page={per_page}&page={page}&sort=updated&order=desc"
        result = gh_api(endpoint)

        if result is None or "items" not in result:
            break

        items = result["items"]
        if not items:
            break

        for item in items:
            prs.append(item["number"])

        if len(items) < per_page:
            break

        # Check if we hit the 1000 result limit
        if page >= 10:
            total_count = result.get("total_count", 0)
            if total_count > 1000:
                print(f"    Warning: {total_count} results but only 1000 accessible")
            break

        page += 1
        time.sleep(REQUEST_DELAY)

    return prs


def search_prs_with_comments(since=None):
    """Search for PRs that dpgeorge has commented on.

    Uses date ranges to work around GitHub's 1000 result limit.
    """
    base_query = f"repo:{REPO} is:pr commenter:{REVIEWER}"

    if since:
        # Incremental sync - single query should be under 1000 results
        print(f"  Searching for PRs updated since {since}...")
        return search_prs_in_range(base_query, f"updated:>={since}")

    # Full sync - query by year to get all results
    all_prs = set()
    current_year = datetime.now().year

    # MicroPython project started ~2013
    for year in range(2013, current_year + 1):
        date_range = f"created:{year}-01-01..{year}-12-31"
        print(f"  Searching PRs from {year}...")
        year_prs = search_prs_in_range(base_query, date_range)
        print(f"    Found {len(year_prs)} PRs from {year}")
        all_prs.update(year_prs)
        time.sleep(REQUEST_DELAY)

    return list(all_prs)


def fetch_pr_details(pr_number):
    """Fetch full PR details."""
    endpoint = f"repos/{REPO}/pulls/{pr_number}"
    return gh_api(endpoint)


def fetch_review_comments(pr_number):
    """Fetch review comments (inline code comments) for a PR."""
    endpoint = f"repos/{REPO}/pulls/{pr_number}/comments"
    comments = gh_api(endpoint, paginate=True) or []
    # Filter to dpgeorge's comments
    return [c for c in comments if c.get("user", {}).get("login") == REVIEWER]


def fetch_issue_comments(pr_number):
    """Fetch issue comments (general discussion) for a PR."""
    endpoint = f"repos/{REPO}/issues/{pr_number}/comments"
    comments = gh_api(endpoint, paginate=True) or []
    # Filter to dpgeorge's comments
    return [c for c in comments if c.get("user", {}).get("login") == REVIEWER]


def fetch_reviews(pr_number):
    """Fetch reviews (APPROVED/CHANGES_REQUESTED) for a PR."""
    endpoint = f"repos/{REPO}/pulls/{pr_number}/reviews"
    reviews = gh_api(endpoint, paginate=True) or []
    # Filter to dpgeorge's reviews
    return [r for r in reviews if r.get("user", {}).get("login") == REVIEWER]


def store_pr(conn, pr):
    """Store PR details in database."""
    conn.execute("""
        INSERT OR REPLACE INTO prs
        (id, number, title, body, author, state, created_at, merged_at, closed_at,
         changed_files, commits, additions, deletions, base_branch)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        pr["id"],
        pr["number"],
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


def store_review_comments(conn, pr_number, comments):
    """Store review comments in database."""
    for c in comments:
        conn.execute("""
            INSERT OR REPLACE INTO review_comments
            (id, pr_number, body, path, line, original_line, diff_hunk,
             created_at, updated_at, in_reply_to_id, commit_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            c["id"],
            pr_number,
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


def store_issue_comments(conn, pr_number, comments):
    """Store issue comments in database."""
    for c in comments:
        conn.execute("""
            INSERT OR REPLACE INTO issue_comments
            (id, pr_number, body, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            c["id"],
            pr_number,
            c["body"],
            c["created_at"],
            c.get("updated_at"),
        ))


def store_reviews(conn, pr_number, reviews):
    """Store reviews in database."""
    for r in reviews:
        conn.execute("""
            INSERT OR REPLACE INTO reviews
            (id, pr_number, state, body, created_at, commit_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            r["id"],
            pr_number,
            r["state"],
            r.get("body"),
            r["submitted_at"],
            r.get("commit_id"),
        ))


def collect_pr(conn, pr_number):
    """Collect all data for a single PR."""
    # Fetch PR details
    pr = fetch_pr_details(pr_number)
    if pr is None:
        print(f"    Failed to fetch PR #{pr_number}", file=sys.stderr)
        return False

    time.sleep(REQUEST_DELAY)

    # Fetch comments
    review_comments = fetch_review_comments(pr_number)
    time.sleep(REQUEST_DELAY)

    issue_comments = fetch_issue_comments(pr_number)
    time.sleep(REQUEST_DELAY)

    reviews = fetch_reviews(pr_number)
    time.sleep(REQUEST_DELAY)

    # Store everything
    store_pr(conn, pr)
    store_review_comments(conn, pr_number, review_comments)
    store_issue_comments(conn, pr_number, issue_comments)
    store_reviews(conn, pr_number, reviews)
    conn.commit()

    return True


def main():
    print(f"Initializing database at {DB_PATH}")
    conn = init_db()

    # Check for incremental mode
    last_sync = get_sync_state(conn, "last_sync")
    collected_prs = get_collected_pr_numbers(conn)

    if last_sync:
        print(f"Incremental sync from {last_sync}")
        print(f"Already have {len(collected_prs)} PRs in database")
    else:
        print("Full collection (no previous sync)")

    # Find PRs to collect
    print(f"\nSearching for PRs commented by {REVIEWER}...")
    pr_numbers = search_prs_with_comments(since=last_sync)
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

        success = collect_pr(conn, pr_number)
        if not success:
            print(f"  Skipping PR #{pr_number}")
            continue

        # Update checkpoint periodically
        if (i + 1) % 10 == 0:
            set_sync_state(conn, "checkpoint_pr", str(pr_number))

    # Update sync timestamp
    set_sync_state(conn, "last_sync", datetime.utcnow().strftime("%Y-%m-%d"))

    # Print summary
    cursor = conn.execute("SELECT COUNT(*) FROM prs")
    total_prs = cursor.fetchone()[0]

    cursor = conn.execute("SELECT COUNT(*) FROM review_comments")
    total_review_comments = cursor.fetchone()[0]

    cursor = conn.execute("SELECT COUNT(*) FROM issue_comments")
    total_issue_comments = cursor.fetchone()[0]

    cursor = conn.execute("SELECT COUNT(*) FROM reviews")
    total_reviews = cursor.fetchone()[0]

    print(f"\nCollection complete!")
    print(f"  PRs: {total_prs}")
    print(f"  Review comments: {total_review_comments}")
    print(f"  Issue comments: {total_issue_comments}")
    print(f"  Reviews: {total_reviews}")

    conn.close()


if __name__ == "__main__":
    main()
