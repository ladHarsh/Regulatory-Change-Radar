"""
ingestion/versioner.py — Detects and tracks new document versions.

Uses MD5 content hashing to determine if a document has changed since it was
last ingested. If the hash is new, creates a new DocumentVersion record.
"""
import hashlib
import os
from typing import Optional, Tuple

from loguru import logger
from sqlalchemy.orm import Session

from app.db.models import Document, DocumentVersion


def compute_content_hash(text: str) -> str:
    """
    Computes an MD5 hash of document text for change detection.
    MD5 is sufficient here — we're detecting accidental content changes,
    not defending against adversarial collisions.
    """
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def get_or_create_document(
    db: Session,
    regulator: str,
    title: str,
    url: str,
    doc_type: str = "circular",
) -> Document:
    """
    Returns the existing Document record for this URL, or creates a new one.

    Args:
        db:        SQLAlchemy session.
        regulator: "RBI" | "SEBI" | "IRDAI".
        title:     Document title.
        url:       Canonical URL (used as unique key).
        doc_type:  "circular" | "guideline" | "notification".

    Returns:
        Document ORM instance.
    """
    doc = db.query(Document).filter(Document.url == url).first()

    if doc:
        logger.debug(f"Document already exists: {url}")
        return doc

    doc = Document(
        regulator=regulator.upper(),
        title=title,
        url=url,
        doc_type=doc_type,
    )
    db.add(doc)
    db.flush()  # Get the ID without committing
    logger.info(f"Created new document: [{regulator}] {title}")
    return doc


def create_version_if_new(
    db: Session,
    document: Document,
    raw_text: str,
    file_path: Optional[str] = None,
    page_count: int = 0,
) -> Tuple[Optional[DocumentVersion], bool]:
    """
    Creates a new DocumentVersion if the content hash is different from the latest.

    Args:
        db:         SQLAlchemy session.
        document:   Parent Document ORM instance.
        raw_text:   Full parsed text of the document.
        file_path:  Optional local file path.
        page_count: Number of pages in the source document.

    Returns:
        Tuple of (DocumentVersion | None, is_new: bool).
        Returns (existing_version, False) if content hasn't changed.
        Returns (new_version, True) if this is a new or changed version.
    """
    content_hash = compute_content_hash(raw_text)

    # Check if this hash already exists for this document
    existing = (
        db.query(DocumentVersion)
        .filter(
            DocumentVersion.document_id == document.id,
            DocumentVersion.content_hash == content_hash,
        )
        .first()
    )

    if existing:
        logger.info(f"Document {document.id} has not changed (hash: {content_hash[:8]}…)")
        return existing, False

    # Find the next version number
    latest_version = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.document_id == document.id)
        .order_by(DocumentVersion.version_num.desc())
        .first()
    )
    next_version_num = (latest_version.version_num + 1) if latest_version else 1

    version = DocumentVersion(
        document_id=document.id,
        version_num=next_version_num,
        content_hash=content_hash,
        raw_text=raw_text,
        file_path=file_path,
        page_count=page_count,
    )
    db.add(version)
    db.flush()  # Get the ID

    logger.info(
        f"New version {next_version_num} for document {document.id} "
        f"({document.title[:50]}…): hash {content_hash[:8]}…"
    )
    return version, True


def get_previous_version(db: Session, version: DocumentVersion) -> Optional[DocumentVersion]:
    """
    Returns the immediately preceding version of the same document, if any.
    Used by the diffing engine to compare old vs. new.
    """
    if version.version_num <= 1:
        return None

    return (
        db.query(DocumentVersion)
        .filter(
            DocumentVersion.document_id == version.document_id,
            DocumentVersion.version_num == version.version_num - 1,
        )
        .first()
    )
