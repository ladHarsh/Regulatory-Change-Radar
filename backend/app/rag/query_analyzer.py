"""
rag/query_analyzer.py — Stage 1: Classifies the query type and extracts structured
candidate attributes for scenario/eligibility questions.

Query types:
  factual     — "What is the minimum experience for ED?"
  eligibility — "Is a 52-year-old with 18 years eligible for ED?"
  scenario    — "A person aged 54 with CA qualification applies..."
  comparison  — "How does RBI's KYC differ from SEBI's?"

For eligibility/scenario queries, candidate attributes (age, experience, income, etc.)
are extracted as structured data so the Reasoning Agent can evaluate them in code,
not via LLM free-text reasoning.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from loguru import logger


# ── Keyword signatures for query type detection ───────────────────────────────

_ELIGIBILITY_KEYWORDS = {
    "eligible", "eligibility", "qualify", "qualified", "can i", "can she",
    "can he", "can they", "can a person", "is a", "does a", "will i",
    "am i", "meets", "meet the", "satisfies", "satisfy",
}

_SCENARIO_KEYWORDS = {
    "year old", "years old", "aged", "age of", "has experience",
    "years of experience", "years experience", "holds a degree",
    "with a qualification", "with an mba", "with ca", "with cfa",
    "earns", "earning", "income of", "salary of",
}

_COMPARISON_KEYWORDS = {
    "differ", "difference", "compare", "vs", "versus", "contrast",
    "how does", "what is the difference",
}

# Regex to extract numeric values with units (age, experience, income)
_NUMERIC_PATTERN = re.compile(
    r"""
    (?P<value>\d+(?:\.\d+)?)          # numeric value (int or float)
    \s*
    (?P<unit>
        years?\s+(?:of\s+)?(?:experience|old|age)?  # "20 years experience" / "52 years old"
        | year(?:\s+old)?                             # "year old"
        | months?                                     # "6 months"
        | crore[s]?                                   # "2 crores"
        | lakh[s]?                                    # "50 lakhs"
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_AGE_PATTERN = re.compile(
    r"(?:aged?\s+(?:of\s+)?|(\d+)[- ]year[- ]old\s)(\d+)|(\d+)\s+years?\s+old",
    re.IGNORECASE,
)


@dataclass
class CandidateAttribute:
    """A single structured attribute extracted from the user's question."""
    attribute: str          # "age" | "experience" | "income" | "qualification"
    value: float            # numeric value
    unit: str               # "years" | "months" | "crores" | etc.
    raw_text: str           # the original phrase that was matched


@dataclass
class QueryAnalysis:
    """Result of query analysis for a single user question."""
    query_type: str                              # factual | eligibility | scenario | comparison
    candidate_attributes: List[CandidateAttribute] = field(default_factory=list)
    domain_hint: Optional[str] = None           # e.g., "KYC", "SEBI ED", "RBI"
    use_structured_reasoning: bool = False       # True for eligibility/scenario
    original_question: str = ""


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_query(question: str) -> QueryAnalysis:
    """
    Classifies the query type and extracts structured candidate attributes.

    Args:
        question: The user's raw natural language question.

    Returns:
        QueryAnalysis with type, extracted attributes, and reasoning path hint.
    """
    q_lower = question.lower()

    # Detect query type
    query_type = _detect_type(q_lower)

    # Extract candidate attributes for eligibility/scenario queries
    attributes: List[CandidateAttribute] = []
    if query_type in ("eligibility", "scenario"):
        attributes = _extract_candidate_attributes(question)

    # Extract domain hint from question for focused retrieval
    domain_hint = _extract_domain_hint(q_lower)

    use_structured = (
        query_type in ("eligibility", "scenario") and len(attributes) > 0
    )

    analysis = QueryAnalysis(
        query_type=query_type,
        candidate_attributes=attributes,
        domain_hint=domain_hint,
        use_structured_reasoning=use_structured,
        original_question=question,
    )

    logger.info(
        f"Query analysis: type={query_type}, "
        f"attributes={[a.attribute for a in attributes]}, "
        f"structured_reasoning={use_structured}"
    )

    return analysis


# ── Private helpers ───────────────────────────────────────────────────────────

def _detect_type(q_lower: str) -> str:
    """Classifies query into one of 4 types based on keyword presence."""

    # Check eligibility keywords first (most specific)
    if any(kw in q_lower for kw in _ELIGIBILITY_KEYWORDS):
        # Further distinguish: if numeric candidate info present → scenario
        if any(kw in q_lower for kw in _SCENARIO_KEYWORDS) or re.search(r"\d+\s*year", q_lower):
            return "scenario"
        return "eligibility"

    # Scenario: has numeric candidate attributes regardless of eligibility words
    if any(kw in q_lower for kw in _SCENARIO_KEYWORDS):
        return "scenario"

    # Comparison
    if any(kw in q_lower for kw in _COMPARISON_KEYWORDS):
        return "comparison"

    # Default: factual
    return "factual"


def _extract_candidate_attributes(question: str) -> List[CandidateAttribute]:
    """
    Extracts numeric candidate attributes (age, experience, income) from the question.
    Uses regex patterns to find common phrasings.
    """
    attributes: List[CandidateAttribute] = []
    seen_attributes: set = set()

    q_lower = question.lower()

    # --- Age patterns ---
    age_patterns = [
        r"(\d+)[- ]year[- ]old",
        r"aged?\s+(\d+)",
        r"age\s+(?:of\s+)?(\d+)",
        r"(\d+)\s+years?\s+old",
    ]
    for pattern in age_patterns:
        m = re.search(pattern, q_lower)
        if m and "age" not in seen_attributes:
            raw = m.group(0)
            val = float(m.group(1))
            attributes.append(CandidateAttribute(
                attribute="age", value=val, unit="years", raw_text=raw
            ))
            seen_attributes.add("age")
            break

    # --- Experience patterns ---
    exp_patterns = [
        r"(\d+)\s+years?\s+(?:of\s+)?post[- ]qualification(?:\s+experience)?",
        r"(\d+)\s+years?\s+(?:of\s+)?experience",
        r"(\d+)\s+years?\s+(?:post[- ]qualification|post[- ]qual)",
        r"experience\s+(?:of\s+)?(\d+)\s+years?",
        r"(\d+)\s+year\s+experience",
    ]
    for pattern in exp_patterns:
        m = re.search(pattern, q_lower)
        if m and "experience" not in seen_attributes:
            raw = m.group(0)
            val = float(m.group(1))
            attributes.append(CandidateAttribute(
                attribute="experience", value=val, unit="years", raw_text=raw
            ))
            seen_attributes.add("experience")
            break

    # --- Income/salary patterns ---
    income_patterns = [
        r"(?:earning|income|salary|earns)\s+(?:of\s+)?(?:rs\.?\s*)?(\d+(?:\.\d+)?)\s*(lakh|crore)",
        r"(?:rs\.?\s*)?(\d+(?:\.\d+)?)\s*(lakh|crore)\s+(?:per\s+)?(?:annual|yearly|month)",
    ]
    for pattern in income_patterns:
        m = re.search(pattern, q_lower)
        if m and "income" not in seen_attributes:
            raw = m.group(0)
            val = float(m.group(1))
            unit = m.group(2)
            attributes.append(CandidateAttribute(
                attribute="income", value=val, unit=unit, raw_text=raw
            ))
            seen_attributes.add("income")
            break

    return attributes


def _extract_domain_hint(q_lower: str) -> Optional[str]:
    """Extracts a domain hint to narrow retrieval (e.g., 'SEBI', 'KYC', 'RBI')."""
    domain_map = {
        "sebi": "SEBI",
        "rbi": "RBI",
        "irdai": "IRDAI",
        "kyc": "KYC",
        "aml": "AML",
        "executive director": "SEBI",
        "ed post": "SEBI",
        "securities": "SEBI",
    }
    for keyword, domain in domain_map.items():
        if keyword in q_lower:
            return domain
    return None
