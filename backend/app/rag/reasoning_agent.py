"""
rag/reasoning_agent.py — Stage 3: Hybrid neuro-symbolic reasoning.

Two paths:
  Path A (structured) — used when query_type is eligibility/scenario AND numeric
    candidate attributes were extracted. The LLM extracts rules as JSON, then Python
    code evaluates them. No LLM arithmetic = no numeric comparison errors.

  Path B (chain-of-thought) — used for qualitative/compound conditions or when
    structured extraction yields insufficient rules. Forces explicit step-by-step
    reasoning before any conclusion.

The path used is logged in ReasoningResult.path_used for evaluation/debugging.
"""
import json
import operator
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger

from app.rag.query_analyzer import CandidateAttribute, QueryAnalysis


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class ExtractedRule:
    """A single eligibility rule extracted from regulatory text."""
    attribute: str      # "age" | "experience" | "income" | "qualification"
    operator: str       # "<=" | ">=" | "<" | ">" | "==" | "in"
    value: Any          # numeric or list
    unit: str           # "years" | "crores" | ""
    raw_text: str       # original sentence this was extracted from
    met: Optional[bool] = None   # filled in after code evaluation


@dataclass
class ReasoningResult:
    """Output of the Reasoning Agent."""
    path_used: str                          # "structured" | "chain_of_thought" | "factual"
    rules_extracted: List[ExtractedRule]    # for structured path
    evaluation_trace: str                   # step-by-step reasoning text
    conclusion: str                         # "ELIGIBLE" | "NOT ELIGIBLE" | answer text
    all_rules_met: Optional[bool]           # None for factual queries
    raw_llm_output: str                     # for debugging


# ── Operator map for code evaluation ─────────────────────────────────────────

_OPS = {
    "<=": operator.le,
    ">=": operator.ge,
    "<":  operator.lt,
    ">":  operator.gt,
    "==": operator.eq,
    "in": lambda val, lst: val in lst,
}


# ── Public API ────────────────────────────────────────────────────────────────

async def run_reasoning(
    question: str,
    analysis: QueryAnalysis,
    retrieved_chunks: List[Dict],
    llm_client,
) -> ReasoningResult:
    """
    Runs the appropriate reasoning path based on query analysis.

    Args:
        question:         Original user question.
        analysis:         QueryAnalysis from Stage 1.
        retrieved_chunks: Top-k reranked chunks from Stage 2.
        llm_client:       Async LLM client (GroqClient or OllamaClient).

    Returns:
        ReasoningResult with path used, rules, trace, and conclusion.
    """
    if analysis.query_type in ("factual", "comparison"):
        logger.info("Reasoning Agent: using Path C (factual pass-through)")
        return ReasoningResult(
            path_used="factual",
            rules_extracted=[],
            evaluation_trace="Factual query — retrieved evidence passed to synthesis.",
            conclusion="See source evidence.",
            all_rules_met=None,
            raw_llm_output="Factual query bypass",
        )
    elif analysis.use_structured_reasoning:
        logger.info("Reasoning Agent: using Path A (structured extraction + code eval)")
        return await _structured_path(question, analysis, retrieved_chunks, llm_client)
    else:
        logger.info("Reasoning Agent: using Path B (chain-of-thought)")
        return await _chain_of_thought_path(question, retrieved_chunks, llm_client)



# ── Path A: Structured extraction + code evaluation ──────────────────────────

async def _structured_path(
    question: str,
    analysis: QueryAnalysis,
    chunks: List[Dict],
    llm_client,
) -> ReasoningResult:
    """
    Step 1: LLM extracts eligibility rules as JSON from retrieved chunks.
    Step 2: Python code evaluates each rule against candidate attributes.
    Step 3: Build a deterministic reasoning trace.
    """
    from app.llm.prompts import build_rule_extraction_prompt

    context = _format_chunks(chunks)
    rule_prompt = build_rule_extraction_prompt(context)

    # Step 1: Extract rules via LLM (fast 8B model is sufficient for JSON extraction)
    raw_rules_json = await llm_client.complete(
        rule_prompt,
        model="llama-3.1-8b-instant",
        temperature=0,
        max_tokens=512,
    )
    rules = _parse_rules_json(raw_rules_json)

    if not rules:
        logger.warning("Structured path: no rules extracted, falling back to chain-of-thought")
        return await _chain_of_thought_path(question, chunks, llm_client)

    # Step 2: Evaluate rules in Python code (no LLM arithmetic)
    candidate_map = {a.attribute: a for a in analysis.candidate_attributes}
    trace_lines = []
    all_met = True

    for rule in rules:
        candidate_attr = candidate_map.get(rule.attribute)
        if candidate_attr is None:
            trace_lines.append(
                f"Rule: {rule.attribute} {rule.operator} {rule.value} {rule.unit} | "
                f"Candidate value: NOT PROVIDED | Met: UNKNOWN"
            )
            continue

        cand_val = candidate_attr.value
        op_fn = _OPS.get(rule.operator)

        if op_fn is None:
            trace_lines.append(
                f"Rule: {rule.attribute} {rule.operator} {rule.value} {rule.unit} | "
                f"Unknown operator — skipped"
            )
            continue

        try:
            result = op_fn(cand_val, rule.value)
        except Exception as e:
            result = False
            logger.warning(f"Rule evaluation error: {e}")

        rule.met = result
        if not result:
            all_met = False

        met_str = "YES" if result else "NO"
        trace_lines.append(
            f"Rule: {rule.attribute} must be {rule.operator} {rule.value} {rule.unit} | "
            f"Candidate value: {cand_val} {candidate_attr.unit} | Met: {met_str}"
        )

    conclusion = "ELIGIBLE" if all_met else "NOT ELIGIBLE"
    trace = "\n".join(trace_lines) + f"\n\nFinal: {conclusion}"

    logger.info(f"Structured reasoning complete: {conclusion} ({len(rules)} rules evaluated)")

    return ReasoningResult(
        path_used="structured",
        rules_extracted=rules,
        evaluation_trace=trace,
        conclusion=conclusion,
        all_rules_met=all_met,
        raw_llm_output=raw_rules_json,
    )


# ── Path B: Chain-of-thought ──────────────────────────────────────────────────

async def _chain_of_thought_path(
    question: str,
    chunks: List[Dict],
    llm_client,
) -> ReasoningResult:
    """
    Forces explicit step-by-step reasoning. The LLM must list each condition
    and whether it's met BEFORE giving a final conclusion.
    """
    from app.llm.prompts import build_chain_of_thought_prompt

    context = _format_chunks(chunks)
    cot_prompt = build_chain_of_thought_prompt(question=question, context=context)

    # 8B instant model is sufficient for structured CoT evaluation
    raw_output = await llm_client.complete(
        cot_prompt,
        model="llama-3.1-8b-instant",
        temperature=0,
        max_tokens=768,
    )

    # Extract conclusion from the chain-of-thought output
    conclusion = _extract_cot_conclusion(raw_output)

    return ReasoningResult(
        path_used="chain_of_thought",
        rules_extracted=[],
        evaluation_trace=raw_output,
        conclusion=conclusion,
        all_rules_met=None,
        raw_llm_output=raw_output,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_chunks(chunks: List[Dict]) -> str:
    """Formats retrieved chunks into a numbered context string."""
    parts = []
    for i, chunk in enumerate(chunks, 1):
        doc = chunk.get("doc_title", "Unknown")
        reg = chunk.get("regulator", "")
        text = chunk.get("text", "")
        parts.append(f"[{i}] {reg} — {doc}:\n{text}")
    return "\n\n---\n\n".join(parts)


def _parse_rules_json(raw: str) -> List[ExtractedRule]:
    """
    Parses the LLM's JSON output into ExtractedRule objects.
    Handles common JSON formatting issues (extra text before/after JSON).
    """
    # Find JSON array in the response
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        logger.warning("No JSON array found in rule extraction response")
        return []

    try:
        data = json.loads(match.group(0))
        rules = []
        for item in data:
            if not isinstance(item, dict):
                continue
            attr = item.get("attribute", "")
            op = item.get("operator", "")
            val = item.get("value")
            unit = item.get("unit", "")
            raw_text = item.get("raw_text", "")

            if not attr or not op or val is None:
                continue

            # Convert value to float for numeric comparisons
            try:
                val = float(val)
            except (TypeError, ValueError):
                pass  # keep as string/list for non-numeric

            rules.append(ExtractedRule(
                attribute=attr.lower(),
                operator=op,
                value=val,
                unit=unit,
                raw_text=raw_text,
            ))
        return rules

    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse rules JSON: {e}\nRaw: {raw[:300]}")
        return []


def _extract_cot_conclusion(cot_output: str) -> str:
    """
    Extracts the final conclusion from chain-of-thought output.
    Looks for 'ELIGIBLE' / 'NOT ELIGIBLE' / explicit answer statements.
    """
    # Look for explicit ELIGIBLE/NOT ELIGIBLE markers
    if "NOT ELIGIBLE" in cot_output.upper():
        return "NOT ELIGIBLE"
    if "ELIGIBLE" in cot_output.upper():
        return "ELIGIBLE"

    # If no eligibility decision, use the last paragraph as the conclusion
    paragraphs = [p.strip() for p in cot_output.split("\n\n") if p.strip()]
    return paragraphs[-1] if paragraphs else cot_output.strip()
