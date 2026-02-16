"""Cross-encoder re-ranking for review retrieval."""

from typing import List, Dict, Any, Optional
import logging

try:
    from sentence_transformers import CrossEncoder
except ImportError:
    raise ImportError(
        "sentence_transformers is required for re-ranking. "
        "Install with: pip install sentence-transformers"
    )

import torch

from .config import get_config

logger = logging.getLogger(__name__)


class ReviewReranker:
    """Cross-encoder re-ranker for review comments."""

    def __init__(self, model_name: Optional[str] = None):
        """Initialize the reranker with a cross-encoder model.

        Args:
            model_name: Model to use (default: BAAI/bge-reranker-large)
        """
        config = get_config()
        self.model_name = model_name or config.reranker_model
        self._model = None
        self._device = None

    @property
    def model(self) -> CrossEncoder:
        """Get the cross-encoder model, lazy loaded."""
        if self._model is None:
            logger.info(f"Loading cross-encoder model: {self.model_name}")
            self._model = CrossEncoder(self.model_name)
            # Move to GPU if available
            if torch.cuda.is_available():
                self._model = self._model.to("cuda")
                logger.info("Cross-encoder model loaded on GPU")
            else:
                logger.info("Cross-encoder model loaded on CPU")
        return self._model

    @property
    def device(self) -> str:
        """Get the device being used."""
        if self._device is None:
            self._device = "cuda" if torch.cuda.is_available() else "cpu"
        return self._device

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: Optional[int] = None,
        batch_size: int = 32,
    ) -> List[Dict[str, Any]]:
        """Re-rank candidates using cross-encoder scoring.

        Args:
            query: Query text (code diff or search query)
            candidates: List of candidate documents with "body" field
            top_k: Return top-k results (if None, return all)
            batch_size: Batch size for scoring

        Returns:
            Re-ranked list of candidates with rerank_score
        """
        if not candidates:
            return []

        # Prepare pairs: (query, candidate_text)
        pairs = []
        for candidate in candidates:
            # Use body for main content, with optional context
            context = candidate.get("body", "")
            if candidate.get("diff_hunk"):
                # Include code context for better scoring
                context = f"Code:\n{candidate['diff_hunk']}\n\nComment:\n{context}"
            pairs.append([query, context])

        # Score all pairs in batches
        logger.debug(f"Re-ranking {len(pairs)} candidates with cross-encoder")
        scores = self.model.predict(pairs, batch_size=batch_size, convert_to_numpy=True)

        # Attach scores to candidates
        for candidate, score in zip(candidates, scores):
            candidate["rerank_score"] = float(score)

        # Sort by rerank score
        reranked = sorted(candidates, key=lambda x: -x["rerank_score"])

        # Return top-k if specified
        if top_k is not None:
            reranked = reranked[:top_k]

        # Add rank
        for i, candidate in enumerate(reranked):
            candidate["rerank_rank"] = i + 1

        return reranked

    def score_pairs(
        self,
        pairs: List[tuple[str, str]],
        batch_size: int = 32,
    ) -> List[float]:
        """Score query-candidate pairs directly.

        Args:
            pairs: List of (query, candidate_text) tuples
            batch_size: Batch size for scoring

        Returns:
            List of scores (one per pair)
        """
        if not pairs:
            return []

        scores = self.model.predict(pairs, batch_size=batch_size, convert_to_numpy=True)
        return [float(s) for s in scores]

    def filter_by_threshold(
        self,
        candidates: List[Dict[str, Any]],
        threshold: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """Filter candidates by rerank score threshold.

        Args:
            candidates: Candidates with rerank_score field
            threshold: Minimum score to keep

        Returns:
            Filtered candidates
        """
        return [c for c in candidates if c.get("rerank_score", -1) >= threshold]


# Global reranker instance
_reranker: Optional[ReviewReranker] = None


def get_reranker() -> ReviewReranker:
    """Get the global reranker instance."""
    global _reranker
    if _reranker is None:
        _reranker = ReviewReranker()
    return _reranker


def rerank_results(
    query: str,
    candidates: List[Dict[str, Any]],
    top_k: int = 10,
    threshold: float = 0.0,
) -> List[Dict[str, Any]]:
    """Convenience function for re-ranking results.

    Args:
        query: Query text
        candidates: Candidate results with "body" field
        top_k: Return top-k results
        threshold: Minimum score threshold

    Returns:
        Re-ranked results
    """
    reranker = get_reranker()
    reranked = reranker.rerank(query, candidates, top_k=top_k)
    if threshold > 0.0:
        reranked = reranker.filter_by_threshold(reranked, threshold)
    return reranked
