"""
retrieval/reranker.py — Cross-encoder reranking using ms-marco-MiniLM.

The cross-encoder jointly encodes the query + each candidate passage
and outputs a relevance score. This is much more accurate than the
bi-encoder similarity used for initial retrieval, but slower — so we
only run it on the top candidates after RRF fusion (not the full corpus).

Model: cross-encoder/ms-marco-MiniLM-L-6-v2 (~85MB, local, no API)
"""
from functools import lru_cache
from typing import Dict, List

from loguru import logger
from sentence_transformers import CrossEncoder

from app.config import get_settings

settings = get_settings()


@lru_cache(maxsize=1)
def get_reranker() -> CrossEncoder:
    """Returns a cached CrossEncoder instance. Downloaded on first call."""
    logger.info(f"Loading reranker model: {settings.reranker_model}")
    model = CrossEncoder(settings.reranker_model, max_length=512)
    logger.info("✅ Reranker model loaded")
    return model


def rerank(
    query: str,
    candidates: List[Dict],
    top_n: int = 5,
    min_score: float = -10.0,
) -> List[Dict]:
    """
    Reranks a list of candidate chunks using the cross-encoder.

    Args:
        query:      The user's natural language query.
        candidates: List of chunk dicts (from hybrid retriever).
                    Each must have a "text" key.
        top_n:      Number of top results to return after reranking.
        min_score:  Minimum rerank score threshold. Candidates scoring below
                    this are excluded. ms-marco scores range ~-10 to +10;
                    relevant passages typically score above -5. Default -8.0
                    retains borderline results while filtering extreme noise.

    Returns:
        Sorted list of top_n candidate dicts with an added "rerank_score" field.
    """
    if not candidates:
        return []

    reranker = get_reranker()

    # Build (query, passage) pairs for the cross-encoder
    pairs = [(query, c["text"]) for c in candidates]

    # Score all pairs in one batch
    scores = reranker.predict(pairs, show_progress_bar=False)

    # Attach scores to candidates
    for candidate, score in zip(candidates, scores):
        candidate["rerank_score"] = float(score)

    # Sort by rerank score descending
    reranked = sorted(candidates, key=lambda x: x["rerank_score"], reverse=True)

    # Apply minimum score threshold — keep at least 1 result even if all are below threshold
    above_threshold = [r for r in reranked if r["rerank_score"] >= min_score]
    filtered = above_threshold if above_threshold else reranked[:1]

    logger.debug(
        f"Reranked {len(candidates)} candidates → top {top_n} "
        f"(best score: {reranked[0]['rerank_score']:.3f} for: "
        f"{reranked[0]['text'][:60]}…) "
        f"[{len(candidates) - len(above_threshold)} below threshold {min_score}]"
    )

    return filtered[:top_n]
