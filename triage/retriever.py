"""Issue retrieval and duplicate detection for triage."""

from typing import List, Dict, Any, Optional, Tuple
import json
import logging
import re
import sqlite3

import numpy as np

from rag.config import get_config, get_triage_config
from rag.embeddings import get_embedder
from rag.indexer import get_vec_connection
from triage.indexer import _ALL_ISSUE_COLS, issue_row_to_dict

logger = logging.getLogger(__name__)

_ISSUE_FILTER_KEYS = frozenset({"repo", "state", "component", "port"})
_SAFE_VALUE_RE = re.compile(r"^[a-zA-Z0-9_/-]+$")


_FTS5_SPECIAL_RE = re.compile(r'["\(\)\*\+\-\^:]')


def _sanitize_fts_query(query: str) -> str:
    """Sanitize a query string for FTS5 MATCH."""
    terms = query.split()
    quoted = []
    for term in terms:
        clean = _FTS5_SPECIAL_RE.sub("", term).strip()
        if clean:
            quoted.append(f'"{clean}"')
    if not quoted:
        return '""'
    return " OR ".join(quoted)


def _title_word_overlap(title_a: str, title_b: str) -> float:
    """Jaccard similarity between title words."""
    if not title_a or not title_b:
        return 0.0
    words_a = set(title_a.lower().split())
    words_b = set(title_b.lower().split())
    # Remove common stop words
    stop = {"the", "a", "an", "is", "in", "on", "of", "to", "for", "with", "and", "or", "not"}
    words_a -= stop
    words_b -= stop
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


class IssueRetriever:
    """Hybrid retrieval for issue triage."""

    def __init__(self):
        self._conn = None
        self._embedder = None

    @property
    def conn(self):
        if self._conn is None:
            self._conn = get_vec_connection()
        return self._conn

    @property
    def embedder(self):
        if self._embedder is None:
            self._embedder = get_embedder()
        return self._embedder

    def search_similar_issues(
        self,
        query: str,
        top_k: int = 10,
        state: Optional[str] = None,
        component: Optional[str] = None,
        port: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Hybrid dense+FTS search on vec_issues."""
        filters = {}
        if state:
            filters["state"] = state
        if component:
            filters["component"] = component
        if port:
            filters["port"] = port

        dense = self._search_dense_issues(query, top_k=100, filter_dict=filters)
        fts = self._search_fts_issues(query, top_k=100)
        fused = self._reciprocal_rank_fusion(dense, fts)
        return fused[:top_k]

    def find_potential_duplicates(
        self,
        issue_title: str,
        issue_body: Optional[str] = None,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """Find potential duplicate issues with heuristic boosting.

        Boosts closed issues with merged closing PRs, same component/port,
        and title word overlap.
        """
        triage_config = get_triage_config()
        query_text = f"{issue_title}\n\n{issue_body or ''}"

        # Dense search (no state filter — we want both open and closed)
        dense = self._search_dense_issues(query_text, top_k=100)
        fts = self._search_fts_issues(query_text, top_k=100)
        candidates = self._reciprocal_rank_fusion(dense, fts)

        # Apply heuristic boosts
        for candidate in candidates:
            score = candidate.get("rrf_score", 0)

            # Boost closed issues (likely resolved)
            if candidate.get("state") == "closed":
                # Check if has merged closing PR
                issue_num = candidate.get("issue_number")
                repo = candidate.get("repo")
                if issue_num and repo:
                    refs = self.check_closing_refs(issue_num, repo)
                    if any(r.get("pr_merged") for r in refs):
                        score *= triage_config.boost_closed_with_merged_pr

            # Title word overlap boost
            candidate_title = candidate.get("title", "")
            overlap = _title_word_overlap(issue_title, candidate_title)
            if overlap > 0.3:
                score *= triage_config.boost_title_overlap

            candidate["rrf_score"] = score

        # Re-sort after boosts
        candidates.sort(key=lambda x: -x.get("rrf_score", 0))
        return candidates[:top_k]

    def find_related_reviews(
        self,
        issue_text: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Search vec_reviews for review comments related to the issue."""
        from rag.retriever import ReviewRetriever
        review_retriever = ReviewRetriever()
        return review_retriever.search_hybrid(
            issue_text, top_k_initial=50, top_k_final=top_k,
        )

    def check_closing_refs(
        self,
        issue_number: int,
        repo: str = "micropython/micropython",
    ) -> List[Dict[str, Any]]:
        """Query issue_closing_refs for PRs that reference this issue."""
        try:
            cursor = self.conn.execute(
                "SELECT issue_number, issue_repo, pr_number, pr_repo, pr_merged "
                "FROM issue_closing_refs "
                "WHERE issue_number = ? AND issue_repo = ?",
                (issue_number, repo),
            )
            return [
                {
                    "issue_number": row[0],
                    "issue_repo": row[1],
                    "pr_number": row[2],
                    "pr_repo": row[3],
                    "pr_merged": bool(row[4]),
                }
                for row in cursor
            ]
        except sqlite3.OperationalError:
            # Table may not exist yet
            return []

    def get_issue(
        self,
        issue_number: int,
        repo: str = "micropython/micropython",
    ) -> Optional[Dict[str, Any]]:
        """Fetch an issue from the issues table."""
        try:
            cursor = self.conn.execute(
                "SELECT * FROM issues WHERE number = ? AND repo = ?",
                (issue_number, repo),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return dict(row)
        except sqlite3.OperationalError:
            return None

    # --- Internal search methods ---

    def _search_dense_issues(
        self,
        query: str,
        top_k: int = 100,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        query_embedding = self.embedder.embed_single(query, is_query=True)
        query_bytes = query_embedding.astype(np.float32).tobytes()

        where_clauses = ["embedding MATCH ?", "k = ?"]
        params: list = [query_bytes, top_k]

        if filter_dict:
            for key, value in filter_dict.items():
                if key not in _ISSUE_FILTER_KEYS:
                    logger.warning("Ignoring unknown filter key: %s", key)
                    continue
                if not _SAFE_VALUE_RE.match(str(value)):
                    logger.warning("Ignoring unsafe filter value for %s: %r", key, value)
                    continue
                where_clauses.append(f"{key} = ?")
                params.append(str(value))

        col_list = ", ".join(_ALL_ISSUE_COLS)
        where = " AND ".join(where_clauses)
        sql = f"SELECT rowid, distance, {col_list} FROM vec_issues WHERE {where}"

        try:
            cursor = self.conn.execute(sql, params)
        except sqlite3.OperationalError as e:
            logger.warning("vec_issues query failed: %s", e)
            return []

        results = []
        for i, row in enumerate(cursor):
            d = issue_row_to_dict(row)
            d["rank"] = i + 1
            d["search_type"] = "dense"
            results.append(d)
        return results

    def _search_fts_issues(
        self,
        query: str,
        top_k: int = 100,
    ) -> List[Dict[str, Any]]:
        sanitized = _sanitize_fts_query(query)

        try:
            fts_sql = "SELECT rowid, rank FROM issue_fts WHERE issue_fts MATCH ? ORDER BY rank LIMIT ?"
            fts_rows = self.conn.execute(fts_sql, [sanitized, top_k]).fetchall()
        except sqlite3.OperationalError as e:
            logger.warning("issue_fts query failed: %s", e)
            return []

        if not fts_rows:
            return []

        rowids = [r[0] for r in fts_rows]
        rank_map = {r[0]: r[1] for r in fts_rows}

        col_list = ", ".join(_ALL_ISSUE_COLS)
        placeholders = ", ".join(["?"] * len(rowids))
        vec_sql = f"SELECT rowid, {col_list} FROM vec_issues WHERE rowid IN ({placeholders})"

        try:
            vec_rows = self.conn.execute(vec_sql, rowids).fetchall()
        except sqlite3.OperationalError as e:
            logger.warning("vec_issues rowid lookup failed: %s", e)
            return []

        row_map = {}
        for row in vec_rows:
            d = issue_row_to_dict(row)
            d["fts_rank"] = rank_map.get(row["rowid"], 0)
            row_map[row["rowid"]] = d

        results = []
        for i, rowid in enumerate(rowids):
            if rowid in row_map:
                d = row_map[rowid]
                d["rank"] = i + 1
                d["search_type"] = "fts"
                results.append(d)
        return results

    def _reciprocal_rank_fusion(
        self,
        dense_results: List[Dict[str, Any]],
        fts_results: List[Dict[str, Any]],
        k: int = 60,
    ) -> List[Dict[str, Any]]:
        """Combine dense and FTS results using RRF."""
        scores: Dict[Tuple, float] = {}
        records: Dict[Tuple, Dict[str, Any]] = {}

        for results in [dense_results, fts_results]:
            for result in results:
                key = (result.get("issue_number"), result.get("repo"))
                rank = result["rank"]
                if key not in scores:
                    scores[key] = 0.0
                    records[key] = result
                scores[key] += 1.0 / (k + rank)

        sorted_keys = sorted(scores.keys(), key=lambda x: -scores[x])
        fused = []
        for i, key in enumerate(sorted_keys):
            record = records[key].copy()
            record["rrf_score"] = scores[key]
            record["rank"] = i + 1
            record["search_type"] = "hybrid"
            fused.append(record)
        return fused


# Global instance
_issue_retriever: Optional[IssueRetriever] = None


def get_issue_retriever() -> IssueRetriever:
    global _issue_retriever
    if _issue_retriever is None:
        _issue_retriever = IssueRetriever()
    return _issue_retriever
