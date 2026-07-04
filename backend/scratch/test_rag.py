import asyncio
from app.rag.query_analyzer import analyze_query
from app.rag.pipeline import RAGPipeline
import sys

# Force utf-8 for windows terminal
sys.stdout.reconfigure(encoding='utf-8')

async def main():
    question = "What is the monthly gross salary offered with and without accommodation?"
    print(f"Question: {question}")
    
    # Check analysis
    analysis = analyze_query(question)
    print(f"Query type: {analysis.query_type}")
    print(f"Candidate Attributes: {analysis.candidate_attributes}")
    print(f"Use structured reasoning: {analysis.use_structured_reasoning}")
    
    # Run pipeline
    print("\nRunning RAG pipeline...")
    pipeline = RAGPipeline()
    result = await pipeline.run(question)
    
    print(f"\nFinal Answer:\n{result.final_answer}")
    print(f"\nReasoning path used: {result.reasoning_path}")
    print(f"Verification issues: {result.verification_issues}")

if __name__ == "__main__":
    asyncio.run(main())
