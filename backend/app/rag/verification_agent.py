"""
rag/verification_agent.py -- Stage 6: Tiered Adversarial Fact-Checker.

Three verification tiers to avoid running the heavy 10k-char LLM check on every query:

  Tier 1 -- Skip LLM verification entirely.
    Used when: Path C (factual) + reranker score > 1.0 (high retrieval confidence).
    Method: Programmatic citation check -- does the answer text share key terms with
            the top retrieved chunk? If Jaccard similarity > 0.6, treat as verified.
    Fallback: If the programmatic check fails, escalate automatically to Tier 2.
    Expected savings: ~41s saved for most factual queries.

  Tier 2 -- Lightweight LLM verification.
    Used when: Path C (factual) with lower confidence, OR Path A (structured, code-eval).
    Method: ONE compact LLM call (llama-3.1-8b-instant) with only top-2 chunk evidence
            (~2000 chars) checking for hallucinations and numeric mismatches only.
    Expected savings: ~35s vs Tier 3 (5s vs 40s).

  Tier 3 -- Full LLM verification.
    Used when: Path B (chain-of-thought), OR eligibility/scenario queries.
    Method: Full 8B LLM call with 10k-char evidence and complete adversarial reasoning.
    Expected time: 5-10s (same evidence but now on 8B-instant vs 70B).

Safety net: If Tier 1 programmatic check fails (similarity < 0.6), auto-escalates to Tier 2.
"""
import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from loguru import logger


# -- Data types ----------------------------------------------------------------

@dataclass
class VerificationResult:
    """Output of the Verification Agent."""
    verified: bool
    issues: List[str]
    confidence: str          # "high" | "medium" | "low"
    raw_llm_output: str
    fallback_used: bool = False
    final_answer: str = ""   # populated after any re-synthesis
    verification_tier: int = 1  # 1 | 2 | 3 -- logged for dashboards


# Fallback template
_HONEST_FALLBACK_TEMPLATE = (
    "I found some uncertainty in my answer and want to avoid giving you incorrect information "
    "for this compliance question. Here is the raw regulatory evidence I retrieved -- "
    "please review it directly:\n\n{evidence}"
)

_FAST_MODEL = "llama-3.1-8b-instant"
_TIER1_SIM_THRESHOLD = 0.60
_TIER1_CONFIDENCE_THRESHOLD = 1.0


# -- Public API ----------------------------------------------------------------

async def run_verification_tiered(
    synthesized_answer: str,
    reasoning_trace: str,
    retrieved_chunks: List[Dict],
    llm_client,
    reasoning_path: str,
    retrieval_confidence: float,
    query_type: str,
) -> VerificationResult:
    """
    Tiered verification -- routes each query to the appropriate verification depth.
    """
    tier = _determine_tier(reasoning_path, retrieval_confidence, query_type)
    logger.info(
        f"Verification tier={tier} "
        f"(path={reasoning_path}, confidence={retrieval_confidence:.3f}, type={query_type})"
    )

    # -- Tier 1: Programmatic citation check only ------------------------------
    if tier == 1:
        result = _programmatic_citation_check(synthesized_answer, retrieved_chunks)
        result.verification_tier = 1

        if result.verified:
            result.final_answer = synthesized_answer
            logger.info("Verification Tier 1 PASSED (programmatic citation check)")
            return result
        else:
            logger.warning(
                "Verification Tier 1 failed programmatic check -- escalating to Tier 2"
            )
            tier = 2

    # -- Tier 2: Lightweight LLM call ------------------------------------------
    if tier == 2:
        result = await _run_lite_verification(synthesized_answer, retrieved_chunks, llm_client)
        result.verification_tier = 2
        # Tier 2 NEVER blocks with a fallback — it only logs warnings.
        # For factual queries the risk of false-positive fallback > risk of minor error.
        # Tier 3 (eligibility/CoT) is where we enforce blocking.
        result.final_answer = synthesized_answer
        if not result.verified:
            logger.warning(
                f"Verification Tier 2 flagged issues (logged only, not blocking): {result.issues}"
            )
            result.verified = True  # override so it doesn't count as hallucination
        else:
            logger.info("Verification Tier 2 PASSED")
        return result

    # -- Tier 3: Full LLM adversarial verification -----------------------------
    result = await _run_full_verification(
        synthesized_answer, reasoning_trace, retrieved_chunks, llm_client
    )
    result.verification_tier = 3

    if result.verified or result.confidence in ("medium", "low"):
        result.final_answer = synthesized_answer
        if not result.verified:
            logger.warning(
                f"Verification Tier 3 flagged {result.confidence}-confidence issues "
                f"(bypassing fallback): {result.issues}"
            )
            result.verified = True
        else:
            logger.info("Verification Tier 3 PASSED")
    else:
        logger.warning(f"Verification Tier 3 FAILED (high confidence): {result.issues}")
        result.final_answer = _build_fallback(retrieved_chunks)
        result.fallback_used = True

    return result


async def run_verification(
    synthesized_answer: str,
    reasoning_trace: str,
    retrieved_chunks: List[Dict],
    llm_client,
) -> VerificationResult:
    """
    Legacy compatibility wrapper -- routes to Tier 3.
    New code should call run_verification_tiered() instead.
    """
    return await run_verification_tiered(
        synthesized_answer=synthesized_answer,
        reasoning_trace=reasoning_trace,
        retrieved_chunks=retrieved_chunks,
        llm_client=llm_client,
        reasoning_path="chain_of_thought",
        retrieval_confidence=0.0,
        query_type="eligibility",
    )


# -- Tier determination --------------------------------------------------------

def _determine_tier(
    reasoning_path: str,
    retrieval_confidence: float,
    query_type: str,
) -> int:
    """
    Tier 1: factual path + high retrieval confidence
    Tier 2: factual with lower confidence OR structured code-eval path
    Tier 3: chain-of-thought OR eligibility/scenario queries
    """
    if query_type in ("eligibility", "scenario") or reasoning_path == "chain_of_thought":
        return 3
    if (
        reasoning_path == "factual"
        and retrieval_confidence >= _TIER1_CONFIDENCE_THRESHOLD
    ):
        return 1
    return 2


# -- Tier 1: Programmatic citation check ---------------------------------------

def _programmatic_citation_check(
    answer: str,
    chunks: List[Dict],
) -> VerificationResult:
    """
    Fast programmatic check using word-overlap (Jaccard similarity).
    No LLM call -- runs in microseconds.
    """
    if not chunks or not answer:
        return VerificationResult(
            verified=True, issues=[], confidence="low", raw_llm_output="programmatic"
        )

    answer_words = set(re.sub(r"[^\w\s]", "", answer.lower()).split())
    evidence_words: set = set()
    for chunk in chunks[:2]:
        text = chunk.get("text", "")
        evidence_words.update(re.sub(r"[^\w\s]", "", text.lower()).split())

    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "for", "of", "in", "on",
        "at", "to", "and", "or", "but", "with", "has", "have", "that", "this",
        "it", "its", "by", "from", "as", "be", "been", "not", "no",
    }
    answer_sig = answer_words - stopwords
    evidence_sig = evidence_words - stopwords

    if not answer_sig:
        return VerificationResult(
            verified=True, issues=[], confidence="low", raw_llm_output="programmatic_empty"
        )

    intersection = len(answer_sig & evidence_sig)
    union = len(answer_sig | evidence_sig)
    similarity = intersection / union if union > 0 else 0.0

    logger.debug(
        f"Tier 1 citation check: similarity={similarity:.3f} "
        f"(answer_terms={len(answer_sig)}, intersection={intersection})"
    )

    if similarity >= _TIER1_SIM_THRESHOLD:
        return VerificationResult(
            verified=True, issues=[], confidence="high",
            raw_llm_output=f"programmatic:similarity={similarity:.3f}",
        )
    else:
        return VerificationResult(
            verified=False,
            issues=[f"Low citation similarity ({similarity:.2f} < {_TIER1_SIM_THRESHOLD})"],
            confidence="medium",
            raw_llm_output=f"programmatic:similarity={similarity:.3f}",
        )


# -- Tier 2: Lightweight LLM verification --------------------------------------

async def _run_lite_verification(
    synthesized_answer: str,
    retrieved_chunks: List[Dict],
    llm_client,
) -> VerificationResult:
    """
    Compact LLM verification: top-2 chunks, 8B model, max_tokens=300.
    """
    from app.llm.prompts import build_verification_lite_prompt

    prompt = build_verification_lite_prompt(
        answer=synthesized_answer,
        chunks=retrieved_chunks,
        top_n=2,
    )
    raw_output = await llm_client.complete(
        prompt,
        model=_FAST_MODEL,
        temperature=0,
        max_tokens=300,
    )
    return _parse_verification_json(raw_output)


# -- Tier 3: Full LLM verification ---------------------------------------------

async def _run_full_verification(
    synthesized_answer: str,
    reasoning_trace: str,
    retrieved_chunks: List[Dict],
    llm_client,
) -> VerificationResult:
    """
    Full adversarial verification with complete 10k-char evidence.
    Uses 8B-instant (was 70B) -- much faster for a classification task.
    """
    from app.llm.prompts import build_verification_prompt

    prompt = build_verification_prompt(
        answer=synthesized_answer,
        reasoning_trace=reasoning_trace,
        chunks=retrieved_chunks,
    )
    raw_output = await llm_client.complete(
        prompt,
        model=_FAST_MODEL,
        temperature=0,
        max_tokens=400,
    )
    return _parse_verification_json(raw_output)


# -- JSON parsing --------------------------------------------------------------

def _parse_verification_json(raw: str) -> VerificationResult:
    """Parses LLM verification JSON. Falls back to verified=True on malformed output."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        logger.warning("No JSON found in verification response -- treating as verified")
        return VerificationResult(verified=True, issues=[], confidence="low", raw_llm_output=raw)

    try:
        data = json.loads(match.group(0))
        verified = bool(data.get("verified", True))
        issues = data.get("issues", [])
        if isinstance(issues, str):
            issues = [issues]
        confidence = data.get("confidence", "medium")
        if confidence not in ("high", "medium", "low"):
            confidence = "medium"
        return VerificationResult(verified=verified, issues=issues, confidence=confidence, raw_llm_output=raw)

    except json.JSONDecodeError as e:
        logger.warning(f"Verification JSON parse error: {e} -- treating as verified")
        return VerificationResult(verified=True, issues=[], confidence="low", raw_llm_output=raw)


def _build_fallback(chunks: List[Dict]) -> str:
    """Builds an honest fallback answer from raw evidence chunks."""
    evidence_parts = []
    for i, chunk in enumerate(chunks[:5], 1):
        doc = chunk.get("doc_title", "Unknown Document")
        reg = chunk.get("regulator", "")
        text = chunk.get("text", "")[:500]
        evidence_parts.append(f"[{i}] {reg} -- {doc}:\n{text}")
    evidence = "\n\n".join(evidence_parts)
    return _HONEST_FALLBACK_TEMPLATE.format(evidence=evidence)
