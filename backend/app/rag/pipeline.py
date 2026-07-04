"""
rag/pipeline.py — Master orchestrator for the full 6-stage RAG pipeline.

Architecture:
  Stage 1: Query Analysis    — classify query type, extract candidate attributes
  Stage 2: Hybrid Retrieval  — BM25 + Dense, RRF, cross-encoder reranking
  Stage 3: Confidence Gate   — if top reranker score < threshold → honest "not found"
  Stage 4: Reasoning Agent   — structured (code eval) or chain-of-thought
  Stage 5: Synthesis Agent   — dedup + professional answer
  Stage 6: Verification      — adversarial fact-check

Each stage is timed independently using time.perf_counter() and the timings are
stored in the PipelineResult for logging and the evaluation dashboard.

Usage:
    pipeline = RAGPipeline()
    result = await pipeline.run(question="Is a 52-year-old eligible for ED?")
    print(result.final_answer)
    print(result.stage_timings)
"""
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger

from app.config import get_settings
from app.rag.query_analyzer import QueryAnalysis, analyze_query
from app.rag.reasoning_agent import ReasoningResult, run_reasoning
from app.rag.synthesis_agent import SynthesisResult, run_synthesis
from app.rag.verification_agent import VerificationResult, run_verification_tiered

settings = get_settings()

# ── Confidence gate threshold ─────────────────────────────────────────────────
# ms-marco MiniLM cross-encoder scores: relevant passages ~> -3, irrelevant ~< -7
# Start conservative at -5: below this → retrieval is too uncertain to answer
_CONFIDENCE_THRESHOLD = -5.0

# ── Semantic Query Cache ─────────────────────────────────────────────────
# In-memory cache: normalized_question -> PipelineResult
# Jaccard similarity of tokenized questions used as the "semantic" key.
# Similarity > 0.85 is treated as the same query (avoids full pipeline re-run).
# Cache is invalidated by calling clear_query_cache() from the ingestion endpoint.
_QUERY_CACHE: Dict[str, "PipelineResult"] = {}
_CACHE_SIM_THRESHOLD = 0.85


def clear_query_cache() -> None:
    """Clears the in-memory query cache. Call after new document ingestion."""
    global _QUERY_CACHE
    _QUERY_CACHE = {}
    logger.info("Query cache cleared after document ingestion")


def _tokenize_query(text: str) -> set:
    """Normalizes and tokenizes a query string for cache key comparison."""
    stopwords = {
        "what", "which", "when", "where", "does", "with", "have", "that",
        "this", "from", "their", "there", "about", "please", "tell", "explain",
        "describe", "a", "an", "the", "is", "are", "for", "of", "in", "on",
    }
    tokens = re.sub(r"[^\w\s]", "", text.lower()).split()
    return {t for t in tokens if t not in stopwords and len(t) > 2}


def _cache_lookup(question: str) -> Optional["PipelineResult"]:
    """Returns cached result if a similar query was already answered, else None."""
    q_tokens = _tokenize_query(question)
    if not q_tokens:
        return None
    for cached_q, cached_result in _QUERY_CACHE.items():
        c_tokens = _tokenize_query(cached_q)
        if not c_tokens:
            continue
        intersection = len(q_tokens & c_tokens)
        union = len(q_tokens | c_tokens)
        similarity = intersection / union if union > 0 else 0.0
        if similarity >= _CACHE_SIM_THRESHOLD:
            logger.info(
                f"Cache HIT (similarity={similarity:.3f}): "
                f"'{question[:50]}' ≈ '{cached_q[:50]}'"
            )
            return cached_result
    return None


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    """Complete output from the full RAG pipeline."""
    # Final answer (or fallback)
    final_answer: str
    verified: bool
    confidence: str             # "high" | "medium" | "low"
    fallback_used: bool

    # Query analysis
    query_type: str
    use_structured_reasoning: bool

    # Sources for citation
    sources: List[Dict] = field(default_factory=list)

    # Stage timings (milliseconds)
    stage_timings: Dict[str, int] = field(default_factory=dict)
    total_latency_ms: int = 0

    # Detailed stage outputs (for logging/evaluation)
    retrieval_confidence: float = 0.0
    dedup_removed: int = 0
    verification_issues: List[str] = field(default_factory=list)

    # Raw stage outputs for debugging
    reasoning_path: str = ""
    reasoning_trace: str = ""


# ── Pipeline class ────────────────────────────────────────────────────────────

class RAGPipeline:
    """
    Orchestrates the full 6-stage RAG pipeline.
    Each stage is independently timed and testable.
    """

    def __init__(self):
        from app.retrieval.hybrid_retriever import HybridRetriever
        from app.llm.groq_client import GroqClient

        self._retriever = HybridRetriever()
        self._llm = GroqClient()

    async def run(
        self,
        question: str,
        top_k: Optional[int] = None,
        regulator_filter: Optional[str] = None,
    ) -> PipelineResult:
        """
        Runs the full pipeline for a user question.

        Args:
            question:         The user's natural language question.
            top_k:            Override final result count (default from config).
            regulator_filter: Restrict retrieval to a specific regulator.

        Returns:
            PipelineResult with final answer, timings, and stage details.
        """
        pipeline_start = time.perf_counter()
        stage_timings: Dict[str, int] = {}

        # ── Cache lookup ─────────────────────────────────────────────────
        # Only cache when no explicit top_k/filter override (those imply unique intent)
        if top_k is None and regulator_filter is None:
            cached = _cache_lookup(question)
            if cached is not None:
                cached.stage_timings["cache_hit"] = _ms(pipeline_start)
                return cached

        # ── Stage 1: Query Analysis ───────────────────────────────────────────
        t0 = time.perf_counter()
        analysis = analyze_query(question)
        stage_timings["query_analysis"] = _ms(t0)

        logger.info(
            f"Pipeline start: '{question[:60]}' | type={analysis.query_type} | "
            f"structured={analysis.use_structured_reasoning}"
        )

        # ── Stage 2: Hybrid Retrieval ─────────────────────────────────────────
        t0 = time.perf_counter()

        # Build domain-aware keyword expansion
        domain_keywords = _build_domain_keywords(analysis, question)

        # Override regulator filter from domain hint if not explicitly provided
        eff_regulator_filter = regulator_filter
        if not eff_regulator_filter and analysis.domain_hint in ("RBI", "SEBI", "IRDAI"):
            eff_regulator_filter = analysis.domain_hint

        retrieved = await self._retriever.search(
            query=question,
            top_k=top_k,
            regulator_filter=eff_regulator_filter,
            domain_keywords=domain_keywords or None,
        )
        stage_timings["retrieval"] = _ms(t0)

        # ── Stage 3: Confidence Gate ──────────────────────────────────────────
        t0 = time.perf_counter()
        retrieval_confidence = 0.0
        if retrieved:
            retrieval_confidence = float(retrieved[0].get("rerank_score", 0.0))

        if not retrieved or retrieval_confidence < _CONFIDENCE_THRESHOLD:
            stage_timings["confidence_gate"] = _ms(t0)
            not_found_answer = (
                "The provided regulatory documents do not contain sufficient "
                "information to answer this question. Please try rephrasing or "
                "check if the relevant document has been ingested."
            )
            return PipelineResult(
                final_answer=not_found_answer,
                verified=False,
                confidence="low",
                fallback_used=True,
                query_type=analysis.query_type,
                use_structured_reasoning=analysis.use_structured_reasoning,
                sources=retrieved,
                stage_timings={**stage_timings, "confidence_gate": _ms(t0)},
                total_latency_ms=_ms(pipeline_start),
                retrieval_confidence=retrieval_confidence,
            )

        stage_timings["confidence_gate"] = _ms(t0)
        logger.info(
            f"Confidence gate PASSED: top score={retrieval_confidence:.3f}, "
            f"{len(retrieved)} chunks retrieved"
        )

        # ── Stage 4: Reasoning Agent ──────────────────────────────────────────
        t0 = time.perf_counter()
        reasoning: ReasoningResult = await run_reasoning(
            question=question,
            analysis=analysis,
            retrieved_chunks=retrieved,
            llm_client=self._llm,
        )
        stage_timings["reasoning"] = _ms(t0)

        # ── Stage 5: Synthesis Agent ──────────────────────────────────────────
        # Cap evidence chunks per query type to reduce prompt size / LLM latency:
        #   factual    → top 2 chunks  (~1000 chars) — answer is almost always in top-1
        #   comparison → top 3 chunks  (~1500 chars) — need context from both sides
        #   eligibility/scenario → top 4 chunks (~2000 chars) — need full rule context
        top_evidence_n = {
            "factual": 2,
            "comparison": 3,
            "eligibility": 4,
            "scenario": 4,
        }.get(analysis.query_type, 3)

        t0 = time.perf_counter()
        synthesis: SynthesisResult = await run_synthesis(
            question=question,
            reasoning_trace=reasoning.evaluation_trace,
            retrieved_chunks=retrieved,
            llm_client=self._llm,
            is_eligibility=analysis.query_type in ("eligibility", "scenario"),
            top_evidence_n=top_evidence_n,
        )
        stage_timings["synthesis"] = _ms(t0)

        # -- Stage 6: Verification Agent (tiered) -------------------------------
        t0 = time.perf_counter()
        verification: VerificationResult = await run_verification_tiered(
            synthesized_answer=synthesis.answer,
            reasoning_trace=reasoning.evaluation_trace,
            retrieved_chunks=retrieved,
            llm_client=self._llm,
            reasoning_path=reasoning.path_used,
            retrieval_confidence=retrieval_confidence,
            query_type=analysis.query_type,
        )
        stage_timings["verification"] = _ms(t0)
        stage_timings["verification_tier"] = verification.verification_tier

        total_ms = _ms(pipeline_start)
        stage_timings["total"] = total_ms

        logger.info(
            f"Pipeline complete: verified={verification.verified}, "
            f"total={total_ms}ms | stages: {stage_timings}"
        )

        result = PipelineResult(
            final_answer=verification.final_answer,
            verified=verification.verified,
            confidence=verification.confidence,
            fallback_used=verification.fallback_used,
            query_type=analysis.query_type,
            use_structured_reasoning=analysis.use_structured_reasoning,
            sources=retrieved,
            stage_timings=stage_timings,
            total_latency_ms=total_ms,
            retrieval_confidence=retrieval_confidence,
            dedup_removed=synthesis.dedup_removed,
            verification_issues=verification.issues,
            reasoning_path=reasoning.path_used,
            reasoning_trace=reasoning.evaluation_trace,
        )

        # Store in cache (only if we didn't use a filter override)
        if top_k is None and regulator_filter is None and not verification.fallback_used:
            _QUERY_CACHE[question] = result

        return result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ms(start: float) -> int:
    """Returns elapsed milliseconds since `start` (from perf_counter)."""
    return int((time.perf_counter() - start) * 1000)


def _build_domain_keywords(analysis: QueryAnalysis, question: str) -> List[str]:
    """
    Builds BM25 keyword hints from the question and analysis.
    For eligibility/scenario queries, adds the extracted attribute names
    to boost retrieval of rule-containing chunks.
    """
    stopwords = {
        "what", "which", "when", "where", "does", "with", "have",
        "that", "this", "from", "their", "there", "about", "required",
        "minimum", "maximum", "please", "tell", "explain", "describe",
        "eligible", "eligibility", "person", "candidate",
    }
    words = [
        w.lower().strip("?,.")
        for w in question.split()
        if len(w) > 3 and w.lower().strip("?.") not in stopwords
    ]

    # Add attribute names for structured queries
    if analysis.use_structured_reasoning:
        for attr in analysis.candidate_attributes:
            words.append(attr.attribute)  # "age", "experience"

    # Deduplicate preserving order
    seen: set = set()
    keywords: List[str] = []
    for w in words:
        if w not in seen:
            seen.add(w)
            keywords.append(w)
        if len(keywords) >= 10:
            break

    return keywords
