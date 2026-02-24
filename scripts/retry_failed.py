#!/usr/bin/env python3
"""Retry failed categorizations with detailed error reporting."""

import json
import sqlite3
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

# Import from categorize_headless
sys.path.insert(0, str(Path(__file__).parent))
from categorize_headless import (
    categorize_batch,
    get_db_connection,
    get_domain_id_map,
    store_categorizations,
    DB_PATH,
)

def get_failed_comments(conn, limit=None):
    """Get all comments marked as FAILED_CATEGORIZATION."""
    query = """
        SELECT cc.comment_id, cc.comment_type, cc.categorized_at
        FROM comment_categories cc
        WHERE cc.theme = 'FAILED_CATEGORIZATION'
        ORDER BY cc.categorized_at
    """

    if limit:
        query += f" LIMIT {limit}"

    cursor = conn.execute(query)
    failed_ids = [(row[0], row[1], row[2]) for row in cursor.fetchall()]

    # Get full comment data
    comments = []
    for comment_id, comment_type, failed_at in failed_ids:
        if comment_type == 'review_comment':
            cursor = conn.execute(
                "SELECT id, body, diff_hunk FROM review_comments WHERE id = ?",
                (comment_id,)
            )
            row = cursor.fetchone()
            if row:
                comments.append({
                    "id": row[0],
                    "type": comment_type,
                    "body": row[1],
                    "context": row[2],
                    "failed_at": failed_at
                })
        elif comment_type == 'issue_comment':
            cursor = conn.execute(
                "SELECT id, body FROM issue_comments WHERE id = ?",
                (comment_id,)
            )
            row = cursor.fetchone()
            if row:
                comments.append({
                    "id": row[0],
                    "type": comment_type,
                    "body": row[1],
                    "context": None,
                    "failed_at": failed_at
                })
        elif comment_type == 'review':
            cursor = conn.execute(
                "SELECT id, body FROM reviews WHERE id = ?",
                (comment_id,)
            )
            row = cursor.fetchone()
            if row:
                comments.append({
                    "id": row[0],
                    "type": comment_type,
                    "body": row[1],
                    "context": None,
                    "failed_at": failed_at
                })

    return comments

def delete_failed_marker(conn, comment_id, comment_type):
    """Remove the FAILED_CATEGORIZATION entry for a comment."""
    conn.execute(
        "DELETE FROM comment_categories WHERE comment_id = ? AND comment_type = ?",
        (comment_id, comment_type)
    )
    conn.commit()

def retry_single_comment(conn, comment, domain_id_map, verbose=True):
    """Retry categorization for a single comment."""
    if verbose:
        size = len(comment['body'] or '') + len(comment['context'] or '')
        print(f"\nRetrying comment {comment['id']} ({comment['type']}, {size} chars)")
        print(f"  Originally failed at: {comment['failed_at']}")

    # Try to categorize
    result = categorize_batch([comment])

    if result is None:
        if verbose:
            print(f"  ✗ Failed again")
        return False

    # Success - store categorization and remove failed marker
    stored = store_categorizations(conn, [comment], result, domain_id_map)

    if stored > 0:
        delete_failed_marker(conn, comment['id'], comment['type'])
        if verbose:
            print(f"  ✓ Successfully categorized")
        return True
    else:
        if verbose:
            print(f"  ✗ Categorization returned but storage failed")
        return False

def retry_batch(conn, comments, domain_id_map, verbose=True):
    """Retry categorization for a batch of comments."""
    if verbose:
        total_size = sum(len(c['body'] or '') + len(c['context'] or '') for c in comments)
        print(f"\nRetrying batch of {len(comments)} comments ({total_size} total chars)")
        for c in comments:
            print(f"  - {c['id']} ({c['type']})")

    # Try to categorize
    result = categorize_batch(comments)

    if result is None:
        if verbose:
            print(f"  ✗ Batch failed")
        return 0

    # Success - store categorizations and remove failed markers
    stored = store_categorizations(conn, comments, result, domain_id_map)

    for comment in comments[:stored]:
        delete_failed_marker(conn, comment['id'], comment['type'])

    if verbose:
        print(f"  ✓ Successfully categorized {stored}/{len(comments)}")

    return stored

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Retry failed categorizations')
    parser.add_argument('--batch-size', type=int, default=1,
                       help='Number of comments to retry at once (default: 1)')
    parser.add_argument('--limit', type=int, default=None,
                       help='Maximum number of failed comments to retry')
    parser.add_argument('--delay', type=int, default=2,
                       help='Delay in seconds between retries (default: 2)')
    parser.add_argument('--show-only', action='store_true',
                       help='Only show failed comments, do not retry')
    parser.add_argument('--stats', action='store_true',
                       help='Show statistics about failed comments')

    args = parser.parse_args()

    conn = get_db_connection()
    domain_id_map = get_domain_id_map(conn)

    # Get all failed comments
    failed_comments = get_failed_comments(conn, args.limit)

    print(f"\nFound {len(failed_comments)} failed comments")

    if args.stats:
        # Show statistics
        by_type = {}
        by_size = {'small': 0, 'medium': 0, 'large': 0, 'very_large': 0}

        for comment in failed_comments:
            # Count by type
            ctype = comment['type']
            by_type[ctype] = by_type.get(ctype, 0) + 1

            # Count by size
            size = len(comment['body'] or '') + len(comment['context'] or '')
            if size < 500:
                by_size['small'] += 1
            elif size < 2000:
                by_size['medium'] += 1
            elif size < 10000:
                by_size['large'] += 1
            else:
                by_size['very_large'] += 1

        print("\nBy type:")
        for ctype, count in sorted(by_type.items()):
            print(f"  {ctype}: {count}")

        print("\nBy size:")
        print(f"  Small (<500 chars): {by_size['small']}")
        print(f"  Medium (500-2K): {by_size['medium']}")
        print(f"  Large (2K-10K): {by_size['large']}")
        print(f"  Very large (>10K): {by_size['very_large']}")

        return

    if args.show_only:
        # Just list the failed comments
        for i, comment in enumerate(failed_comments, 1):
            size = len(comment['body'] or '') + len(comment['context'] or '')
            print(f"{i}. ID {comment['id']} ({comment['type']}, {size} chars)")
            print(f"   Failed at: {comment['failed_at']}")
            if comment['body']:
                preview = comment['body'][:100].replace('\n', ' ')
                print(f"   Preview: {preview}...")
        return

    # Retry the failed comments
    total_retried = 0
    total_success = 0

    if args.batch_size == 1:
        # Retry one at a time
        for i, comment in enumerate(failed_comments, 1):
            print(f"\n[{i}/{len(failed_comments)}]", end=" ")
            success = retry_single_comment(conn, comment, domain_id_map)
            total_retried += 1
            if success:
                total_success += 1

            if i < len(failed_comments):
                time.sleep(args.delay)
    else:
        # Retry in batches
        for i in range(0, len(failed_comments), args.batch_size):
            batch = failed_comments[i:i+args.batch_size]
            batch_num = (i // args.batch_size) + 1
            total_batches = (len(failed_comments) + args.batch_size - 1) // args.batch_size

            print(f"\n[Batch {batch_num}/{total_batches}]", end=" ")
            success_count = retry_batch(conn, batch, domain_id_map)
            total_retried += len(batch)
            total_success += success_count

            if i + args.batch_size < len(failed_comments):
                time.sleep(args.delay)

    print(f"\n\nRetry Summary:")
    print(f"  Total retried: {total_retried}")
    print(f"  Successful: {total_success}")
    print(f"  Still failed: {total_retried - total_success}")
    print(f"  Success rate: {total_success/total_retried*100:.1f}%")

    conn.close()

if __name__ == "__main__":
    main()
