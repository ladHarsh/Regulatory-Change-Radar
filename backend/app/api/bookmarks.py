"""
api/bookmarks.py — Bookmark endpoints for v2.0.

Routes:
  GET    /api/bookmarks          — List all bookmarks
  POST   /api/bookmarks          — Create a bookmark
  DELETE /api/bookmarks/{id}     — Delete a bookmark
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.db.models import Bookmark, Document, ChangeRecord
from app.db.session import get_db

router = APIRouter(prefix="/api/bookmarks", tags=["bookmarks"])


class BookmarkIn(BaseModel):
    document_id: Optional[int] = None
    change_record_id: Optional[int] = None


class BookmarkOut(BaseModel):
    id: int
    document_id: Optional[int]
    change_record_id: Optional[int]
    created_at: str
    doc_title: Optional[str] = None
    regulator: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("", response_model=List[BookmarkOut])
def list_bookmarks(db: Session = Depends(get_db)):
    bookmarks = (
        db.query(Bookmark)
        .options(
            joinedload(Bookmark.document),
            joinedload(Bookmark.change_record),
        )
        .order_by(Bookmark.created_at.desc())
        .all()
    )
    return [_bm_out(b) for b in bookmarks]


@router.post("", response_model=BookmarkOut, status_code=201)
def create_bookmark(payload: BookmarkIn, db: Session = Depends(get_db)):
    if not payload.document_id and not payload.change_record_id:
        raise HTTPException(status_code=400, detail="Provide document_id or change_record_id")
    bm = Bookmark(
        document_id=payload.document_id,
        change_record_id=payload.change_record_id,
    )
    db.add(bm)
    db.commit()
    db.refresh(bm)
    # reload with relationships
    bm = db.query(Bookmark).options(joinedload(Bookmark.document), joinedload(Bookmark.change_record)).filter(Bookmark.id == bm.id).first()
    return _bm_out(bm)


@router.delete("/{bookmark_id}", status_code=204)
def delete_bookmark(bookmark_id: int, db: Session = Depends(get_db)):
    bm = db.query(Bookmark).filter(Bookmark.id == bookmark_id).first()
    if not bm:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    db.delete(bm)
    db.commit()


def _bm_out(b: Bookmark) -> BookmarkOut:
    doc_title = None
    regulator = None
    if b.document:
        doc_title = b.document.title
        regulator = b.document.regulator
    elif b.change_record:
        doc_title = getattr(b.change_record, "impact_summary", None)
    return BookmarkOut(
        id=b.id,
        document_id=b.document_id,
        change_record_id=b.change_record_id,
        created_at=b.created_at.isoformat(),
        doc_title=doc_title,
        regulator=regulator,
    )
