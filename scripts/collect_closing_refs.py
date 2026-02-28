#!/usr/bin/env python3
"""
Collect closing references (issue-PR links) from GitHub timeline events.

For each issue, fetches timeline events and extracts cross-referenced PRs
with their merge status. Stores explicit issue-PR closing relationships.
Supports resume from checkpoint.
"""

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from collect_utils import (
    DB_PATH, REQUEST_DELAY, gh_api, init_db_with_schema,
    get_sync_state, set_sync_state
)

TRIAGE_SCHEMA_PATH = Path(__file__).parent.parent / "triage_schema.sql"


def get_all_issue_numbers(conn, repo):
    """Get all issue numbers currently in database for a repo."""
    cursor = conn.execute("SELECT number FROM issues WHERE repo = ?", (repo,))
    return [row[0] for row in cursor.fetchall()]


def get_collected_prs(conn):
    """Get set of (repo, number) tuples for all PRs in database."""
    cursor = conn.execute("SELECT repo, number FROM prs")
    return {(row[0], row[1]) for row in cursor.fetchall()}


def fetch_timeline_events(repo, issue_number):
    """Fetch timeline events for an issue (paginated)."""
    endpoint = f"repos/{repo}/issues/{issue_number}/timeline"
    return gh_api(endpoint, paginate=True) or []


def fetch_pr_details(repo, pr_number):
    """Fetch PR details to check merge status."""
    endpoint = f"repos/{repo}/pulls/{pr_number}"
    return gh_api(endpoint)


def check_pr_merged(conn, repo, pr_number, pr_cache):
    """Check if a PR is merged, using cache and API fallback."""
    key = (repo, pr_number)

    # Check cache first
    if key in pr_cache:
        return pr_cache[key]

    # Check local database
    cursor = conn.execute(
        "SELECT state FROM prs WHERE repo = ? AND number = ?",
        (repo, pr_number)
    )
    row = cursor.fetchone()
    if row:
        merged = row[0] == "merged"
        pr_cache[key] = merged
        return merged

    # Fetch from API
    pr = fetch_pr_details(repo, pr_number)
    time.sleep(REQUEST_DELAY)

    if pr is None:
        # Couldn't fetch, assume not merged
        pr_cache[key] = False
        return False

    # Check if merged (state is either "open" or "closed", need to check merged field)
    merged = pr.get("merged", False)
    pr_cache[key] = merged
    return merged


def store_closing_ref(conn, issue_number, issue_repo, pr_number, pr_repo, pr_merged):
    """Store an issue-PR closing reference in database."""
    conn.execute("""
        INSERT OR REPLACE INTO issue_closing_refs
        (issue_number, issue_repo, pr_number, pr_repo, pr_merged)
        VALUES (?, ?, ?, ?, ?)
    """, (issue_number, issue_repo, pr_number, pr_repo, int(pr_merged)))


def process_issue_timeline(conn, repo, issue_number, pr_cache):
    """Process timeline events for an issue and extract closing refs."""
    events = fetch_timeline_events(repo, issue_number)
    time.sleep(REQUEST_DELAY)

    refs_found = 0

    for event in events:
        # Look for cross-referenced events
        if event.get("event") != "cross-referenced":
            continue

        source = event.get("source", {})
        if "issue" not in source:
            continue

        issue_data = source["issue"]
        # Only interested in PRs (issues with pull_request field)
        if "pull_request" not in issue_data:
            continue

        pr_number = issue_data.get("number")
        if pr_number is None:
            continue

        # For cross-refs, we need to infer PR repo from the source
        # The source.issue.repository_url can be parsed, but it's safer to assume same repo
        pr_repo = repo

        # Check if PR is merged
        pr_merged = check_pr_merged(conn, pr_repo, pr_number, pr_cache)

        # Store the reference
        store_closing_ref(conn, issue_number, repo, pr_number, pr_repo, pr_merged)
        refs_found += 1

    return refs_found


def main():
    parser = argparse.ArgumentParser(
        description="Collect issue-PR closing references from GitHub timeline events."
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

    # Repo-scoped sync state key
    checkpoint_key = f"checkpoint_closing_ref:{repo}"

    # Get last checkpoint
    last_checkpoint = get_sync_state(conn, checkpoint_key)
    checkpoint_issue_number = int(last_checkpoint) if last_checkpoint else 0

    # Get all issues to process
    print(f"\nFetching all issues for {repo}...")
    issue_numbers = get_all_issue_numbers(conn, repo)
    print(f"Found {len(issue_numbers)} issues")

    # Filter to issues we haven't processed yet
    issues_to_process = [n for n in issue_numbers if n > checkpoint_issue_number]
    if checkpoint_issue_number > 0:
        print(f"Resuming from checkpoint: issue #{checkpoint_issue_number}")
        print(f"{len(issues_to_process)} issues remaining")

    # Estimate time
    total_calls = len(issues_to_process)  # One timeline fetch per issue
    estimated_hours = (total_calls * REQUEST_DELAY) / 3600
    print(f"Estimated time: {estimated_hours:.1f} hours ({total_calls} API calls)")

    # PR cache: {(repo, number): merged_bool}
    pr_cache = {}

    # Process issues
    start_time = datetime.now()
    total_refs = 0

    for i, issue_number in enumerate(issues_to_process):
        elapsed = datetime.now() - start_time
        rate = (i + 1) / max(elapsed.total_seconds(), 1) * 3600

        print(f"[{i+1}/{len(issues_to_process)}] Issue #{issue_number} ({rate:.0f} issues/hour)")

        refs = process_issue_timeline(conn, repo, issue_number, pr_cache)
        if refs > 0:
            print(f"  Found {refs} closing reference(s)")
            total_refs += refs

        conn.commit()

        # Update checkpoint periodically
        if (i + 1) % 10 == 0:
            set_sync_state(conn, checkpoint_key, str(issue_number))

    # Final checkpoint
    if issues_to_process:
        set_sync_state(conn, checkpoint_key, str(issues_to_process[-1]))

    # Print summary
    cursor = conn.execute(
        "SELECT COUNT(*) FROM issue_closing_refs WHERE issue_repo = ?", (repo,)
    )
    total_in_db = cursor.fetchone()[0]

    print(f"\nCollection complete!")
    print(f"  Total closing references found this run: {total_refs}")
    print(f"  Total in database ({repo}): {total_in_db}")

    # Show merged vs unmerged breakdown
    cursor = conn.execute(
        "SELECT pr_merged, COUNT(*) FROM issue_closing_refs WHERE issue_repo = ? GROUP BY pr_merged",
        (repo,)
    )
    for merged, count in cursor:
        status = "merged" if merged else "unmerged"
        print(f"    {status}: {count}")

    conn.close()


if __name__ == "__main__":
    main()
