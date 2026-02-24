"""Evaluation framework for MicroPython review RAG system."""

import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass, asdict
from collections import defaultdict
import sqlite3

logger = logging.getLogger(__name__)


@dataclass
class EvaluationSample:
    """Single evaluation sample."""

    pr_number: int
    pr_title: str
    diff_text: str
    actual_reviews: List[Dict[str, Any]]
    domain: Optional[str] = None
    severity: Optional[str] = None
    language_context: Optional[str] = None


@dataclass
class RetrievalMetrics:
    """Metrics for retrieval quality."""

    mean_reciprocal_rank: float = 0.0  # MRR
    ndcg_at_k: Dict[int, float] = None  # NDCG@5, @10, etc.
    recall_at_k: Dict[int, float] = None  # Recall@5, @10, etc.
    precision_at_k: Dict[int, float] = None  # Precision@5, @10, etc.
    map_score: float = 0.0  # Mean Average Precision

    def __post_init__(self):
        """Initialize default dictionaries."""
        if self.ndcg_at_k is None:
            self.ndcg_at_k = {}
        if self.recall_at_k is None:
            self.recall_at_k = {}
        if self.precision_at_k is None:
            self.precision_at_k = {}


class DatasetBuilder:
    """Build evaluation datasets from the database."""

    def __init__(self, db_path: str):
        """Initialize dataset builder.

        Args:
            db_path: Path to SQLite database
        """
        self.db_path = db_path

    def build_dataset(
        self,
        sample_size: int = 100,
        stratify_by: Optional[str] = None,
        output_path: Optional[Path] = None,
        repo: str = "micropython/micropython",
    ) -> List[EvaluationSample]:
        """Build evaluation dataset by sampling PRs.

        Args:
            sample_size: Number of samples to generate
            stratify_by: Field to stratify by ("domain", "severity", "component")
            output_path: Optional path to save dataset as JSON
            repo: GitHub repository slug

        Returns:
            List of evaluation samples
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        samples = []

        try:
            # Get diverse PRs
            if stratify_by:
                samples = self._sample_stratified(cursor, sample_size, stratify_by, repo=repo)
            else:
                samples = self._sample_random(cursor, sample_size, repo=repo)

            logger.info(f"Created evaluation dataset with {len(samples)} samples")

            # Save if path provided
            if output_path:
                self._save_dataset(samples, output_path)

            return samples
        finally:
            conn.close()

    def _sample_random(
        self, cursor, sample_size: int, repo: str = "micropython/micropython",
    ) -> List[EvaluationSample]:
        """Sample random PRs from database.

        Args:
            cursor: Database cursor
            sample_size: Number of samples
            repo: GitHub repository slug

        Returns:
            List of evaluation samples
        """
        samples = []

        # Get random PRs with reviews
        cursor.execute("""
            SELECT DISTINCT pr_number
            FROM review_comments
            WHERE repo = ?
            UNION
            SELECT DISTINCT pr_number
            FROM issue_comments
            WHERE repo = ?
            ORDER BY RANDOM()
            LIMIT ?
        """, (repo, repo, sample_size))

        pr_numbers = [row[0] for row in cursor.fetchall()]

        for pr_number in pr_numbers:
            sample = self._get_sample_for_pr(cursor, pr_number, repo=repo)
            if sample:
                samples.append(sample)

        return samples

    def _sample_stratified(
        self,
        cursor,
        sample_size: int,
        stratify_by: str,
        repo: str = "micropython/micropython",
    ) -> List[EvaluationSample]:
        """Sample PRs stratified by a field.

        Args:
            cursor: Database cursor
            sample_size: Number of samples
            stratify_by: Field to stratify by
            repo: GitHub repository slug

        Returns:
            List of evaluation samples
        """
        samples = []

        # Get distinct values for stratification
        cursor.execute(f"""
            SELECT DISTINCT {stratify_by}
            FROM comment_categories
            WHERE {stratify_by} IS NOT NULL
        """)

        values = [row[0] for row in cursor.fetchall()]
        samples_per_value = sample_size // len(values)

        for value in values:
            cursor.execute(f"""
                SELECT DISTINCT rc.pr_number
                FROM comment_categories cc
                JOIN review_comments rc ON cc.comment_id = rc.id AND cc.comment_type = 'review_comment'
                WHERE cc.{stratify_by} = ? AND rc.repo = ?
                ORDER BY RANDOM()
                LIMIT ?
            """, (value, repo, samples_per_value))

            pr_numbers = [row[0] for row in cursor.fetchall()]

            for pr_number in pr_numbers:
                sample = self._get_sample_for_pr(cursor, pr_number, repo=repo)
                if sample:
                    samples.append(sample)

        return samples

    def _get_sample_for_pr(
        self, cursor, pr_number: int, repo: str = "micropython/micropython",
    ) -> Optional[EvaluationSample]:
        """Get a complete sample for a PR.

        Args:
            cursor: Database cursor
            pr_number: PR number
            repo: GitHub repository slug

        Returns:
            EvaluationSample or None
        """
        # Get PR title
        cursor.execute("""
            SELECT body FROM reviews
            WHERE pr_number = ? AND repo = ? AND body IS NOT NULL
            LIMIT 1
        """, (pr_number, repo))

        review = cursor.fetchone()
        pr_title = review[0][:100] if review else f"PR #{pr_number}"

        # Get actual reviews (for evaluation)
        cursor.execute("""
            SELECT rc.id, rc.body, d.name, cc.severity
            FROM review_comments rc
            LEFT JOIN comment_categories cc ON rc.id = cc.comment_id AND cc.comment_type = 'review_comment'
            LEFT JOIN domains d ON cc.domain_id = d.id
            WHERE rc.pr_number = ? AND rc.repo = ?
            UNION
            SELECT ic.id, ic.body, d.name, cc.severity
            FROM issue_comments ic
            LEFT JOIN comment_categories cc ON ic.id = cc.comment_id AND cc.comment_type = 'issue_comment'
            LEFT JOIN domains d ON cc.domain_id = d.id
            WHERE ic.pr_number = ? AND ic.repo = ?
            LIMIT 10
        """, (pr_number, repo, pr_number, repo))

        reviews = [
            {
                "comment_id": row[0],
                "body": row[1],
                "domain": row[2],
                "severity": row[3],
            }
            for row in cursor.fetchall()
        ]

        if not reviews:
            return None

        # Get a review comment with diff (for the "query")
        cursor.execute("""
            SELECT diff_hunk FROM review_comments
            WHERE pr_number = ? AND repo = ? AND diff_hunk IS NOT NULL
            LIMIT 1
        """, (pr_number, repo))

        diff_row = cursor.fetchone()
        diff_text = diff_row[0] if diff_row else f"# PR #{pr_number}"

        return EvaluationSample(
            pr_number=pr_number,
            pr_title=pr_title,
            diff_text=diff_text,
            actual_reviews=reviews,
            domain=reviews[0].get("domain") if reviews else None,
            severity=reviews[0].get("severity") if reviews else None,
        )

    def _save_dataset(
        self,
        samples: List[EvaluationSample],
        output_path: Path,
    ) -> None:
        """Save dataset to JSON file.

        Args:
            samples: Evaluation samples
            output_path: Output file path
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        data = [
            {
                **asdict(s),
                "actual_reviews": s.actual_reviews,
            }
            for s in samples
        ]

        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)

        logger.info(f"Saved dataset to {output_path}")


class RetrievalEvaluator:
    """Evaluate retrieval quality."""

    def __init__(self):
        """Initialize retrieval evaluator."""
        pass

    def evaluate_sample(
        self,
        retrieved: List[Dict[str, Any]],
        relevant: List[Dict[str, Any]],
        k_values: List[int] = None,
    ) -> RetrievalMetrics:
        """Evaluate retrieval for a single sample.

        Args:
            retrieved: Retrieved results (ranked)
            relevant: Relevant/actual results
            k_values: K values for metrics (default: [5, 10])

        Returns:
            RetrievalMetrics
        """
        if k_values is None:
            k_values = [5, 10]

        relevant_ids = self._get_ids(relevant)
        retrieved_ids = self._get_ids(retrieved)

        metrics = RetrievalMetrics()

        # Mean Reciprocal Rank
        metrics.mean_reciprocal_rank = self._mrr(retrieved_ids, relevant_ids)

        # NDCG@k
        for k in k_values:
            metrics.ndcg_at_k[k] = self._ndcg_at_k(retrieved_ids, relevant_ids, k)

        # Recall@k
        for k in k_values:
            metrics.recall_at_k[k] = self._recall_at_k(retrieved_ids, relevant_ids, k)

        # Precision@k
        for k in k_values:
            metrics.precision_at_k[k] = self._precision_at_k(retrieved_ids, relevant_ids, k)

        # MAP
        metrics.map_score = self._map(retrieved_ids, relevant_ids)

        return metrics

    def _get_ids(self, results: List[Dict[str, Any]]) -> List[str]:
        """Extract IDs from results."""
        ids = []
        for r in results:
            if "comment_id" in r:
                ids.append(f"c_{r['comment_id']}")
            elif "id" in r:
                ids.append(f"i_{r['id']}")
            else:
                # Use body hash as fallback
                import hashlib
                body = r.get("body", "")
                ids.append(hashlib.md5(body.encode()).hexdigest()[:8])
        return ids

    def _mrr(self, retrieved: List[str], relevant: Set[str]) -> float:
        """Calculate Mean Reciprocal Rank."""
        for i, item_id in enumerate(retrieved):
            if item_id in relevant:
                return 1.0 / (i + 1)
        return 0.0

    def _ndcg_at_k(self, retrieved: List[str], relevant: Set[str], k: int) -> float:
        """Calculate NDCG@k (Normalized Discounted Cumulative Gain)."""
        dcg = 0.0
        for i in range(min(k, len(retrieved))):
            if retrieved[i] in relevant:
                dcg += 1.0 / (i + 1)

        # Ideal DCG (all relevant items at top)
        idcg = 0.0
        for i in range(min(k, len(relevant))):
            idcg += 1.0 / (i + 1)

        if idcg == 0:
            return 0.0

        return dcg / idcg

    def _recall_at_k(self, retrieved: List[str], relevant: Set[str], k: int) -> float:
        """Calculate Recall@k."""
        if not relevant:
            return 0.0

        hits = len(set(retrieved[:k]) & relevant)
        return hits / len(relevant)

    def _precision_at_k(self, retrieved: List[str], relevant: Set[str], k: int) -> float:
        """Calculate Precision@k."""
        if k == 0:
            return 0.0

        hits = len(set(retrieved[:k]) & relevant)
        return hits / k

    def _map(self, retrieved: List[str], relevant: Set[str]) -> float:
        """Calculate Mean Average Precision."""
        if not relevant:
            return 0.0

        ap = 0.0
        hits = 0

        for i, item_id in enumerate(retrieved):
            if item_id in relevant:
                hits += 1
                ap += hits / (i + 1)

        return ap / len(relevant)


class EvaluationPipeline:
    """End-to-end evaluation pipeline."""

    def __init__(self, db_path: str):
        """Initialize evaluation pipeline.

        Args:
            db_path: Path to SQLite database
        """
        self.db_path = db_path
        self.dataset_builder = DatasetBuilder(db_path)
        self.retrieval_evaluator = RetrievalEvaluator()

    def run_evaluation(
        self,
        retriever,
        sample_size: int = 50,
        output_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Run full evaluation pipeline.

        Args:
            retriever: ReviewRetriever instance to evaluate
            sample_size: Number of samples
            output_dir: Optional directory to save results

        Returns:
            Evaluation results
        """
        # Build dataset
        dataset = self.dataset_builder.build_dataset(
            sample_size=sample_size,
            output_path=Path(output_dir) / "eval_dataset.json" if output_dir else None,
        )

        # Evaluate each sample
        all_metrics = []
        for sample in dataset:
            # Retrieve results for this sample
            retrieved = retriever.get_similar_reviews(sample.diff_text, top_k=10)

            # Evaluate
            metrics = self.retrieval_evaluator.evaluate_sample(
                retrieved=retrieved,
                relevant=sample.actual_reviews,
            )

            all_metrics.append({
                "pr_number": sample.pr_number,
                "metrics": asdict(metrics),
            })

        # Aggregate metrics
        summary = self._aggregate_metrics(all_metrics)

        if output_dir:
            self._save_results(all_metrics, summary, output_dir)

        return {
            "summary": summary,
            "per_sample": all_metrics,
        }

    def _aggregate_metrics(self, all_metrics: List[Dict[str, Any]]) -> Dict[str, float]:
        """Aggregate metrics across samples."""
        summary = defaultdict(list)

        for item in all_metrics:
            metrics = item["metrics"]
            summary["mrr"].append(metrics["mean_reciprocal_rank"])
            summary["map"].append(metrics["map_score"])

            for k, score in metrics.get("ndcg_at_k", {}).items():
                summary[f"ndcg@{k}"].append(score)

            for k, score in metrics.get("recall_at_k", {}).items():
                summary[f"recall@{k}"].append(score)

            for k, score in metrics.get("precision_at_k", {}).items():
                summary[f"precision@{k}"].append(score)

        # Average each metric
        return {
            key: sum(values) / len(values) if values else 0.0
            for key, values in summary.items()
        }

    def _save_results(
        self,
        per_sample: List[Dict[str, Any]],
        summary: Dict[str, float],
        output_dir: Path,
    ) -> None:
        """Save evaluation results."""
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save summary
        with open(output_dir / "summary.json", "w") as f:
            json.dump(summary, f, indent=2)

        # Save per-sample results
        with open(output_dir / "per_sample.json", "w") as f:
            json.dump(per_sample, f, indent=2)

        logger.info(f"Saved evaluation results to {output_dir}")
