"""
retrieval/embeddings.py — Wrapper for BAAI/bge-small-en-v1.5 embeddings.

The model is downloaded on first use (~130MB) and cached in the Hugging Face
cache directory. All subsequent calls use the cached model — no API key required.

The model runs entirely on CPU, so no GPU is required.
"""
from functools import lru_cache
from typing import List, Union

import numpy as np
from loguru import logger
from sentence_transformers import SentenceTransformer

from app.config import get_settings

settings = get_settings()


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    """
    Returns a cached SentenceTransformer instance.
    Downloaded on first call, cached for the lifetime of the process.
    """
    logger.info(f"Loading embedding model: {settings.embedding_model}")
    model = SentenceTransformer(settings.embedding_model)
    logger.info(f"✅ Embedding model loaded (dim={model.get_sentence_embedding_dimension()})")
    return model


def embed_texts(texts: List[str], batch_size: int = 32, normalize: bool = True) -> np.ndarray:
    """
    Encodes a list of texts into embedding vectors.

    Args:
        texts:      List of strings to embed.
        batch_size: Number of texts to process per batch (adjust based on RAM).
        normalize:  If True, L2-normalizes embeddings (required for cosine similarity
                    via dot product — avoids a separate normalize step at query time).

    Returns:
        numpy array of shape (len(texts), embedding_dim).
    """
    model = get_embedding_model()

    if not texts:
        return np.array([])

    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=normalize,
        show_progress_bar=len(texts) > 100,
    )

    return embeddings


def embed_query(query: str) -> np.ndarray:
    """
    Encodes a single query string.
    BGE models use a query prefix for better retrieval performance.
    """
    # BGE models benefit from a query prefix (as per their paper)
    prefixed = f"Represent this sentence for searching relevant passages: {query}"
    return embed_texts([prefixed])[0]


def embed_documents(documents: List[str]) -> np.ndarray:
    """
    Encodes document texts (no query prefix — BGE distinction).
    """
    return embed_texts(documents)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """
    Computes cosine similarity between two normalized embedding vectors.
    Since we normalize at encode time, this is just a dot product.
    """
    return float(np.dot(a, b))


def batch_cosine_similarity(query_emb: np.ndarray, doc_embs: np.ndarray) -> np.ndarray:
    """
    Computes cosine similarity between a query and a matrix of document embeddings.
    Returns a 1D array of similarity scores.
    """
    return doc_embs @ query_emb
