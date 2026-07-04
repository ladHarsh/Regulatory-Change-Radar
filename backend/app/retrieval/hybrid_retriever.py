"""
retrieval/hybrid_retriever.py — Reciprocal Rank Fusion (RRF) of dense + BM25 retrieval.

WHY RRF instead of score averaging:
  BM25 scores are unbounded integers; cosine similarity scores are in [-1, 1].
  Averaging them directly is meaningless because the scales are incompatible.
  RRF sidesteps this by using rank positions instead of raw scores.
  Each result gets a score of 1/(k + rank), summed across both retrievers.
  Results that rank high in BOTH retrievers float to the top.
  k=60 is the standard constant (from the original Cormack et al. 2009 paper).
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Union

from loguru import logger

from app.config import get_settings
from app.retrieval.vector_store import VectorStore
from app.retrieval.bm25_index import BM25Index
from app.retrieval.reranker import rerank

settings = get_settings()

# Thread pool for concurrent BM25 + dense retrieval calls
_RETRIEVAL_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="retrieval")

# RRF constant — controls how much weight is given to rank vs. raw score
# k=60 is the empirically validated default from the original paper
RRF_K = 60

# If BM25 chunk count is this many fewer than ChromaDB count, rebuild BM25
# A ratio of 0.8 means: rebuild if BM25 has < 80% of ChromaDB's chunks
_BM25_STALENESS_RATIO = 0.8


def reciprocal_rank_fusion(
    dense_results: List[Dict],
    bm25_results: List[Dict],
    k: int = RRF_K,
) -> List[Dict]:
    """
    Fuses dense (vector) and sparse (BM25) retrieval results using RRF.

    Algorithm:
      For each result in each list at rank r (1-indexed):
        rrf_score += 1 / (k + r)
      Sort all unique results by their total rrf_score descending.

    Args:
        dense_results: Results from ChromaDB similarity search (must have "chunk_id").
        bm25_results:  Results from BM25 index search (must have "chunk_id").
        k:             RRF constant (default 60).

    Returns:
        Merged and re-ranked list with "rrf_score" field added.
    """
    # Build a map: chunk_id → merged result dict + accumulated RRF score
    scores: Dict[str, float] = {}
    result_map: Dict[str, Dict] = {}

    for rank, result in enumerate(dense_results, start=1):
        cid = result["chunk_id"]
        rrf = 1.0 / (k + rank)
        scores[cid] = scores.get(cid, 0.0) + rrf
        if cid not in result_map:
            result_map[cid] = result.copy()

    for rank, result in enumerate(bm25_results, start=1):
        cid = result["chunk_id"]
        rrf = 1.0 / (k + rank)
        scores[cid] = scores.get(cid, 0.0) + rrf
        if cid not in result_map:
            result_map[cid] = result.copy()

    # Sort by RRF score descending
    sorted_ids = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)

    fused = []
    for i, cid in enumerate(sorted_ids):
        result = result_map[cid].copy()
        result["rrf_score"] = scores[cid]
        result["fused_rank"] = i + 1
        fused.append(result)

    logger.debug(
        f"RRF fusion: {len(dense_results)} dense + {len(bm25_results)} BM25 "
        f"→ {len(fused)} unique candidates"
    )

    return fused


class HybridRetriever:
    """
    Orchestrates the full 3-stage retrieval pipeline:
      1. Dense (ChromaDB vector search)
      2. Sparse (BM25 keyword search)
      3. RRF fusion
      4. Cross-encoder reranking

    Stale BM25 Detection:
      On construction, if BM25 chunk count is significantly lower than
      ChromaDB chunk count, the index is automatically rebuilt from the DB.
      This prevents silent retrieval failures when new documents are ingested
      but the BM25 cache is not updated.
    """

    def __init__(self):
        self._vector_store = VectorStore()
        self._bm25 = BM25Index()
        self._auto_rebuild_bm25_if_stale()

    def _auto_rebuild_bm25_if_stale(self) -> None:
        """
        Checks whether the BM25 index is stale relative to ChromaDB and
        rebuilds it if necessary.

        A stale index happens when:
          - Documents were ingested after the last BM25 rebuild
          - The BM25 cache file was deleted
          - A fresh install where BM25 was never built

        We compare chunk counts. If BM25 has < 80% of ChromaDB's chunks,
        we rebuild from scratch using a temporary DB session.
        """
        chroma_count = self._vector_store.count
        bm25_count = len(self._bm25._chunk_store)

        if chroma_count == 0:
            return  # Nothing indexed yet, nothing to rebuild

        # Determine if BM25 is materially behind ChromaDB
        is_empty = bm25_count == 0
        is_stale = (
            not is_empty
            and chroma_count > 0
            and (bm25_count / chroma_count) < _BM25_STALENESS_RATIO
        )

        if is_empty or is_stale:
            reason = "empty" if is_empty else f"stale ({bm25_count} chunks vs {chroma_count} in ChromaDB)"
            logger.warning(
                f"BM25 index is {reason} — auto-rebuilding from database..."
            )
            try:
                from app.db.session import SessionLocal
                db = SessionLocal()
                try:
                    self._bm25.rebuild(db)
                    logger.info(
                        f"✅ BM25 auto-rebuild complete: "
                        f"{len(self._bm25._chunk_store)} chunks indexed"
                    )
                finally:
                    db.close()
            except Exception as exc:
                logger.error(f"BM25 auto-rebuild failed: {exc}")
        else:
            logger.debug(
                f"BM25 index is fresh: {bm25_count} chunks "
                f"(ChromaDB has {chroma_count})"
            )

    async def search(
        self,
        query: str,
        top_k: int = None,
        regulator_filter: Optional[Union[str, List[str]]] = None,
        domain_keywords: Optional[List[str]] = None,
    ) -> List[Dict]:
        """
        Full hybrid search pipeline — BM25 and dense search run concurrently.

        Args:
            query:            Natural language query.
            top_k:            Number of final results (default from config).
            regulator_filter: Optional regulator or list of regulators to restrict
                              dense vector search.
            domain_keywords:  Optional domain-specific keyword hints for BM25.

        Returns:
            Reranked list of up to top_k chunk dicts.
        """
        if top_k is None:
            top_k = settings.rerank_top_n

        candidate_k = settings.retrieval_top_k

        # Build BM25 query with domain keyword hints
        bm25_query = query
        if domain_keywords:
            keyword_hint = " ".join(domain_keywords[:5])
            bm25_query = f"{query} {keyword_hint}"

        # --- Run BM25 + dense search concurrently ----------------------------
        loop = asyncio.get_event_loop()
        dense_task = loop.run_in_executor(
            _RETRIEVAL_EXECUTOR,
            lambda: self._vector_store.similarity_search(
                query=query, k=candidate_k, regulator_filter=regulator_filter
            ),
        )
        bm25_task = loop.run_in_executor(
            _RETRIEVAL_EXECUTOR,
            lambda: self._bm25.search(query=bm25_query, k=candidate_k),
        )
        dense_results, bm25_results = await asyncio.gather(dense_task, bm25_task)
        # ---------------------------------------------------------------------

        if not dense_results and not bm25_results:
            logger.warning(f"No results from either retriever for query: '{query[:60]}'")
            return []

        # Stage 3: RRF fusion
        fused = reciprocal_rank_fusion(dense_results, bm25_results)

        # Stage 4: Cross-encoder reranking (on top candidates only)
        reranked = await loop.run_in_executor(
            _RETRIEVAL_EXECUTOR,
            lambda: rerank(query=query, candidates=fused[:candidate_k], top_n=top_k),
        )

        logger.info(
            f"Hybrid search for '{query[:60]}': "
            f"{len(dense_results)} dense + {len(bm25_results)} BM25 "
            f"-> {len(fused)} fused -> {len(reranked)} reranked "
            f"(regulator_filter={regulator_filter})"
        )

        return reranked
