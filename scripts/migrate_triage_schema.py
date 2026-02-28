#!/usr/bin/env python3
"""Apply triage schema extensions to the existing reviews database."""

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "reviews.db"
SCHEMA_PATH = Path(__file__).parent.parent / "triage_schema.sql"


def main():
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}", file=sys.stderr)
        return 1

    print(f"Applying triage schema to {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)

    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.commit()

    # Verify tables exist
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
        "('issues', 'dpgeorge_issue_comments', 'issue_closing_refs')"
    ).fetchall()
    table_names = [t[0] for t in tables]

    expected = {"issues", "dpgeorge_issue_comments", "issue_closing_refs"}
    if expected <= set(table_names):
        print(f"OK: tables created: {', '.join(sorted(table_names))}")
    else:
        missing = expected - set(table_names)
        print(f"ERROR: missing tables: {', '.join(sorted(missing))}", file=sys.stderr)
        conn.close()
        return 1

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
