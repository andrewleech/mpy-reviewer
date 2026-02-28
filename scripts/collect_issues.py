#!/usr/bin/env python3
"""
Collect all issues (open and closed) from a MicroPython repository.

For each issue, collects metadata and dpgeorge's comments.
Uses search API with date-range splits to work around GitHub's 1000-result limit.
Supports resume from checkpoint and incremental updates.
"""

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from collect_utils import (
    REVIEWER, DB_PATH, REQUEST_DELAY, gh_api, init_db_with_schema,
    get_sync_state, set_sync_state, search_in_range
)

TRIAGE_SCHEMA_PATH = Path(__file__).parent.parent / "triage_schema.sql"


def get_collected_issue_numbers(conn, repo):
    """Get set of issue numbers already collected for this repo."""
    cursor = conn.execute("SELECT number FROM issues WHERE repo = ?", (repo,))
    return {row[0] for row in cursor.fetchall()}


def search_issues_with_date_range(repo, since=None):
    """Search for all issues (excluding PRs) in a repo.

    Uses date ranges to work around GitHub's 1000 result limit.
    """
    base_query = f"repo:{repo} is:issue -is:pr"

    if since:
        # Incremental sync - single query should be under 1000 results
        print(f"  Searching for issues updated since {since}...")
        return search_in_range(base_query, f"updated:>={since}")

    # Full sync - query by year to get all results
    all_issues = set()
    current_year = datetime.now().year

    # MicroPython project started ~2013
    for year in range(2013, current_year + 1):
        date_range = f"created:{year}-01-01..{year}-12-31"
        print(f"  Searching issues from {year}...")
        year_issues = search_in_range(base_query, date_range)
        print(f"    Found {len(year_issues)} issues from {year}")
        all_issues.update(year_issues)
        time.sleep(REQUEST_DELAY)

    return list(all_issues)


def fetch_issue_details(repo, issue_number):
    """Fetch full issue details."""
    endpoint = f"repos/{repo}/issues/{issue_number}"
    return gh_api(endpoint)


def fetch_issue_comments(repo, issue_number):
    """Fetch all comments on an issue."""
    endpoint = f"repos/{repo}/issues/{issue_number}/comments"
    comments = gh_api(endpoint, paginate=True) or []
    # Filter to dpgeorge's comments
    return [c for c in comments if c.get("user", {}).get("login") == REVIEWER]


def store_issue(conn, repo, issue):
    """Store issue details in database."""
    labels = issue.get("labels", [])
    labels_json = json.dumps([label["name"] for label in labels])

    conn.execute("""
        INSERT OR REPLACE INTO issues
        (id, number, repo, title, body, author, state, labels, created_at,
         closed_at, updated_at, comments_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        issue["id"],
        issue["number"],
        repo,
        issue["title"],
        issue["body"],
        issue["user"]["login"],
        issue["state"],
        labels_json,
        issue["created_at"],
        issue.get("closed_at"),
        issue.get("updated_at"),
        issue.get("comments"),
    ))


def store_issue_comments(conn, repo, issue_number, comments):
    """Store dpgeorge's comments on an issue in database."""
    for c in comments:
        conn.execute("""
            INSERT OR REPLACE INTO dpgeorge_issue_comments
            (id, issue_number, repo, body, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            c["id"],
            issue_number,
            repo,
            c["body"],
            c["created_at"],
            c.get("updated_at"),
        ))


def collect_issue(conn, repo, issue_number):
    """Collect all data for a single issue."""
    # Fetch issue details
    issue = fetch_issue_details(repo, issue_number)
    if issue is None:
        print(f"    Failed to fetch issue #{issue_number}", file=sys.stderr)
        return False

    time.sleep(REQUEST_DELAY)

    # Fetch comments
    comments = fetch_issue_comments(repo, issue_number)
    time.sleep(REQUEST_DELAY)

    # Store everything
    store_issue(conn, repo, issue)
    store_issue_comments(conn, repo, issue_number, comments)
    conn.commit()

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Collect all issues and dpgeorge's comments from a GitHub repository."
    )
    parser.add_argument(
        "--repo",
        default="micropython/micropython",
        help="GitHub repository (default: micropython/micropython)",
    )
    args = parser.parse_args()
    repo = args.repo

    print(f"Initializing database at {DB_PATH}")
    conn = init_db_with_schema(TRIAGE_SCHEMA_PATH)

    # Repo-scoped sync state keys
    sync_key = f"last_issue_sync:{repo}"
    checkpoint_key = f"checkpoint_issue:{repo}"

    # Check for incremental mode
    last_sync = get_sync_state(conn, sync_key)
    collected_issues = get_collected_issue_numbers(conn, repo)

    if last_sync:
        print(f"Incremental sync for {repo} from {last_sync}")
        print(f"Already have {len(collected_issues)} issues in database for {repo}")
    else:
        print(f"Full collection for {repo} (no previous sync)")

    # Find issues to collect
    print(f"\nSearching for issues on {repo}...")
    issue_numbers = search_issues_with_date_range(repo, since=last_sync)
    print(f"Found {len(issue_numbers)} issues total")

    # Filter out already collected (for full sync)
    if not last_sync:
        issue_numbers = [n for n in issue_numbers if n not in collected_issues]
        print(f"{len(issue_numbers)} issues to collect (excluding already collected)")

    # Estimate time
    api_calls_per_issue = 2  # Issue details + comments
    total_calls = len(issue_numbers) * api_calls_per_issue
    estimated_hours = (total_calls * REQUEST_DELAY) / 3600
    print(f"Estimated time: {estimated_hours:.1f} hours ({total_calls} API calls)")

    # Collect issues
    start_time = datetime.now()
    for i, issue_number in enumerate(issue_numbers):
        elapsed = datetime.now() - start_time
        rate = (i + 1) / max(elapsed.total_seconds(), 1) * 3600

        print(f"[{i+1}/{len(issue_numbers)}] Issue #{issue_number} ({rate:.0f} issues/hour)")

        success = collect_issue(conn, repo, issue_number)
        if not success:
            print(f"  Skipping issue #{issue_number}")
            continue

        # Update checkpoint periodically
        if (i + 1) % 10 == 0:
            set_sync_state(conn, checkpoint_key, str(issue_number))

    # Update sync timestamp
    set_sync_state(conn, sync_key, datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    # Print summary
    cursor = conn.execute("SELECT repo, COUNT(*) FROM issues GROUP BY repo")
    print(f"\nCollection complete!")
    for row in cursor:
        print(f"  Issues ({row[0]}): {row[1]}")

    cursor = conn.execute(
        "SELECT COUNT(*) FROM dpgeorge_issue_comments WHERE repo = ?", (repo,)
    )
    total_comments = cursor.fetchone()[0]
    print(f"  dpgeorge comments ({repo}): {total_comments}")

    conn.close()


if __name__ == "__main__":
    main()
