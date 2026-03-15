"""Embedding generation using CodeRankEmbed (nomic-ai/CodeRankEmbed).

CodeRankEmbed is a 137M bi-encoder trained on CoRNStack for code retrieval.
Queries require a task prefix; documents/code do not.
"""

from typing import List, Optional
import logging
import os

import numpy as np
from tqdm import tqdm

from .config import get_config

logger = logging.getLogger(__name__)


class CodeEmbedder:
    """CodeRankEmbed embedder with query/document distinction.

    Query embeddings use the task prefix required by the model.
    Document embeddings (for indexing) do not.
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        max_seq_length: Optional[int] = None,
    ):
        config = get_config()
        self.model_name = model_name or config.embedding_model
        self.device = device or config.device
        self.max_seq_length = max_seq_length or config.max_seq_length
        self.query_prefix = config.embedding_query_prefix

        self._model = None

    def _load_model(self):
        """Lazy load the SentenceTransformer model."""
        if self._model is not None:
            return

        from sentence_transformers import SentenceTransformer

        logger.info(f"Loading embedding model: {self.model_name}")
        logger.info(f"Using device: {self.device}")

        self._model = SentenceTransformer(
            self.model_name,
            trust_remote_code=True,
            device=self.device,
        )
        self._model.max_seq_length = self.max_seq_length

        if os.environ.get("MPY_REVIEWER_FP16", "").lower() in ("1", "true"):
            self._model = self._model.half()
            logger.info("Model converted to float16")

        logger.info("Model loaded successfully")

    @property
    def model(self):
        self._load_model()
        return self._model

    def embed_single(self, text: str, is_query: bool = True) -> np.ndarray:
        """Embed a single text string.

        Args:
            text: Text to embed.
            is_query: If True, prepend the query task prefix. Use True for
                      search queries, False for documents being indexed.

        Returns:
            Embedding vector as numpy array (768 dimensions).
        """
        # Truncate to ~max_seq_length tokens worth of characters.
        # SentenceTransformer tokenizes the full input before truncating,
        # so very long texts (e.g. full diffs) cause O(n) slowdowns on CPU
        # with no quality benefit beyond the model's token window.
        # Rough heuristic: 1 token ≈ 3 chars for code.
        char_limit = self.max_seq_length * 3
        if len(text) > char_limit:
            logger.info("Truncating embed input from %d to %d chars", len(text), char_limit)
            text = text[:char_limit]

        return self.embed_batch([text], is_query=is_query)[0]

    def embed_batch(
        self,
        texts: List[str],
        is_query: bool = True,
        show_progress: bool = False,
    ) -> np.ndarray:
        """Embed a batch of texts.

        Args:
            texts: List of texts to embed.
            is_query: If True, prepend query task prefix to each text.
            show_progress: Whether to show progress bar.

        Returns:
            Array of embeddings with shape (len(texts), 768).
        """
        config = get_config()
        batch_size = config.embedding_batch_size

        if is_query:
            texts = [self.query_prefix + t for t in texts]

        all_embeddings = []

        iterator = range(0, len(texts), batch_size)
        if show_progress:
            iterator = tqdm(iterator, desc="Embedding", unit="batch")

        for i in iterator:
            batch_texts = texts[i : i + batch_size]
            embeddings = self.model.encode(
                batch_texts,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            all_embeddings.append(np.asarray(embeddings))

        return np.vstack(all_embeddings)

    def embed_with_context(
        self,
        comment_body: str,
        diff_hunk: Optional[str] = None,
        is_query: bool = True,
    ) -> np.ndarray:
        """Embed a comment with optional code context.

        Args:
            comment_body: The review comment text.
            diff_hunk: Optional code diff context.
            is_query: Whether this is a query or document embedding.

        Returns:
            Embedding vector.
        """
        if diff_hunk:
            text = f"{comment_body}\n\nCode context:\n{diff_hunk}"
        else:
            text = comment_body

        return self.embed_single(text, is_query=is_query)


# Backwards-compatible alias
JinaEmbedder = CodeEmbedder

# Global embedder instance (lazy loaded)
_embedder: Optional[CodeEmbedder] = None


def get_embedder() -> CodeEmbedder:
    """Get the global embedder instance."""
    global _embedder
    if _embedder is None:
        _embedder = CodeEmbedder()
    return _embedder


def embed_texts(
    texts: List[str],
    show_progress: bool = False,
    is_query: bool = True,
) -> np.ndarray:
    """Convenience function to embed texts using the global embedder."""
    return get_embedder().embed_batch(texts, show_progress=show_progress, is_query=is_query)


def embed_text(text: str, is_query: bool = True) -> np.ndarray:
    """Convenience function to embed a single text."""
    return get_embedder().embed_single(text, is_query=is_query)
