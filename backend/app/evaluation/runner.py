"""
evaluation/runner.py — Evaluation suite runner.

Computes the 5 pipeline metrics:
  1. Retrieval Accuracy  — Recall@5: was the correct chunk in the top-5 results?
  2. Answer Accuracy     — LLM-as-judge: 1-5 score comparing generated vs expected answer
  3. Hallucination Rate  — % of answers where the Verification Agent returned verified=False
  4. Avg + P95 Latency   — per-request total latency in ms (avg and 95th percentile)

Results are stored in EvalRun + EvalResult tables and returned as a dict
that the evaluation API endpoint sends to the frontend dashboard.
"""
import asyncio
import json
import re
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
from loguru import logger
from sqlalchemy.orm import Session

from app.db.models import EvalResult, EvalRun, EvalTestCase
from app.evaluation.test_cases import LABELED_TEST_CASES


# ── Public API ────────────────────────────────────────────────────────────────

async def run_evaluation_suite(db: Session) -> Dict:
    """
    Runs all labeled test cases through the full pipeline and computes metrics.

    Args:
        db: SQLAlchemy session.

    Returns:
        Dict with aggregate metrics and per-question results.
    """
    from app.rag.pipeline import RAGPipeline
    from app.llm.groq_client import GroqClient
    from app.llm.prompts import build_llm_judge_prompt

    # Seed test cases into DB if not already present
    _seed_test_cases(db)

    pipeline = RAGPipeline()
    llm = GroqClient()

    # Create an EvalRun record
    run = EvalRun(run_at=datetime.utcnow(), total_cases=len(LABELED_TEST_CASES))
    db.add(run)
    db.commit()
    db.refresh(run)

    logger.info(f"Starting evaluation run #{run.id} with {len(LABELED_TEST_CASES)} test cases")

    latencies: List[int] = []
    retrieval_correct_count = 0
    judge_scores: List[float] = []
    hallucinations = 0
    per_question_results = []

    # Fetch test case IDs from DB
    test_cases_db = db.query(EvalTestCase).order_by(EvalTestCase.id).all()
    test_case_map = {tc.question: tc for tc in test_cases_db}

    # ── Run all test cases in concurrent batches of 3 ─────────────────────────
    # Batch size 3 stays within Groq's rate limits (~6 req/min on free tier)
    BATCH_SIZE = 3
    all_test_items = [
        (i, tc_data, test_case_map.get(tc_data["question"]))
        for i, tc_data in enumerate(LABELED_TEST_CASES)
        if test_case_map.get(tc_data["question"])
    ]

    async def _run_single(i: int, tc_data: dict, tc_db) -> dict:
        """Runs a single test case through the pipeline and LLM judge."""
        question = tc_data["question"]
        expected_answer = tc_data["expected_answer"]
        expected_keywords = tc_data.get("expected_chunk_keywords", [])

        logger.info(f"Evaluating [{i+1}/{len(LABELED_TEST_CASES)}]: {question[:60]}...")

        error_msg = None
        result = None

        try:
            result = await pipeline.run(question=question)
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Pipeline error for test case {i+1}: {e}")

        # Retrieval accuracy (Recall@5)
        retrieved_correct = False
        if result and result.sources and expected_keywords:
            retrieved_texts = " ".join(s.get("text", "") for s in result.sources[:5]).lower()
            matched = sum(1 for kw in expected_keywords if kw.lower() in retrieved_texts)
            retrieved_correct = matched >= max(1, len(expected_keywords) // 2)

        # LLM-as-judge answer accuracy
        judge_score = None
        if result and result.final_answer:
            try:
                judge_prompt = build_llm_judge_prompt(
                    question=question,
                    expected_answer=expected_answer,
                    generated_answer=result.final_answer,
                )
                judge_raw = await llm.complete(judge_prompt)
                judge_score = _parse_judge_score(judge_raw)
            except Exception as e:
                logger.warning(f"LLM judge failed for test case {i+1}: {e}")

        verified = result.verified if result else None
        latency_ms = result.total_latency_ms if result else None

        return {
            "tc_db": tc_db,
            "tc_data": tc_data,
            "result": result,
            "retrieved_correct": retrieved_correct,
            "judge_score": judge_score,
            "verified": verified,
            "latency_ms": latency_ms,
            "error_msg": error_msg,
        }

    # Process in batches
    batch_outputs = []
    for batch_start in range(0, len(all_test_items), BATCH_SIZE):
        batch = all_test_items[batch_start:batch_start + BATCH_SIZE]
        logger.info(
            f"Running evaluation batch {batch_start // BATCH_SIZE + 1} "
            f"({len(batch)} queries concurrently)"
        )
        batch_results = await asyncio.gather(*[
            _run_single(i, tc_data, tc_db)
            for i, tc_data, tc_db in batch
        ])
        batch_outputs.extend(batch_results)
        # Brief pause between batches to respect Groq rate limits
        if batch_start + BATCH_SIZE < len(all_test_items):
            await asyncio.sleep(1.0)

    # ── Aggregate results from all batches ────────────────────────────────────
    for output in batch_outputs:
        tc_db = output["tc_db"]
        tc_data = output["tc_data"]
        result = output["result"]
        retrieved_correct = output["retrieved_correct"]
        judge_score = output["judge_score"]
        verified = output["verified"]
        latency_ms = output["latency_ms"]
        error_msg = output["error_msg"]

        if retrieved_correct:
            retrieval_correct_count += 1
        if judge_score is not None:
            judge_scores.append(judge_score)
        if result and not verified:
            hallucinations += 1
        if latency_ms:
            latencies.append(latency_ms)

        eval_result = EvalResult(
            run_id=run.id,
            test_case_id=tc_db.id,
            generated_answer=result.final_answer if result else None,
            retrieved_correct=retrieved_correct,
            answer_score=judge_score,
            verified=verified,
            latency_ms=latency_ms,
            stage_timings_json=json.dumps(result.stage_timings) if result else None,
            error=error_msg,
        )
        db.add(eval_result)

        per_question_results.append({
            "question": tc_data["question"][:80] + ("..." if len(tc_data["question"]) > 80 else ""),
            "query_type": tc_data["query_type"],
            "retrieved_correct": retrieved_correct,
            "answer_score": judge_score,
            "verified": verified,
            "latency_ms": latency_ms,
            "error": error_msg,
        })

        # Small delay to avoid rate limiting
        await asyncio.sleep(0.5)

    # ── Compute aggregate metrics ──────────────────────────────────────────
    n = len(LABELED_TEST_CASES)
    retrieval_accuracy = retrieval_correct_count / n if n > 0 else 0.0
    answer_accuracy = float(np.mean(judge_scores)) if judge_scores else 0.0
    hallucination_rate = hallucinations / n if n > 0 else 0.0
    avg_latency = float(np.mean(latencies)) if latencies else 0.0
    p95_latency = float(np.percentile(latencies, 95)) if latencies else 0.0

    # Update the EvalRun with aggregate metrics
    run.total_cases = n
    run.retrieval_accuracy = retrieval_accuracy
    run.answer_accuracy = answer_accuracy
    run.hallucination_rate = hallucination_rate
    run.avg_latency_ms = avg_latency
    run.p95_latency_ms = p95_latency
    db.commit()

    logger.info(
        f"Evaluation run #{run.id} complete: "
        f"retrieval={retrieval_accuracy:.2%}, "
        f"accuracy={answer_accuracy:.2f}/5, "
        f"hallucination={hallucination_rate:.2%}, "
        f"avg_latency={avg_latency:.0f}ms, "
        f"p95={p95_latency:.0f}ms"
    )

    return {
        "run_id": run.id,
        "run_at": run.run_at.isoformat(),
        "total_cases": n,
        "metrics": {
            "retrieval_accuracy": round(retrieval_accuracy, 4),
            "answer_accuracy": round(answer_accuracy, 2),
            "hallucination_rate": round(hallucination_rate, 4),
            "avg_latency_ms": round(avg_latency, 1),
            "p95_latency_ms": round(p95_latency, 1),
        },
        "per_question": per_question_results,
    }


def get_latest_metrics(db: Session) -> Optional[Dict]:
    """Returns the metrics from the most recent evaluation run."""
    run = db.query(EvalRun).order_by(EvalRun.run_at.desc()).first()
    if not run:
        return None

    # Also get the run before it for trend arrows
    prev_run = (
        db.query(EvalRun)
        .filter(EvalRun.id < run.id)
        .order_by(EvalRun.run_at.desc())
        .first()
    )

    def delta(current, prev):
        if prev is None or current is None:
            return None
        return round(current - prev, 4)

    return {
        "run_id": run.id,
        "run_at": run.run_at.isoformat(),
        "total_cases": run.total_cases,
        "metrics": {
            "retrieval_accuracy": run.retrieval_accuracy,
            "answer_accuracy": run.answer_accuracy,
            "hallucination_rate": run.hallucination_rate,
            "avg_latency_ms": run.avg_latency_ms,
            "p95_latency_ms": run.p95_latency_ms,
        },
        "deltas": {
            "retrieval_accuracy": delta(run.retrieval_accuracy, prev_run.retrieval_accuracy if prev_run else None),
            "answer_accuracy": delta(run.answer_accuracy, prev_run.answer_accuracy if prev_run else None),
            "hallucination_rate": delta(run.hallucination_rate, prev_run.hallucination_rate if prev_run else None),
            "avg_latency_ms": delta(run.avg_latency_ms, prev_run.avg_latency_ms if prev_run else None),
        },
    }


def get_latest_results(db: Session) -> List[Dict]:
    """Returns per-question results from the most recent run."""
    run = db.query(EvalRun).order_by(EvalRun.run_at.desc()).first()
    if not run:
        return []

    results = (
        db.query(EvalResult)
        .filter(EvalResult.run_id == run.id)
        .all()
    )

    output = []
    for r in results:
        tc = r.test_case
        output.append({
            "question": tc.question[:80] + ("..." if len(tc.question) > 80 else "") if tc else "",
            "query_type": tc.query_type if tc else "",
            "retrieved_correct": r.retrieved_correct,
            "answer_score": r.answer_score,
            "verified": r.verified,
            "latency_ms": r.latency_ms,
            "stage_timings": json.loads(r.stage_timings_json) if r.stage_timings_json else {},
            "error": r.error,
        })
    return output


def get_history(db: Session, limit: int = 10) -> List[Dict]:
    """Returns summary of past evaluation runs for trend charts."""
    runs = db.query(EvalRun).order_by(EvalRun.run_at.desc()).limit(limit).all()
    return [
        {
            "run_id": r.id,
            "run_at": r.run_at.isoformat(),
            "retrieval_accuracy": r.retrieval_accuracy,
            "answer_accuracy": r.answer_accuracy,
            "hallucination_rate": r.hallucination_rate,
            "avg_latency_ms": r.avg_latency_ms,
            "p95_latency_ms": r.p95_latency_ms,
        }
        for r in runs
    ]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_judge_score(raw: str) -> Optional[float]:
    """Parses LLM-as-judge response and returns a numeric 1-5 score."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        score = data.get("score")
        if score is not None:
            return float(score)
    except (json.JSONDecodeError, TypeError):
        pass
    # Fallback: look for lone digit
    m = re.search(r'\b([1-5])\b', raw)
    if m:
        return float(m.group(1))
    return None


def _seed_test_cases(db: Session) -> None:
    """Seeds labeled test cases into the DB if not already present."""
    existing_count = db.query(EvalTestCase).count()
    if existing_count >= len(LABELED_TEST_CASES):
        return

    # Clear and re-seed to ensure consistency
    db.query(EvalTestCase).delete()
    for tc in LABELED_TEST_CASES:
        keywords = tc.get("expected_chunk_keywords", [])
        db.add(EvalTestCase(
            question=tc["question"],
            expected_answer=tc["expected_answer"],
            expected_chunk_keywords=json.dumps(keywords),
            query_type=tc.get("query_type", "factual"),
        ))
    db.commit()
    logger.info(f"Seeded {len(LABELED_TEST_CASES)} evaluation test cases")
