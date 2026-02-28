#!/usr/bin/env python3
"""
Shared utilities for collecting data from GitHub repositories.

Provides common functions for GitHub API access, database initialization,
sync state management, and search operations with pagination.
"""

import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

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


def init_db_with_schema(schema_path):
    """Initialize the database with a specific schema file.

    Args:
        schema_path: Path to the SQL schema file to execute.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    with open(schema_path) as f:
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


def search_in_range(base_query, date_range=None):
    """Search GitHub with optional date range, handling pagination.

    Args:
        base_query: Base search query (e.g., "repo:owner/name is:pr")
        date_range: Optional date range filter (e.g., "created:2020-01-01..2020-12-31")

    Returns:
        List of item numbers found in search results.
    """
    query = base_query
    if date_range:
        query += f" {date_range}"

    items = []
    page = 1
    per_page = 100

    while True:
        endpoint = f"search/issues?q={quote(query)}&per_page={per_page}&page={page}&sort=updated&order=desc"
        result = gh_api(endpoint)

        if result is None or "items" not in result:
            break

        result_items = result["items"]
        if not result_items:
            break

        for item in result_items:
            items.append(item["number"])

        if len(result_items) < per_page:
            break

        # Check if we hit the 1000 result limit
        if page >= 10:
            total_count = result.get("total_count", 0)
            if total_count > 1000:
                print(f"    Warning: {total_count} results but only 1000 accessible")
            break

        page += 1
        time.sleep(REQUEST_DELAY)

    return items
