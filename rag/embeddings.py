"""Embedding generation using Jina Embeddings v2 Base Code."""

from typing import List, Optional
import logging

import torch
import numpy as np
from tqdm import tqdm

from .config import get_config

logger = logging.getLogger(__name__)


class JinaEmbedder:
    """Jina Embeddings v2 Base Code embedder with batching support."""

    def __init__(
        self,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        max_seq_length: Optional[int] = None,
    ):
        """Initialize the embedder.

        Args:
            model_name: HuggingFace model name (default: jinaai/jina-embeddings-v2-base-code)
            device: Device to use (cuda/cpu, auto-detected if None)
            max_seq_length: Maximum sequence length (default: 8192)
        """
        config = get_config()
        self.model_name = model_name or config.embedding_model
        self.device = device or config.device
        self.max_seq_length = max_seq_length or config.max_seq_length

        self._model = None
        self._tokenizer = None

    def _load_model(self):
        """Lazy load the model and tokenizer."""
        if self._model is not None:
            return

        from transformers import AutoModel, AutoTokenizer

        logger.info(f"Loading embedding model: {self.model_name}")
        logger.info(f"Using device: {self.device}")

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self._model = AutoModel.from_pretrained(
            self.model_name, trust_remote_code=True
        )
        self._model = self._model.to(self.device)
        self._model.eval()

        logger.info("Model loaded successfully")

    @property
    def model(self):
        """Get the model, loading if necessary."""
        self._load_model()
        return self._model

    @property
    def tokenizer(self):
        """Get the tokenizer, loading if necessary."""
        self._load_model()
        return self._tokenizer

    def embed_single(self, text: str) -> np.ndarray:
        """Embed a single text string.

        Args:
            text: Text to embed

        Returns:
            Embedding vector as numpy array (768 dimensions)
        """
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: List[str], show_progress: bool = False) -> np.ndarray:
        """Embed a batch of texts.

        Args:
            texts: List of texts to embed
            show_progress: Whether to show progress bar

        Returns:
            Array of embeddings with shape (len(texts), 768)
        """
        config = get_config()
        batch_size = config.embedding_batch_size

        all_embeddings = []

        iterator = range(0, len(texts), batch_size)
        if show_progress:
            iterator = tqdm(iterator, desc="Embedding", unit="batch")

        for i in iterator:
            batch_texts = texts[i : i + batch_size]
            embeddings = self._embed_batch_internal(batch_texts)
            all_embeddings.append(embeddings)

        return np.vstack(all_embeddings)

    def _embed_batch_internal(self, texts: List[str]) -> np.ndarray:
        """Internal batch embedding without progress tracking.

        Uses mean pooling over token embeddings.
        """
        # Tokenize
        inputs = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=self.max_seq_length,
            return_tensors="pt",
        )

        # Move to device
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        # Get embeddings
        with torch.no_grad():
            outputs = self.model(**inputs)

        # Mean pooling - average of all token embeddings (excluding padding)
        attention_mask = inputs["attention_mask"]
        token_embeddings = outputs.last_hidden_state

        # Expand attention mask to match embedding dimensions
        input_mask_expanded = (
            attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
        )

        # Sum embeddings and divide by number of tokens
        sum_embeddings = torch.sum(token_embeddings * input_mask_expanded, dim=1)
        sum_mask = torch.clamp(input_mask_expanded.sum(dim=1), min=1e-9)
        embeddings = sum_embeddings / sum_mask

        # Normalize embeddings (L2 normalization)
        embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)

        return embeddings.cpu().numpy()

    def embed_with_context(
        self, comment_body: str, diff_hunk: Optional[str] = None
    ) -> np.ndarray:
        """Embed a comment with optional code context.

        Args:
            comment_body: The review comment text
            diff_hunk: Optional code diff context

        Returns:
            Embedding vector
        """
        if diff_hunk:
            text = f"{comment_body}\n\nCode context:\n{diff_hunk}"
        else:
            text = comment_body

        return self.embed_single(text)


# Global embedder instance (lazy loaded)
_embedder: Optional[JinaEmbedder] = None


def get_embedder() -> JinaEmbedder:
    """Get the global embedder instance."""
    global _embedder
    if _embedder is None:
        _embedder = JinaEmbedder()
    return _embedder


def embed_texts(texts: List[str], show_progress: bool = False) -> np.ndarray:
    """Convenience function to embed texts using the global embedder.

    Args:
        texts: List of texts to embed
        show_progress: Whether to show progress bar

    Returns:
        Array of embeddings
    """
    return get_embedder().embed_batch(texts, show_progress=show_progress)


def embed_text(text: str) -> np.ndarray:
    """Convenience function to embed a single text.

    Args:
        text: Text to embed

    Returns:
        Embedding vector
    """
    return get_embedder().embed_single(text)
