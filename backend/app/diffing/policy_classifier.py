"""
diffing/policy_classifier.py — Policy domain classification and regulation mapping.

This module solves the false-positive problem in conflict detection by first
determining WHAT type of policy was uploaded before retrieving any regulatory chunks.

For example:
  - A KYC policy -> restrict to RBI KYC Directions, AML guidelines, Video KYC rules
  - A Capital Adequacy policy -> restrict to RBI Basel/CRAR circulars
  - A Securities policy -> restrict to SEBI regulations

This prevents semantic-similarity-based false positives where a KYC clause
about "identity verification" retrieves unrelated cloud-security regulations.
"""
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List

from loguru import logger


class PolicyDomain(str, Enum):
    """Known policy domains with clear regulatory mappings."""
    KYC              = "KYC"
    AML              = "AML"
    CAPITAL_ADEQUACY = "Capital Adequacy"
    LENDING          = "Lending"
    SECURITIES       = "Securities"
    MUTUAL_FUNDS     = "Mutual Funds"
    DATA_PRIVACY     = "Data Privacy"
    INSURANCE        = "Insurance"
    FOREX            = "Forex"
    PAYMENTS         = "Payments"
    CORPORATE_GOV    = "Corporate Governance"
    GENERAL          = "General"


# Maps each domain to the regulators AND keyword hints used to scope retrieval
DOMAIN_REGULATION_MAP: Dict[str, Dict] = {
    PolicyDomain.KYC.value: {
        "regulators": ["RBI", "SEBI"],
        "keywords": [
            "kyc", "know your customer", "customer due diligence", "cdd",
            "video kyc", "vkyc", "aadhaar", "pan", "identification",
            "beneficial owner", "risk categorisation", "politically exposed",
            "pep", "fiu", "aml", "pmla", "financial intelligence",
        ],
        "description": "KYC / Customer Due Diligence",
    },
    PolicyDomain.AML.value: {
        "regulators": ["RBI", "SEBI"],
        "keywords": [
            "anti-money laundering", "aml", "pmla", "suspicious transaction",
            "str", "ctr", "cash transaction report", "fiu", "financial intelligence",
            "terrorist financing", "ctf", "sanctions", "ofac", "hawala",
            "money laundering", "proceeds of crime",
        ],
        "description": "Anti-Money Laundering / CFT",
    },
    PolicyDomain.CAPITAL_ADEQUACY.value: {
        "regulators": ["RBI"],
        "keywords": [
            "capital adequacy", "crar", "tier 1", "tier 2", "basel",
            "risk weighted assets", "rwa", "leverage ratio", "lcr",
            "nsfr", "capital conservation buffer", "countercyclical buffer",
            "minimum capital requirement",
        ],
        "description": "Capital Adequacy / Basel",
    },
    PolicyDomain.LENDING.value: {
        "regulators": ["RBI"],
        "keywords": [
            "lending", "loan", "credit", "npa", "npa classification",
            "provisioning", "asset quality", "priority sector", "psl",
            "microfinance", "mfi", "nbfc", "housing finance", "interest rate",
            "moratorium", "restructuring", "recovery",
        ],
        "description": "Lending / Credit",
    },
    PolicyDomain.SECURITIES.value: {
        "regulators": ["SEBI"],
        "keywords": [
            "securities", "equity", "trading", "stock exchange", "broker",
            "depository", "insider trading", "upsi", "takeover", "open offer",
            "listing obligation", "lodr", "prospectus", "ipo", "ofs",
            "market manipulation", "surveillance", "circuit breaker",
        ],
        "description": "Securities / Capital Markets",
    },
    PolicyDomain.MUTUAL_FUNDS.value: {
        "regulators": ["SEBI"],
        "keywords": [
            "mutual fund", "amc", "nav", "scheme", "unit holder",
            "portfolio", "expense ratio", "distributor", "amfi",
            "sip", "systematic investment", "redemption", "exit load",
        ],
        "description": "Mutual Funds",
    },
    PolicyDomain.DATA_PRIVACY.value: {
        "regulators": ["RBI", "SEBI"],
        "keywords": [
            "data protection", "data privacy", "personal data", "consent",
            "data breach", "information security", "it act", "dpdp",
            "data localisation", "data residency", "gdpr", "pii",
            "sensitive personal information", "spi",
        ],
        "description": "Data Privacy / Information Security",
    },
    PolicyDomain.FOREX.value: {
        "regulators": ["RBI"],
        "keywords": [
            "forex", "foreign exchange", "fema", "fdi", "odi",
            "external commercial borrowing", "ecb", "nre", "nro",
            "remittance", "liberalised remittance scheme", "lrs",
            "fedai", "authorised dealer",
        ],
        "description": "Foreign Exchange / FEMA",
    },
    PolicyDomain.PAYMENTS.value: {
        "regulators": ["RBI"],
        "keywords": [
            "payment", "upi", "prepaid", "ppi", "wallet", "payment gateway",
            "psp", "payment aggregator", "pa", "nodal account", "settlement",
            "rtgs", "neft", "imps", "bbps", "bharat bill payment",
        ],
        "description": "Payments / Digital Payments",
    },
    PolicyDomain.CORPORATE_GOV.value: {
        "regulators": ["SEBI", "RBI"],
        "keywords": [
            "corporate governance", "board of directors", "audit committee",
            "independent director", "related party", "whistleblower",
            "compliance officer", "nomination", "remuneration",
        ],
        "description": "Corporate Governance",
    },
    PolicyDomain.INSURANCE.value: {
        "regulators": ["SEBI"],
        "keywords": [
            "insurance", "premium", "policyholder", "claim", "underwriting",
            "reinsurance", "irdai", "life insurance", "general insurance",
        ],
        "description": "Insurance",
    },
    PolicyDomain.GENERAL.value: {
        "regulators": ["RBI", "SEBI"],
        "keywords": [],
        "description": "General Compliance",
    },
}


@dataclass
class PolicyClassification:
    """
    Result of classifying an uploaded policy document.

    Attributes:
        domain:          Detected compliance domain.
        regulators:      Applicable regulators to scope retrieval.
        domain_keywords: Domain-specific keywords to boost BM25 retrieval.
        description:     Human-readable label for the UI badge.
        confidence:      0-1 score from the LLM.
        reasoning:       LLM explanation for the classification.
    """
    domain: str
    regulators: List[str]
    domain_keywords: List[str]
    description: str
    confidence: float = 0.8
    reasoning: str = ""


# ── Prompt Template ────────────────────────────────────────────────────────────

_CLASSIFICATION_PROMPT = """\
You are a regulatory compliance expert for the Indian financial sector.

Analyze the following policy document excerpt and classify it into EXACTLY ONE
of these compliance domains:

- KYC              (Know Your Customer, customer due diligence, video KYC, AML linkage)
- AML              (Anti-Money Laundering, PMLA, suspicious transactions, FIU)
- Capital Adequacy (Basel, CRAR, capital buffers, risk-weighted assets)
- Lending          (Credit/loan policies, NPA, provisioning, PSL, NBFC)
- Securities       (Equity trading, broker, SEBI LODR, insider trading, IPO)
- Mutual Funds     (AMC, NAV, scheme documents, AMFI)
- Data Privacy     (Data protection, DPDP, IT Act, information security)
- Forex            (FEMA, FDI, ECB, remittance, NRE/NRO)
- Payments         (UPI, PPI, payment gateway, RTGS, NEFT)
- Corporate Governance (Board, audit committee, independent directors)
- Insurance        (IRDAI, premium, policyholder, underwriting)
- General          (Use ONLY if the document does not fit any above domain)

POLICY EXCERPT (first 3000 characters):
{policy_excerpt}

Respond with ONLY valid JSON in this exact format (no markdown, no explanation):
{{
  "domain": "<one of the domain names above>",
  "confidence": <0.0 to 1.0>,
  "reasoning": "<one sentence explaining the classification>"
}}"""


# ── Classifier Function ────────────────────────────────────────────────────────

def classify_policy(raw_text: str) -> PolicyClassification:
    """
    Classifies the compliance domain of an uploaded policy document.

    Uses ONE LLM call per document (not per clause) to keep latency low.
    Falls back to GENERAL domain if the LLM call fails.

    Args:
        raw_text: Full extracted text of the policy document.

    Returns:
        PolicyClassification with domain, applicable regulators, and keywords.
    """
    excerpt = raw_text[:3000].strip()
    prompt = _CLASSIFICATION_PROMPT.format(policy_excerpt=excerpt)

    try:
        from app.llm.groq_client import GroqClient
        import asyncio

        client = GroqClient()
        loop = asyncio.new_event_loop()
        response = loop.run_until_complete(client.complete(prompt, temperature=0.0))
        loop.close()

        classification = _parse_classification_response(response)
        logger.info(
            f"Policy classified as: {classification.domain} "
            f"(confidence={classification.confidence:.2f}, "
            f"regulators={classification.regulators})"
        )
        return classification

    except Exception as exc:
        logger.warning(f"Policy classification LLM call failed: {exc}. Falling back to GENERAL.")
        return _fallback_classification()


def _parse_classification_response(response: str) -> PolicyClassification:
    """Parses the LLM JSON response into a PolicyClassification."""
    response = response.strip()
    response = re.sub(r"^```(?:json)?\s*", "", response)
    response = re.sub(r"\s*```$", "", response)
    response = response.strip()

    try:
        data = json.loads(response)
        domain_str = str(data.get("domain", "General")).strip()
        confidence = float(data.get("confidence", 0.8))
        reasoning = str(data.get("reasoning", ""))

        matched_domain = _match_domain(domain_str)
        domain_info = DOMAIN_REGULATION_MAP.get(
            matched_domain, DOMAIN_REGULATION_MAP[PolicyDomain.GENERAL.value]
        )

        return PolicyClassification(
            domain=matched_domain,
            regulators=domain_info["regulators"],
            domain_keywords=domain_info["keywords"],
            description=domain_info["description"],
            confidence=max(0.0, min(1.0, confidence)),
            reasoning=reasoning,
        )

    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning(f"Failed to parse classification JSON: {exc} — response: {response[:200]}")
        return _fallback_classification()


def _match_domain(domain_str: str) -> str:
    """Fuzzy-matches a domain string to a canonical PolicyDomain value."""
    domain_lower = domain_str.lower().strip()

    # Exact match first (case-insensitive)
    for domain in PolicyDomain:
        if domain_lower == domain.value.lower():
            return domain.value

    # Substring match fallback
    match_map = {
        "kyc": PolicyDomain.KYC.value,
        "aml": PolicyDomain.AML.value,
        "capital": PolicyDomain.CAPITAL_ADEQUACY.value,
        "basel": PolicyDomain.CAPITAL_ADEQUACY.value,
        "lend": PolicyDomain.LENDING.value,
        "credit": PolicyDomain.LENDING.value,
        "loan": PolicyDomain.LENDING.value,
        "securit": PolicyDomain.SECURITIES.value,
        "mutual": PolicyDomain.MUTUAL_FUNDS.value,
        "data": PolicyDomain.DATA_PRIVACY.value,
        "privacy": PolicyDomain.DATA_PRIVACY.value,
        "forex": PolicyDomain.FOREX.value,
        "foreign exchange": PolicyDomain.FOREX.value,
        "fema": PolicyDomain.FOREX.value,
        "payment": PolicyDomain.PAYMENTS.value,
        "upi": PolicyDomain.PAYMENTS.value,
        "corporate": PolicyDomain.CORPORATE_GOV.value,
        "governance": PolicyDomain.CORPORATE_GOV.value,
        "insurance": PolicyDomain.INSURANCE.value,
    }

    for key, matched in match_map.items():
        if key in domain_lower:
            return matched

    return PolicyDomain.GENERAL.value


def _fallback_classification() -> PolicyClassification:
    """Returns a GENERAL domain classification when LLM is unavailable."""
    info = DOMAIN_REGULATION_MAP[PolicyDomain.GENERAL.value]
    return PolicyClassification(
        domain=PolicyDomain.GENERAL.value,
        regulators=info["regulators"],
        domain_keywords=info["keywords"],
        description=info["description"],
        confidence=0.5,
        reasoning="Classification unavailable — using general domain as fallback.",
    )


def get_domain_display_info(domain: str) -> Dict:
    """
    Returns UI display information for a domain string.
    Used by the API to return badge/color data to the frontend.
    """
    emoji_map = {
        PolicyDomain.KYC.value:              ("ID", "#0ea5e9"),
        PolicyDomain.AML.value:              ("AML", "#ef4444"),
        PolicyDomain.CAPITAL_ADEQUACY.value: ("CAP", "#8b5cf6"),
        PolicyDomain.LENDING.value:          ("LEND", "#f59e0b"),
        PolicyDomain.SECURITIES.value:       ("SEC", "#10b981"),
        PolicyDomain.MUTUAL_FUNDS.value:     ("MF", "#06b6d4"),
        PolicyDomain.DATA_PRIVACY.value:     ("DATA", "#6366f1"),
        PolicyDomain.FOREX.value:            ("FX", "#84cc16"),
        PolicyDomain.PAYMENTS.value:         ("PAY", "#f97316"),
        PolicyDomain.CORPORATE_GOV.value:    ("GOV", "#64748b"),
        PolicyDomain.INSURANCE.value:        ("INS", "#a3a3a3"),
        PolicyDomain.GENERAL.value:          ("GEN", "#9ca3af"),
    }
    badge, color = emoji_map.get(domain, ("GEN", "#9ca3af"))
    info = DOMAIN_REGULATION_MAP.get(domain, DOMAIN_REGULATION_MAP[PolicyDomain.GENERAL.value])
    return {
        "badge": badge,
        "color": color,
        "description": info["description"],
        "regulators": info["regulators"],
    }

