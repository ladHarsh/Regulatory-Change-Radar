"""
evaluation/ragas_eval.py — RAGAS-based retrieval quality evaluation.

Evaluates the RAG pipeline on a curated test set of 15 question/answer pairs
drawn from actual RBI and SEBI circular content.

Metrics measured:
  - context_precision:  How much of the retrieved context is relevant?
  - context_recall:     How much of the ground-truth answer is covered by context?
  - faithfulness:       Does the generated answer stay faithful to the context?
  - answer_relevancy:   Does the answer address the question asked?

Run with:
  python -m app.evaluation.ragas_eval
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from loguru import logger

# ── Test Set ──────────────────────────────────────────────────────────────────
# 15 representative questions covering RBI and SEBI regulatory domains.
# Ground truth answers are paraphrased from actual regulatory text.

TEST_DATASET = [
    {
        "question": "What are the KYC requirements for new bank account opening as per RBI guidelines?",
        "ground_truth": "RBI mandates customers to provide officially valid documents (OVD) including proof of identity and proof of address. Aadhaar, PAN, passport, voter ID, and driving license are accepted OVDs.",
    },
    {
        "question": "What is the maximum loan-to-value ratio for gold loans as per RBI?",
        "ground_truth": "RBI has set the maximum loan-to-value (LTV) ratio for loans against gold at 75% of the value of gold.",
    },
    {
        "question": "What are SEBI's disclosure requirements for listed companies regarding related party transactions?",
        "ground_truth": "SEBI requires listed entities to disclose material related party transactions to stock exchanges and obtain shareholder approval for transactions exceeding specified thresholds.",
    },
    {
        "question": "What is the definition of a 'systemically important' NBFC according to RBI?",
        "ground_truth": "An NBFC with asset size of INR 500 crore or above is classified as Systemically Important (NBFC-SI) by RBI.",
    },
    {
        "question": "What are the minimum capital requirements for setting up a new private sector bank in India?",
        "ground_truth": "RBI mandates a minimum paid-up voting equity capital of INR 500 crore for new private sector banks.",
    },
    {
        "question": "What are SEBI's regulations on insider trading?",
        "ground_truth": "SEBI's PIT Regulations prohibit designated persons from trading in securities when in possession of unpublished price sensitive information (UPSI).",
    },
    {
        "question": "What is the Prompt Corrective Action (PCA) framework by RBI?",
        "ground_truth": "RBI's PCA framework imposes restrictions on banks that breach certain risk thresholds related to capital adequacy, asset quality, and profitability.",
    },
    {
        "question": "What are the reporting requirements for suspicious transactions under PMLA?",
        "ground_truth": "Regulated entities must report suspicious transactions to the Financial Intelligence Unit-India (FIU-IND) within 7 days of coming to their knowledge.",
    },
    {
        "question": "What are SEBI's guidelines for credit rating agencies?",
        "ground_truth": "SEBI registered CRAs must follow a code of conduct, maintain independence, and disclose rating methodologies. They must review ratings at least annually.",
    },
    {
        "question": "What are the priority sector lending targets for commercial banks?",
        "ground_truth": "Domestic scheduled commercial banks must lend 40% of Adjusted Net Bank Credit (ANBC) to priority sectors including agriculture, MSMEs, and weaker sections.",
    },
    {
        "question": "What are the RBI guidelines on digital lending?",
        "ground_truth": "RBI mandates digital lenders to disburse loan amounts only to bank accounts of borrowers, prohibiting pass-through accounts. Loan details must be reported to credit bureaus.",
    },
    {
        "question": "What is the lock-in period for shares allotted to promoters in an IPO under SEBI regulations?",
        "ground_truth": "SEBI mandates a minimum lock-in period of 18 months for shares allotted to promoters beyond the minimum promoter contribution, and 6 months for minimum promoter contribution.",
    },
    {
        "question": "What are the RBI guidelines on co-lending arrangements between banks and NBFCs?",
        "ground_truth": "RBI's co-lending model allows banks to co-lend with NBFCs/HFCs for priority sector loans. The bank must retain at least 20% of the individual loan on its books.",
    },
    {
        "question": "What are SEBI's regulations for mutual fund expense ratios?",
        "ground_truth": "SEBI caps the total expense ratio for equity schemes at 2.25% for the first INR 500 crore of AUM, declining in slabs as AUM increases.",
    },
    {
        "question": "What are the RBI regulations on prepayment charges for floating rate loans?",
        "ground_truth": "RBI prohibits banks from charging foreclosure charges or prepayment penalties on floating rate term loans sanctioned to individual borrowers.",
    },
]


def run_evaluation(output_dir: str = "./data/eval") -> Dict:
    """
    Runs RAGAS evaluation on the test dataset.

    Args:
        output_dir: Directory to save evaluation results.

    Returns:
        Dict with metric scores and per-question breakdown.
    """
    from datasets import Dataset
    from ragas import evaluate
    from ragas.metrics import (
        context_precision,
        context_recall,
        faithfulness,
        answer_relevancy,
    )
    from langchain_groq import ChatGroq
    from langchain_community.embeddings import HuggingFaceEmbeddings

    from app.config import get_settings
    from app.retrieval.hybrid_retriever import HybridRetriever

    settings = get_settings()
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    logger.info(f"Running RAGAS evaluation on {len(TEST_DATASET)} questions...")

    retriever = HybridRetriever()

    # Collect RAG results for each question
    questions = []
    answers = []
    contexts_list = []
    ground_truths = []

    for item in TEST_DATASET:
        question = item["question"]
        ground_truth = item["ground_truth"]

        # Retrieve contexts
        chunks = retriever.search(query=question, top_k=5)
        contexts = [c["text"] for c in chunks]

        # Generate answer using LLM
        from app.llm.prompts import build_rag_prompt
        from app.llm.groq_client import GroqClient
        import asyncio

        prompt = build_rag_prompt(question, chunks)
        client = GroqClient()
        loop = asyncio.new_event_loop()
        answer = loop.run_until_complete(client.complete(prompt, max_tokens=512))
        loop.close()

        questions.append(question)
        answers.append(answer)
        contexts_list.append(contexts)
        ground_truths.append(ground_truth)

        logger.info(f"Evaluated: {question[:60]}…")

    # Build RAGAS dataset
    dataset = Dataset.from_dict({
        "question": questions,
        "answer": answers,
        "contexts": contexts_list,
        "ground_truth": ground_truths,
    })

    # LLM and embeddings for RAGAS evaluation
    llm = ChatGroq(
        groq_api_key=settings.groq_api_key,
        model_name="llama-3.1-8b-instant",  # Faster/cheaper model for eval
        temperature=0,
    )
    embeddings = HuggingFaceEmbeddings(model_name=settings.embedding_model)

    result = evaluate(
        dataset=dataset,
        metrics=[context_precision, context_recall, faithfulness, answer_relevancy],
        llm=llm,
        embeddings=embeddings,
    )

    scores = {
        "context_precision": float(result["context_precision"]),
        "context_recall": float(result["context_recall"]),
        "faithfulness": float(result["faithfulness"]),
        "answer_relevancy": float(result["answer_relevancy"]),
        "evaluated_at": datetime.utcnow().isoformat(),
        "num_questions": len(TEST_DATASET),
    }

    # Save results
    output_path = Path(output_dir) / f"ragas_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_path, "w") as f:
        json.dump(scores, f, indent=2)

    logger.info(f"RAGAS evaluation complete. Results saved to {output_path}")
    logger.info(f"Scores: {scores}")

    return scores


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    scores = run_evaluation()
    print("\n=== RAGAS Evaluation Results ===")
    for metric, value in scores.items():
        if isinstance(value, float):
            print(f"  {metric:25s}: {value:.4f}")
