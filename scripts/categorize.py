#!/usr/bin/env python3
"""
Categorize dpgeorge's review comments using Claude AI.

Processes uncategorized comments from the database and uses Claude Haiku
to extract domain, theme, severity, and style example information.
Supports batching and resume from checkpoint.
"""

import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import anthropic

DB_PATH = Path(__file__).parent.parent / "data" / "reviews.db"
BATCH_SIZE = 10
REQUEST_DELAY = 0.1  # Small delay between API calls


def get_db_connection():
    """Get database connection."""
    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)
    return sqlite3.connect(DB_PATH)


def get_domain_id_map(conn):
    """Get mapping of domain names to IDs."""
    cursor = conn.execute("SELECT id, name FROM domains")
    return {row[1]: row[0] for row in cursor.fetchall()}


def get_checkpoint(conn):
    """Get the last processed checkpoint."""
    cursor = conn.execute(
        "SELECT value FROM sync_state WHERE key = 'categorize_checkpoint'"
    )
    row = cursor.fetchone()
    return int(row[0]) if row else 0


def set_checkpoint(conn, checkpoint):
    """Store the categorization checkpoint."""
    conn.execute(
        "INSERT OR REPLACE INTO sync_state (key, value) VALUES (?, ?)",
        ("categorize_checkpoint", str(checkpoint)),
    )
    conn.commit()


def get_uncategorized_comments(conn, limit, offset=0):
    """Get uncategorized comments from all types."""
    comments = []

    # Review comments
    cursor = conn.execute("""
        SELECT id, 'review_comment' as type, body, diff_hunk
        FROM review_comments
        WHERE id NOT IN (
            SELECT comment_id FROM comment_categories
            WHERE comment_type = 'review_comment'
        )
        ORDER BY id
        LIMIT ? OFFSET ?
    """, (limit, offset))
    comments.extend([
        {"id": row[0], "type": row[1], "body": row[2], "context": row[3]}
        for row in cursor.fetchall()
    ])

    # Issue comments
    cursor = conn.execute("""
        SELECT id, 'issue_comment' as type, body, NULL
        FROM issue_comments
        WHERE id NOT IN (
            SELECT comment_id FROM comment_categories
            WHERE comment_type = 'issue_comment'
        )
        ORDER BY id
        LIMIT ? OFFSET ?
    """, (limit - len(comments), offset))
    comments.extend([
        {"id": row[0], "type": row[1], "body": row[2], "context": row[3]}
        for row in cursor.fetchall()
    ])

    # Reviews
    cursor = conn.execute("""
        SELECT id, 'review' as type, body, NULL
        FROM reviews
        WHERE id NOT IN (
            SELECT comment_id FROM comment_categories
            WHERE comment_type = 'review'
        )
        ORDER BY id
        LIMIT ? OFFSET ?
    """, (limit - len(comments), offset))
    comments.extend([
        {"id": row[0], "type": row[1], "body": row[2], "context": row[3]}
        for row in cursor.fetchall()
    ])

    return comments


def categorize_comment(client, comment):
    """Use Claude to categorize a single comment."""
    body = comment["body"] or ""
    context = comment["context"] or ""

    if context:
        prompt = f"""Analyze this code review comment and categorize it.

Comment: {body}

Code context (diff):
{context}

Respond with valid JSON only (no other text):
{{
  "domain": "one of: code_style, memory, error_handling, api_design, performance, portability, documentation, testing, security, architecture, build_system, correctness",
  "theme": "brief description of the specific issue or pattern",
  "severity": "blocking | suggestion | nitpick",
  "is_style_example": true or false
}}"""
    else:
        prompt = f"""Analyze this code review comment and categorize it.

Comment: {body}

Respond with valid JSON only (no other text):
{{
  "domain": "one of: code_style, memory, error_handling, api_design, performance, portability, documentation, testing, security, architecture, build_system, correctness",
  "theme": "brief description of the specific issue or pattern",
  "severity": "blocking | suggestion | nitpick",
  "is_style_example": true or false
}}"""

    try:
        message = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = message.content[0].text.strip()

        # Extract JSON from response (in case model includes extra text)
        try:
            result = json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract JSON from the response
            import re
            match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if match:
                result = json.loads(match.group(0))
            else:
                raise

        # Validate fields
        required_fields = ["domain", "theme", "severity", "is_style_example"]
        if not all(field in result for field in required_fields):
            print(f"    Missing required fields in response for comment {comment['id']}",
                  file=sys.stderr)
            return None

        # Validate severity value
        if result["severity"] not in ["blocking", "suggestion", "nitpick"]:
            print(f"    Invalid severity '{result['severity']}' for comment {comment['id']}",
                  file=sys.stderr)
            return None

        # Validate is_style_example is boolean
        if not isinstance(result["is_style_example"], bool):
            result["is_style_example"] = bool(result["is_style_example"])

        return result

    except anthropic.APIError as e:
        print(f"    API error for comment {comment['id']}: {e}", file=sys.stderr)
        return None


def store_categorization(conn, comment, category, domain_id_map):
    """Store categorization in database."""
    domain_id = domain_id_map.get(category["domain"])
    if not domain_id:
        print(f"  Warning: Unknown domain '{category['domain']}'", file=sys.stderr)
        return False

    severity_map = {
        "blocking": "blocking",
        "suggestion": "suggestion",
        "nitpick": "nitpick",
    }
    severity = severity_map.get(category["severity"])
    if not severity:
        print(f"  Warning: Unknown severity '{category['severity']}'", file=sys.stderr)
        return False

    is_style_example = 1 if category["is_style_example"] else 0

    try:
        conn.execute("""
            INSERT INTO comment_categories
            (comment_id, comment_type, domain_id, theme, severity, is_style_example,
             categorized_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            comment["id"],
            comment["type"],
            domain_id,
            category["theme"],
            severity,
            is_style_example,
            datetime.utcnow().isoformat() + "Z",
        ))
        return True
    except sqlite3.Error as e:
        print(f"  Database error storing category for comment {comment['id']}: {e}",
              file=sys.stderr)
        return False


def process_batch(client, conn, comments, domain_id_map):
    """Process a batch of comments."""
    if not comments:
        return 0

    successful = 0
    for comment in comments:
        # Skip if empty body
        if not comment.get("body") or not comment["body"].strip():
            print(f"  Skipping empty comment {comment['id']}")
            continue

        category = categorize_comment(client, comment)
        if category is None:
            print(f"  Failed to categorize comment {comment['id']}", file=sys.stderr)
            continue

        if store_categorization(conn, comment, category, domain_id_map):
            successful += 1
        else:
            print(f"  Failed to store categorization for comment {comment['id']}",
                  file=sys.stderr)

        time.sleep(REQUEST_DELAY)

    conn.commit()
    return successful


def get_total_uncategorized(conn):
    """Get total count of uncategorized comments."""
    cursor = conn.execute("""
        SELECT COUNT(*)
        FROM (
            SELECT id FROM review_comments
            WHERE id NOT IN (
                SELECT comment_id FROM comment_categories
                WHERE comment_type = 'review_comment'
            )
            UNION ALL
            SELECT id FROM issue_comments
            WHERE id NOT IN (
                SELECT comment_id FROM comment_categories
                WHERE comment_type = 'issue_comment'
            )
            UNION ALL
            SELECT id FROM reviews
            WHERE id NOT IN (
                SELECT comment_id FROM comment_categories
                WHERE comment_type = 'review'
            )
        )
    """)
    return cursor.fetchone()[0]


def main():
    # Check for API key
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic()

    conn = get_db_connection()
    domain_id_map = get_domain_id_map(conn)

    print(f"Connecting to database at {DB_PATH}")

    # Get stats
    total_uncategorized = get_total_uncategorized(conn)
    checkpoint = get_checkpoint(conn)

    if total_uncategorized == 0:
        print("No uncategorized comments found")
        conn.close()
        return

    print(f"Total uncategorized comments: {total_uncategorized}")
    if checkpoint > 0:
        print(f"Resuming from checkpoint: {checkpoint}")

    # Process in batches
    processed = 0
    batch_num = 0
    total_categorized = 0
    start_time = datetime.now()

    while processed < total_uncategorized:
        batch_num += 1
        offset = processed
        comments = get_uncategorized_comments(conn, BATCH_SIZE, offset)

        if not comments:
            break

        print(f"\nBatch {batch_num}: Processing {len(comments)} comments "
              f"(total: {processed}/{total_uncategorized})")

        successful = process_batch(client, conn, comments, domain_id_map)
        total_categorized += successful
        processed += len(comments)

        # Update checkpoint
        if comments:
            set_checkpoint(conn, comments[-1]["id"])

        # Progress report
        elapsed = datetime.now() - start_time
        rate = total_categorized / max(elapsed.total_seconds(), 1)
        remaining = total_uncategorized - processed
        eta_seconds = remaining / max(rate, 0.01)
        eta_minutes = eta_seconds / 60

        print(f"  Categorized: {successful}/{len(comments)}")
        print(f"  Rate: {rate:.1f} comments/sec")
        if eta_minutes > 0:
            print(f"  ETA: {eta_minutes:.0f} minutes")

    # Final stats
    elapsed = datetime.now() - start_time
    cursor = conn.execute("SELECT COUNT(*) FROM comment_categories")
    total_in_db = cursor.fetchone()[0]

    print(f"\nCategorization complete!")
    print(f"  Total processed: {total_categorized}")
    print(f"  Total in database: {total_in_db}")
    print(f"  Time elapsed: {elapsed.total_seconds():.1f}s")

    # Domain breakdown
    print("\nDomain breakdown:")
    cursor = conn.execute("""
        SELECT d.name, COUNT(*) as count
        FROM comment_categories cc
        JOIN domains d ON cc.domain_id = d.id
        GROUP BY d.name
        ORDER BY count DESC
    """)
    for domain, count in cursor.fetchall():
        print(f"  {domain}: {count}")

    # Severity breakdown
    print("\nSeverity breakdown:")
    cursor = conn.execute("""
        SELECT severity, COUNT(*) as count
        FROM comment_categories
        GROUP BY severity
        ORDER BY count DESC
    """)
    for severity, count in cursor.fetchall():
        print(f"  {severity}: {count}")

    # Style examples
    cursor = conn.execute("""
        SELECT COUNT(*) FROM comment_categories
        WHERE is_style_example = 1
    """)
    style_examples = cursor.fetchone()[0]
    print(f"\nStyle examples: {style_examples}")

    conn.close()


if __name__ == "__main__":
    main()
