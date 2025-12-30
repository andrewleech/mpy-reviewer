"""Index dpgeorge reviews into LanceDB."""

import sqlite3
import logging
from typing import Iterator, Dict, Any, Optional
from pathlib import Path

import lancedb
import pyarrow as pa
from tqdm import tqdm

from .config import get_config
from .embeddings import get_embedder

logger = logging.getLogger(__name__)


def get_sqlite_connection() -> sqlite3.Connection:
    """Get a connection to the SQLite database."""
    config = get_config()
    conn = sqlite3.connect(config.sqlite_db_path)
    conn.row_factory = sqlite3.Row
    return conn


def iter_review_comments(conn: sqlite3.Connection) -> Iterator[Dict[str, Any]]:
    """Iterate over all review comments with their categorizations.

    Yields dicts with comment data and metadata.
    """
    query = """
        SELECT
            rc.id as comment_id,
            'review_comment' as comment_type,
            rc.body,
            rc.diff_hunk,
            rc.path as file_path,
            rc.pr_number,
            cc.domain_id,
            d.name as domain,
            cc.theme,
            cc.severity,
            cc.component,
            cc.port,
            cc.subsystem,
            cc.language_context,
            cc.code_construct,
            cc.concern_type,
            cc.feedback_type,
            cc.is_style_example,
            cc.is_pattern,
            cc.cpython_related,
            cc.has_code_suggestion,
            cc.keywords
        FROM review_comments rc
        JOIN comment_categories cc ON rc.id = cc.comment_id AND cc.comment_type = 'review_comment'
        LEFT JOIN domains d ON cc.domain_id = d.id
        WHERE cc.theme != 'FAILED_CATEGORIZATION'
    """

    cursor = conn.execute(query)
    for row in cursor:
        yield dict(row)


def iter_issue_comments(conn: sqlite3.Connection) -> Iterator[Dict[str, Any]]:
    """Iterate over all issue comments with their categorizations."""
    query = """
        SELECT
            ic.id as comment_id,
            'issue_comment' as comment_type,
            ic.body,
            NULL as diff_hunk,
            NULL as file_path,
            ic.pr_number,
            cc.domain_id,
            d.name as domain,
            cc.theme,
            cc.severity,
            cc.component,
            cc.port,
            cc.subsystem,
            cc.language_context,
            cc.code_construct,
            cc.concern_type,
            cc.feedback_type,
            cc.is_style_example,
            cc.is_pattern,
            cc.cpython_related,
            cc.has_code_suggestion,
            cc.keywords
        FROM issue_comments ic
        JOIN comment_categories cc ON ic.id = cc.comment_id AND cc.comment_type = 'issue_comment'
        LEFT JOIN domains d ON cc.domain_id = d.id
        WHERE cc.theme != 'FAILED_CATEGORIZATION'
    """

    cursor = conn.execute(query)
    for row in cursor:
        yield dict(row)


def iter_reviews(conn: sqlite3.Connection) -> Iterator[Dict[str, Any]]:
    """Iterate over all review summaries with their categorizations."""
    query = """
        SELECT
            r.id as comment_id,
            'review' as comment_type,
            r.body,
            NULL as diff_hunk,
            NULL as file_path,
            r.pr_number,
            cc.domain_id,
            d.name as domain,
            cc.theme,
            cc.severity,
            cc.component,
            cc.port,
            cc.subsystem,
            cc.language_context,
            cc.code_construct,
            cc.concern_type,
            cc.feedback_type,
            cc.is_style_example,
            cc.is_pattern,
            cc.cpython_related,
            cc.has_code_suggestion,
            cc.keywords
        FROM reviews r
        JOIN comment_categories cc ON r.id = cc.comment_id AND cc.comment_type = 'review'
        LEFT JOIN domains d ON cc.domain_id = d.id
        WHERE cc.theme != 'FAILED_CATEGORIZATION'
          AND r.body IS NOT NULL AND r.body != ''
    """

    cursor = conn.execute(query)
    for row in cursor:
        yield dict(row)


def iter_all_comments(conn: sqlite3.Connection) -> Iterator[Dict[str, Any]]:
    """Iterate over all comments (review_comments, issue_comments, reviews)."""
    yield from iter_review_comments(conn)
    yield from iter_issue_comments(conn)
    yield from iter_reviews(conn)


def count_comments(conn: sqlite3.Connection) -> int:
    """Count total number of categorized comments."""
    query = """
        SELECT COUNT(*) FROM comment_categories
        WHERE theme != 'FAILED_CATEGORIZATION'
    """
    return conn.execute(query).fetchone()[0]


def build_index(
    batch_size: int = 100,
    show_progress: bool = True,
    force: bool = False,
) -> int:
    """Build the LanceDB index from SQLite data.

    Args:
        batch_size: Number of records to process at once
        show_progress: Whether to show progress bar
        force: Whether to overwrite existing index

    Returns:
        Number of records indexed
    """
    config = get_config()
    embedder = get_embedder()

    # Check if index exists
    lance_path = config.lance_db_path
    table_exists = (lance_path / "dpgeorge_reviews.lance").exists()

    if table_exists and not force:
        logger.warning(
            f"Index already exists at {lance_path}. Use force=True to overwrite."
        )
        return 0

    # Connect to databases
    conn = get_sqlite_connection()
    db = lancedb.connect(str(lance_path))

    total_count = count_comments(conn)
    logger.info(f"Building index for {total_count} comments")

    # Process in chunks to avoid memory bloat
    batch_texts = []
    batch_records = []
    table = None
    total_indexed = 0
    chunk_size = batch_size * 10  # Write 10 batches at a time

    iterator = iter_all_comments(conn)
    if show_progress:
        iterator = tqdm(iterator, total=total_count, desc="Indexing")

    for comment in iterator:
        try:
            # Prepare text for embedding
            text = comment["body"] or ""
            if comment["diff_hunk"]:
                text = f"{text}\n\nCode context:\n{comment['diff_hunk']}"

            batch_texts.append(text)
            batch_records.append(comment)

            # Process batch when full
            if len(batch_texts) >= batch_size:
                logger.info(f"Processing batch of {len(batch_texts)} texts, total indexed so far: {total_indexed}")
                try:
                    embeddings = embedder.embed_batch(batch_texts)
                    logger.info(f"Successfully embedded {len(embeddings)} texts")
                except Exception as e:
                    logger.error(f"Error embedding batch: {e}", exc_info=True)
                    raise

                for i, record in enumerate(batch_records):
                    record["vector"] = embeddings[i].tolist()

                # Write chunk to LanceDB (incremental)
                try:
                    if table is None:
                        # First chunk: create table
                        logger.info(f"Creating LanceDB table with {len(batch_records)} initial records")
                        table = db.create_table("dpgeorge_reviews", batch_records, mode="overwrite")
                        logger.info("Table created successfully")
                    else:
                        # Subsequent chunks: add to table
                        logger.info(f"Adding {len(batch_records)} records to existing table")
                        table.add(batch_records)
                        logger.info("Records added successfully")
                except Exception as e:
                    logger.error(f"Error writing to LanceDB: {e}", exc_info=True)
                    raise

                total_indexed += len(batch_records)
                batch_texts = []
                batch_records = []
        except Exception as e:
            logger.error(f"Error processing comment {comment.get('comment_id', 'unknown')}: {e}", exc_info=True)
            raise

    # Process remaining records
    if batch_texts:
        logger.info(f"Processing final batch of {len(batch_texts)} texts")
        try:
            embeddings = embedder.embed_batch(batch_texts)
            logger.info(f"Successfully embedded {len(embeddings)} final texts")
            for i, record in enumerate(batch_records):
                record["vector"] = embeddings[i].tolist()

            if table is None:
                logger.info(f"Creating LanceDB table with {len(batch_records)} records (final batch)")
                table = db.create_table("dpgeorge_reviews", batch_records, mode="overwrite")
                logger.info("Table created successfully")
            else:
                logger.info(f"Adding final {len(batch_records)} records to table")
                table.add(batch_records)
                logger.info("Final records added successfully")

            total_indexed += len(batch_records)
        except Exception as e:
            logger.error(f"Error processing final batch: {e}", exc_info=True)
            raise

    # Create full-text search index on body
    if table is not None:
        logger.info("Creating full-text search index")
        table.create_fts_index("body", replace=True)
        logger.info("Index built successfully")
    else:
        logger.warning("No records to index")

    conn.close()
    return total_indexed


def get_lance_table():
    """Get the LanceDB table for querying."""
    config = get_config()
    db = lancedb.connect(str(config.lance_db_path))
    return db.open_table("dpgeorge_reviews")


def index_stats() -> Dict[str, Any]:
    """Get statistics about the index."""
    config = get_config()

    stats = {
        "lance_path": str(config.lance_db_path),
        "exists": False,
        "num_records": 0,
    }

    lance_path = config.lance_db_path / "dpgeorge_reviews.lance"
    if lance_path.exists():
        stats["exists"] = True
        try:
            table = get_lance_table()
            stats["num_records"] = len(table)
        except Exception as e:
            stats["error"] = str(e)

    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    build_index(force=True)
