"""Configuration management for mpy-reviewer."""

from pathlib import Path
from dataclasses import dataclass, field
import os


def _detect_micropython_repo() -> Path | None:
    """Walk up from CWD looking for a MicroPython checkout.

    Identifies a MicroPython repo by the presence of py/runtime.c,
    which is unique to MicroPython checkouts.
    """
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
