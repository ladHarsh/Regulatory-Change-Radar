"""
retrieval/bm25_index.py — BM25 keyword search index using rank_bm25.

The index is built in-memory from all chunks stored in the database.
It is rebuilt whenever new documents are ingested. For production scale,
this would be persisted to disk — for this dataset size (hundreds of docs),
in-memory rebuild is fast (<1 second for ~5000 chunks).
"""
import pickle
import re
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger
from rank_bm25 import BM25Okapi
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import DocumentChunk, DocumentVersion, Document

settings = get_settings()

# Path to persist the serialized BM25 index
_BM25_CACHE_PATH = Path(settings.data_dir) / "bm25_index.pkl"


def _tokenize(text: str) -> List[str]:
    """
    Tokenizes text for BM25.
    Lowercase, remove punctuation, split on whitespace.
    Simple tokenization is intentional — more complexity doesn't help BM25.
    """
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return text.split()


class BM25Index:
    """
    BM25 keyword index over all document chunks.

    Usage:
        index = BM25Index()
        index.rebuild(db)            # build from DB
        results = index.search(query, k=20)
    """

    def __init__(self):
        self._bm25: Optional[BM25Okapi] = None
        self._chunk_store: List[Dict] = []   # Parallel list to BM25 index rows
        self._load_from_cache()

    def rebuild(self, db: Session) -> None:
        """
        Rebuilds the BM25 index from all chunks in the database.
        This is fast for typical regulatory document corpora (<10k chunks).

        Args:
            db: SQLAlchemy database session.
        """
        logger.info("Rebuilding BM25 index...")

        chunks = (
            db.query(DocumentChunk, DocumentVersion, Document)
            .join(DocumentVersion, DocumentChunk.version_id == DocumentVersion.id)
            .join(Document, DocumentVersion.document_id == Document.id)
            .all()
        )

        if not chunks:
            logger.warning("No chunks found — BM25 index will be empty")
            self._bm25 = None
            self._chunk_store = []
            return

        corpus_tokens = []
        self._chunk_store = []

        for chunk, version, doc in chunks:
            tokens = _tokenize(chunk.text)
            corpus_tokens.append(tokens)
            self._chunk_store.append({
                "chunk_id": chunk.chunk_id,
                "text": chunk.text,
                "doc_title": doc.title,
                "regulator": doc.regulator,
                "section_ref": chunk.section_ref,
                "version_id": version.id,
                "doc_id": doc.id,
            })

        self._bm25 = BM25Okapi(corpus_tokens)
        logger.info(f"BM25 index built with {len(corpus_tokens)} chunks")

        self._save_to_cache()

    def search(self, query: str, k: int = 20) -> List[Dict]:
        """
        Returns the top-k chunks for a query using BM25 scoring.

        Args:
            query: Natural language query string.
            k:     Number of results to return.

        Returns:
            List of result dicts sorted by BM25 score (descending).
            Each dict includes: chunk_id, text, metadata fields, score, rank.
        """
        if self._bm25 is None or not self._chunk_store:
            logger.warning("BM25 index is empty — returning no results")
            return []

        query_tokens = _tokenize(query)
        scores = self._bm25.get_scores(query_tokens)

        # Get top-k indices by score
        sorted_indices = sorted(
            range(len(scores)),
            key=lambda i: scores[i],
            reverse=True,
        )[:k]

        results = []
        for rank, idx in enumerate(sorted_indices):
            if scores[idx] <= 0:
                break  # BM25 score of 0 means no term overlap at all
            result = {
                **self._chunk_store[idx],
                "score": float(scores[idx]),
                "rank": rank + 1,
            }
            results.append(result)

        return results

    def _save_to_cache(self) -> None:
        """Serializes the index to disk for reuse across restarts."""
        try:
            _BM25_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(_BM25_CACHE_PATH, "wb") as f:
                pickle.dump({"bm25": self._bm25, "store": self._chunk_store}, f)
            logger.debug(f"BM25 index saved to {_BM25_CACHE_PATH}")
        except Exception as exc:
            logger.warning(f"Could not save BM25 cache: {exc}")

    def _load_from_cache(self) -> None:
        """Loads a previously built index from disk, if available."""
        if not _BM25_CACHE_PATH.exists():
            return
        try:
            with open(_BM25_CACHE_PATH, "rb") as f:
                data = pickle.load(f)
            self._bm25 = data["bm25"]
            self._chunk_store = data["store"]
            logger.info(f"BM25 index loaded from cache ({len(self._chunk_store)} chunks)")
        except Exception as exc:
            logger.warning(f"Could not load BM25 cache: {exc}")
