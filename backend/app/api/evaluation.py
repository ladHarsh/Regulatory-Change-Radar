"""
api/evaluation.py — Evaluation dashboard REST endpoints.

Routes:
  GET  /api/evaluation/metrics      — Latest run aggregate metrics + deltas vs prev run
  GET  /api/evaluation/results      — Per-question results from latest run
  GET  /api/evaluation/history      — Historical metrics for trend charts (last 10 runs)
  POST /api/evaluation/run          — Trigger a full evaluation suite run (async)
  GET  /api/evaluation/test-cases   — List all labeled test cases
  GET  /api/evaluation/status       — Is an evaluation currently running?
"""
import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])

# Simple in-memory flag to prevent concurrent evaluation runs
_eval_running = False
_eval_last_result: Optional[Dict] = None


@router.get("/metrics")
def get_metrics(db: Session = Depends(get_db)):
    """
    Returns the aggregate metrics from the most recent evaluation run,
    plus delta vs the previous run for trend arrows.
    """
    from app.evaluation.runner import get_latest_metrics
    metrics = get_latest_metrics(db)
    if not metrics:
        return JSONResponse({"message": "No evaluation runs yet. Click 'Run Evaluation Suite' to start."}, status_code=200)
    return metrics


@router.get("/results")
def get_results(db: Session = Depends(get_db)):
    """Returns per-question results from the most recent evaluation run."""
    from app.evaluation.runner import get_latest_results
    results = get_latest_results(db)
    return {"results": results, "count": len(results)}


@router.get("/history")
def get_history(limit: int = 10, db: Session = Depends(get_db)):
    """Returns the last N evaluation runs for trend charts."""
    from app.evaluation.runner import get_history
    return {"runs": get_history(db, limit=limit)}


@router.get("/status")
def get_status():
    """Returns whether an evaluation is currently running."""
    global _eval_running
    return {"running": _eval_running}


@router.post("/run")
async def trigger_evaluation(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Triggers the full evaluation suite as a background task.
    Returns immediately with run_id; poll /api/evaluation/status to check progress.
    """
    global _eval_running

    if _eval_running:
        raise HTTPException(status_code=409, detail="An evaluation run is already in progress.")

    async def _run():
        global _eval_running, _eval_last_result
        _eval_running = True
        try:
            from app.db.session import SessionLocal
            from app.evaluation.runner import run_evaluation_suite
            run_db = SessionLocal()
            try:
                _eval_last_result = await run_evaluation_suite(run_db)
            finally:
                run_db.close()
        except Exception as e:
            import traceback
            from loguru import logger
            logger.error(f"Evaluation run failed: {e}\n{traceback.format_exc()}")
        finally:
            _eval_running = False

    background_tasks.add_task(_run)
    return {"message": "Evaluation suite started", "status": "running"}


@router.get("/test-cases")
def get_test_cases(db: Session = Depends(get_db)):
    """Returns all labeled test cases."""
    from app.db.models import EvalTestCase
    from app.evaluation.runner import _seed_test_cases
    import json

    _seed_test_cases(db)
    cases = db.query(EvalTestCase).order_by(EvalTestCase.id).all()
    return {
        "test_cases": [
            {
                "id": tc.id,
                "question": tc.question,
                "expected_answer": tc.expected_answer,
                "query_type": tc.query_type,
                "expected_chunk_keywords": json.loads(tc.expected_chunk_keywords or "[]"),
            }
            for tc in cases
        ],
        "count": len(cases),
    }
