"""
llm/prompts.py — All prompt templates, centralized.

Keeping prompts in one place ensures consistency and makes it easy to
iterate on prompt quality without hunting through business logic files.
"""
from typing import Dict, List, Optional


# ── Impact Summary Prompt ─────────────────────────────────────────────────────

IMPACT_SUMMARY_TEMPLATE = """\
You are a regulatory compliance analyst. Given an OLD clause and a NEW clause from \
a regulatory document, explain in 2-3 plain-English sentences:
1. What specifically changed
2. Who is affected (which teams/processes)
3. Whether this increases, decreases, or doesn't change compliance risk

OLD: {old_clause}
NEW: {new_clause}

Respond in this exact JSON format:
{{"summary": "...", "affected_area": "...", "risk_direction": "increased|decreased|unchanged"}}"""


REMOVAL_SUMMARY_TEMPLATE = """\
You are a regulatory compliance analyst. The following clause has been REMOVED \
from a regulatory document. Explain in 2-3 plain-English sentences:
1. What obligation or requirement this clause created
2. What teams/processes were affected by it
3. Whether its removal increases, decreases, or doesn't change compliance risk

REMOVED CLAUSE: {old_clause}

Respond in this exact JSON format:
{{"summary": "...", "affected_area": "...", "risk_direction": "increased|decreased|unchanged"}}"""


# ── Policy Conflict Check Prompt ──────────────────────────────────────────────

POLICY_CONFLICT_TEMPLATE = """\
You are a regulatory compliance analyst for the Indian financial sector.

Your task is to determine whether an internal company POLICY CLAUSE conflicts with
a REGULATORY REQUIREMENT. You must ONLY flag a genuine conflict if BOTH of the
following are true:
  1. The regulation is applicable to the same compliance domain as the policy
     (e.g., a KYC policy should only be checked against KYC/AML/identity regulations,
     NOT against cloud security, cybersecurity, or other unrelated frameworks).
  2. The policy clause contradicts, falls short of, or is incompatible with the
     specific obligation stated in the regulation.

POLICY DOMAIN: {policy_domain}
APPLICABLE REGULATORS: {applicable_regulators}

POLICY CLAUSE:
{policy_clause}

REGULATORY CLAUSE (from {regulation_source}):
{regulation_clause}

DECISION RULES:
- If the regulation is from a DIFFERENT compliance domain than the policy, respond
  with conflict=false and explain that this regulation is not applicable.
- If the regulation IS applicable but the policy already satisfies it, respond
  with conflict=false.
- Only respond with conflict=true if there is a REAL, SPECIFIC contradiction.

Respond in JSON: {{"conflict": true|false, "explanation": "...", "suggested_fix": "..."}}\
"""


# ── RAG Answer Prompt ─────────────────────────────────────────────────────────

RAG_ANSWER_TEMPLATE = """\
You are an expert regulatory compliance analyst. Your job is to read the retrieved \
regulatory context below and produce a high-quality, concise answer to the user's question.

STRICT RULES:
1. ACT LIKE AN ANALYST — do NOT copy or paste retrieved text verbatim. Extract the key \
facts and write a clean, professional summary in your own words.
2. DEDUPLICATE — if the same fact appears in multiple chunks, state it ONCE. Never \
repeat the same information.
3. SYNTHESIZE — if relevant information is spread across multiple chunks, combine it \
into a single coherent answer.
4. BE DIRECT — answer the question immediately. Do NOT add hedging phrases like \
"it is not explicitly mentioned" or "however, it is mentioned" if the answer exists in \
any chunk. Just state the fact.
5. CITE SOURCES — after each key fact, add a brief citation in the format [chunk N] or \
[Document Name]. Use citations as supporting evidence, not as the main content.
6. ONLY if NO chunk contains the answer, respond with exactly: \
"The provided regulatory documents do not contain this information."
7. Never invent or infer facts not explicitly present in the retrieved context.

Retrieved Context:
{context}

Question: {question}

Concise Answer:"""


# ── Builder Functions ─────────────────────────────────────────────────────────

def build_impact_summary_prompt(old_clause: str, new_clause: str) -> str:
    """Builds the LLM prompt for impact summary generation."""
    # Truncate very long clauses to avoid exceeding context limits
    old_clause = _truncate(old_clause, 1500)
    new_clause = _truncate(new_clause, 1500)
    return IMPACT_SUMMARY_TEMPLATE.format(old_clause=old_clause, new_clause=new_clause)


def build_removal_summary_prompt(old_clause: str) -> str:
    """Builds the LLM prompt for a removed clause summary."""
    old_clause = _truncate(old_clause, 2000)
    return REMOVAL_SUMMARY_TEMPLATE.format(old_clause=old_clause)


def build_policy_conflict_prompt(
    policy_clause: str,
    regulation_clause: str,
    policy_domain: str = "General",
    applicable_regulators: str = "RBI, SEBI",
    regulation_source: str = "regulatory document",
) -> str:
    """Builds the domain-aware LLM prompt for policy conflict detection."""
    policy_clause = _truncate(policy_clause, 1000)
    regulation_clause = _truncate(regulation_clause, 1000)
    return POLICY_CONFLICT_TEMPLATE.format(
        policy_clause=policy_clause,
        regulation_clause=regulation_clause,
        policy_domain=policy_domain,
        applicable_regulators=applicable_regulators,
        regulation_source=regulation_source,
    )


def build_rag_prompt(question: str, retrieved_chunks: List[Dict]) -> str:
    """
    Builds the RAG answer prompt from retrieved chunks.

    Args:
        question:         The user's natural language question.
        retrieved_chunks: List of chunk dicts from the hybrid retriever.
                          Each must have: text, doc_title, regulator, section_ref.

    Returns:
        Formatted prompt string.
    """
    context_parts = []
    for i, chunk in enumerate(retrieved_chunks, start=1):
        doc_title = chunk.get("doc_title", "Unknown Document")
        regulator = chunk.get("regulator", "")
        section_ref = chunk.get("section_ref", "")
        source_label = f"[{i}] {regulator} — {doc_title}"
        if section_ref:
            source_label += f" ({section_ref})"

        context_parts.append(f"{source_label}:\n{chunk['text']}")

    context = "\n\n---\n\n".join(context_parts)

    return RAG_ANSWER_TEMPLATE.format(
        context=_truncate(context, 8000),
        question=question,
    )


def _truncate(text: str, max_chars: int) -> str:
    """Truncates text to max_chars, appending an ellipsis indicator if truncated."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n[...truncated for context window...]"


# ── RAG Pipeline v3 Prompt Templates ─────────────────────────────────────────

RULE_EXTRACTION_TEMPLATE = """\
You are a regulatory compliance analyst. Extract ALL eligibility conditions from the \
regulatory text below as a structured JSON array.

REGULATORY TEXT:
{context}

INSTRUCTIONS:
- Extract ONLY conditions that are explicitly stated (age limits, experience requirements, \
  income thresholds, qualification requirements).
- For each condition, return a JSON object with these exact keys:
  "attribute": the thing being constrained (e.g., "age", "experience", "income", "qualification")
  "operator": the comparison operator ("<=", ">=", "<", ">", "==")
  "value": the numeric threshold (number only, no units in this field)
  "unit": the unit string (e.g., "years", "crores", "lakhs", "")
  "raw_text": the exact sentence this was extracted from
- If a condition uses "minimum X years", use ">=" operator.
- If a condition uses "maximum X years" or "not exceeding X", use "<=" operator.
- Return ONLY the JSON array, no other text.

Example output:
[
  {{"attribute": "age", "operator": "<=", "value": 55, "unit": "years", "raw_text": "Age should not exceed 55 years"}},
  {{"attribute": "experience", "operator": ">=", "value": 20, "unit": "years", "raw_text": "minimum 20 years of experience"}}
]

JSON Array:"""


CHAIN_OF_THOUGHT_TEMPLATE = """\
You are a regulatory compliance analyst. Evaluate whether the candidate described \
in the question meets the eligibility criteria from the regulatory context.

REGULATORY CONTEXT:
{context}

QUESTION: {question}

INSTRUCTIONS — follow this EXACT format:
1. First, list every eligibility condition you find in the context, one per line:
   "Condition: [condition text]"

2. For each condition, state the candidate's value and whether it is met:
   "Rule: [rule] | Candidate value: [value] | Met: YES/NO"

3. Only after listing ALL rules, give your conclusion:
   "Final: ELIGIBLE" or "Final: NOT ELIGIBLE"
   Followed by one sentence explaining why.

IMPORTANT: If your final conclusion contradicts any "Met: NO" line, recheck before responding.
If the context does not mention a condition relevant to the question, state that explicitly.

Evaluation:"""


SYNTHESIS_TEMPLATE = """\
You are synthesizing a final answer from verified regulatory reasoning. \
Write a clean, professional response.

REASONING TRACE:
{reasoning_trace}

SOURCE EVIDENCE:
{evidence}

QUESTION: {question}

SYNTHESIS RULES:
1. Do NOT copy raw source text verbatim — summarize in your own words.
2. Do NOT repeat the same fact more than once.
3. For eligibility/scenario questions: clearly state the conclusion (eligible/not eligible) \
   FIRST, then explain which conditions were met or not met.
4. For factual questions: answer directly in 2-4 sentences.
5. End with a "Basis:" line citing the specific document(s) used.
6. Use bullet points ONLY if the answer has 3+ distinct parts.

{eligibility_instruction}

Concise Answer:"""


VERIFICATION_TEMPLATE = """\
You are a strict fact-checker. Your job is to verify that the FINAL ANSWER is \
fully supported by the SOURCE EVIDENCE and REASONING TRACE below.

FINAL ANSWER:
{answer}

REASONING TRACE:
{reasoning_trace}

SOURCE EVIDENCE:
{evidence}

CHECK FOR:
1. Any claim in the answer NOT supported by the evidence (hallucination)
2. Any numeric value, date, or threshold in the answer that differs from the evidence
3. Logical contradictions (e.g., answer says ELIGIBLE but a rule evaluation says NOT MET)
4. Vague or hedging language that contradicts clear evidence (e.g., "may be" when evidence says "must be")

CRITICAL VERIFICATION RULE:
- Do NOT flag omissions of facts from the evidence that are unrelated to the user's specific question.
- The final answer is ONLY expected to answer the user's question, not summarize all facts in the retrieved evidence. For example, if the question is only about educational qualifications, do NOT complain that the answer fails to mention age limits or experience.
- Set "verified" to true if the claims made in the answer are true according to the evidence, even if other facts in the evidence were omitted.

Return ONLY this JSON object (no other text):
{{
  "verified": true or false,
  "issues": ["issue 1", "issue 2"],
  "confidence": "high" or "medium" or "low"
}}

Rules:
- "verified": true ONLY if you found no issues based on the criteria above
- "issues": empty list [] if verified=true
- "confidence": "high" if evidence clearly supports/contradicts, "low" if evidence is ambiguous

JSON:"""


# ── Tier-2 Lightweight Verification ──────────────────────────────────────────
# Used for factual and Path-A structured queries where full 10k-char evidence
# is unnecessary. Passes only the top-2 chunks (~2000 chars) for a fast check.

VERIFICATION_LITE_TEMPLATE = """\
You are a compliance fact-checker. Quickly verify the ANSWER against the EVIDENCE.

ANSWER: {answer}

EVIDENCE (top chunks only):
{evidence}

Check ONLY:
1. Does the answer contain any claim directly contradicted by the evidence? (hallucination)
2. Are numeric values/dates in the answer exactly correct per the evidence?

IMPORTANT: Do NOT flag omissions — only flag direct contradictions or wrong numbers.
Return ONLY JSON:
{{"verified": true or false, "issues": [], "confidence": "high" or "medium" or "low"}}

JSON:"""


LLM_JUDGE_TEMPLATE = """\
You are evaluating the quality of a RAG system's answer against a ground-truth expected answer.

QUESTION: {question}
EXPECTED ANSWER: {expected_answer}
GENERATED ANSWER: {generated_answer}

Score the generated answer on a scale of 1-5:
  5 — Completely correct, covers all key facts, no errors
  4 — Mostly correct, minor omissions or phrasing differences
  3 — Partially correct, some key facts present but missing or wrong details
  2 — Mostly incorrect or missing the main point
  1 — Completely wrong or irrelevant

Return ONLY this JSON:
{{"score": 1-5, "reason": "one sentence explanation"}}

JSON:"""


# ── Pipeline v3 Builder Functions ─────────────────────────────────────────────

def build_rule_extraction_prompt(context: str) -> str:
    """Builds the prompt for extracting eligibility rules as JSON."""
    return RULE_EXTRACTION_TEMPLATE.format(
        context=_truncate(context, 6000)
    )


def build_chain_of_thought_prompt(question: str, context: str) -> str:
    """Builds the chain-of-thought eligibility reasoning prompt."""
    return CHAIN_OF_THOUGHT_TEMPLATE.format(
        context=_truncate(context, 6000),
        question=question,
    )


def build_synthesis_prompt(
    question: str,
    reasoning_trace: str,
    chunks: list,
    is_eligibility: bool = False,
) -> str:
    """Builds the answer synthesis prompt from reasoning trace and evidence."""
    evidence_parts = []
    for i, chunk in enumerate(chunks, 1):
        doc = chunk.get("doc_title", "Unknown")
        reg = chunk.get("regulator", "")
        text = chunk.get("text", "")
        evidence_parts.append(f"[{i}] {reg} — {doc}:\n{text}")
    evidence = "\n\n".join(evidence_parts)

    eligibility_instruction = (
        "Since this is an eligibility question, your FIRST sentence must clearly state "
        "whether the candidate IS or IS NOT eligible."
        if is_eligibility else ""
    )

    return SYNTHESIS_TEMPLATE.format(
        reasoning_trace=_truncate(reasoning_trace, 2000),
        evidence=_truncate(evidence, 5000),
        question=question,
        eligibility_instruction=eligibility_instruction,
    )


def build_verification_prompt(
    answer: str,
    reasoning_trace: str,
    chunks: list,
) -> str:
    """Builds the full (Tier-3) adversarial verification prompt."""
    evidence_parts = []
    for i, chunk in enumerate(chunks, 1):
        doc = chunk.get("doc_title", "Unknown")
        text = chunk.get("text", "")
        evidence_parts.append(f"[{i}] {doc}:\n{text}")
    evidence = "\n\n".join(evidence_parts)

    return VERIFICATION_TEMPLATE.format(
        answer=_truncate(answer, 1500),
        reasoning_trace=_truncate(reasoning_trace, 2000),
        evidence=_truncate(evidence, 10000),
    )


def build_verification_lite_prompt(
    answer: str,
    chunks: list,
    top_n: int = 2,
) -> str:
    """Builds the compact (Tier-2) verification prompt using only top_n chunks."""
    evidence_parts = []
    for i, chunk in enumerate(chunks[:top_n], 1):
        doc = chunk.get("doc_title", "Unknown")
        text = chunk.get("text", "")
        evidence_parts.append(f"[{i}] {doc}:\n{text}")
    evidence = "\n\n".join(evidence_parts)

    return VERIFICATION_LITE_TEMPLATE.format(
        answer=_truncate(answer, 1000),
        evidence=_truncate(evidence, 2000),
    )



def build_llm_judge_prompt(
    question: str,
    expected_answer: str,
    generated_answer: str,
) -> str:
    """Builds the LLM-as-judge scoring prompt for evaluation."""
    return LLM_JUDGE_TEMPLATE.format(
        question=question,
        expected_answer=_truncate(expected_answer, 500),
        generated_answer=_truncate(generated_answer, 500),
    )
