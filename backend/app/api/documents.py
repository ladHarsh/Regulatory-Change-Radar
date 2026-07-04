"""
api/documents.py — Endpoints for managing regulatory documents.

Routes:
  POST /api/documents/ingest       — Trigger scraping + ingestion of new circulars
  GET  /api/documents              — List all ingested regulatory documents
  GET  /api/documents/{id}         — Get a single document by ID
  GET  /api/documents/{id}/versions — Version history of a document
"""
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from loguru import logger

from app.db.models import Document, DocumentVersion
from app.db.session import get_db

router = APIRouter(prefix="/api/documents", tags=["documents"])


# ── Pydantic Response Schemas ─────────────────────────────────────────────────

class DocumentVersionOut(BaseModel):
    id: int
    version_num: int
    content_hash: str
    page_count: int
    ingested_at: str

    class Config:
        from_attributes = True


class DocumentOut(BaseModel):
    id: int
    regulator: str
    title: str
    url: str
    doc_type: str
    created_at: str
    version_count: int

    class Config:
        from_attributes = True


class IngestRequest(BaseModel):
    regulators: List[str] = ["RBI", "SEBI"]
    max_docs: int = 10


class IngestResponse(BaseModel):
    status: str
    message: str
    task_id: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/ingest", response_model=IngestResponse)
async def trigger_ingestion(
    request: IngestRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Triggers the ingestion pipeline in the background.
    Scrapes public RBI/SEBI circular pages, downloads PDFs,
    parses, chunks, embeds, and stores them.
    Returns immediately with a task status.
    """
    logger.info(f"API: Ingestion requested via POST /api/documents/ingest with regulators={request.regulators}, max_docs={request.max_docs}")
    
    # Import here to avoid circular imports and heavy startup cost
    from app.ingestion.pipeline import run_ingestion_pipeline
    # Invalidate the query cache whenever new documents are ingested
    from app.rag.pipeline import clear_query_cache
    clear_query_cache()

    background_tasks.add_task(
        run_ingestion_pipeline,
        regulators=request.regulators,
        max_docs=request.max_docs,
    )

    logger.info("API: Ingestion background task scheduled successfully.")

    return IngestResponse(
        status="started",
        message=f"Ingestion started for {request.regulators}. Check /api/documents for results.",
    )


@router.get("", response_model=List[DocumentOut])
def list_documents(
    regulator: Optional[str] = Query(None, description="Filter by regulator: RBI | SEBI | IRDAI"),
    db: Session = Depends(get_db),
):
    """
    Returns all ingested regulatory documents.
    Optionally filter by regulator.
    """
    query = db.query(Document)
    if regulator:
        query = query.filter(Document.regulator == regulator.upper())

    documents = query.order_by(Document.created_at.desc()).all()

    result = []
    for doc in documents:
        result.append(
            DocumentOut(
                id=doc.id,
                regulator=doc.regulator,
                title=doc.title,
                url=doc.url,
                doc_type=doc.doc_type,
                created_at=doc.created_at.isoformat(),
                version_count=len(doc.versions),
            )
        )
    return result


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: int, db: Session = Depends(get_db)):
    """Returns a single document by its ID."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    return DocumentOut(
        id=doc.id,
        regulator=doc.regulator,
        title=doc.title,
        url=doc.url,
        doc_type=doc.doc_type,
        created_at=doc.created_at.isoformat(),
        version_count=len(doc.versions),
    )


@router.get("/{doc_id}/versions", response_model=List[DocumentVersionOut])
def get_document_versions(doc_id: int, db: Session = Depends(get_db)):
    """Returns the version history for a specific document."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    versions = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.document_id == doc_id)
        .order_by(DocumentVersion.version_num.desc())
        .all()
    )

    return [
        DocumentVersionOut(
            id=v.id,
            version_num=v.version_num,
            content_hash=v.content_hash,
            page_count=v.page_count,
            ingested_at=v.ingested_at.isoformat(),
        )
        for v in versions
    ]
