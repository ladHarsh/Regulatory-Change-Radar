"""
rag/__init__.py — Multi-stage RAG pipeline package.

Stages (each independently testable):
  1. query_analyzer   — Detects query type and extracts candidate attributes
  2. reasoning_agent  — Structured rule extraction + code evaluation OR chain-of-thought
  3. synthesis_agent  — Dedup + concise professional answer generation
  4. verification_agent — Adversarial fact-checker against retrieved evidence
  5. pipeline         — Orchestrates all stages with per-stage timing
"""
