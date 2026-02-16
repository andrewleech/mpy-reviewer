#!/usr/bin/env python3
"""
Test enhanced categorization on a small batch.

Usage:
    python3 scripts/test_categorization.py           # Setup test batch
    python3 scripts/categorize_headless.py           # Run categorization (will process test batch)
    python3 scripts/test_categorization.py --verify  # Verify results
"""

import subprocess
import sqlite3
import json
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "reviews.db"
TEST_IDS_PATH = Path("/tmp/test_comment_ids.json")


def setup_test_batch():
    """Select 5 diverse comments for testing."""
    conn = sqlite3.connect(DB_PATH)
    test_comments = []

    print("Selecting test comments...")

    # 1 Python comment
    cursor = conn.execute("""
        SELECT id, body FROM review_comments
        WHERE path LIKE '%.py' AND id NOT IN (
            SELECT comment_id FROM comment_categories
            WHERE comment_type = 'review_comment'
        )
        LIMIT 1
    """)
    if row := cursor.fetchone():
        test_comments.append(('review_comment', row[0]))
        print(f"  ✓ Python comment: {row[0]} ({row[1][:50]}...)")

    # 1 C comment
    cursor = conn.execute("""
        SELECT id, body FROM review_comments
        WHERE path LIKE '%.c' AND id NOT IN (
            SELECT comment_id FROM comment_categories
            WHERE comment_type = 'review_comment'
        )
        LIMIT 1
    """)
    if row := cursor.fetchone():
        test_comments.append(('review_comment', row[0]))
        print(f"  ✓ C comment: {row[0]} ({row[1][:50]}...)")

    # 1 docs comment
    cursor = conn.execute("""
        SELECT id, body FROM review_comments
        WHERE path LIKE 'docs/%' AND id NOT IN (
            SELECT comment_id FROM comment_categories
            WHERE comment_type = 'review_comment'
        )
        LIMIT 1
    """)
    if row := cursor.fetchone():
        test_comments.append(('review_comment', row[0]))
        print(f"  ✓ Docs comment: {row[0]} ({row[1][:50]}...)")

    # 1 Makefile comment
    cursor = conn.execute("""
        SELECT id, body FROM review_comments
        WHERE (path LIKE '%Makefile%' OR path LIKE '%.mk') AND id NOT IN (
            SELECT comment_id FROM comment_categories
            WHERE comment_type = 'review_comment'
        )
        LIMIT 1
    """)
    if row := cursor.fetchone():
        test_comments.append(('review_comment', row[0]))
        print(f"  ✓ Makefile comment: {row[0]} ({row[1][:50]}...)")

    # 1 generic comment (any remaining)
    cursor = conn.execute("""
        SELECT id, body FROM review_comments
        WHERE id NOT IN (
            SELECT comment_id FROM comment_categories
            WHERE comment_type = 'review_comment'
        )
        LIMIT 1
    """)
    if row := cursor.fetchone():
        test_comments.append(('review_comment', row[0]))
        print(f"  ✓ Generic comment: {row[0]} ({row[1][:50]}...)")

    conn.close()

    if not test_comments:
        print("\n✗ No uncategorized comments found for testing!")
        print("  All comments may already be categorized.")
        return False

    # Save test comment IDs
    TEST_IDS_PATH.write_text(json.dumps(test_comments, indent=2))

    print(f"\n✓ Selected {len(test_comments)} test comments")
    print(f"  Saved to: {TEST_IDS_PATH}")
    print("\nNext steps:")
    print("  1. Run: python3 scripts/categorize_headless.py")
    print("     (This will categorize these comments along with others)")
    print("  2. Verify: python3 scripts/test_categorization.py --verify")
    return True


def verify_results():
    """Verify test categorizations."""
    if not TEST_IDS_PATH.exists():
        print("✗ No test batch found. Run without --verify first.")
        return False

    test_comments = json.loads(TEST_IDS_PATH.read_text())
    conn = sqlite3.connect(DB_PATH)

    print(f"Verifying categorization of {len(test_comments)} test comments...\n")

    all_verified = True
    for comment_type, comment_id in test_comments:
        cursor = conn.execute("""
            SELECT
                d.name as domain, theme, severity, component, port, subsystem,
                language_context, code_construct, concern_type, feedback_type,
                is_pattern, cpython_related, has_code_suggestion, keywords
            FROM comment_categories cc
            JOIN domains d ON cc.domain_id = d.id
            WHERE cc.comment_id = ? AND cc.comment_type = ?
        """, (comment_id, comment_type))

        row = cursor.fetchone()
        if row:
            print(f"✓ Comment {comment_id} ({comment_type}):")
            print(f"  Domain: {row[0]}, Theme: {row[1]}")
            print(f"  Severity: {row[2]}, Component: {row[3]}")
            print(f"  Language: {row[6]}, Construct: {row[7]}")
            print(f"  Concern: {row[8]}, Feedback: {row[9]}")
            print(f"  Port: {row[4] or 'null'}, Subsystem: {row[5] or 'null'}")
            print(f"  Pattern: {bool(row[10])}, CPython: {bool(row[11])}, Code: {bool(row[12])}")
            print(f"  Keywords: {row[13]}")
            print()
        else:
            print(f"✗ Comment {comment_id} ({comment_type}): NOT categorized")
            all_verified = False
            print()

    conn.close()

    if all_verified:
        print("✓ All test comments successfully categorized with 13-field schema!")
        return True
    else:
        print("✗ Some comments were not categorized. Check categorization errors.")
        return False


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--verify':
        success = verify_results()
        sys.exit(0 if success else 1)
    else:
        success = setup_test_batch()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
