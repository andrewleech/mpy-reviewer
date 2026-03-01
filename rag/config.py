"""Configuration management for mpy-reviewer."""

from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
import os


def _detect_micropython_repo() -> Path | None:
    """Find a MicroPython checkout.

    Checks MPY_CHECKOUT env var first, then walks up from CWD.
    Identifies a MicroPython repo by the presence of py/runtime.c.
    """
    env_path = os.environ.get("MPY_CHECKOUT")
    if env_path:
        p = Path(env_path)
        if (p / "py" / "runtime.c").is_file():
            return p

    try:
        cwd = Path.cwd().resolve()
    except OSError:
        return None
    for d in [cwd, *cwd.parents]:
        if (d / "py" / "runtime.c").is_file():
            return d
    return None


@dataclass
class Config:
    """Configuration for the RAG system."""

    # Paths
    project_root: Path = field(default_factory=lambda: Path(__file__).parent.parent)
    sqlite_db_path: Path = field(default=None)
    micropython_repo_path: Path = field(default=None)

    # Embedding model
    embedding_model: str = "nomic-ai/CodeRankEmbed"
    embedding_dim: int = 768
    max_seq_length: int = 8192
    embedding_query_prefix: str = "Represent this query for searching relevant code: "

    # Device
    device: str = field(default=None)

    # Retrieval settings
    top_k_initial: int = 100  # Initial retrieval count
    top_k_rerank: int = 30  # After metadata filtering
    top_k_final: int = 8  # Final examples to return

    # Re-ranker model
    reranker_model: str = "BAAI/bge-reranker-large"

    # Batch sizes
    embedding_batch_size: int = 32
    index_batch_size: int = 100

    def __post_init__(self):
        # Set default paths relative to project root
        if self.sqlite_db_path is None:
            self.sqlite_db_path = self.project_root / "data" / "reviews.db"
        if self.micropython_repo_path is None:
            self.micropython_repo_path = _detect_micropython_repo()

        # Auto-detect device
        if self.device is None:
            import torch
            self.device = "cuda" if torch.cuda.is_available() else "cpu"


# Global config instance
_config: Config | None = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def set_config(config: Config) -> None:
    """Set the global configuration instance."""
    global _config
    _config = config


@dataclass
class TriageConfig:
    """Confidence thresholds and settings for issue triage."""

    # Duplicate detection thresholds (output confidence values)
    duplicate_high_confidence: float = 0.85
    duplicate_medium_confidence: float = 0.60

    # RRF score thresholds for duplicate detection.
    # RRF with k=60 and 2 sources (dense+FTS) produces scores in the
    # 0.01-0.04 range. Near-exact duplicates score ~0.035-0.039 (with
    # heuristic boosts), closely related issues score ~0.028-0.035.
    similarity_high: float = 0.035
    similarity_medium: float = 0.025

    # Label confidence thresholds
    label_auto_apply: float = 0.85
    label_suggest: float = 0.60

    # Closing ref confidence (merged PR that references the issue)
    closing_ref_merged_confidence: float = 0.95

    # Retrieval settings
    top_k_similar_issues: int = 5
    top_k_related_reviews: int = 5

    # Heuristic boost factors
    boost_closed_with_merged_pr: float = 1.5
    boost_same_component: float = 1.3
    boost_title_overlap: float = 1.2


# Global triage config
_triage_config: Optional[TriageConfig] = None


def get_triage_config() -> TriageConfig:
    """Get the global triage configuration instance."""
    global _triage_config
    if _triage_config is None:
        _triage_config = TriageConfig()
    return _triage_config
