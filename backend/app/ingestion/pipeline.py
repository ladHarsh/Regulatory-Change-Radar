"""
ingestion/pipeline.py — Orchestrates the full ingestion pipeline.

Called by the /api/documents/ingest endpoint as a background task.
Steps:
  1. Scrape circular listings from each regulator
  2. Download each document
  3. Parse PDF/HTML → clean text
  4. Version check — skip if content unchanged
  5. Chunk the text
  6. Embed chunks + store in ChromaDB
  7. Rebuild BM25 index
  8. Run semantic diff against previous version (if exists)
"""
import os
from typing import List

from loguru import logger

from app.config import get_settings
from app.db.session import get_db_context
from app.ingestion.scraper import scrape_circulars, download_document
from app.ingestion.parser import parse_url, parse_pdf
from app.ingestion.chunker import chunk_document
from app.ingestion.versioner import (
    get_or_create_document,
    create_version_if_new,
    get_previous_version,
)

settings = get_settings()


def run_ingestion_pipeline(
    regulators: List[str] = None,
    max_docs: int = 10,
) -> dict:
    """
    Full ingestion pipeline — safe to run as a background task.
    Returns a summary dict with counts of new/updated documents.

    Args:
        regulators: List of regulator codes (default: ["RBI", "SEBI"]).
        max_docs:   Max documents to fetch per regulator.
    """
    if regulators is None:
        regulators = ["RBI", "SEBI"]

    logger.info(f"[SYNC PIPELINE] Starting ingestion pipeline for {regulators}, max_docs={max_docs}")

    # ── Step 1: Scrape ────────────────────────────────────────────────────────
    logger.info("[SYNC PIPELINE] Step 1: Initiating scraping of regulator listing pages...")
    circular_metadata = scrape_circulars(regulators=regulators, max_docs=max_docs)
    logger.info(f"[SYNC PIPELINE] Step 1 Complete: Scraped metadata for {len(circular_metadata)} circulars. Details: {[c.get('url') for c in circular_metadata]}")

    docs_dir = os.path.join(settings.data_dir, "documents")
    os.makedirs(docs_dir, exist_ok=True)
    logger.info(f"[SYNC PIPELINE] Download folder ready at: {docs_dir}")

    new_versions = []
    skipped = 0
    errors = 0

    with get_db_context() as db:
        logger.info("[SYNC PIPELINE] Database connection opened for processing circular metadata.")
        for idx, meta in enumerate(circular_metadata, 1):
            try:
                url = meta["url"]
                regulator = meta["regulator"]
                title = meta["title"]
                pdf_url = meta.get("pdf_url") or url

                logger.info(f"[SYNC PIPELINE] Processing doc {idx}/{len(circular_metadata)}: '{title}' ({regulator})")
                logger.info(f"[SYNC PIPELINE] Source URL: {url} | PDF URL: {pdf_url}")

                # ── Step 2: Download ──────────────────────────────────────────
                safe_name = _safe_filename(title or url.split("/")[-1])
                ext = ".pdf" if pdf_url.endswith(".pdf") else ".html"
                file_path = os.path.join(docs_dir, f"{regulator}_{safe_name[:80]}{ext}")

                logger.info(f"[SYNC PIPELINE] Step 2: Downloading document to {file_path}")
                success = download_document(pdf_url or url, file_path)
                logger.info(f"[SYNC PIPELINE] Step 2 Status: Download success={success}")
                
                if not success:
                    logger.warning(f"[SYNC PIPELINE] Direct download failed for {pdf_url}. Attempting to parse raw URL {url} directly...")
                    # Try parsing URL directly without saving
                    try:
                        parsed = parse_url(url)
                        logger.info("[SYNC PIPELINE] Successfully parsed raw URL content.")
                    except Exception as parse_err:
                        logger.error(f"[SYNC PIPELINE] Failed to parse raw URL directly: {parse_err}")
                        errors += 1
                        continue
                    raw_text = parsed["text"]
                    page_count = parsed["page_count"]
                    file_path = None
                else:
                    # ── Step 3: Parse ─────────────────────────────────────────
                    logger.info(f"[SYNC PIPELINE] Step 3: Parsing document content from {file_path}...")
                    if file_path and file_path.endswith(".pdf"):
                        parsed = parse_pdf(file_path)
                    else:
                        parsed = parse_url(url)
                    raw_text = parsed["text"]
                    page_count = parsed["page_count"]
                    logger.info(f"[SYNC PIPELINE] Step 3 Complete: Parsed {len(raw_text or '')} characters, Page count={page_count}")

                if not raw_text or len(raw_text) < 100:
                    logger.warning(f"[SYNC PIPELINE] Skipping {url}: too little text extracted ({len(raw_text or '')} chars)")
                    skipped += 1
                    continue

                # ── Step 4: Version check ─────────────────────────────────────
                logger.info(f"[SYNC PIPELINE] Step 4: Performing database version check for URL: {url}")
                document = get_or_create_document(
                    db=db,
                    regulator=regulator,
                    title=title,
                    url=url,
                    doc_type=meta.get("doc_type", "circular"),
                )
                logger.info(f"[SYNC PIPELINE] Document ID in DB: {document.id}")

                version, is_new = create_version_if_new(
                    db=db,
                    document=document,
                    raw_text=raw_text,
                    file_path=file_path,
                    page_count=page_count,
                )
                logger.info(f"[SYNC PIPELINE] Version check result: is_new={is_new}, Version ID={version.id if version else None}")

                if not is_new:
                    logger.info(f"[SYNC PIPELINE] Content is identical to previous version. Skipping remaining processing for doc {idx}.")
                    skipped += 1
                    continue

                new_versions.append((document.id, version.id))
                logger.info(f"[SYNC PIPELINE] Added Document {document.id} / Version {version.id} to indexing queue.")

            except Exception as exc:
                logger.error(f"[SYNC PIPELINE] Error processing circular index {idx} ({meta.get('url', '?')}): {exc}")
                errors += 1

    logger.info(f"[SYNC PIPELINE] Finished database transactional stage. Total new versions to process: {len(new_versions)}")
    # ── Steps 5-8: Embed + index + diff (outside the DB context) ─────────────
    for doc_id, version_id in new_versions:
        try:
            logger.info(f"[SYNC PIPELINE] Initiating index/chunk/diff pipeline for Doc ID {doc_id}, Version ID {version_id}...")
            _process_new_version(doc_id, version_id)
            logger.info(f"[SYNC PIPELINE] Completed index/chunk/diff pipeline for Doc ID {doc_id}, Version ID {version_id}")
        except Exception as exc:
            logger.error(f"[SYNC PIPELINE] Critical exception in post-version processing (Doc={doc_id}, Ver={version_id}): {exc}")
            errors += 1

    summary = {
        "total_scraped": len(circular_metadata),
        "new_versions": len(new_versions),
        "skipped_unchanged": skipped,
        "errors": errors,
    }
    logger.info(f"[SYNC PIPELINE] Ingestion flow finished. Result Summary: {summary}")
    return summary


def _process_new_version(doc_id: int, version_id: int) -> None:
    """
    Handles embedding, indexing, and diffing for a newly created version.
    """
    from app.retrieval.vector_store import VectorStore
    from app.retrieval.bm25_index import BM25Index
    from app.diffing.semantic_diff import run_semantic_diff

    with get_db_context() as db:
        # Reload from DB in this context
        from app.db.models import DocumentVersion, Document
        version = db.query(DocumentVersion).filter(DocumentVersion.id == version_id).first()
        document = db.query(Document).filter(Document.id == doc_id).first()

        if not version or not document:
            return

        # ── Step 5: Chunk ─────────────────────────────────────────────────────
        logger.info(f"[PROCESSOR] Step 5: Starting chunking for Doc ID {document.id}, Version ID {version.id}...")
        chunks = chunk_document(
            text=version.raw_text,
            doc_id=document.id,
            version_id=version.id,
            regulator=document.regulator,
            doc_title=document.title,
        )
        logger.info(f"[PROCESSOR] Step 5 Complete: Created {len(chunks)} chunks.")

        # ── Step 6: Store chunks in DB + ChromaDB ────────────────────────────
        logger.info(f"[PROCESSOR] Step 6: Writing chunks to relational database + vector store...")
        vector_store = VectorStore()
        from app.db.models import DocumentChunk

        for chunk in chunks:
            db_chunk = DocumentChunk(
                version_id=version.id,
                chunk_index=chunk["chunk_index"],
                chunk_id=chunk["chunk_id"],
                text=chunk["text"],
                token_count=chunk["token_count"],
            )
            db.add(db_chunk)

        db.flush()
        logger.info(f"[PROCESSOR] Saved chunks database table.")

        # Add to ChromaDB
        logger.info(f"[PROCESSOR] Inserting chunks into ChromaDB index...")
        vector_store.add_chunks(chunks)
        logger.info(f"[PROCESSOR] Step 6 Complete: Chunks indexed successfully in DB & ChromaDB.")

        # ── Step 7: Rebuild BM25 index ────────────────────────────────────────
        logger.info(f"[PROCESSOR] Step 7: Rebuilding BM25 keyword index...")
        bm25 = BM25Index()
        bm25.rebuild(db)
        logger.info(f"[PROCESSOR] Step 7 Complete: BM25 index rebuilt.")

        # ── Step 8: Semantic diff against previous version ───────────────────
        logger.info(f"[PROCESSOR] Step 8: Resolving previous version history for document...")
        previous = get_previous_version(db, version)
        if previous:
            logger.info(
                f"[PROCESSOR] Found previous version. Running semantic diff: version {previous.version_num} → {version.version_num} "
                f"for document {document.id}"
            )
            run_semantic_diff(
                db=db,
                old_version=previous,
                new_version=version,
            )
        else:
            logger.info(
                f"[PROCESSOR] No previous version for document {document.id} — "
                f"tagging all clauses as NEW"
            )
            run_semantic_diff(
                db=db,
                old_version=None,
                new_version=version,
            )
        logger.info(f"[PROCESSOR] Step 8 Complete: Semantic diff completed successfully.")


def _safe_filename(name: str) -> str:
    """Sanitizes a string for use as a filename."""
    import re
    return re.sub(r'[^\w\-_. ]', '_', name).strip()
