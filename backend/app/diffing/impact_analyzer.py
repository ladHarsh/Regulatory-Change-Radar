"""
diffing/impact_analyzer.py — LLM-powered impact analysis for regulatory changes.

For each MODIFIED or NEW clause detected by the semantic diff engine,
this module calls the LLM with a structured prompt to produce:
  - A 2-3 sentence plain-English impact summary
  - The affected compliance area (e.g., "KYC", "Capital Adequacy")
  - Whether the change increases, decreases, or doesn't change compliance risk

Also handles the policy conflict check pipeline.
"""
import json
import re
from typing import Dict, Optional

from loguru import logger

from app.llm.prompts import (
    build_impact_summary_prompt,
    build_policy_conflict_prompt,
    build_removal_summary_prompt,
)


def generate_impact_summary(
    old_clause: Optional[str],
    new_clause: Optional[str],
) -> Dict:
    """
    Calls the LLM to generate a plain-English impact summary for a clause change.

    Args:
        old_clause: Text of the old clause (None if this is a NEW clause).
        new_clause: Text of the new clause (None if this is a REMOVED clause).

    Returns:
        Dict with keys: summary, affected_area, risk_direction.
        Falls back to sensible defaults if LLM call fails or JSON is malformed.
    """
    from app.llm.groq_client import GroqClient

    if old_clause is None and new_clause is None:
        return {
            "summary": "No clause content available for analysis.",
            "affected_area": "Unknown",
            "risk_direction": "unchanged",
        }

    # Build the appropriate prompt
    if new_clause is None:
        # REMOVED clause
        prompt = build_removal_summary_prompt(old_clause)
    elif old_clause is None:
        # NEW clause (no prior version)
        prompt = build_impact_summary_prompt(old_clause="[Not present in previous version]", new_clause=new_clause)
    else:
        prompt = build_impact_summary_prompt(old_clause=old_clause, new_clause=new_clause)

    try:
        client = GroqClient()
        # Use synchronous call since this runs in a background task
        import asyncio
        loop = asyncio.new_event_loop()
        response = loop.run_until_complete(client.complete(prompt))
        loop.close()

        return _parse_impact_json(response)

    except Exception as exc:
        logger.warning(f"Impact analysis LLM call failed: {exc}")
        return _fallback_impact(old_clause, new_clause)


def _parse_impact_json(response: str) -> Dict:
    """
    Parses the LLM's JSON response.
    Handles cases where the LLM wraps JSON in markdown code fences.
    """
    # Strip markdown code fences if present
    response = response.strip()
    response = re.sub(r"^```(?:json)?\s*", "", response)
    response = re.sub(r"\s*```$", "", response)
    response = response.strip()

    try:
        data = json.loads(response)
        return {
            "summary": str(data.get("summary", "No summary available.")),
            "affected_area": str(data.get("affected_area", "General compliance")),
            "risk_direction": _validate_risk_direction(data.get("risk_direction")),
        }
    except json.JSONDecodeError:
        # LLM returned natural language instead of JSON — extract what we can
        logger.warning(f"LLM returned non-JSON response: {response[:200]}")
        return {
            "summary": response[:500] if len(response) > 10 else "Impact analysis unavailable.",
            "affected_area": "General compliance",
            "risk_direction": "unchanged",
        }


def _validate_risk_direction(value: Optional[str]) -> str:
    """Ensures risk_direction is one of the allowed values."""
    allowed = {"increased", "decreased", "unchanged"}
    if value and str(value).lower() in allowed:
        return str(value).lower()
    return "unchanged"


def _fallback_impact(old_clause: Optional[str], new_clause: Optional[str]) -> Dict:
    """Returns a generic fallback impact when the LLM is unavailable."""
    if new_clause is None:
        return {
            "summary": "A regulatory clause was removed. Review impact on related internal policies.",
            "affected_area": "General compliance",
            "risk_direction": "increased",
        }
    if old_clause is None:
        return {
            "summary": "A new regulatory clause has been introduced. Review for compliance implications.",
            "affected_area": "General compliance",
            "risk_direction": "increased",
        }
    return {
        "summary": "This regulatory clause was modified. Review to determine impact on existing policies.",
        "affected_area": "General compliance",
        "risk_direction": "unchanged",
    }


# ── Policy Conflict Check ─────────────────────────────────────────────────────

active_checks = set()


def is_checking_policy(policy_id: int) -> bool:
    """Returns True if the policy document is currently undergoing conflict check."""
    return policy_id in active_checks


def run_policy_conflict_check(policy_id: int) -> None:
    """
    Background task: checks a policy document against regulations scoped to its domain.

    Pipeline:
      0. Classify the policy document's compliance domain (KYC, AML, Securities, etc.)
      1. For each policy clause, retrieve ONLY regulations applicable to that domain
      2. Ask the LLM to determine if there's a REAL conflict (domain context provided)
      3. Store results as PolicyConflict records

    Args:
        policy_id: The ID of the PolicyDocument to check.
    """
    from app.db.session import get_db_context
    from app.db.models import PolicyDocument, PolicyConflict, ChangeRecord
    from app.diffing.clause_splitter import split_into_clauses
    from app.diffing.policy_classifier import classify_policy
    from app.retrieval.hybrid_retriever import HybridRetriever
    from app.llm.groq_client import GroqClient
    import asyncio

    logger.info(f"Starting policy conflict check for policy {policy_id}")
    active_checks.add(policy_id)

    try:
        with get_db_context() as db:
            policy = db.query(PolicyDocument).filter(PolicyDocument.id == policy_id).first()
            if not policy:
                logger.error(f"Policy {policy_id} not found")
                return

            # Clear existing conflicts before checking
            db.query(PolicyConflict).filter(PolicyConflict.policy_id == policy_id).delete()
            db.commit()

            # ── Step 0: Classify the policy domain ────────────────────────────
            logger.info(f"[POLICY CLASSIFIER] Classifying policy {policy_id}...")
            classification = classify_policy(policy.raw_text)
            logger.info(
                f"[POLICY CLASSIFIER] Domain: {classification.domain} | "
                f"Regulators: {classification.regulators} | "
                f"Confidence: {classification.confidence:.2f}"
            )

            # Store domain on the policy record if the column exists
            if hasattr(policy, "policy_domain"):
                policy.policy_domain = classification.domain
                policy.policy_domain_confidence = classification.confidence
                db.commit()

            applicable_regulators_str = ", ".join(classification.regulators)

            # ── Step 1: Split policy into clauses ─────────────────────────────
            policy_clauses = split_into_clauses(policy.raw_text)
            logger.info(f"Policy has {len(policy_clauses)} clauses to check")

            retriever = HybridRetriever()
            client = GroqClient()

            for policy_clause in policy_clauses:
                if len(policy_clause.text) < 50:
                    continue  # Skip very short clauses (likely headers)

                try:
                    # ── Step 2: Retrieve DOMAIN-SCOPED regulatory chunks ───────
                    relevant_chunks = retriever.search(
                        query=policy_clause.text[:500],
                        top_k=3,
                        regulator_filter=classification.regulators,
                        domain_keywords=classification.domain_keywords,
                    )

                    for chunk in relevant_chunks:
                        regulation_text = chunk["text"]
                        regulation_source = (
                            f"{chunk.get('regulator', 'Unknown')} — "
                            f"{chunk.get('doc_title', 'regulatory document')}"
                        )

                        # ── Step 3: Domain-aware conflict check ────────────────
                        prompt = build_policy_conflict_prompt(
                            policy_clause=policy_clause.text,
                            regulation_clause=regulation_text,
                            policy_domain=classification.domain,
                            applicable_regulators=applicable_regulators_str,
                            regulation_source=regulation_source,
                        )

                        loop = asyncio.new_event_loop()
                        response = loop.run_until_complete(client.complete(prompt))
                        loop.close()

                        result = _parse_conflict_json(response)

                        # Find a matching ChangeRecord for this regulation chunk
                        change_record = (
                            db.query(ChangeRecord)
                            .filter(ChangeRecord.new_clause.contains(regulation_text[:100]))
                            .first()
                        )

                        conflict = PolicyConflict(
                            policy_id=policy_id,
                            change_record_id=change_record.id if change_record else None,
                            policy_clause=policy_clause.text,
                            regulation_clause=regulation_text,
                            conflict=result.get("conflict", False),
                            explanation=result.get("explanation"),
                            suggested_fix=result.get("suggested_fix"),
                            conflict_score=0.9 if result.get("conflict") else 0.1,
                        )
                        db.add(conflict)

                except Exception as exc:
                    logger.warning(f"Conflict check failed for policy clause {policy_clause.id}: {exc}")
    finally:
        active_checks.discard(policy_id)

    logger.info(f"Policy conflict check complete for policy {policy_id}")


def _parse_conflict_json(response: str) -> Dict:
    """Parses the LLM's conflict check JSON response."""
    response = response.strip()
    response = re.sub(r"^```(?:json)?\s*", "", response)
    response = re.sub(r"\s*```$", "", response)

    try:
        data = json.loads(response.strip())
        return {
            "conflict": bool(data.get("conflict", False)),
            "explanation": str(data.get("explanation", "")),
            "suggested_fix": str(data.get("suggested_fix", "")),
        }
    except json.JSONDecodeError:
        return {
            "conflict": False,
            "explanation": response[:500],
            "suggested_fix": "",
        }
