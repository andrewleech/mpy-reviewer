"""Multi-stage hybrid retrieval for dpgeorge reviews."""

from typing import List, Dict, Any, Optional
import logging

import numpy as np

from .config import get_config
from .embeddings import get_embedder
from .indexer import get_lance_table

logger = logging.getLogger(__name__)


class ReviewRetriever:
    """Hybrid retrieval combining dense and full-text search."""

    def __init__(self):
        """Initialize the retriever."""
        self._table = None
        self._embedder = None

    @property
    def table(self):
        """Get the LanceDB table, lazy loaded."""
        if self._table is None:
            self._table = get_lance_table()
        return self._table

    @property
    def embedder(self):
        """Get the embedder, lazy loaded."""
        if self._embedder is None:
            self._embedder = get_embedder()
        return self._embedder

    def search_dense(
        self,
        query: str,
        top_k: int = 100,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Search using dense embeddings only.

        Args:
            query: Query text
            top_k: Number of results to return
            filter_dict: Optional metadata filters

        Returns:
            List of matching records with scores
        """
        # Embed the query
        query_embedding = self.embedder.embed_single(query)

        # Build the search
        search = self.table.search(query_embedding).limit(top_k)

        # Apply filters if provided
        if filter_dict:
            for key, value in filter_dict.items():
                search = search.where(f"{key} = '{value}'")

        # Execute and return results
        results = search.to_list()

        # Add rank and normalize scores
        for i, result in enumerate(results):
            result["rank"] = i + 1
            result["search_type"] = "dense"

        return results

    def search_fts(
        self,
        query: str,
        top_k: int = 100,
    ) -> List[Dict[str, Any]]:
        """Search using full-text search only.

        Args:
            query: Query text
            top_k: Number of results to return

        Returns:
            List of matching records with scores
        """
        # Use FTS search
        results = self.table.search(query, query_type="fts").limit(top_k).to_list()

        # Add rank and search type
        for i, result in enumerate(results):
            result["rank"] = i + 1
            result["search_type"] = "fts"

        return results

    def search_hybrid(
        self,
        query: str,
        top_k_initial: int = 100,
        top_k_final: int = 20,
        filter_dict: Optional[Dict[str, Any]] = None,
        rrf_k: int = 60,
    ) -> List[Dict[str, Any]]:
        """Hybrid search combining dense and full-text search.

        Uses Reciprocal Rank Fusion (RRF) to combine results.

        Args:
            query: Query text
            top_k_initial: Number of results from each search type
            top_k_final: Final number of results to return
            filter_dict: Optional metadata filters
            rrf_k: RRF parameter (higher = more weight to lower ranks)

        Returns:
            List of fused results with RRF scores
        """
        # Get results from both search types
        dense_results = self.search_dense(query, top_k_initial, filter_dict)
        fts_results = self.search_fts(query, top_k_initial)

        # Apply RRF
        fused = self._reciprocal_rank_fusion(
            [dense_results, fts_results], k=rrf_k
        )

        # Return top_k_final
        return fused[:top_k_final]

    def _reciprocal_rank_fusion(
        self,
        result_lists: List[List[Dict[str, Any]]],
        k: int = 60,
    ) -> List[Dict[str, Any]]:
        """Combine multiple result lists using Reciprocal Rank Fusion.

        RRF score = sum(1 / (k + rank)) across all lists

        Args:
            result_lists: List of result lists, each with 'comment_id' and 'rank'
            k: RRF parameter

        Returns:
            Fused list sorted by RRF score
        """
        scores: Dict[int, float] = {}
        records: Dict[int, Dict[str, Any]] = {}

        for results in result_lists:
            for result in results:
                comment_id = result["comment_id"]
                rank = result["rank"]

                if comment_id not in scores:
                    scores[comment_id] = 0.0
                    records[comment_id] = result

                scores[comment_id] += 1.0 / (k + rank)

        # Sort by RRF score
        sorted_ids = sorted(scores.keys(), key=lambda x: -scores[x])

        # Build result list
        fused_results = []
        for i, comment_id in enumerate(sorted_ids):
            record = records[comment_id].copy()
            record["rrf_score"] = scores[comment_id]
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
        """Search with metadata filters.

        Args:
            query: Query text
            domain: Filter by domain (e.g., 'correctness', 'code_style')
            severity: Filter by severity ('blocking', 'suggestion', 'nitpick')
            component: Filter by component ('py_core', 'extmod', etc.)
            language_context: Filter by language ('c_code', 'python_code', etc.)
            is_style_example: Filter for style examples only
            top_k: Number of results to return

        Returns:
            Filtered results
        """
        config = get_config()

        # Build filter dict
        filters = {}
        if domain:
            filters["domain"] = domain
        if severity:
            filters["severity"] = severity
        if component:
            filters["component"] = component
        if language_context:
            filters["language_context"] = language_context

        # Get more initial results if filtering
        initial_k = config.top_k_initial if filters else top_k * 2

        # Hybrid search
        results = self.search_hybrid(
            query,
            top_k_initial=initial_k,
            top_k_final=initial_k,
            filter_dict=filters,
        )

        # Additional filtering for booleans
        if is_style_example is not None:
            results = [
                r for r in results
                if r.get("is_style_example") == is_style_example
            ]

        return results[:top_k]

    def get_similar_reviews(
        self,
        diff_text: str,
        top_k: int = 8,
        prefer_style_examples: bool = True,
    ) -> List[Dict[str, Any]]:
        """Find reviews similar to a code diff.

        This is the main entry point for finding relevant past reviews.

        Args:
            diff_text: Code diff to find similar reviews for
            top_k: Number of results to return
            prefer_style_examples: Boost style examples in ranking

        Returns:
            List of similar reviews
        """
        config = get_config()

        # Get initial results
        results = self.search_hybrid(
            diff_text,
            top_k_initial=config.top_k_initial,
            top_k_final=config.top_k_rerank,
        )

        # Boost style examples if requested
        if prefer_style_examples:
            for result in results:
                if result.get("is_style_example"):
                    result["rrf_score"] *= 1.2

            # Re-sort
            results.sort(key=lambda x: -x.get("rrf_score", 0))

        # Apply diversity selection (MMR-style)
        diverse_results = self._select_diverse(results, top_k)

        return diverse_results

    def _select_diverse(
        self,
        results: List[Dict[str, Any]],
        top_k: int,
        lambda_param: float = 0.7,
    ) -> List[Dict[str, Any]]:
        """Select diverse results using MMR-style selection.

        Tries to balance relevance with diversity across domains/severities.

        Args:
            results: Candidate results
            top_k: Number to select
            lambda_param: Balance between relevance and diversity

        Returns:
            Diverse subset of results
        """
        if len(results) <= top_k:
            return results

        selected = []
        remaining = results.copy()

        # Track which domains/severities we've seen
        seen_domains = set()
        seen_severities = set()

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

                # Combined score
                score = lambda_param * relevance + (1 - lambda_param) * diversity

                if score > best_score:
                    best_score = score
                    best_idx = i

            # Select best candidate
            selected.append(remaining.pop(best_idx))

            # Update seen sets
            if selected[-1].get("domain"):
                seen_domains.add(selected[-1]["domain"])
            if selected[-1].get("severity"):
                seen_severities.add(selected[-1]["severity"])

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
    """Convenience function for hybrid search.

    Args:
        query: Query text
        top_k: Number of results
        **kwargs: Additional filters (domain, severity, component, etc.)

    Returns:
        Search results
    """
    retriever = get_retriever()
    return retriever.search_with_filters(query, top_k=top_k, **kwargs)


def find_similar(diff_text: str, top_k: int = 8) -> List[Dict[str, Any]]:
    """Find reviews similar to a code diff.

    Args:
        diff_text: Code diff text
        top_k: Number of results

    Returns:
        Similar reviews
    """
    retriever = get_retriever()
    return retriever.get_similar_reviews(diff_text, top_k=top_k)
