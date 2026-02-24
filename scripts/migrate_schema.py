#!/usr/bin/env python3
"""
Migrate database schema to support enhanced categorization fields and multi-repo.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "reviews.db"


def migrate():
    conn = sqlite3.connect(DB_PATH)

    # --- Phase 1: Enhanced categorization columns (original migration) ---

    new_columns = [
        ("component", "TEXT"),
        ("port", "TEXT"),
        ("subsystem", "TEXT"),
        ("language_context", "TEXT"),
        ("code_construct", "TEXT"),
        ("concern_type", "TEXT"),
        ("feedback_type", "TEXT"),
        ("is_pattern", "INTEGER DEFAULT 0"),
        ("cpython_related", "INTEGER DEFAULT 0"),
        ("has_code_suggestion", "INTEGER DEFAULT 0"),
        ("keywords", "TEXT"),  # JSON array
    ]

    # Check which columns already exist
    cursor = conn.execute('PRAGMA table_info(comment_categories)')
    existing_columns = {row[1] for row in cursor.fetchall()}

    print("Adding new columns to comment_categories...")
    for col_name, col_type in new_columns:
        if col_name not in existing_columns:
            try:
                conn.execute(f'ALTER TABLE comment_categories ADD COLUMN {col_name} {col_type}')
                print(f"  + Added {col_name}")
            except sqlite3.OperationalError as e:
                print(f"  x Failed to add {col_name}: {e}")
        else:
            print(f"  - {col_name} already exists")

    conn.commit()

    # --- Phase 2: Add repo column to prs, review_comments, issue_comments, reviews ---

    _migrate_repo_column(conn)

    # Verify schema
    for table in ("prs", "review_comments", "issue_comments", "reviews", "comment_categories"):
        cursor = conn.execute(f'PRAGMA table_info({table})')
        cols = [row[1] for row in cursor.fetchall()]
        print(f"\n{table} columns: {', '.join(cols)}")

    conn.close()
    print("\nMigration complete!")


def _migrate_repo_column(conn):
    """Add repo column to all four data tables and fix prs UNIQUE constraint."""
    default_repo = "micropython/micropython"

    # --- Simple tables: just ALTER TABLE ADD COLUMN ---
    for table in ("review_comments", "issue_comments", "reviews"):
        cursor = conn.execute(f'PRAGMA table_info({table})')
        existing = {row[1] for row in cursor.fetchall()}
        if "repo" in existing:
            print(f"\n{table}: repo column already exists")
            continue

        print(f"\n{table}: adding repo column...")
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN repo TEXT NOT NULL DEFAULT '{default_repo}'"
        )
        conn.commit()
        print(f"  + Added repo column")

    # --- prs table: needs rebuild to change UNIQUE(number) → UNIQUE(repo, number) ---
    cursor = conn.execute('PRAGMA table_info(prs)')
    existing = {row[1] for row in cursor.fetchall()}
    if "repo" not in existing:
        print("\nprs: rebuilding table (UNIQUE(number) -> UNIQUE(repo, number))...")

        # Wrap in explicit transaction so a crash mid-rebuild rolls back cleanly
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("ALTER TABLE prs RENAME TO prs_old")

            conn.execute(f"""
                CREATE TABLE prs (
                    id INTEGER PRIMARY KEY,
                    number INTEGER NOT NULL,
                    repo TEXT NOT NULL DEFAULT '{default_repo}',
                    title TEXT,
                    body TEXT,
                    author TEXT,
                    state TEXT,
                    created_at TEXT,
                    merged_at TEXT,
                    closed_at TEXT,
                    changed_files INTEGER,
                    commits INTEGER,
                    additions INTEGER,
                    deletions INTEGER,
                    base_branch TEXT,
                    UNIQUE(repo, number)
                )
            """)

            conn.execute(f"""
                INSERT INTO prs
                    (id, number, repo, title, body, author, state, created_at, merged_at,
                     closed_at, changed_files, commits, additions, deletions, base_branch)
                SELECT
                    id, number, '{default_repo}', title, body, author, state, created_at, merged_at,
                    closed_at, changed_files, commits, additions, deletions, base_branch
                FROM prs_old
            """)

            conn.execute("DROP TABLE prs_old")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        print("  + Rebuilt prs with UNIQUE(repo, number)")
    else:
        print("\nprs: repo column already exists")

    # Ensure all indexes exist (idempotent, also recreates any lost during rebuild)
    print("\nEnsuring indexes...")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_prs_repo ON prs(repo)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_prs_created ON prs(created_at)")

    # Drop old single-column indexes and recreate as composite
    for table, idx_name in [
        ("review_comments", "idx_review_comments_pr"),
        ("issue_comments", "idx_issue_comments_pr"),
        ("reviews", "idx_reviews_pr"),
    ]:
        # Check if existing index is single-column (needs upgrade to composite)
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (idx_name,)
        ).fetchone()
        if row and "repo" not in (row[0] or ""):
            conn.execute(f"DROP INDEX IF EXISTS {idx_name}")
            print(f"  - Dropped old single-column {idx_name}")
        conn.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}(pr_number, repo)")
        print(f"  + {idx_name}")

    conn.commit()


if __name__ == "__main__":
    migrate()
