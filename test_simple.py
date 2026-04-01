#!/usr/bin/env python3
"""
Simple integration test for hallucination detection system.
Tests that detectors load and pipeline runs without crashing.
"""

import asyncio
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """Test that all modules can be imported."""
    print("Testing imports...")
    try:
        from hallucination_types import HallucinationType, HALLUCINATION_INFO
        print("  [OK] hallucination_types")
        from hallucination_detectors import HallucinationDetectorAggregator
        print("  [OK] hallucination_detectors")
        from Fact_checker.fact_checker import FactCheckPipeline, KnowledgeChunk
        print("  [OK] FactCheckPipeline")
        from Rag_engine.core.engine import RAGEngine, FactRecord
        print("  [OK] RAGEngine")
        from saas_layer.saas_wrapper import SaaSFactCheckService
        print("  [OK] SaaS wrapper")
        return True
    except Exception as e:
        print(f"  [FAIL] Import failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_factcheck_pipeline():
    """Test FactCheckPipeline with detectors."""
    print("\nTesting FactCheckPipeline...")
    try:
        from Fact_checker.fact_checker import FactCheckPipeline, KnowledgeChunk

        # Use mock API key (will trigger mock client)
        api_key = os.environ.get("ANTHROPIC_API_KEY", "mock-key-for-testing")
        pipeline = FactCheckPipeline(api_key=api_key, model_name="groq/llama-3.3-70b-versatile")

        # Load small corpus
        chunks = [
            KnowledgeChunk(
                chunk_id="T1",
                text="OpenAI was founded in December 2015.",
                source_url="https://example.com/openai",
                source_domain="example.com",
                authority_tier=4,
                trust_score=0.9,
            ),
            KnowledgeChunk(
                chunk_id="T2",
                text="Python was created by Guido van Rossum in 1991.",
                source_url="https://example.com/python",
                source_domain="example.com",
                authority_tier=4,
                trust_score=0.95,
            )
        ]
        pipeline.load_corpus(chunks)

        # Run a simple check
        result = await pipeline.check("When was OpenAI founded?")
        print(f" [OK] Pipeline executed")
        print(f"    - Total claims: {result.total_claims}")
        print(f"    - Verdicts: {len(result.verdicts)}")
        print(f"    - Hallucination rate: {result.halluc_rate:.1%}")
        print(f"    - Detected types: {result.halluc_types}")

        # Test streaming
        count = 0
        async for event in pipeline.check_stream("Who created Python?"):
            count += 1
            if event.is_final:
                print(f" [OK] Streaming completed ({count} events)")
                break

        return True
    except Exception as e:
        print(f" [FAIL] FactCheckPipeline test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_rag_engine():
    """Test RAGEngine with detectors."""
    print("\nTesting RAGEngine...")
    try:
        from Rag_engine.core.engine import RAGEngine, FactRecord

        api_key = os.environ.get("ANTHROPIC_API_KEY", "mock-key-for-testing")
        engine = RAGEngine(api_key=api_key, model_name="llama-3.3-70b-versatile")

        facts = [
            FactRecord(
                fact_id="R1",
                claim_text="OpenAI was founded in December 2015 in San Francisco.",
                source_urls=["https://example.com/openai"],
                source_type="wikipedia",
                authority_tier=4,
                trust_score=0.88,
                last_verified_at=asyncio.get_event_loop().time() - 86400,
            )
        ]
        engine.load_corpus(facts)
        print(f" [OK] RAGEngine loaded corpus ({len(facts)} facts)")
        print(f"  - Detectors enabled: {engine._detectors_enabled}")

        # Test query (will use mock LLM)
        count = 0
        async for token in engine.query("When was OpenAI founded?"):
            count += 1
            if token.is_final:
                print(f" [OK] RAG query completed ({count} tokens)")
                break

        stats = engine.stats()
        print(f"  - Stats: {json.dumps(stats, indent=4)}")

        return True
    except Exception as e:
        print(f" [FAIL] RAGEngine test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_saas_service():
    """Test SaaS multi-tenancy."""
    print("\nTesting SaaS service...")
    try:
        from saas_layer.saas_wrapper import SaaSFactCheckService

        service = SaaSFactCheckService()
        service.register_tenant(
            tenant_id="test_tenant",
            name="Test Corp",
            api_key="test-secret-key",
            rate_limit_rpm=10,
            monthly_quota=100
        )
        print(" [OK] Tenant registered")

        metrics = service.get_metrics()
        print(f"  - Metrics: {json.dumps(metrics, indent=4)}")
        print(f"  - Tenants: {service.list_tenants()}")

        return True
    except Exception as e:
        print(f" [FAIL] SaaS service test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    print("=" * 70)
    print("HALLUCINATION DETECTION SYSTEM - INTEGRATION TEST")
    print("=" * 70)

    results = []

    # Test 1: Imports
    results.append(("Imports", test_imports()))

    # Test 2: SaaS service (no LLM needed)
    results.append(("SaaS Service", await test_saas_service()))

    # Test 3: FactCheckPipeline (uses LLM mock)
    results.append(("FactCheckPipeline", await test_factcheck_pipeline()))

    # Test 4: RAGEngine (uses LLM mock)
    results.append(("RAGEngine", await test_rag_engine()))

    # Summary
    print("\n" + "=" * 70)
    print("RESULTS:")
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")

    total = len(results)
    passed = sum(1 for _, p in results if p)
    print(f"\nOverall: {passed}/{total} passed")
    print("=" * 70)

    return passed == total

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
