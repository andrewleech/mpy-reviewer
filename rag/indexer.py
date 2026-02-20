"""Index reviews into sqlite-vec (vec0 + FTS5)."""

import sqlite3
import logging
from typing import Iterator, Dict, Any, Optional

import numpy as np
import sqlite_vec
from tqdm import tqdm

from .config import get_config
from .embeddings import get_embedder

logger = logging.getLogger(__name__)

# Metadata columns stored in vec0 (filterable in KNN WHERE clause).
_VEC_META_COLS = [
    "comment_id", "comment_type", "domain", "severity", "component",
    "port", "subsystem", "language_context", "code_construct",
    "concern_type", "feedback_type",
]

# Auxiliary columns stored in vec0 (retrieved but not filterable).
_VEC_AUX_COLS = [
    "body", "diff_hunk", "file_path", "pr_number", "domain_id",
    "theme", "is_style_example", "is_pattern", "cpython_related",
    "has_code_suggestion", "keywords",
]

# Integer auxiliary columns (need int conversion on read, not NULL→None).
_INT_AUX_COLS = {
    "pr_number", "domain_id", "is_style_example", "is_pattern",
    "cpython_related", "has_code_suggestion",
}

# All non-vector columns returned by queries.
_ALL_COLS = _VEC_META_COLS + _VEC_AUX_COLS

_CREATE_VEC_TABLE = """
CREATE VIRTUAL TABLE IF NOT EXISTS vec_reviews USING vec0(
    embedding float[768] distance_metric=cosine,
    comment_id integer,
    comment_type text,
    domain text,
    severity text,
    component text,
    port text,
    subsystem text,
    language_context text,
    code_construct text,
    concern_type text,
    feedback_type text,
    +body text,
    +diff_hunk text,
    +file_path text,
    +pr_number integer,
    +domain_id integer,
    +theme text,
    +is_style_example integer,
    +is_pattern integer,
    +cpython_related integer,
    +has_code_suggestion integer,
    +keywords text
)
"""

_CREATE_FTS_TABLE = """
CREATE VIRTUAL TABLE IF NOT EXISTS review_fts USING fts5(
    body,
    content='',
    content_rowid='rowid'
)
"""

_CREATE_META_TABLE = """
CREATE TABLE IF NOT EXISTS vec_index_meta (
    key TEXT PRIMARY KEY,
    value TEXT
)
"""


def _write_index_meta(conn: sqlite3.Connection, model_name: str, record_count: int) -> None:
    """Write embedding model metadata into the database."""
    conn.execute(
        "INSERT OR REPLACE INTO vec_index_meta (key, value) VALUES (?, ?)",
        ("embedding_model", model_name),
    )
    conn.execute(
        "INSERT OR REPLACE INTO vec_index_meta (key, value) VALUES (?, ?)",
        ("record_count", str(record_count)),
    )
    conn.commit()


def _check_index_model(conn: sqlite3.Connection, expected_model: str) -> None:
    """Warn if the index was built with a different embedding model."""
    try:
        row = conn.execute(
            "SELECT value FROM vec_index_meta WHERE key = 'embedding_model'"
        ).fetchone()
    except sqlite3.OperationalError:
        # Table doesn't exist yet
        return
    if row is None:
        logger.warning(
            "No index metadata found — cannot verify embedding model compatibility. "
            "If search quality is poor, rebuild the index with: python scripts/build_index_resume.py"
        )
        return
    index_model = row[0]
    if index_model != expected_model:
        logger.warning(
            f"Embedding model mismatch: index was built with '{index_model}' "
            f"but config specifies '{expected_model}'. Retrieval quality will be "
            f"degraded. Rebuild the index with: python scripts/build_index_resume.py"
        )


def _load_vec(conn: sqlite3.Connection) -> None:
    """Load the sqlite-vec extension into a connection."""
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)


def get_sqlite_connection() -> sqlite3.Connection:
    """Get a connection to the SQLite database with sqlite-vec loaded."""
    config = get_config()
    conn = sqlite3.connect(config.sqlite_db_path)
    conn.row_factory = sqlite3.Row
    _load_vec(conn)
    return conn


def _vec_table_exists(conn: sqlite3.Connection) -> bool:
    """Check if the vec_reviews virtual table exists."""
    row = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='vec_reviews'"
    ).fetchone()
    return row[0] > 0


def _nullify_empty(d: Dict[str, Any]) -> Dict[str, Any]:
    """Convert empty-string metadata values back to None.

    vec0 cannot store NULL in metadata columns so we store '' on insert
    and convert back here.
    """
    for key in _VEC_META_COLS:
        if key in d and d[key] == "":
            d[key] = None
    # Also handle integer aux cols that came back as 0 when they should be None
    # (not needed — 0 is a valid value for booleans)
    return d


def _row_to_dict(row: sqlite3.Row, include_distance: bool = False) -> Dict[str, Any]:
    """Convert a sqlite3.Row from vec_reviews into a result dict."""
    keys = row.keys()
    d = {k: row[k] for k in keys if k != "embedding"}
    return _nullify_empty(d)


def _prepare_record(record: Dict[str, Any], embedding: np.ndarray) -> tuple:
    """Prepare a record for INSERT into vec_reviews.

    Returns a tuple of values in the column order expected by the INSERT statement.
    vec0 metadata columns cannot store NULL, so we coerce to empty string.
    """
    vec_bytes = embedding.astype(np.float32).tobytes()

    vals = [vec_bytes]  # embedding first

    # Metadata columns — coerce None to ""
    for col in _VEC_META_COLS:
        v = record.get(col)
        vals.append("" if v is None else v)

    # Auxiliary columns — None is OK for aux cols
    for col in _VEC_AUX_COLS:
        vals.append(record.get(col))

    return tuple(vals)


def _insert_batch(
    conn: sqlite3.Connection,
    records: list,
    embeddings: np.ndarray,
) -> None:
    """Insert a batch of records into vec_reviews and review_fts."""
    col_names = "embedding, " + ", ".join(_VEC_META_COLS + _VEC_AUX_COLS)
    placeholders = ", ".join(["?"] * (1 + len(_VEC_META_COLS) + len(_VEC_AUX_COLS)))
    insert_sql = f"INSERT INTO vec_reviews ({col_names}) VALUES ({placeholders})"

    for i, record in enumerate(records):
        row_vals = _prepare_record(record, embeddings[i])
        cursor = conn.execute(insert_sql, row_vals)
        rowid = cursor.lastrowid

        # Mirror body into FTS5
        body = record.get("body") or ""
        conn.execute(
            "INSERT INTO review_fts (rowid, body) VALUES (?, ?)",
            (rowid, body),
        )


def iter_review_comments(conn: sqlite3.Connection) -> Iterator[Dict[str, Any]]:
    """Iterate over all review comments with their categorizations."""
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


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """Create vec0, FTS5, and metadata tables if they don't exist."""
    conn.execute(_CREATE_VEC_TABLE)
    conn.execute(_CREATE_FTS_TABLE)
    conn.execute(_CREATE_META_TABLE)
    conn.commit()


def build_index(
    batch_size: int = 100,
    show_progress: bool = True,
    force: bool = False,
) -> int:
    """Build the sqlite-vec index from SQLite data.

    Args:
        batch_size: Number of records to process at once.
        show_progress: Whether to show progress bar.
        force: Whether to overwrite existing index.

    Returns:
        Number of records indexed.
    """
    config = get_config()
    embedder = get_embedder()
    conn = get_sqlite_connection()

    if _vec_table_exists(conn) and not force:
        logger.warning("Index already exists. Use force=True to overwrite.")
        conn.close()
        return 0

    if force and _vec_table_exists(conn):
        conn.execute("DROP TABLE IF EXISTS vec_reviews")
        conn.execute("DROP TABLE IF EXISTS review_fts")
        conn.execute("DROP TABLE IF EXISTS vec_index_meta")
        conn.commit()

    _ensure_tables(conn)

    total_count = count_comments(conn)
    logger.info(f"Building index for {total_count} comments")

    batch_texts = []
    batch_records = []
    total_indexed = 0

    iterator = iter_all_comments(conn)
    if show_progress:
        iterator = tqdm(iterator, total=total_count, desc="Indexing")

    for comment in iterator:
        text = comment["body"] or ""
        if comment["diff_hunk"]:
            text = f"{text}\n\nCode context:\n{comment['diff_hunk']}"

        batch_texts.append(text)
        batch_records.append(comment)

        if len(batch_texts) >= batch_size:
            embeddings = embedder.embed_batch(batch_texts, is_query=False)
            _insert_batch(conn, batch_records, embeddings)
            conn.commit()

            total_indexed += len(batch_records)
            batch_texts = []
            batch_records = []

    # Process remaining records
    if batch_texts:
        embeddings = embedder.embed_batch(batch_texts, is_query=False)
        _insert_batch(conn, batch_records, embeddings)
        conn.commit()
        total_indexed += len(batch_records)

    if total_indexed > 0:
        _write_index_meta(conn, config.embedding_model, total_indexed)
        logger.info(f"Index built: {total_indexed} records")
    else:
        logger.warning("No records to index")

    conn.close()
    return total_indexed


def get_vec_connection() -> sqlite3.Connection:
    """Get a sqlite3 connection with sqlite-vec loaded, for querying.

    Checks that the index exists and the embedding model matches.
    """
    config = get_config()
    conn = sqlite3.connect(config.sqlite_db_path)
    conn.row_factory = sqlite3.Row
    _load_vec(conn)
    _check_index_model(conn, config.embedding_model)
    return conn


def index_stats() -> Dict[str, Any]:
    """Get statistics about the index."""
    config = get_config()

    stats = {
        "db_path": str(config.sqlite_db_path),
        "exists": False,
        "num_records": 0,
    }

    try:
        conn = get_sqlite_connection()
        if _vec_table_exists(conn):
            stats["exists"] = True
            row = conn.execute("SELECT count(*) FROM vec_reviews").fetchone()
            stats["num_records"] = row[0]
        conn.close()
    except Exception as e:
        stats["error"] = str(e)

    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    build_index(force=True)
