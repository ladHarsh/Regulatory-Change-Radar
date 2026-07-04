"""
api/query.py — RAG query endpoint (Pipeline v3).

Routes:
  POST /api/query          — Ask a natural language question via the full 6-stage pipeline
  GET  /api/query/history  — Recent query history for the current session

Pipeline stages (see app/rag/pipeline.py):
  1. Query Analysis → 2. Hybrid Retrieval → 3. Confidence Gate →
  4. Reasoning Agent → 5. Synthesis Agent → 6. Verification Agent
"""
import json
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import QueryLog
from app.db.session import get_db

router = APIRouter(prefix="/api/query", tags=["query"])


# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str
    stream: bool = True
    top_k: Optional[int] = None  # None → use settings.rerank_top_n
    regulator_filter: Optional[str] = None  # "RBI" | "SEBI" | None (all)


class SourceChunk(BaseModel):
    doc_title: str
    regulator: str
    section_ref: Optional[str]
    text: str
    score: float


class QueryResponse(BaseModel):
    question: str
    answer: str
    sources: List[SourceChunk]
    latency_ms: int
    query_type: str
    verified: bool
    stage_timings: Dict[str, int]


class QueryHistoryItem(BaseModel):
    id: int
    query_text: str
    answer: Optional[str]
    created_at: str

    class Config:
        from_attributes = True


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("", response_model=None)
async def query(
    request: QueryRequest,
    db: Session = Depends(get_db),
):
    """
    Main RAG query endpoint — Pipeline v3.

    Streaming mode (stream=True):
      Emits SSE events:
        data: {"type": "stage", "stage": "retrieval", "duration_ms": 230}
        data: {"type": "chunk", "text": "..."}
        data: {"type": "done", "sources": [...], "latency_ms": 123,
               "query_type": "factual", "verified": true, "stage_timings": {...}}

    Non-streaming mode (stream=False):
      Returns QueryResponse JSON directly.
    """
    from app.rag.pipeline import RAGPipeline

    pipeline = RAGPipeline()

    if request.stream:
        async def event_stream():
            # Run the full pipeline
            result = await pipeline.run(
                question=request.question,
                top_k=request.top_k,
                regulator_filter=request.regulator_filter,
            )

            # Emit stage timing events so the frontend can show progress
            for stage, ms in result.stage_timings.items():
                if stage != "total":
                    yield f"data: {json.dumps({'type': 'stage', 'stage': stage, 'duration_ms': ms})}\n\n"

            # Stream the answer word by word for a "typing" effect
            words = result.final_answer.split(" ")
            chunk_size = 3  # emit 3 words at a time
            for i in range(0, len(words), chunk_size):
                chunk_text = " ".join(words[i:i + chunk_size]) + " "
                yield f"data: {json.dumps({'type': 'chunk', 'text': chunk_text})}\n\n"

            # Build sources list
            sources = [
                SourceChunk(
                    doc_title=r.get("doc_title", "Unknown"),
                    regulator=r.get("regulator", "Unknown"),
                    section_ref=r.get("section_ref"),
                    text=r["text"],
                    score=r.get("score", 0.0),
                ).model_dump()
                for r in result.sources
            ]

            # Persist to query log with full pipeline metadata
            log = QueryLog(
                query_text=request.question,
                answer=result.final_answer,
                sources_json=json.dumps(sources),
                latency_ms=result.total_latency_ms,
                query_type=result.query_type,
                verified=result.verified,
                stage_timings_json=json.dumps(result.stage_timings),
                retrieval_confidence=result.retrieval_confidence,
                reasoning_path=result.reasoning_path,
                fallback_used=result.fallback_used,
            )
            db.add(log)
            db.commit()

            yield f"data: {json.dumps({'type': 'done', 'sources': sources, 'latency_ms': result.total_latency_ms, 'query_type': result.query_type, 'verified': result.verified, 'stage_timings': result.stage_timings})}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    else:
        result = await pipeline.run(
            question=request.question,
            top_k=request.top_k,
            regulator_filter=request.regulator_filter,
        )

        sources = [
            SourceChunk(
                doc_title=r.get("doc_title", "Unknown"),
                regulator=r.get("regulator", "Unknown"),
                section_ref=r.get("section_ref"),
                text=r["text"],
                score=r.get("score", 0.0),
            )
            for r in result.sources
        ]

        log = QueryLog(
            query_text=request.question,
            answer=result.final_answer,
            sources_json=json.dumps([s.model_dump() for s in sources]),
            latency_ms=result.total_latency_ms,
            query_type=result.query_type,
            verified=result.verified,
            stage_timings_json=json.dumps(result.stage_timings),
            retrieval_confidence=result.retrieval_confidence,
            reasoning_path=result.reasoning_path,
            fallback_used=result.fallback_used,
        )
        db.add(log)
        db.commit()

        return QueryResponse(
            question=request.question,
            answer=result.final_answer,
            sources=sources,
            latency_ms=result.total_latency_ms,
            query_type=result.query_type,
            verified=result.verified,
            stage_timings=result.stage_timings,
        )


@router.get("/history", response_model=List[QueryHistoryItem])
def get_query_history(skip: int = 0, limit: int = 20, db: Session = Depends(get_db)):
    """Returns recent query history in reverse chronological order."""
    logs = (
        db.query(QueryLog)
        .order_by(QueryLog.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [
        QueryHistoryItem(
            id=log.id,
            query_text=log.query_text,
            answer=log.answer,
            created_at=log.created_at.isoformat(),
        )
        for log in logs
    ]
