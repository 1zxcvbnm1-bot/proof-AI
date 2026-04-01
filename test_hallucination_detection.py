#!/usr/bin/env python3
"""
Quick test to validate hallucination detector integration with FactCheckPipeline.
"""

import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from Fact_checker.fact_checker import FactCheckPipeline, KnowledgeChunk

async def main():
    print("=" * 70)
    print("HALLUCINATION DETECTION INTEGRATION TEST")
    print("=" * 70)

    # Initialize pipeline with mock API key (will use mock client if invalid)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "mock-key")
    print(f"\n[1] Initializing FactCheckPipeline...")
    pipeline = FactCheckPipeline(api_key=api_key, model_name="groq/llama-3.3-70b-versatile")

    # Load demo corpus
    print(f"[2] Loading demo corpus...")
    demo_chunks = [
        KnowledgeChunk(
            chunk_id="C001",
            text="OpenAI was founded in December 2015 by Sam Altman and others.",
            source_url="https://en.wikipedia.org/wiki/OpenAI",
            source_domain="wikipedia.org",
            authority_tier=4,
            trust_score=0.88,
        ),
        KnowledgeChunk(
            chunk_id="C002",
            text="Anthropic was founded in 2021 by former OpenAI researchers.",
            source_url="https://en.wikipedia.org/wiki/Anthropic",
            source_domain="wikipedia.org",
            authority_tier=4,
            trust_score=0.92,
        ),
        KnowledgeChunk(
            chunk_id="C003",
            text="Python was created by Guido van Rossum and first released in 1991.",
            source_url="https://en.wikipedia.org/wiki/Python",
            source_domain="wikipedia.org",
            authority_tier=4,
            trust_score=0.95,
        ),
    ]
    pipeline.load_corpus(demo_chunks)

    # Test queries (including some with hallucination triggers)
    test_cases = [
        ("When was OpenAI founded?", "Should be VERIFIED"),
        ("Who created Python?", "Should be VERIFIED"),
        ("OpenAI was founded in 1999 by Elon Musk", "Should be BLOCKED - date + entity fabrication"),
        ("The capital of France is London", "Should be BLOCKED - false claim not in corpus"),
        ("Python was created by Elon Musk", "Should detect ENTITY_FABRICATION (Elon Musk not creator)"),
    ]

    print(f"[3] Running {len(test_cases)} test cases...\n")

    for i, (query, expected) in enumerate(test_cases, 1):
        print(f"Test {i}: {query}")
        print(f"Expected: {expected}")

        try:
            result = await pipeline.check(query)
            print(f"  → Verdicts: {len(result.verdicts)} claims")
            for v in result.verdicts:
                print(f"    - Claim: {v.claim.text[:60]}...")
                print(f"      Verdict: {v.verdict.value}, Confidence: {v.confidence:.2f}")
                print(f"      Hallucination type: {v.halluc_type.value}")
                if v.hallucination_flags:
                    print(f"      Detector flags: {[f.hallucination_type.value for f in v.hallucination_flags]}")
            print(f"  Overall hallucination rate: {result.halluc_rate:.1%}")
        except Exception as e:
            print(f"  ✗ Error: {e}")
            import traceback
            traceback.print_exc()

        print()

    print("=" * 70)
    print("Pipeline stats:")
    stats = pipeline.stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print()

    # Test streaming
    print("[4] Testing streaming output...")
    query = "When was Anthropic founded?"
    print(f"Query: {query}")
    print("Stream:")
    async for token in pipeline.check_stream(query):
        if token.is_final:
            print("\n[END]")
        else:
            print(token.text, end="", flush=True)

    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
