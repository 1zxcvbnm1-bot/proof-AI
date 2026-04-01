"""
RAG Engine — Quick-start demo
Run: python demo.py
"""

import asyncio
import os
import time
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'core'))
from engine import RAGEngine, FactRecord


async def main():
    print("\n" + "═"*60)
    print("  REAL-TIME RAG ORCHESTRATION ENGINE — DEMO")
    print("═"*60 + "\n")

    # 1. Initialize engine
    from dotenv import load_dotenv; load_dotenv()
    api_key = os.environ.get("GROQ_API_KEY", "gsk_P1ac3h0ld3rGr0qK3yT0B3R3plac3dByR3alOn3")
    if not api_key:
        print("  ⚠️  GROQ_API_KEY not set — cannot run RAG demo")
        print("  Set it with: $env:GROQ_API_KEY = 'gsk_...'")
        return
    engine = RAGEngine(api_key=api_key, model_name="llama-3.3-70b-versatile")
    

    # 2. Load sample verified corpus
    corpus = [
        FactRecord(
            fact_id="F001",
            claim_text="Hallucination in AI models refers to generating confident but factually incorrect output.",
            source_urls=["https://arxiv.org/abs/2309.01219"],
            source_type="academic",
            authority_tier=2,
            trust_score=0.95,
            last_verified_at=time.time() - 86400 * 7,
        ),
        FactRecord(
            fact_id="F002",
            claim_text="RAG (Retrieval-Augmented Generation) grounds LLM outputs in external verified knowledge.",
            source_urls=["https://arxiv.org/abs/2005.11401"],
            source_type="academic",
            authority_tier=2,
            trust_score=0.97,
            last_verified_at=time.time() - 86400 * 14,
        ),
        FactRecord(
            fact_id="F003",
            claim_text="GDPR Article 17 gives individuals the right to request erasure of their personal data.",
            source_urls=["https://gdpr-info.eu/art-17-gdpr/"],
            source_type="gov_site",
            authority_tier=1,
            trust_score=0.99,
            last_verified_at=time.time() - 86400 * 30,
        ),
    ]
    engine.load_corpus(corpus)

    # 3. Run a streaming query
    query = "What is RAG and how does it prevent hallucinations?"
    print(f"Query: {query}\n")
    print("─"*60)
    print("Streaming verified response:\n")

    async for token in engine.query(query, session_id="demo-session-1"):
        if token.is_final:
            break
        if token.claim_id:
            print(f"\n  [📎 fact:{token.claim_id} | conf:{token.confidence:.2f} | {token.status}]\n", end="")
        else:
            print(token.text, end="", flush=True)

    print("\n\n" + "─"*60)
    print(f"\nEngine stats: {engine.stats()}")
    print(f"Audit log: {len(engine.audit._log)} entries")
    print(f"Hallucination rate: {engine.audit.hallucination_rate():.1%}")


if __name__ == "__main__":
    asyncio.run(main())
