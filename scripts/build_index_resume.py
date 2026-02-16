#!/usr/bin/env python3
"""Resume-capable index builder with memory management.

This script builds the LanceDB vector index from categorized comments in SQLite.
It supports resuming from interruptions and uses aggressive memory management
for systems with limited RAM.

Usage:
    python scripts/build_index_resume.py

The script will:
- Check for existing indexed records and skip them
- Process in small batches (batch_size=4) to limit memory
- Force garbage collection periodically
- Log progress every 100 records
- Handle interruptions gracefully (just re-run to resume)

Performance (CPU-only, WSL2, 45GB RAM):
- Time: ~5 hours for 18,614 records
- Memory: ~6GB peak usage
- Speed: 2-13 items/sec depending on text length
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

# Import after chdir so relative paths work
import lancedb
from tqdm import tqdm

from rag.indexer import get_sqlite_connection, iter_all_comments, count_comments
from rag.embeddings import get_embedder
from rag.config import get_config


def build_index_with_resume(
    batch_size: int = 4,
    gc_interval: int = 50,
    progress_interval: int = 25,
):
    """Build the vector index with resume capability.

    Args:
        batch_size: Number of records to embed at once (lower = less memory)
        gc_interval: Force garbage collection every N batches
        progress_interval: Log progress every N batches
    """
    config = get_config()
    db = lancedb.connect(str(config.lance_db_path))

    # Check for existing index
    try:
        table = db.open_table("reviews")
        existing = table.to_pandas()[['comment_id', 'comment_type']]
        indexed_keys = set(zip(existing['comment_id'], existing['comment_type']))
        logger.info(f"Resuming: {len(indexed_keys)} records already indexed")
    except Exception:
        table = None
        indexed_keys = set()
        logger.info("Starting fresh index build")

    # Get counts
    conn = get_sqlite_connection()
    total = count_comments(conn)
    remaining = total - len(indexed_keys)
    logger.info(f"Total categorized: {total}, Remaining to index: {remaining}")

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

    iterator = iter_all_comments(conn)
    pbar = tqdm(iterator, total=total, desc="Indexing")

    for comment in pbar:
        key = (comment['comment_id'], comment['comment_type'])
        if key in indexed_keys:
            continue

        # Prepare text for embedding
        text = comment["body"] or ""
        if comment["diff_hunk"]:
            text = f"{text}\n\nCode context:\n{comment['diff_hunk']}"

        batch_texts.append(text)
        batch_records.append(comment)

        if len(batch_texts) >= batch_size:
            # Embed batch
            embeddings = embedder.embed_batch(batch_texts)
            for i, record in enumerate(batch_records):
                record["vector"] = embeddings[i].tolist()

            # Write to LanceDB
            if table is None:
                table = db.create_table("reviews", batch_records, mode="overwrite")
            else:
                table.add(batch_records)

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
        embeddings = embedder.embed_batch(batch_texts)
        for i, record in enumerate(batch_records):
            record["vector"] = embeddings[i].tolist()

        if table is None:
            table = db.create_table("reviews", batch_records, mode="overwrite")
        else:
            table.add(batch_records)

        processed += len(batch_records)

    pbar.close()
    conn.close()

    total_indexed = len(indexed_keys) + processed
    logger.info(f"=== COMPLETE: {total_indexed} total records indexed ===")

    # Create full-text search index
    if table is not None:
        logger.info("Creating full-text search index on 'body' column...")
        try:
            table.create_fts_index("body", replace=True)
            logger.info("✓ Full-text search index created successfully")
        except Exception as e:
            logger.warning(f"Failed to create FTS index (non-fatal): {e}")

    return total_indexed


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Build LanceDB vector index with resume capability"
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
        count = build_index_with_resume(
            batch_size=args.batch_size,
            gc_interval=args.gc_interval,
        )
        logger.info(f"Successfully indexed {count} records")
        return 0
    except KeyboardInterrupt:
        logger.info("Interrupted. Re-run to resume from checkpoint.")
        return 1
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
