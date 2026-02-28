#!/usr/bin/env python3
"""Resume-capable issue index builder with memory management.

This script builds the sqlite-vec vector index from issues in SQLite.
It supports resuming from interruptions and uses aggressive memory management
for systems with limited RAM.

Usage:
    python scripts/build_issue_index.py

The script will:
- Check for existing indexed records and skip them
- Process in small batches (batch_size=4) to limit memory
- Force garbage collection periodically
- Log progress every 25 batches
- Handle interruptions gracefully (just re-run to resume)

Performance (CPU-only, WSL2, 45GB RAM):
- Time: ~5-55 min for ~6,451 issues (2-13 items/sec depending on text length)
- Memory: ~4-6GB peak usage
"""

import logging
import gc
import os
import sys
from pathlib import Path

# Change to project root
PROJECT_ROOT = Path(__file__).parent.parent
os.chdir(PROJECT_ROOT)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logging.getLogger('transformers').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

from tqdm import tqdm

from triage.indexer import (
    iter_issues, count_issues,
    _ensure_issue_tables, _insert_issue_batch, _vec_issues_table_exists,
)
from rag.indexer import get_sqlite_connection, _write_index_meta
from rag.embeddings import get_embedder
from rag.config import get_config


def build_issue_index_with_resume(
    batch_size: int = 4,
    gc_interval: int = 50,
    progress_interval: int = 25,
):
    """Build the issue vector index with resume capability.

    Args:
        batch_size: Number of records to embed at once (lower = less memory)
        gc_interval: Force garbage collection every N batches
        progress_interval: Log progress every N batches
    """
    config = get_config()
    conn = get_sqlite_connection()

    # Ensure tables exist
    _ensure_issue_tables(conn)

    # Check for existing indexed records
    indexed_keys = set()
    if _vec_issues_table_exists(conn):
        cursor = conn.execute("SELECT issue_number, repo FROM vec_issues")
        for row in cursor:
            indexed_keys.add((row[0], row[1]))
        logger.info(f"Resuming: {len(indexed_keys)} records already indexed")
    else:
        logger.info("Starting fresh index build")

    # Get counts
    total = count_issues(conn)
    remaining = total - len(indexed_keys)
    logger.info(f"Total issues: {total}, Remaining to index: {remaining}")

    if remaining == 0:
        logger.info("All records already indexed!")
        conn.close()
        return len(indexed_keys)

    # Load embedder
    logger.info("Loading embedding model...")
    embedder = get_embedder()
    logger.info(f"Using device: {embedder.device}")

    # Process records
    batch_texts = []
    batch_records = []
    processed = 0
    batch_count = 0

    iterator = iter_issues(conn)
    pbar = tqdm(iterator, total=total, desc="Indexing issues")

    for issue in pbar:
        key = (issue['issue_number'], issue['repo'])
        if key in indexed_keys:
            continue

        # Prepare text for embedding (title + body)
        text = f"{issue['title']}\n\n{issue['body'] or ''}"

        batch_texts.append(text)
        batch_records.append(issue)

        if len(batch_texts) >= batch_size:
            # Embed batch
            embeddings = embedder.embed_batch(batch_texts, is_query=False)

            # Write to sqlite-vec
            _insert_issue_batch(conn, batch_records, embeddings)
            conn.commit()

            processed += len(batch_records)
            batch_count += 1

            # Progress logging
            if batch_count % progress_interval == 0:
                total_indexed = len(indexed_keys) + processed
                logger.info(f"Progress: {processed} new records (total: {total_indexed})")

            # Force garbage collection
            if batch_count % gc_interval == 0:
                gc.collect()

            batch_texts = []
            batch_records = []

    # Process remaining records
    if batch_texts:
        embeddings = embedder.embed_batch(batch_texts, is_query=False)
        _insert_issue_batch(conn, batch_records, embeddings)
        conn.commit()
        processed += len(batch_records)

    pbar.close()

    total_indexed = len(indexed_keys) + processed
    logger.info(f"=== COMPLETE: {total_indexed} total issue records indexed ===")

    # Write metadata
    _write_index_meta(conn, config.embedding_model, total_indexed)

    conn.close()
    return total_indexed


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Build sqlite-vec issue vector index with resume capability"
    )
    parser.add_argument(
        "--batch-size", type=int, default=4,
        help="Batch size for embedding (default: 4, lower = less memory)"
    )
    parser.add_argument(
        "--gc-interval", type=int, default=50,
        help="Force GC every N batches (default: 50)"
    )

    args = parser.parse_args()

    try:
        count = build_issue_index_with_resume(
            batch_size=args.batch_size,
            gc_interval=args.gc_interval,
        )
        logger.info(f"Successfully indexed {count} issue records")
        return 0
    except KeyboardInterrupt:
        logger.info("Interrupted. Re-run to resume from checkpoint.")
        return 1
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
