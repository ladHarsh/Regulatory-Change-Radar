"""
diffing/semantic_diff.py — The core clause-level semantic diff engine.

This is the differentiating IP of the Regulatory Change Radar.

Algorithm:
  1. Split both document versions into clause-level units
  2. Embed every clause from both versions
  3. For each clause in the NEW version, find its best match in the OLD version
     via cosine similarity
  4. Classify each match:
       UNCHANGED  → similarity > DIFF_UNCHANGED_THRESHOLD (default 0.95)
       MODIFIED   → similarity between DIFF_MODIFIED_THRESHOLD (0.75) and 0.95
       NEW        → no good match (best similarity < DIFF_MODIFIED_THRESHOLD)
  5. OLD clauses that have no match in the NEW version → REMOVED
  6. For MODIFIED/NEW clauses: call the LLM for plain-English impact summaries
  7. Store all ChangeRecord rows in SQLite

This is NOT a text diff (like Python's difflib). It's a semantic comparison
that can detect paraphrased or restructured clauses — critical for regulatory
docs where the same requirement can be expressed differently.
"""
from typing import Dict, List, Optional, Tuple

import numpy as np
from loguru import logger
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import ChangeRecord, DocumentVersion
from app.diffing.clause_splitter import Clause, split_into_clauses
from app.retrieval.embeddings import embed_documents

settings = get_settings()


# ── Change Type Constants ─────────────────────────────────────────────────────
UNCHANGED = "UNCHANGED"
MODIFIED = "MODIFIED"
NEW = "NEW"
REMOVED = "REMOVED"


def _derive_severity(risk_direction: Optional[str], change_type: str) -> str:
    """
    Maps LLM-assigned risk direction + change type to a display severity.
    Used for color-coded badges in the UI.
    """
    if change_type == REMOVED:
        return "High"
    if risk_direction == "increased":
        return "High"
    if risk_direction == "decreased":
        return "Low"
    if change_type == NEW:
        return "Medium"
    return "Medium"


def run_semantic_diff(
    db: Session,
    old_version: Optional[DocumentVersion],
    new_version: DocumentVersion,
) -> List[ChangeRecord]:
    """
    Runs the full semantic diff pipeline between two document versions.

    If old_version is None (first ingestion), all clauses in new_version
    are tagged as NEW.

    Args:
        db:          SQLAlchemy session (must be within a transaction context).
        old_version: Previous DocumentVersion (may be None for first ingestion).
        new_version: Newly ingested DocumentVersion.

    Returns:
        List of created ChangeRecord ORM instances.
    """
    logger.info(
        f"Starting semantic diff: "
        f"old_version={old_version.id if old_version else 'None'} → "
        f"new_version={new_version.id}"
    )

    # ── Step 1: Split into clauses ────────────────────────────────────────────
    new_clauses = split_into_clauses(new_version.raw_text)
    old_clauses = split_into_clauses(old_version.raw_text) if old_version else []

    logger.info(
        f"Clause extraction: {len(old_clauses)} old clauses, {len(new_clauses)} new clauses"
    )

    if not new_clauses:
        logger.warning(f"No clauses extracted from new version {new_version.id}")
        return []

    # ── Step 2: Embed all clauses ─────────────────────────────────────────────
    new_texts = [c.text for c in new_clauses]
    new_embeddings = embed_documents(new_texts)  # shape: (N_new, dim)

    if old_clauses:
        old_texts = [c.text for c in old_clauses]
        old_embeddings = embed_documents(old_texts)  # shape: (N_old, dim)
    else:
        old_embeddings = np.array([])

    # ── Step 3 & 4: Match and classify each new clause ────────────────────────
    change_results = _classify_new_clauses(
        new_clauses=new_clauses,
        new_embeddings=new_embeddings,
        old_clauses=old_clauses,
        old_embeddings=old_embeddings,
    )

    # ── Step 5: Detect REMOVED clauses ───────────────────────────────────────
    matched_old_ids = {r["matched_old_id"] for r in change_results if r["matched_old_id"] is not None}
    removed_clauses = [c for c in old_clauses if c.id not in matched_old_ids]

    # ── Step 6: LLM impact analysis ───────────────────────────────────────────
    from app.diffing.impact_analyzer import generate_impact_summary

    change_records = []
    lm_needed = [r for r in change_results if r["change_type"] in (MODIFIED, NEW)]

    logger.info(
        f"Diff result: "
        f"{sum(1 for r in change_results if r['change_type'] == UNCHANGED)} unchanged, "
        f"{sum(1 for r in change_results if r['change_type'] == MODIFIED)} modified, "
        f"{sum(1 for r in change_results if r['change_type'] == NEW)} new, "
        f"{len(removed_clauses)} removed"
    )

    # Generate impact summaries for changed clauses
    for result in lm_needed:
        try:
            impact = generate_impact_summary(
                old_clause=result.get("old_clause_text"),
                new_clause=result["new_clause_text"],
            )
        except Exception as exc:
            logger.warning(f"LLM impact analysis failed: {exc}")
            impact = {
                "summary": "Impact analysis unavailable.",
                "affected_area": "Unknown",
                "risk_direction": "unchanged",
            }

        severity = _derive_severity(impact.get("risk_direction"), result["change_type"])

        record = ChangeRecord(
            old_version_id=old_version.id if old_version else None,
            new_version_id=new_version.id,
            change_type=result["change_type"],
            similarity_score=result.get("similarity_score"),
            old_clause=result.get("old_clause_text"),
            new_clause=result["new_clause_text"],
            old_section_ref=result.get("old_section_ref"),
            new_section_ref=result.get("new_section_ref"),
            impact_summary=impact.get("summary"),
            affected_area=impact.get("affected_area"),
            risk_direction=impact.get("risk_direction"),
            severity=severity,
        )
        db.add(record)
        change_records.append(record)

    # ── Store REMOVED clauses ─────────────────────────────────────────────────
    for clause in removed_clauses:
        try:
            impact = generate_impact_summary(
                old_clause=clause.text,
                new_clause=None,
            )
        except Exception:
            impact = {
                "summary": f"Clause '{clause.section_ref or 'Unknown'}' was removed from the regulation.",
                "affected_area": "Unknown",
                "risk_direction": "increased",
            }

        record = ChangeRecord(
            old_version_id=old_version.id if old_version else None,
            new_version_id=new_version.id,
            change_type=REMOVED,
            similarity_score=None,
            old_clause=clause.text,
            new_clause=None,
            old_section_ref=clause.section_ref,
            new_section_ref=None,
            impact_summary=impact.get("summary"),
            affected_area=impact.get("affected_area"),
            risk_direction=impact.get("risk_direction"),
            severity="High",  # Removals are always High severity
        )
        db.add(record)
        change_records.append(record)

    db.flush()
    logger.info(f"Semantic diff complete: {len(change_records)} ChangeRecords created")
    return change_records


def _classify_new_clauses(
    new_clauses: List[Clause],
    new_embeddings: np.ndarray,
    old_clauses: List[Clause],
    old_embeddings: np.ndarray,
) -> List[Dict]:
    """
    For each new clause, find its best match in the old version and classify it.

    Returns a list of result dicts with change classification and matched clause info.
    """
    unchanged_threshold = settings.diff_unchanged_threshold
    modified_threshold = settings.diff_modified_threshold

    results = []

    for i, new_clause in enumerate(new_clauses):
        new_emb = new_embeddings[i]

        if len(old_embeddings) == 0:
            # No old version — everything is NEW
            results.append({
                "new_clause_text": new_clause.text,
                "new_section_ref": new_clause.section_ref,
                "old_clause_text": None,
                "old_section_ref": None,
                "matched_old_id": None,
                "similarity_score": None,
                "change_type": NEW,
            })
            continue

        # Compute cosine similarity against all old clause embeddings
        # Since embeddings are L2-normalized, this is just a dot product
        similarities = old_embeddings @ new_emb  # shape: (N_old,)

        best_idx = int(np.argmax(similarities))
        best_score = float(similarities[best_idx])
        best_old_clause = old_clauses[best_idx]

        # ── Classification ────────────────────────────────────────────────────
        if best_score >= unchanged_threshold:
            change_type = UNCHANGED
        elif best_score >= modified_threshold:
            change_type = MODIFIED
        else:
            change_type = NEW
            best_old_clause = None  # No meaningful match

        results.append({
            "new_clause_text": new_clause.text,
            "new_section_ref": new_clause.section_ref,
            "old_clause_text": best_old_clause.text if best_old_clause else None,
            "old_section_ref": best_old_clause.section_ref if best_old_clause else None,
            "matched_old_id": best_old_clause.id if best_old_clause else None,
            "similarity_score": best_score,
            "change_type": change_type,
        })

    return results
