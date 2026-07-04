"""
api/changes.py — Endpoints for the regulatory change timeline.

Routes:
  GET /api/changes/timeline — Chronological feed of detected regulatory changes
  GET /api/changes/{id}    — Detailed diff + LLM impact summary for one change
  GET /api/changes/stats   — Summary statistics for the dashboard
"""
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.db.models import ChangeRecord, Document, DocumentVersion
from app.db.session import get_db

router = APIRouter(prefix="/api/changes", tags=["changes"])


# ── Pydantic Response Schemas ─────────────────────────────────────────────────

class ChangeRecordOut(BaseModel):
    id: int
    change_type: str              # MODIFIED | NEW | REMOVED
    severity: Optional[str]       # High | Medium | Low
    regulator: Optional[str]
    doc_title: Optional[str]
    old_clause: Optional[str]
    new_clause: Optional[str]
    old_section_ref: Optional[str]
    new_section_ref: Optional[str]
    impact_summary: Optional[str]
    affected_area: Optional[str]
    risk_direction: Optional[str]
    similarity_score: Optional[float]
    detected_at: str

    class Config:
        from_attributes = True


class ChangeStats(BaseModel):
    total_changes: int
    changes_this_month: int
    high_severity_count: int
    medium_severity_count: int
    low_severity_count: int
    last_detected_at: Optional[str]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/stats", response_model=ChangeStats)
def get_change_stats(db: Session = Depends(get_db)):
    """
    Returns aggregate statistics used by the dashboard stat cards.
    """
    total = db.query(ChangeRecord).filter(ChangeRecord.change_type != "UNCHANGED").count()

    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    this_month = (
        db.query(ChangeRecord)
        .filter(ChangeRecord.change_type != "UNCHANGED", ChangeRecord.detected_at >= month_start)
        .count()
    )

    high = db.query(ChangeRecord).filter(ChangeRecord.severity == "High").count()
    medium = db.query(ChangeRecord).filter(ChangeRecord.severity == "Medium").count()
    low = db.query(ChangeRecord).filter(ChangeRecord.severity == "Low").count()

    last = (
        db.query(ChangeRecord)
        .filter(ChangeRecord.change_type != "UNCHANGED")
        .order_by(ChangeRecord.detected_at.desc())
        .first()
    )

    return ChangeStats(
        total_changes=total,
        changes_this_month=this_month,
        high_severity_count=high,
        medium_severity_count=medium,
        low_severity_count=low,
        last_detected_at=last.detected_at.isoformat() if last else None,
    )


@router.get("/timeline", response_model=List[ChangeRecordOut])
def get_timeline(
    regulator: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    change_type: Optional[str] = Query(None),
    days: Optional[int] = Query(None, description="Limit to last N days"),
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """
    Returns chronological feed of regulatory changes.
    Supports filtering by regulator, severity, change_type, and date range.
    """
    query = (
        db.query(ChangeRecord)
        .options(
            joinedload(ChangeRecord.new_version).joinedload(DocumentVersion.document)
        )
        .filter(ChangeRecord.change_type != "UNCHANGED")
        .order_by(ChangeRecord.detected_at.desc())
    )

    if severity:
        query = query.filter(ChangeRecord.severity == severity)
    if change_type:
        query = query.filter(ChangeRecord.change_type == change_type.upper())
    if days:
        cutoff = datetime.utcnow() - timedelta(days=days)
        query = query.filter(ChangeRecord.detected_at >= cutoff)
    if regulator:
        # Subquery to find change IDs belonging to this regulator
        matching_ids = (
            db.query(ChangeRecord.id)
            .join(ChangeRecord.new_version)
            .join(DocumentVersion.document)
            .filter(Document.regulator == regulator.upper())
            .subquery()
        )
        query = query.filter(ChangeRecord.id.in_(matching_ids))

    changes = query.offset(skip).limit(limit).all()

    return [_change_to_out(c) for c in changes]


@router.get("/{change_id}", response_model=ChangeRecordOut)
def get_change(change_id: int, db: Session = Depends(get_db)):
    """
    Returns full detail for a single change record including the complete
    old/new clause text and LLM impact summary.
    """
    change = (
        db.query(ChangeRecord)
        .options(
            joinedload(ChangeRecord.new_version).joinedload(DocumentVersion.document),
            joinedload(ChangeRecord.old_version),
        )
        .filter(ChangeRecord.id == change_id)
        .first()
    )
    if not change:
        raise HTTPException(status_code=404, detail=f"Change {change_id} not found")

    return _change_to_out(change)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _change_to_out(change: ChangeRecord) -> ChangeRecordOut:
    """Converts a ChangeRecord ORM object to its Pydantic output model."""
    regulator = None
    doc_title = None
    if change.new_version and change.new_version.document:
        regulator = change.new_version.document.regulator
        doc_title = change.new_version.document.title

    return ChangeRecordOut(
        id=change.id,
        change_type=change.change_type,
        severity=change.severity,
        regulator=regulator,
        doc_title=doc_title,
        old_clause=change.old_clause,
        new_clause=change.new_clause,
        old_section_ref=change.old_section_ref,
        new_section_ref=change.new_section_ref,
        impact_summary=change.impact_summary,
        affected_area=change.affected_area,
        risk_direction=change.risk_direction,
        similarity_score=change.similarity_score,
        detected_at=change.detected_at.isoformat(),
    )
