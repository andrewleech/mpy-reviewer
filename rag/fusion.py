"""Result fusion for combining review RAG and codebase RAG outputs."""

from typing import List, Dict, Any, Tuple
from collections import defaultdict
import logging

from .config import get_config

logger = logging.getLogger(__name__)


class ResultFusion:
    """Fuse results from multiple retrieval sources (review RAG, codebase RAG)."""

    def __init__(self):
        """Initialize the fusion engine."""
        self.config = get_config()

    def reciprocal_rank_fusion(
        self,
        ranking_lists: List[List[Dict[str, Any]]],
        k: int = 60,
        weights: List[float] = None,
    ) -> List[Dict[str, Any]]:
        """Combine multiple ranking lists using Reciprocal Rank Fusion.

        RRF formula: score = sum(weight * 1 / (k + rank))

        Args:
            ranking_lists: List of ranked result lists (each with 'comment_id' or 'id')
            k: RRF parameter (higher = more weight to lower ranks)
            weights: Optional weights for each ranking list (must sum to 1.0)

        Returns:
            Fused results sorted by RRF score
        """
        if not ranking_lists or all(len(l) == 0 for l in ranking_lists):
            return []

        # Default equal weights
        if weights is None:
            weights = [1.0 / len(ranking_lists)] * len(ranking_lists)

        assert len(weights) == len(ranking_lists), "Weights must match number of ranking lists"
        assert abs(sum(weights) - 1.0) < 0.01, "Weights must sum to 1.0"

        scores: Dict[str, float] = defaultdict(float)
        records: Dict[str, Dict[str, Any]] = {}

        # Accumulate RRF scores
        for ranking, weight in zip(ranking_lists, weights):
            for rank, result in enumerate(ranking):
                # Get unique ID for this result
                result_id = self._get_result_id(result)

                if result_id not in records:
                    records[result_id] = result.copy()

                # Add weighted RRF score
                rrf_component = weight / (k + rank)
                scores[result_id] += rrf_component

        # Sort by combined score
        sorted_ids = sorted(scores.keys(), key=lambda x: -scores[x])

        # Build final result list
        fused_results = []
        for i, result_id in enumerate(sorted_ids):
            result = records[result_id].copy()
            result["fusion_score"] = scores[result_id]
            result["fusion_rank"] = i + 1
            fused_results.append(result)

        return fused_results

    def weighted_combination(
        self,
        review_results: List[Dict[str, Any]],
        codebase_results: List[Dict[str, Any]],
        review_weight: float = 0.6,
        codebase_weight: float = 0.4,
    ) -> List[Dict[str, Any]]:
        """Combine results using weighted scoring.

        Weights reflect the importance of each source:
        - review_weight: Importance of review examples
        - codebase_weight: Importance of code context

        Args:
            review_results: Ranked review examples
            codebase_results: Ranked code context results
            review_weight: Weight for review results (0-1)
            codebase_weight: Weight for codebase results (0-1)

        Returns:
            Combined results sorted by weighted score
        """
        # Normalize weights
        total = review_weight + codebase_weight
        review_weight = review_weight / total
        codebase_weight = codebase_weight / total

        combined: Dict[str, Dict[str, Any]] = {}

        # Add review results
        for i, result in enumerate(review_results):
            result_id = self._get_result_id(result)
            combined[result_id] = result.copy()
            # Normalize rank-based score (inverse of rank)
            combined[result_id]["review_score"] = 1.0 / (1 + i)

        # Add codebase results (only if not already included)
        for i, result in enumerate(codebase_results):
            result_id = self._get_result_id(result)
            if result_id not in combined:
                combined[result_id] = result.copy()
            combined[result_id]["codebase_score"] = 1.0 / (1 + i)

        # Compute final weighted scores
        for result_id, result in combined.items():
            review_score = result.get("review_score", 0.0)
            codebase_score = result.get("codebase_score", 0.0)

            result["weighted_score"] = (
                review_weight * review_score +
                codebase_weight * codebase_score
            )

        # Sort by weighted score
        sorted_results = sorted(
            combined.values(),
            key=lambda x: -x["weighted_score"]
        )

        # Add rank
        for i, result in enumerate(sorted_results):
            result["fusion_rank"] = i + 1

        return sorted_results

    def hybrid_fusion(
        self,
        review_results: List[Dict[str, Any]],
        codebase_results: List[Dict[str, Any]],
        fusion_strategy: str = "rrf",
        review_weight: float = 0.6,
        codebase_weight: float = 0.4,
        rrf_k: int = 60,
    ) -> List[Dict[str, Any]]:
        """Apply hybrid fusion combining RRF and weighted strategies.

        Args:
            review_results: Ranked review examples
            codebase_results: Ranked code context results
            fusion_strategy: "rrf" or "weighted"
            review_weight: Weight for review source (if weighted)
            codebase_weight: Weight for codebase source (if weighted)
            rrf_k: RRF parameter

        Returns:
            Fused results
        """
        if fusion_strategy == "rrf":
            return self.reciprocal_rank_fusion(
                [review_results, codebase_results],
                k=rrf_k,
                weights=[review_weight / (review_weight + codebase_weight),
                         codebase_weight / (review_weight + codebase_weight)]
            )
        elif fusion_strategy == "weighted":
            return self.weighted_combination(
                review_results,
                codebase_results,
                review_weight=review_weight,
                codebase_weight=codebase_weight
            )
        else:
            raise ValueError(f"Unknown fusion strategy: {fusion_strategy}")

    def allocate_context_budget(
        self,
        fused_results: List[Dict[str, Any]],
        total_tokens: int = 15000,
        review_budget: int = 5000,
        codebase_budget: int = 5000,
        style_guide_budget: int = 1500,
    ) -> Dict[str, Any]:
        """Allocate context tokens across different result types.

        Args:
            fused_results: Fused results to allocate
            total_tokens: Total token budget
            review_budget: Tokens for review examples
            codebase_budget: Tokens for codebase context
            style_guide_budget: Tokens for style guide

        Returns:
            Dictionary mapping result_id to allocated tokens
        """
        allocation: Dict[str, int] = {}

        # Separate by type
        review_items = [r for r in fused_results if "comment_type" in r]
        codebase_items = [r for r in fused_results if "file" in r and "comment_type" not in r]

        # Allocate review tokens
        review_per_item = review_budget // max(1, len(review_items)) if review_items else 0
        for item in review_items:
            item_id = self._get_result_id(item)
            allocation[item_id] = min(review_per_item, 800)  # Max 800 per example

        # Allocate codebase tokens
        codebase_per_item = codebase_budget // max(1, len(codebase_items)) if codebase_items else 0
        for item in codebase_items:
            item_id = self._get_result_id(item)
            allocation[item_id] = min(codebase_per_item, 500)  # Max 500 per definition

        return allocation

    def diversify_results(
        self,
        results: List[Dict[str, Any]],
        top_k: int = 10,
        lambda_param: float = 0.7,
    ) -> List[Dict[str, Any]]:
        """Select diverse results balancing relevance and coverage.

        Uses Maximal Marginal Relevance (MMR) style selection.

        Args:
            results: Ranked results to diversify
            top_k: Number of results to select
            lambda_param: Balance between relevance (1.0) and diversity (0.0)

        Returns:
            Diverse subset of results
        """
        if len(results) <= top_k:
            return results

        selected = []
        remaining = results.copy()

        # Track attributes we've already covered
        seen_domains = set()
        seen_components = set()
        seen_files = set()
        seen_types = set()

        while len(selected) < top_k and remaining:
            best_score = -1.0
            best_idx = 0

            for i, candidate in enumerate(remaining):
                # Relevance score (normalized)
                relevance = candidate.get("fusion_score", 0.0)

                # Diversity bonus for new attributes
                diversity = 0.0

                # New domain
                domain = candidate.get("domain", candidate.get("type"))
                if domain and domain not in seen_domains:
                    diversity += 0.15

                # New component
                component = candidate.get("component", candidate.get("file"))
                if component and component not in seen_components:
                    diversity += 0.10

                # New file
                file_path = candidate.get("file")
                if file_path and file_path not in seen_files:
                    diversity += 0.10

                # New item type
                item_type = "review" if "comment_type" in candidate else "codebase"
                if item_type not in seen_types:
                    diversity += 0.15

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
            if selected[-1].get("component"):
                seen_components.add(selected[-1]["component"])
            if selected[-1].get("file"):
                seen_files.add(selected[-1]["file"])
            item_type = "review" if "comment_type" in selected[-1] else "codebase"
            seen_types.add(item_type)

        return selected

    def _get_result_id(self, result: Dict[str, Any]) -> str:
        """Get unique ID for a result."""
        # Try different ID fields
        if "comment_id" in result:
            return f"review_{result['comment_id']}"
        elif "id" in result:
            return f"codebase_{result['id']}"
        elif "file" in result and "line" in result:
            return f"codebase_{result['file']}_{result['line']}"
        else:
            # Fallback to hash of content
            import hashlib
            content = str(result.get("body", result.get("context", "")))
            return f"unknown_{hashlib.md5(content.encode()).hexdigest()[:8]}"


# Global fusion instance
_fusion: ResultFusion = None


def get_fusion() -> ResultFusion:
    """Get the global fusion instance."""
    global _fusion
    if _fusion is None:
        _fusion = ResultFusion()
    return _fusion


def fuse_results(
    review_results: List[Dict[str, Any]],
    codebase_results: List[Dict[str, Any]],
    strategy: str = "rrf",
    review_weight: float = 0.6,
    codebase_weight: float = 0.4,
) -> List[Dict[str, Any]]:
    """Convenience function to fuse review and codebase results.

    Args:
        review_results: Review RAG results
        codebase_results: Codebase RAG results
        strategy: Fusion strategy ("rrf" or "weighted")
        review_weight: Weight for review results
        codebase_weight: Weight for codebase results

    Returns:
        Fused results
    """
    fusion = get_fusion()
    return fusion.hybrid_fusion(
        review_results,
        codebase_results,
        fusion_strategy=strategy,
        review_weight=review_weight,
        codebase_weight=codebase_weight,
    )
