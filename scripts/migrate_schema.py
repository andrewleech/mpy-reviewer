#!/usr/bin/env python3
"""
Migrate database schema to support enhanced categorization fields.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "reviews.db"

def migrate():
    conn = sqlite3.connect(DB_PATH)

    # Add new columns to comment_categories
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
                print(f"  ✓ Added {col_name}")
            except sqlite3.OperationalError as e:
                print(f"  ✗ Failed to add {col_name}: {e}")
        else:
            print(f"  - {col_name} already exists")

    conn.commit()

    # Verify schema
    cursor = conn.execute('PRAGMA table_info(comment_categories)')
    print("\nFinal schema:")
    for row in cursor.fetchall():
        print(f"  {row[1]} ({row[2]})")

    conn.close()
    print("\nMigration complete!")

if __name__ == "__main__":
    migrate()
