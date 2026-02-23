"""Multi-stage hybrid retrieval for MicroPython reviews."""

from typing import List, Dict, Any, Optional, Tuple
import logging
import os
import re
import sqlite3

import numpy as np

from .config import get_config
from .embeddings import get_embedder
from .indexer import get_vec_connection, _row_to_dict, _ALL_COLS

logger = logging.getLogger(__name__)

# Columns that are valid filter targets in vec0 KNN WHERE clauses.
_ALLOWED_FILTER_KEYS = frozenset({
    "domain", "severity", "component", "port", "subsystem",
    "language_context", "code_construct", "concern_type", "feedback_type",
})

# Pattern for safe filter values: alphanumeric, underscores, hyphens.
_SAFE_VALUE_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

# Severity ordering: most critical first.
_SEVERITY_ORDER = {"blocking": 0, "suggestion": 1, "nitpick": 2}

# FTS5 special characters that need quoting.
_FTS5_SPECIAL = re.compile(r'["\(\)\*:]')


def _sanitize_fts_query(query: str) -> str:
    """Sanitize a query string for FTS5 MATCH.

    Wraps individual terms in double-quotes and joins with OR
    to avoid FTS5 syntax errors from special characters.
    """
    # Split into words, strip punctuation
    terms = query.split()
    quoted = []
    for term in terms:
        # Remove characters that are problematic inside FTS5 double-quoted strings
        clean = term.replace('"', '').strip()
        if clean:
            quoted.append(f'"{clean}"')
    if not quoted:
        return '""'
    return " OR ".join(quoted)


def _path_overlap(review_path: str, diff_path: str) -> bool:
    """Check if two file paths share a meaningful prefix.

    Returns True if the paths share at least one directory component
    (e.g. both under "py/" or "ports/stm32/").
    """
    if not review_path or not diff_path:
        return False
    review_parts = review_path.split("/")
    diff_parts = diff_path.split("/")
    # Check for shared prefix of at least 1 directory
    shared = 0
    for r, d in zip(review_parts, diff_parts):
        if r == d:
            shared += 1
        else:
            break
    return shared >= 1


def _path_affinity_score(review_path: str, diff_files: List[str]) -> float:
    """Score how well a review's file path matches the diff files.

    Returns a multiplier: 1.0 (no match), up to 1.5 (exact file match).
    """
    if not review_path or not diff_files:
        return 1.0

    best = 1.0
    for diff_file in diff_files:
        if review_path == diff_file:
            # Exact file match
            return 1.5
        elif os.path.dirname(review_path) == os.path.dirname(diff_file):
            # Same directory
            best = max(best, 1.4)
        elif _path_overlap(review_path, diff_file):
            # Shared prefix (e.g. both under py/)
            best = max(best, 1.2)

    return best


class ReviewRetriever:
    """Hybrid retrieval combining dense and full-text search."""

    def __init__(self):
        self._conn = None
        self._embedder = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = get_vec_connection()
        return self._conn

    @property
    def embedder(self):
        if self._embedder is None:
            self._embedder = get_embedder()
        return self._embedder

    def search_dense(
        self,
        query: str,
        top_k: int = 100,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Search using dense embeddings only."""
        query_embedding = self.embedder.embed_single(query, is_query=True)
        query_bytes = query_embedding.astype(np.float32).tobytes()

        # Build the KNN query with optional metadata filters
        where_clauses = ["embedding MATCH ?", "k = ?"]
        params: list = [query_bytes, top_k]

        if filter_dict:
            for key, value in filter_dict.items():
                if key not in _ALLOWED_FILTER_KEYS:
                    logger.warning(f"Ignoring unknown filter key: {key}")
                    continue
                if not _SAFE_VALUE_RE.match(str(value)):
                    logger.warning(f"Ignoring unsafe filter value for {key}: {value!r}")
                    continue
                where_clauses.append(f"{key} = ?")
                params.append(str(value))

        col_list = ", ".join(_ALL_COLS)
        where = " AND ".join(where_clauses)
        sql = f"SELECT rowid, distance, {col_list} FROM vec_reviews WHERE {where}"

        cursor = self.conn.execute(sql, params)
        results = []
        for i, row in enumerate(cursor):
            d = _row_to_dict(row)
            d["rank"] = i + 1
            d["search_type"] = "dense"
            results.append(d)

        return results

    def search_fts(
        self,
        query: str,
        top_k: int = 100,
    ) -> List[Dict[str, Any]]:
        """Search using full-text search only."""
        sanitized = _sanitize_fts_query(query)

        # Get rowids and ranks from FTS5
        fts_sql = "SELECT rowid, rank FROM review_fts WHERE review_fts MATCH ? ORDER BY rank LIMIT ?"
        fts_rows = self.conn.execute(fts_sql, [sanitized, top_k]).fetchall()

        if not fts_rows:
            return []

        rowids = [r[0] for r in fts_rows]
        rank_map = {r[0]: r[1] for r in fts_rows}

        # Fetch full records from vec_reviews
        col_list = ", ".join(_ALL_COLS)
        placeholders = ", ".join(["?"] * len(rowids))
        vec_sql = f"SELECT rowid, {col_list} FROM vec_reviews WHERE rowid IN ({placeholders})"
        vec_rows = self.conn.execute(vec_sql, rowids).fetchall()

        # Build dict keyed by rowid for ordering
        row_map = {}
        for row in vec_rows:
            d = _row_to_dict(row)
            d["fts_rank"] = rank_map.get(row["rowid"], 0)
            row_map[row["rowid"]] = d

        # Return in FTS rank order
        results = []
        for i, rowid in enumerate(rowids):
            if rowid in row_map:
                d = row_map[rowid]
                d["rank"] = i + 1
                d["search_type"] = "fts"
                results.append(d)

        return results

    def search_hybrid(
        self,
        query: str,
        top_k_initial: int = 100,
        top_k_final: int = 20,
        filter_dict: Optional[Dict[str, Any]] = None,
        rrf_k: int = 60,
    ) -> List[Dict[str, Any]]:
        """Hybrid search combining dense and full-text search with RRF."""
        dense_results = self.search_dense(query, top_k_initial, filter_dict)
        fts_results = self.search_fts(query, top_k_initial)

        fused = self._reciprocal_rank_fusion(
            [dense_results, fts_results], k=rrf_k
        )

        return fused[:top_k_final]

    def _reciprocal_rank_fusion(
        self,
        result_lists: List[List[Dict[str, Any]]],
        k: int = 60,
    ) -> List[Dict[str, Any]]:
        """Combine multiple result lists using Reciprocal Rank Fusion.

        Keys by (comment_id, comment_type) to correctly handle
        different comment types with the same numeric id.
        """
        scores: Dict[Tuple, float] = {}
        records: Dict[Tuple, Dict[str, Any]] = {}

        for results in result_lists:
            for result in results:
                key = (result["comment_id"], result["comment_type"])
                rank = result["rank"]

                if key not in scores:
                    scores[key] = 0.0
                    records[key] = result

                scores[key] += 1.0 / (k + rank)

        sorted_keys = sorted(scores.keys(), key=lambda x: -scores[x])

        fused_results = []
        for i, key in enumerate(sorted_keys):
            record = records[key].copy()
            record["rrf_score"] = scores[key]
            record["rank"] = i + 1
            record["search_type"] = "hybrid"
            fused_results.append(record)

        return fused_results

    def search_with_filters(
        self,
        query: str,
        domain: Optional[str] = None,
        severity: Optional[str] = None,
        component: Optional[str] = None,
        language_context: Optional[str] = None,
        is_style_example: Optional[bool] = None,
        top_k: int = 20,
    ) -> List[Dict[str, Any]]:
        """Search with metadata filters."""
        config = get_config()

        filters = {}
        if domain:
            filters["domain"] = domain
        if severity:
            filters["severity"] = severity
        if component:
            filters["component"] = component
        if language_context:
            filters["language_context"] = language_context

        initial_k = config.top_k_initial if filters else top_k * 2

        results = self.search_hybrid(
            query,
            top_k_initial=initial_k,
            top_k_final=initial_k,
            filter_dict=filters,
        )

        if is_style_example is not None:
            results = [
                r for r in results
                if r.get("is_style_example") == is_style_example
            ]

        results = results[:top_k]

        # Sort by severity (blocking first), then by relevance within each group
        results.sort(
            key=lambda x: (
                _SEVERITY_ORDER.get(x.get("severity", ""), 9),
                -x.get("rrf_score", 0),
            )
        )

        return results

    def get_similar_reviews(
        self,
        diff_text: str,
        top_k: int = 8,
        prefer_style_examples: bool = True,
        diff_files: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Find reviews similar to a code diff.

        This is the main entry point for finding relevant past reviews.

        Args:
            diff_text: Code diff to find similar reviews for.
            top_k: Number of results to return.
            prefer_style_examples: Boost style examples in ranking.
            diff_files: List of file paths from the diff, used for
                        file-path affinity boosting.
        """
        config = get_config()

        results = self.search_hybrid(
            diff_text,
            top_k_initial=config.top_k_initial,
            top_k_final=config.top_k_rerank,
        )

        # --- Heuristic score adjustments ---

        for result in results:
            score = result.get("rrf_score", 0)

            # Style example boost
            if prefer_style_examples and result.get("is_style_example"):
                score *= 1.2

            # File-path affinity boost
            review_path = result.get("file_path") or result.get("path")
            if diff_files and review_path:
                score *= _path_affinity_score(review_path, diff_files)

            # Pattern preference: reusable patterns are more instructive
            if result.get("is_pattern"):
                score *= 1.15

            # Code suggestion preference: shows actual preferred code
            if result.get("has_code_suggestion"):
                score *= 1.1

            result["rrf_score"] = score

        # Re-sort after boosts
        results.sort(key=lambda x: -x.get("rrf_score", 0))

        # Apply diversity selection with severity constraints
        diverse_results = self._select_diverse(results, top_k)

        # Expand with thread context (reply chains)
        try:
            from .graph_expander import expand_results_with_threads
            diverse_results = expand_results_with_threads(diverse_results)
        except Exception as e:
            logger.debug(f"Thread expansion skipped: {e}")

        # Sort by severity (blocking first), then by relevance within each group
        diverse_results.sort(
            key=lambda x: (
                _SEVERITY_ORDER.get(x.get("severity", ""), 9),
                -x.get("rrf_score", 0),
            )
        )

        return diverse_results

    def _select_diverse(
        self,
        results: List[Dict[str, Any]],
        top_k: int,
        lambda_param: float = 0.7,
    ) -> List[Dict[str, Any]]:
        """Select diverse results using MMR-style selection with severity constraints.

        Ensures the final set includes at least one of each severity level
        (blocking, suggestion, nitpick) when available. Uses recency as a
        tiebreaker when scores are similar.
        """
        if len(results) <= top_k:
            return results

        selected = []
        remaining = results.copy()

        # Track which domains/severities we've seen
        seen_domains = set()
        seen_severities = set()

        # Identify available severities for enforcement
        severity_pool = {}
        for r in results:
            sev = r.get("severity")
            if sev and sev not in severity_pool:
                severity_pool[sev] = r

        # Pre-select one of each severity if available and top_k allows
        required_severities = ["blocking", "suggestion", "nitpick"]
        reserved = []
        for sev in required_severities:
            if sev in severity_pool and len(reserved) < top_k - 1:
                reserved.append(severity_pool[sev])

        while len(selected) < top_k and remaining:
            best_score = -1
            best_idx = 0

            for i, candidate in enumerate(remaining):
                # Base score from RRF
                relevance = candidate.get("rrf_score", 0)

                # Diversity bonus for new domains/severities
                diversity = 0
                if candidate.get("domain") not in seen_domains:
                    diversity += 0.1
                if candidate.get("severity") not in seen_severities:
                    diversity += 0.1

                # Severity enforcement: boost reserved candidates if their
                # severity hasn't been seen yet
                if (candidate in reserved
                        and candidate.get("severity") not in seen_severities):
                    diversity += 0.15

                # Combined score
                score = lambda_param * relevance + (1 - lambda_param) * diversity

                if score > best_score:
                    best_score = score
                    best_idx = i

            chosen = remaining.pop(best_idx)
            selected.append(chosen)

            if chosen.get("domain"):
                seen_domains.add(chosen["domain"])
            if chosen.get("severity"):
                seen_severities.add(chosen["severity"])

        return selected


# Global retriever instance
_retriever: Optional[ReviewRetriever] = None


def get_retriever() -> ReviewRetriever:
    """Get the global retriever instance."""
    global _retriever
    if _retriever is None:
        _retriever = ReviewRetriever()
    return _retriever


def search(query: str, top_k: int = 10, **kwargs) -> List[Dict[str, Any]]:
    """Convenience function for hybrid search."""
    retriever = get_retriever()
    return retriever.search_with_filters(query, top_k=top_k, **kwargs)


def find_similar(
    diff_text: str, top_k: int = 8, diff_files: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Find reviews similar to a code diff."""
    retriever = get_retriever()
    return retriever.get_similar_reviews(diff_text, top_k=top_k, diff_files=diff_files)
