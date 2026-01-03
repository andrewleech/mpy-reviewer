#!/usr/bin/env python3
"""Add full-text search index to existing LanceDB table."""

import logging
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import lancedb
from rag.config import get_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def add_fts_index():
    """Add FTS index to existing table."""
    config = get_config()

    logger.info(f"Connecting to LanceDB at {config.lance_db_path}")
    db = lancedb.connect(str(config.lance_db_path))

    try:
        table = db.open_table("dpgeorge_reviews")
        logger.info(f"Found table with {len(table)} records")
    except Exception as e:
        logger.error(f"Failed to open table: {e}")
        return 1

    logger.info("Creating full-text search index on 'body' column...")
    try:
        table.create_fts_index("body", replace=True)
        logger.info("✓ Full-text search index created successfully")
        return 0
    except Exception as e:
        logger.error(f"Failed to create FTS index: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(add_fts_index())
