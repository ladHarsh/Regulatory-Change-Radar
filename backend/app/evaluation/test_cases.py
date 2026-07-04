"""
evaluation/test_cases.py — Labeled test suite for the evaluation dashboard.

Contains 25 Q&A pairs covering:
  - Simple factual queries (10)    — "What is X?" questions with known answers
  - Eligibility/scenario queries (10) — "Is this person eligible?" with boundary cases
  - Comparison queries (5)          — "How does X differ from Y?"

Used by evaluation/runner.py to compute:
  - Retrieval Accuracy (Recall@5)
  - Answer Accuracy (LLM-as-judge)
  - Hallucination Rate
  - P95 Latency
"""

# Each test case has:
#   question:                 The user question
#   expected_answer:          Ground-truth answer key (not necessarily verbatim — used for LLM judge)
#   expected_chunk_keywords:  Keywords that MUST appear in a retrieved chunk for Recall@k
#   query_type:               factual | eligibility | scenario | comparison

LABELED_TEST_CASES = [

    # ── Factual queries ────────────────────────────────────────────────────────

    {
        "question": "What is the minimum post-qualification experience required for the Executive Director position at SEBI?",
        "expected_answer": "A minimum of 20 years of post-qualification experience is required for the Executive Director position at SEBI.",
        "expected_chunk_keywords": ["20 years", "experience", "Executive Director"],
        "query_type": "factual",
    },
    {
        "question": "What educational qualifications are accepted for the SEBI Executive Director position?",
        "expected_answer": "Accepted qualifications include MBA/MMS (Finance), CA, CS, CFA, CWA, LLB, and Post Graduation in Economics or Finance.",
        "expected_chunk_keywords": ["MBA", "CA", "CFA", "qualification"],
        "query_type": "factual",
    },
    {
        "question": "What is the maximum age limit for applying to the SEBI Executive Director post?",
        "expected_answer": "The maximum age limit is 55 years for the Executive Director post at SEBI.",
        "expected_chunk_keywords": ["55", "age", "Executive Director"],
        "query_type": "factual",
    },
    {
        "question": "What is the mode of selection for the SEBI Executive Director post?",
        "expected_answer": "The mode of selection is Interview. SEBI will also follow a search-cum-selection process to widen the pool of candidates.",
        "expected_chunk_keywords": ["interview", "selection", "search"],
        "query_type": "factual",
    },
    {
        "question": "Will an outstation candidate get travel reimbursement for the SEBI ED interview?",
        "expected_answer": "Yes, outstation candidates called for the interview will be reimbursed economy class air fare for to and fro journey by the shortest route from their place of residence.",
        "expected_chunk_keywords": ["outstation", "economy", "air fare", "reimbursed"],
        "query_type": "factual",
    },
    {
        "question": "Can a SEBI Executive Director appointee on contract basis claim permanent employment?",
        "expected_answer": "No. A candidate appointed on deputation or contract basis will not be entitled to permanent employment with SEBI.",
        "expected_chunk_keywords": ["permanent", "contract", "deputation", "not entitled"],
        "query_type": "factual",
    },
    {
        "question": "What documents must be submitted by candidates applying on deputation basis for the SEBI ED post?",
        "expected_answer": "Deputation candidates must submit Vigilance Clearance, Cadre Clearance, and Annual Confidential Reports for the last 5 years, along with the application.",
        "expected_chunk_keywords": ["vigilance", "cadre clearance", "confidential reports", "deputation"],
        "query_type": "factual",
    },
    {
        "question": "Does SEBI have the right to cancel the advertisement for the Executive Director post?",
        "expected_answer": "Yes. SEBI reserves the right to cancel the advertisement fully or partly on any grounds, and also the right to not fill up the post at all.",
        "expected_chunk_keywords": ["cancel", "advertisement", "reserves the right"],
        "query_type": "factual",
    },
    {
        "question": "What happens if a candidate submits false information in their SEBI ED application?",
        "expected_answer": "If a candidate knowingly or willfully furnishes incorrect or false information, their candidature or appointment is liable to be cancelled or terminated.",
        "expected_chunk_keywords": ["false", "incorrect", "cancelled", "terminated"],
        "query_type": "factual",
    },
    {
        "question": "What effect does canvassing have on a SEBI ED application?",
        "expected_answer": "Canvassing in any form will disqualify the candidate from consideration for the Executive Director position.",
        "expected_chunk_keywords": ["canvassing", "disqualify"],
        "query_type": "factual",
    },

    # ── Eligibility / Scenario queries ─────────────────────────────────────────

    {
        "question": "A candidate is 52 years old with 22 years of post-qualification experience and holds an MBA in Finance. Are they eligible for the SEBI Executive Director position?",
        "expected_answer": "Yes, this candidate is eligible. They are 52 years old (within the 55-year age limit), have 22 years of experience (meets the 20-year minimum), and hold an MBA in Finance (an accepted qualification).",
        "expected_chunk_keywords": ["55", "20 years", "MBA", "eligible"],
        "query_type": "scenario",
    },
    {
        "question": "Can a 56-year-old candidate apply for the SEBI Executive Director post?",
        "expected_answer": "No. The maximum age limit is 55 years, so a 56-year-old candidate does not meet the age eligibility criterion.",
        "expected_chunk_keywords": ["55", "age", "not eligible"],
        "query_type": "eligibility",
    },
    {
        "question": "A candidate is exactly 55 years old with 21 years of experience and a CA qualification. Are they eligible for the SEBI ED post?",
        "expected_answer": "Yes, this candidate is eligible. They are 55 years old (exactly at the age limit), have 21 years of experience (exceeds the 20-year minimum), and hold a CA qualification (explicitly accepted).",
        "expected_chunk_keywords": ["55", "20 years", "CA", "eligible"],
        "query_type": "scenario",
    },
    {
        "question": "Is a 54-year-old candidate with only 18 years of post-qualification experience eligible for the SEBI ED post?",
        "expected_answer": "No, this candidate is not eligible. While they meet the age requirement (54 ≤ 55), they do not meet the minimum experience requirement of 20 years (they have only 18 years).",
        "expected_chunk_keywords": ["20 years", "experience", "minimum"],
        "query_type": "scenario",
    },
    {
        "question": "A candidate is 55 years and 6 months old. Can they apply for the SEBI ED position?",
        "expected_answer": "No, this candidate is not eligible as they exceed the maximum age limit of 55 years.",
        "expected_chunk_keywords": ["55", "age", "exceed", "maximum"],
        "query_type": "eligibility",
    },
    {
        "question": "Does a candidate with an LLB degree qualify for the SEBI Executive Director role?",
        "expected_answer": "Yes. LLB (Bachelor of Laws) is an explicitly accepted educational qualification for the SEBI Executive Director position.",
        "expected_chunk_keywords": ["LLB", "qualification", "Executive Director"],
        "query_type": "eligibility",
    },
    {
        "question": "Is a candidate with exactly 20 years of post-qualification experience eligible for the SEBI ED post?",
        "expected_answer": "Yes, a candidate with exactly 20 years of post-qualification experience meets the minimum experience requirement for the SEBI Executive Director post.",
        "expected_chunk_keywords": ["20 years", "minimum", "experience"],
        "query_type": "eligibility",
    },
    {
        "question": "Can a government servant apply for the SEBI Executive Director post on deputation basis?",
        "expected_answer": "Yes, government servants can apply on deputation basis. They must route their application through their employer and submit an advance copy to SEBI by the last date of application.",
        "expected_chunk_keywords": ["deputation", "employer", "advance copy"],
        "query_type": "eligibility",
    },
    {
        "question": "A candidate with a Post Graduate degree in Economics has 25 years of experience and is 50 years old. Are they eligible for the SEBI ED post?",
        "expected_answer": "Yes, this candidate is fully eligible. They satisfy all three criteria: age (50 ≤ 55), experience (25 ≥ 20 years), and qualification (Post Graduation in Economics is an accepted qualification).",
        "expected_chunk_keywords": ["economics", "20 years", "55", "eligible"],
        "query_type": "scenario",
    },
    {
        "question": "A candidate with a CWA qualification, age 48, and 19 years of experience applies for the SEBI ED post. What is missing?",
        "expected_answer": "The candidate does not meet the minimum experience requirement of 20 years (they have only 19 years). Their age (48) and qualification (CWA) both satisfy the criteria.",
        "expected_chunk_keywords": ["20 years", "CWA", "experience", "minimum"],
        "query_type": "scenario",
    },

    # ── Comparison queries ─────────────────────────────────────────────────────

    {
        "question": "What are the different ways a candidate can be appointed to the SEBI Executive Director post?",
        "expected_answer": "A candidate can be appointed on a regular basis, on deputation, or on contract basis. Deputation and contract appointees are not entitled to permanent employment with SEBI.",
        "expected_chunk_keywords": ["deputation", "contract", "regular", "appointed"],
        "query_type": "comparison",
    },
    {
        "question": "What is the difference between submitting an application on deputation basis versus direct application for the SEBI ED post?",
        "expected_answer": "Deputation applicants must route their application through their employer institution, submit an advance copy to SEBI by the last date, and also provide Vigilance Clearance, Cadre Clearance, and last 5 years' ACRs. Direct applicants do not have these routing requirements.",
        "expected_chunk_keywords": ["deputation", "employer", "direct", "advance copy"],
        "query_type": "comparison",
    },
    {
        "question": "What are the different accepted qualifications for the SEBI Executive Director post and how do they differ?",
        "expected_answer": "The accepted qualifications span finance, law, and accounting: MBA/MMS (Finance) is a management degree; CA (Chartered Accountant) and CWA (Cost and Works Accountant) are professional accounting qualifications; CS (Company Secretary) focuses on corporate governance; CFA (Chartered Financial Analyst) is an investment credential; LLB covers law. Post Graduation in Economics or Finance from a recognized institution is also accepted.",
        "expected_chunk_keywords": ["MBA", "CA", "CFA", "LLB", "CWA", "CS"],
        "query_type": "comparison",
    },
    {
        "question": "Does SEBI's right to cancel the advertisement differ from its right to not fill the post?",
        "expected_answer": "Yes. SEBI can cancel the advertisement fully or partially on any grounds (removing the vacancy announcement), while separately it can choose to not fill the post even without cancelling the advertisement. These are two distinct reserved rights.",
        "expected_chunk_keywords": ["cancel", "not fill", "reserves the right"],
        "query_type": "comparison",
    },
    {
        "question": "What are the consequences of canvassing versus submitting false information in a SEBI ED application?",
        "expected_answer": "Both result in disqualification, but at different stages. Canvassing in any form disqualifies the candidate immediately. Submitting false information results in cancellation or termination of candidature/appointment, which can happen even after selection if discovered later.",
        "expected_chunk_keywords": ["canvassing", "disqualify", "false", "terminated"],
        "query_type": "comparison",
    },
]


def get_all_test_cases() -> list:
    """Returns all labeled test cases as a list of dicts."""
    return LABELED_TEST_CASES


def get_test_cases_by_type(query_type: str) -> list:
    """Returns test cases filtered by query type."""
    return [tc for tc in LABELED_TEST_CASES if tc["query_type"] == query_type]
