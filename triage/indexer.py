"""Index issues into sqlite-vec (vec0 + FTS5)."""

import sqlite3
import logging
from typing import Iterator, Dict, Any, Optional

import numpy as np
import sqlite_vec

from rag.config import get_config
from rag.embeddings import get_embedder
from rag.indexer import get_sqlite_connection, _load_vec, _write_index_meta

logger = logging.getLogger(__name__)

# Metadata columns stored in vec0 (filterable in KNN WHERE clause).
_VEC_ISSUES_META_COLS = [
    "issue_number", "repo", "state", "component", "port",
]

# Auxiliary columns stored in vec0 (retrieved but not filterable).
_VEC_ISSUES_AUX_COLS = [
    "title", "body", "labels", "author", "created_at", "closed_at", "comments_count",
]

# All non-vector columns returned by queries.
_ALL_ISSUE_COLS = _VEC_ISSUES_META_COLS + _VEC_ISSUES_AUX_COLS

_CREATE_VEC_ISSUES = """
CREATE VIRTUAL TABLE IF NOT EXISTS vec_issues USING vec0(
    embedding float[768] distance_metric=cosine,
    issue_number integer,
    repo text,
    state text,
    component text,
    port text,
    +title text,
    +body text,
    +labels text,
    +author text,
    +created_at text,
    +closed_at text,
    +comments_count integer
)
"""

_CREATE_ISSUE_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS issue_fts USING fts5(
    title,
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


def _nullify_empty_issues(d: Dict[str, Any]) -> Dict[str, Any]:
    """Convert empty-string metadata values back to None.

    vec0 cannot store NULL in metadata columns so we store '' on insert
    and convert back here.
    """
    for key in _VEC_ISSUES_META_COLS:
        if key in d and d[key] == "":
            d[key] = None
    return d


def issue_row_to_dict(row: sqlite3.Row, include_distance: bool = False) -> Dict[str, Any]:
    """Convert a sqlite3.Row from vec_issues into a result dict."""
    keys = row.keys()
    d = {k: row[k] for k in keys if k != "embedding"}
    return _nullify_empty_issues(d)


def _prepare_issue_record(record: Dict[str, Any], embedding: np.ndarray) -> tuple:
    """Prepare a record for INSERT into vec_issues.

    Returns a tuple of values in the column order expected by the INSERT statement.
    vec0 metadata columns cannot store NULL, so we coerce to empty string.
    """
    vec_bytes = embedding.astype(np.float32).tobytes()

    vals = [vec_bytes]  # embedding first

    # Metadata columns — coerce None to ""
    for col in _VEC_ISSUES_META_COLS:
        v = record.get(col)
        vals.append("" if v is None else v)

    # Auxiliary columns — None is OK for aux cols
    for col in _VEC_ISSUES_AUX_COLS:
        vals.append(record.get(col))

    return tuple(vals)


def _insert_issue_batch(
    conn: sqlite3.Connection,
    records: list,
    embeddings: np.ndarray,
) -> None:
    """Insert a batch of records into vec_issues and issue_fts."""
    col_names = "embedding, " + ", ".join(_VEC_ISSUES_META_COLS + _VEC_ISSUES_AUX_COLS)
    placeholders = ", ".join(["?"] * (1 + len(_VEC_ISSUES_META_COLS) + len(_VEC_ISSUES_AUX_COLS)))
    insert_sql = f"INSERT INTO vec_issues ({col_names}) VALUES ({placeholders})"

    for i, record in enumerate(records):
        row_vals = _prepare_issue_record(record, embeddings[i])
        cursor = conn.execute(insert_sql, row_vals)
        rowid = cursor.lastrowid

        # Mirror title and body into FTS5
        title = record.get("title") or ""
        body = record.get("body") or ""
        conn.execute(
            "INSERT INTO issue_fts (rowid, title, body) VALUES (?, ?, ?)",
            (rowid, title, body),
        )


def _vec_issues_table_exists(conn: sqlite3.Connection) -> bool:
    """Check if the vec_issues virtual table exists."""
    row = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='vec_issues'"
    ).fetchone()
    return row[0] > 0


def _ensure_issue_tables(conn: sqlite3.Connection) -> None:
    """Create vec_issues, issue_fts, and metadata tables if they don't exist."""
    conn.execute(_CREATE_VEC_ISSUES)
    conn.execute(_CREATE_ISSUE_FTS)
    conn.execute(_CREATE_META_TABLE)
    conn.commit()


def iter_issues(conn: sqlite3.Connection) -> Iterator[Dict[str, Any]]:
    """Iterate over all issues from the issues table."""
    query = "SELECT number, repo, title, body, author, state, labels, created_at, closed_at, comments_count FROM issues"
    cursor = conn.execute(query)
    for row in cursor:
        yield {
            "issue_number": row[0],
            "repo": row[1],
            "title": row[2],
            "body": row[3],
            "author": row[4],
            "state": row[5],
            "labels": row[6],
            "created_at": row[7],
            "closed_at": row[8],
            "comments_count": row[9],
            "component": None,
            "port": None,
        }


def count_issues(conn: sqlite3.Connection) -> int:
    """Count total number of issues in the issues table."""
    row = conn.execute("SELECT COUNT(*) FROM issues").fetchone()
    return row[0] if row else 0


def issue_index_stats(conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """Get statistics about the issue index.

    Args:
        conn: Optional database connection. If None, opens a new connection.

    Returns:
        Dict with 'exists' and 'num_records' keys (and 'error' if applicable).
    """
    should_close = conn is None
    if conn is None:
        conn = get_sqlite_connection()

    stats = {
        "exists": False,
        "num_records": 0,
    }

    try:
        if _vec_issues_table_exists(conn):
            stats["exists"] = True
            row = conn.execute("SELECT count(*) FROM vec_issues").fetchone()
            stats["num_records"] = row[0] if row else 0
    except Exception as e:
        stats["error"] = str(e)
    finally:
        if should_close:
            conn.close()

    return stats
