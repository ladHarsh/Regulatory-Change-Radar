"""
retrieval/vector_store.py — ChromaDB interface for storing and querying chunk embeddings.

ChromaDB runs in embedded (in-process) mode — no server or Docker required.
Data is persisted to disk at CHROMA_DIR.
"""
from typing import Dict, List, Optional, Union

import chromadb
from chromadb.config import Settings as ChromaSettings
from loguru import logger

from app.config import get_settings
from app.retrieval.embeddings import embed_query, embed_documents

settings = get_settings()

# Collection name in ChromaDB
COLLECTION_NAME = "regulatory_chunks"


class VectorStore:
    """
    Thin wrapper around ChromaDB for adding and querying document chunks.

    All embedding is done locally using the BGE model — ChromaDB is used
    purely as a vector storage and approximate nearest-neighbor search engine.
    """

    def __init__(self):
        self._client = chromadb.PersistentClient(
            path=settings.chroma_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},  # Use cosine distance
        )
        logger.debug(f"ChromaDB collection '{COLLECTION_NAME}' loaded with {self._collection.count()} items")

    def add_chunks(self, chunks: List[Dict]) -> None:
        """
        Embeds and stores a list of chunks in ChromaDB.
        Idempotent — chunks with existing IDs are upserted (not duplicated).

        Args:
            chunks: List of chunk dicts from chunker.py.
                    Each must have: chunk_id, text, metadata.
        """
        if not chunks:
            return

        texts = [c["text"] for c in chunks]
        ids = [c["chunk_id"] for c in chunks]
        metadatas = [
            {k: str(v) for k, v in c["metadata"].items()}  # ChromaDB requires string metadata values
            for c in chunks
        ]

        # Embed all texts
        embeddings = embed_documents(texts)

        self._collection.upsert(
            ids=ids,
            embeddings=embeddings.tolist(),
            documents=texts,
            metadatas=metadatas,
        )

        logger.info(f"Upserted {len(chunks)} chunks into ChromaDB")

    def similarity_search(
        self,
        query: str,
        k: int = 20,
        regulator_filter: Optional[Union[str, List[str]]] = None,
    ) -> List[Dict]:
        """
        Retrieves the top-k most similar chunks for a given query.

        Args:
            query:            Natural language query string.
            k:                Number of results to return.
            regulator_filter: Optional filter — a single regulator string ("RBI") or
                              a list of regulators (["RBI", "SEBI"]) applied as metadata filter.

        Returns:
            List of result dicts with: chunk_id, text, metadata, score.
        """
        if self._collection.count() == 0:
            logger.warning("ChromaDB collection is empty — no results returned")
            return []

        query_embedding = embed_query(query)

        where = None
        if regulator_filter:
            if isinstance(regulator_filter, list):
                if len(regulator_filter) == 1:
                    where = {"regulator": regulator_filter[0].upper()}
                elif len(regulator_filter) > 1:
                    where = {"$or": [{"regulator": r.upper()} for r in regulator_filter]}
            else:
                where = {"regulator": regulator_filter.upper()}

        results = self._collection.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=min(k, self._collection.count()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        output = []
        for i, (doc, meta, dist) in enumerate(zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        )):
            # ChromaDB cosine distance → similarity: similarity = 1 - distance
            score = 1.0 - dist
            output.append({
                "chunk_id": results["ids"][0][i],
                "text": doc,
                "metadata": meta,
                "score": score,
                "doc_title": meta.get("doc_title", "Unknown"),
                "regulator": meta.get("regulator", "Unknown"),
                "section_ref": meta.get("section_ref"),
                "rank": i + 1,  # 1-indexed rank for RRF
            })

        return output

    def get_embeddings_by_ids(self, chunk_ids: List[str]) -> Dict[str, List[float]]:
        """
        Retrieves stored embeddings for specific chunk IDs.
        Used by the semantic diff engine.
        """
        if not chunk_ids:
            return {}

        results = self._collection.get(ids=chunk_ids, include=["embeddings"])
        return {
            id_: emb
            for id_, emb in zip(results["ids"], results["embeddings"])
        }

    def delete_version_chunks(self, version_id: int) -> None:
        """
        Deletes all chunks belonging to a specific document version.
        Used when re-ingesting or cleaning up.
        """
        self._collection.delete(where={"version_id": str(version_id)})
        logger.info(f"Deleted chunks for version {version_id} from ChromaDB")

    @property
    def count(self) -> int:
        """Returns the total number of chunks stored in ChromaDB."""
        return self._collection.count()
