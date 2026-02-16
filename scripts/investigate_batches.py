#!/usr/bin/env python3
"""Investigate specific batches that are causing timeouts."""

import sqlite3
import json
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "reviews.db"

def get_uncategorized_comments():
    """Get all uncategorized comments in the same order as categorize_headless.py."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Same query as categorize_headless.py
    query = """
        WITH categorized AS (
            SELECT comment_id, comment_type
            FROM comment_categories
        )
        SELECT
            rc.id,
            'review' as type,
            rc.pr_number,
            rc.body,
            rc.path,
            rc.diff_hunk,
            rc.created_at
        FROM review_comments rc
        LEFT JOIN categorized c ON rc.id = c.comment_id AND c.comment_type = 'review'
        WHERE c.comment_id IS NULL

        UNION ALL

        SELECT
            ic.id,
            'issue' as type,
            ic.pr_number,
            ic.body,
            NULL as path,
            NULL as diff_hunk,
            ic.created_at
        FROM issue_comments ic
        LEFT JOIN categorized c ON ic.id = c.comment_id AND c.comment_type = 'issue'
        WHERE c.comment_id IS NULL

        UNION ALL

        SELECT
            r.id,
            'review_summary' as type,
            r.pr_number,
            r.body,
            NULL as path,
            NULL as diff_hunk,
            r.created_at
        FROM reviews r
        LEFT JOIN categorized c ON r.id = c.comment_id AND c.comment_type = 'review_summary'
        WHERE c.comment_id IS NULL AND r.body IS NOT NULL AND r.body != ''

        ORDER BY created_at
    """

    cursor = conn.execute(query)
    comments = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return comments

def analyze_batch(comments, start_idx, end_idx):
    """Analyze a specific batch of comments."""
    batch = comments[start_idx:end_idx]

    print(f"\n{'='*80}")
    print(f"Batch {start_idx}-{end_idx-1} ({len(batch)} comments)")
    print(f"{'='*80}")

    for i, comment in enumerate(batch, start=start_idx):
        body_len = len(comment['body']) if comment['body'] else 0
        diff_len = len(comment['diff_hunk']) if comment['diff_hunk'] else 0
        total_len = body_len + diff_len

        print(f"\n[{i}] ID: {comment['id']}, Type: {comment['type']}, PR: {comment['pr_number']}")
        print(f"  Body length: {body_len}, Diff length: {diff_len}, Total: {total_len}")

        if comment['path']:
            print(f"  Path: {comment['path']}")

        # Show first 200 chars of body
        if comment['body']:
            preview = comment['body'][:200].replace('\n', ' ')
            print(f"  Body preview: {preview}...")

        # Check for unusual characteristics
        if total_len > 5000:
            print(f"  ⚠️  VERY LONG COMMENT ({total_len} chars)")

        if comment['body'] and comment['body'].count('```') > 10:
            print(f"  ⚠️  MANY CODE BLOCKS ({comment['body'].count('```')//2} blocks)")

        if comment['diff_hunk'] and len(comment['diff_hunk']) > 2000:
            print(f"  ⚠️  LARGE DIFF ({len(comment['diff_hunk'])} chars)")

def main():
    print("Getting uncategorized comments...")
    comments = get_uncategorized_comments()

    print(f"\nTotal uncategorized: {len(comments)}")

    # Analyze the problematic batches
    batch_ranges = [
        (1631, 1641),  # First failed batch
        (1641, 1651),  # Second failed batch
        (1651, 1661),  # Third failed batch
        (1661, 1671),  # Fourth failed batch
        (1671, 1681),  # Fifth failed batch
    ]

    for start, end in batch_ranges:
        if start < len(comments):
            actual_end = min(end, len(comments))
            analyze_batch(comments, start, actual_end)

    # Summary statistics
    print(f"\n{'='*80}")
    print("SUMMARY STATISTICS FOR PROBLEMATIC RANGE (1631-1681)")
    print(f"{'='*80}")

    problematic_comments = comments[1631:1681]

    total_chars = sum(
        (len(c['body']) if c['body'] else 0) +
        (len(c['diff_hunk']) if c['diff_hunk'] else 0)
        for c in problematic_comments
    )

    avg_chars = total_chars / len(problematic_comments) if problematic_comments else 0

    max_comment = max(
        problematic_comments,
        key=lambda c: (len(c['body']) if c['body'] else 0) + (len(c['diff_hunk']) if c['diff_hunk'] else 0)
    ) if problematic_comments else None

    print(f"Total comments: {len(problematic_comments)}")
    print(f"Total characters: {total_chars:,}")
    print(f"Average characters per comment: {avg_chars:.0f}")

    if max_comment:
        max_len = (len(max_comment['body']) if max_comment['body'] else 0) + \
                  (len(max_comment['diff_hunk']) if max_comment['diff_hunk'] else 0)
        print(f"\nLargest comment: ID {max_comment['id']}, {max_len:,} chars")
        print(f"  PR: {max_comment['pr_number']}")
        print(f"  Type: {max_comment['type']}")

    # Compare to a "normal" batch
    print(f"\n{'='*80}")
    print("COMPARISON TO NORMAL BATCH (1000-1050)")
    print(f"{'='*80}")

    normal_comments = comments[1000:1050]
    normal_total = sum(
        (len(c['body']) if c['body'] else 0) +
        (len(c['diff_hunk']) if c['diff_hunk'] else 0)
        for c in normal_comments
    )
    normal_avg = normal_total / len(normal_comments) if normal_comments else 0

    print(f"Normal batch avg chars: {normal_avg:.0f}")
    print(f"Problematic batch avg chars: {avg_chars:.0f}")
    print(f"Difference: {avg_chars - normal_avg:+.0f} chars ({(avg_chars/normal_avg - 1)*100:+.0f}%)")

if __name__ == "__main__":
    main()
