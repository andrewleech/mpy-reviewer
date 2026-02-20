#!/usr/bin/env python3
"""Rebuild FTS5 index from existing vec_reviews data."""

import logging
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from rag.indexer import get_sqlite_connection, _vec_table_exists

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def rebuild_fts_index():
    """Rebuild the FTS5 index from vec_reviews body column."""
    conn = get_sqlite_connection()

    if not _vec_table_exists(conn):
        logger.error("vec_reviews table not found. Build the index first.")
        conn.close()
        return 1

    count = conn.execute("SELECT count(*) FROM vec_reviews").fetchone()[0]
    logger.info(f"Found {count} records in vec_reviews")

    logger.info("Dropping existing FTS index if present...")
    conn.execute("DROP TABLE IF EXISTS review_fts")
    conn.commit()

    logger.info("Creating FTS5 table...")
    conn.execute("""
        CREATE VIRTUAL TABLE review_fts USING fts5(
            body,
            content='',
            content_rowid='rowid'
        )
    """)

    logger.info("Populating FTS index from vec_reviews...")
    conn.execute("""
        INSERT INTO review_fts (rowid, body)
        SELECT rowid, body FROM vec_reviews
    """)
    conn.commit()

    fts_count = conn.execute("SELECT count(*) FROM review_fts").fetchone()[0]
    logger.info(f"FTS index rebuilt with {fts_count} records")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(rebuild_fts_index())
