"""
rag/synthesis_agent.py — Stage 4: Answer Synthesis.

Responsibilities:
  1. Deduplicate near-identical retrieved chunks (embedding similarity > 0.92)
     before passing to the LLM — prevents the model from repeating the same fact
     verbatim multiple times.
  2. Combine the reasoning trace + deduplicated evidence into a concise,
     professional answer using a strict synthesis prompt.
  3. Returns the answer + dedup stats for logging.

This runs AFTER the reasoning agent, so it receives the full reasoning trace
(which may include structured rule evaluation) and the original cited chunks.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
from loguru import logger


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class SynthesisResult:
    """Output of the Synthesis Agent."""
    answer: str
    dedup_removed: int          # how many chunks were dropped as near-duplicates
    unique_chunks_used: int     # chunks remaining after dedup
    citations: List[str]        # doc titles of chunks used


# ── Dedup threshold ───────────────────────────────────────────────────────────

_DEDUP_SIMILARITY_THRESHOLD = 0.92


# ── Public API ────────────────────────────────────────────────────────────────

async def run_synthesis(
    question: str,
    reasoning_trace: str,
    retrieved_chunks: List[Dict],
    llm_client,
    is_eligibility: bool = False,
    top_evidence_n: int = 5,
) -> SynthesisResult:
    """
    Synthesizes a final professional answer from the reasoning output and evidence.

    Args:
        question:         Original user question.
        reasoning_trace:  Output from the reasoning agent (rules + trace + conclusion).
        retrieved_chunks: Top-k reranked chunks from retrieval.
        llm_client:       Async LLM client.
        is_eligibility:   True for eligibility/scenario queries — triggers structured
                          formatting in the synthesis prompt.

    Returns:
        SynthesisResult with the final answer and dedup statistics.
    """
    from app.llm.prompts import build_synthesis_prompt

    # Step 1: Semantic deduplication — then cap to top_evidence_n chunks
    # Capping AFTER dedup ensures we use the best unique chunks, not raw top-k
    unique_chunks, removed = _semantic_dedup(retrieved_chunks)
    unique_chunks = unique_chunks[:top_evidence_n]  # enforce evidence cap

    logger.info(
        f"Synthesis dedup: {len(retrieved_chunks)} chunks → "
        f"{len(unique_chunks)} unique ({removed} removed as near-duplicates)"
    )

    # Step 2: Build synthesis prompt
    prompt = build_synthesis_prompt(
        question=question,
        reasoning_trace=reasoning_trace,
        chunks=unique_chunks,
        is_eligibility=is_eligibility,
    )

    # Step 3: LLM call for synthesis — keep full 70B model for user-visible quality
    # but cap tokens since compliance answers are concise by nature
    answer = await llm_client.complete(prompt, max_tokens=800, temperature=0.1)

    citations = list({
        c.get("doc_title", "Unknown")
        for c in unique_chunks
        if c.get("doc_title")
    })

    return SynthesisResult(
        answer=answer.strip(),
        dedup_removed=removed,
        unique_chunks_used=len(unique_chunks),
        citations=citations,
    )


# ── Semantic deduplication ────────────────────────────────────────────────────

def _semantic_dedup(
    chunks: List[Dict],
    threshold: float = _DEDUP_SIMILARITY_THRESHOLD,
) -> Tuple[List[Dict], int]:
    """
    Removes near-duplicate chunks based on embedding similarity.

    Uses the text embeddings already stored in each chunk dict if available,
    otherwise falls back to hash-based exact dedup for performance.

    Args:
        chunks:    List of chunk dicts from the retriever.
        threshold: Cosine similarity above which chunks are treated as duplicates.

    Returns:
        (unique_chunks, removed_count)
    """
    if len(chunks) <= 1:
        return chunks, 0

    # Try embedding-based dedup first
    try:
        return _embedding_dedup(chunks, threshold)
    except Exception as e:
        logger.warning(f"Embedding dedup failed ({e}), falling back to text-hash dedup")
        return _text_hash_dedup(chunks)


def _embedding_dedup(
    chunks: List[Dict],
    threshold: float,
) -> Tuple[List[Dict], int]:
    """
    Embeds all chunks and removes those with cosine similarity > threshold
    relative to any already-kept chunk.
    """
    from app.retrieval.embeddings import embed_documents

    texts = [c["text"] for c in chunks]
    embeddings = embed_documents(texts)  # shape: (n, dim)

    # Normalize for cosine similarity
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    normed = embeddings / norms

    kept_indices: List[int] = []
    removed = 0

    for i in range(len(chunks)):
        is_duplicate = False
        for j in kept_indices:
            similarity = float(np.dot(normed[i], normed[j]))
            if similarity >= threshold:
                is_duplicate = True
                removed += 1
                logger.debug(
                    f"Dedup: chunk {i} similarity {similarity:.3f} to chunk {j} → removed"
                )
                break
        if not is_duplicate:
            kept_indices.append(i)

    unique_chunks = [chunks[i] for i in kept_indices]
    return unique_chunks, removed


def _text_hash_dedup(chunks: List[Dict]) -> Tuple[List[Dict], int]:
    """Fallback: exact text dedup using first-200-char hash."""
    seen: set = set()
    unique: List[Dict] = []
    removed = 0

    for chunk in chunks:
        key = chunk["text"][:200].strip().lower()
        if key not in seen:
            seen.add(key)
            unique.append(chunk)
        else:
            removed += 1

    return unique, removed
