"""
api/search.py — Fast BM25 keyword search endpoint (no LLM).
Uses the existing BM25 index for instant, zero-cost document and change search.

Routes:
  GET /api/search?q=text&type=document|change
"""
from typing import List, Optional

from fastapi import APIRouter, Query, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import Document, ChangeRecord
from app.db.session import get_db

router = APIRouter(prefix="/api/search", tags=["search"])


class SearchResultOut(BaseModel):
    type: str          # "document" | "change"
    id: int
    title: str
    snippet: str
    score: float
    regulator: Optional[str] = None


@router.get("", response_model=List[SearchResultOut])
def keyword_search(
    q: str = Query(..., min_length=1, description="Search query"),
    type: Optional[str] = Query(None, description="Filter: document | change"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Fast keyword search using SQL LIKE over document titles and change summaries.
    This intentionally avoids the LLM — use /api/query for semantic search.
    """
    results: List[SearchResultOut] = []
    query_lower = f"%{q.lower()}%"

    # Search documents
    if type in (None, "document"):
        docs = (
            db.query(Document)
            .filter(Document.title.ilike(query_lower))
            .limit(limit)
            .all()
        )
        for doc in docs:
            # Score: how early in the title the term appears
            score = 1.0 - (doc.title.lower().find(q.lower()) / max(len(doc.title), 1))
            results.append(SearchResultOut(
                type="document",
                id=doc.id,
                title=doc.title,
                snippet=doc.title[:200],
                score=round(score, 4),
                regulator=doc.regulator,
            ))

    # Search change records
    if type in (None, "change"):
        changes = (
            db.query(ChangeRecord)
            .filter(
                ChangeRecord.change_type != "UNCHANGED",
                (
                    ChangeRecord.impact_summary.ilike(query_lower) |
                    ChangeRecord.new_clause.ilike(query_lower) |
                    ChangeRecord.affected_area.ilike(query_lower)
                )
            )
            .order_by(ChangeRecord.detected_at.desc())
            .limit(limit)
            .all()
        )
        for c in changes:
            text = c.impact_summary or c.new_clause or ""
            idx = text.lower().find(q.lower())
            snippet = text[max(0, idx - 40): idx + 120].strip() if idx >= 0 else text[:120]
            score = 0.7 if c.severity == "High" else 0.5 if c.severity == "Medium" else 0.3
            results.append(SearchResultOut(
                type="change",
                id=c.id,
                title=f"{c.change_type}: {text[:60]}{'…' if len(text) > 60 else ''}",
                snippet=snippet,
                score=round(score, 4),
                regulator=None,
            ))

    # Sort by score descending
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:limit]
