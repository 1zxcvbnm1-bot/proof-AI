#!/usr/bin/env python3
"""
Quick PROOF-AI demo using the library directly.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def main():
    from Fact_checker.fact_checker import FactCheckPipeline, KnowledgeChunk

    # Use mock mode (no API key needed)
    print("=" * 70)
    print("PROOF-AI QUICK DEMO")
    print("=" * 70)

    # Initialize pipeline
    print("\n[1] Initializing FactCheckPipeline...")
    pipeline = FactCheckPipeline(api_key="mock")

    # Load knowledge corpus
    print("[2] Loading knowledge corpus...")
    corpus = [
        KnowledgeChunk(
            chunk_id="K1",
            text="Python was created by Guido van Rossum and first released in 1991.",
            source_url="https://en.wikipedia.org/wiki/Python_(programming_language)",
            source_domain="wikipedia.org",
            authority_tier=4,
            trust_score=0.95
        ),
        KnowledgeChunk(
            chunk_id="K2",
            text="OpenAI was founded in December 2015 by Elon Musk, Sam Altman, and others.",
            source_url="https://en.wikipedia.org/wiki/OpenAI",
            source_domain="wikipedia.org",
            authority_tier=4,
            trust_score=0.93
        ),
        KnowledgeChunk(
            chunk_id="K3",
            text="RAG (Retrieval-Augmented Generation) was introduced by Facebook AI Research in 2020.",
            source_url="https://arxiv.org/abs/2005.11401",
            source_domain="arxiv.org",
            authority_tier=2,
            trust_score=0.97
        )
    ]
    pipeline.load_corpus(corpus)
    print(f"    Loaded {len(corpus)} knowledge chunks")

    # Test query
    print("\n[3] Running fact-check on a query...")
    query = "Who created Python and when was it released?"
    print(f"    Query: {query}")

    result = await pipeline.check(query)

    print(f"\n[4] Results:")
    print(f"    Total claims extracted: {result.total_claims}")
    print(f"    Verified: {result.verified}")
    print(f"    Blocked: {result.blocked}")
    print(f"    Conflicts: {result.conflicts}")
    print(f"    Overall hallucination rate: {result.halluc_rate:.1%}")
    print(f"    Detected hallucination types: {result.halluc_types}")

    print("\n[5] Verdicts:")
    for i, verdict in enumerate(result.verdicts, 1):
        print(f"\n    Verdict {i}:")
        print(f"      Claim: {verdict.claim.text}")
        print(f"      Status: {verdict.verdict.value}")
        print(f"      Confidence: {verdict.confidence:.2f}")
        print(f"      Hallucination type: {verdict.halluc_type.value}")
        print(f"      Explanation: {verdict.explanation[:100]}...")

    print("\n" + "=" * 70)
    print("Demo completed successfully!")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
