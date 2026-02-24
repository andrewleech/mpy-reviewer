#!/usr/bin/env python3
"""Test the file-based categorization approach with a large comment."""

import sys
from pathlib import Path

# Add parent dir to path to import from categorize_headless
sys.path.insert(0, str(Path(__file__).parent))

from categorize_headless import categorize_batch, get_db_connection

def test_large_comment():
    """Test categorization with a large comment (34KB)."""
    conn = get_db_connection()

    # Get the largest uncategorized comment
    cursor = conn.execute("""
        WITH categorized AS (
            SELECT comment_id, comment_type FROM comment_categories
        )
        SELECT rc.id, 'review' as type, rc.body, rc.diff_hunk
        FROM review_comments rc
        LEFT JOIN categorized c ON rc.id = c.comment_id AND c.comment_type = 'review'
        WHERE c.comment_id IS NULL
        ORDER BY LENGTH(COALESCE(rc.body, '')) + LENGTH(COALESCE(rc.diff_hunk, '')) DESC
        LIMIT 1
    """)

    row = cursor.fetchone()
    if not row:
        print("No uncategorized comments found")
        return

    comment = {
        "id": row[0],
        "type": row[1],
        "body": row[2],
        "context": row[3]
    }

    total_size = (len(row[2]) if row[2] else 0) + (len(row[3]) if row[3] else 0)
    print(f"Testing with comment ID {comment['id']}")
    print(f"Total size: {total_size:,} bytes")
    print(f"\nAttempting categorization with file-based approach...")

    result = categorize_batch([comment])

    if result:
        print(f"\n✓ Success! Got {len(result)} categorization(s)")
        print(f"\nFirst categorization:")
        import json
        print(json.dumps(result[0], indent=2))
    else:
        print("\n✗ Failed to categorize")
        return 1

    conn.close()
    return 0

if __name__ == "__main__":
    sys.exit(test_large_comment())
