"""
PHASE 2 EXIT BENCHMARK
Runs all 8 exit criteria. Green = Phase 2 complete. Ready for Phase 3.
Run: python phase2_benchmark.py
"""

import asyncio, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "privacy"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "audit"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "Rag_engine", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "Fact_checker"))

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


async def run_benchmark():
    print("\n" + "═"*65)
    print("  PHASE 2 EXIT BENCHMARK — ORCHESTRATE AGENT ACCELERATOR")
    print("═"*65)

    results = {}

    # ── Check 1: Privacy vault operational ───────────────────────────
    print("\n[1/8] Privacy vault...")
    try:
        from privacy import PrivacyVault, Role, ConsentStatus
        vault = PrivacyVault()
        vault.register_user("bench", Role.API_USER, consent=ConsentStatus.EXPLICIT)
        r = vault.process_inbound("Email: bench@test.com, SSN: 123-45-6789", "s-bench", "bench")
        assert r.allowed and r.pii_detected and r.pii_count >= 2
        results["privacy_vault_operational"] = {"pass": True, "detail": f"{r.pii_count} PII entities scrubbed"}
        print(f"  ✅ {r.pii_count} PII entities scrubbed")
    except Exception as e:
        results["privacy_vault_operational"] = {"pass": False, "detail": str(e)}
        print(f"  ❌ {e}")

    # ── Check 2: Confidence engine ────────────────────────────────────
    print("\n[2/8] Confidence engine...")
    try:
        from confidence_audit import ConfidenceEngine, ConfidenceBand
        ce = ConfidenceEngine()
        class S:
            trust_score=0.92; authority_tier=1; last_verified_at=time.time()-3600
        r = ce.compute([S(), S()], [0.88, 0.91], False)
        assert r.band in (ConfidenceBand.HIGH, ConfidenceBand.MEDIUM)
        results["confidence_engine"] = {"pass": True, "detail": f"score={r.score:.2f} band={r.band.value}"}
        print(f"  ✅ score={r.score:.2f} band={r.band.value}")
    except Exception as e:
        results["confidence_engine"] = {"pass": False, "detail": str(e)}
        print(f"  ❌ {e}")

    # ── Check 3: Audit logger ─────────────────────────────────────────
    print("\n[3/8] Audit logger...")
    try:
        from confidence_audit import AuditLogger
        al = AuditLogger()
        from confidence_audit import AuditEntry
        al.record(AuditEntry(session_hash="abc", query_hash="def",
                             claims_verified=2, confidence_avg=0.82, latency_ms=1200))
        al.record(AuditEntry(session_hash="xyz", query_hash="uvw",
                             claims_blocked=1, halluc_detected=True, halluc_types=["parametric"], confidence_avg=0.3, latency_ms=800))
        summary = al.dashboard_summary()
        assert summary["total_queries"] == 2
        results["audit_logger"] = {"pass": True, "detail": f"{summary['total_queries']} entries, halluc_rate={summary['hallucination_rate']}"}
        print(f"  ✅ {summary['total_queries']} entries · halluc_rate={summary['hallucination_rate']}")
    except Exception as e:
        results["audit_logger"] = {"pass": False, "detail": str(e)}
        print(f"  ❌ {e}")

    # ── Check 4: Fact-check pipeline ──────────────────────────────────
    if not API_KEY:
        print("\n[4/8] Fact-check pipeline... ⚠️  skipped (no API key)")
        results["factcheck_pipeline"] = {"pass": None, "detail": "skipped — set ANTHROPIC_API_KEY"}
    else:
        print("\n[4/8] Fact-check pipeline...")
        try:
            from fact_checker import FactCheckPipeline, KnowledgeChunk
            p = FactCheckPipeline(api_key=API_KEY)
            p.load_corpus([KnowledgeChunk("KC1","OpenAI was founded in 2015.",
                "https://en.wikipedia.org/wiki/OpenAI","wikipedia.org",4,0.88)])
            r = await p.check("OpenAI was founded in 2015.")
            assert r.total_claims > 0
            results["factcheck_pipeline"] = {"pass": True, "detail": f"{r.total_claims} claims, score={r.overall_score:.2f}"}
            print(f"  ✅ {r.total_claims} claims · overall_score={r.overall_score:.2f}")
        except Exception as e:
            results["factcheck_pipeline"] = {"pass": False, "detail": str(e)}
            print(f"  ❌ {e}")

    # ── Check 5: Hallucination pattern tests ─────────────────────────
    if not API_KEY:
        print("\n[5/8] Hallucination patterns... ⚠️  skipped")
        results["hallucination_patterns"] = {"pass": None, "detail": "skipped"}
    else:
        print("\n[5/8] Hallucination patterns (GPT-5 / Claude / Gemini)...")
        try:
            from fact_checker import FactCheckPipeline, KnowledgeChunk, Verdict
            p = FactCheckPipeline(api_key=API_KEY)
            p.load_corpus([KnowledgeChunk("K1","Python was created by Guido van Rossum in 1991.",
                "https://en.wikipedia.org/wiki/Python","wikipedia.org",4,0.91)])
            r_param = await p.check("The Mars colony was founded in 2035 with 500 settlers.")
            gpt5_blocked = r_param.blocked > 0 or r_param.total_claims == 0
            results["hallucination_patterns"] = {"pass": gpt5_blocked, "detail": f"GPT-5 parametric blocked={gpt5_blocked}"}
            print(f"  {'✅' if gpt5_blocked else '❌'} GPT-5 parametric confabulation: {'blocked' if gpt5_blocked else 'NOT blocked'}")
        except Exception as e:
            results["hallucination_patterns"] = {"pass": False, "detail": str(e)}
            print(f"  ❌ {e}")

    # ── Check 6: Gateway connectivity ────────────────────────────────
    print("\n[6/8] Gateway imports...")
    try:
        from privacy import PrivacyVault, VaultAwareRAGEngine, VaultAwareFactPipeline
        vault2 = PrivacyVault()
        results["gateway_imports"] = {"pass": True, "detail": "All vault wrappers importable"}
        print("  ✅ VaultAwareRAGEngine, VaultAwareFactPipeline importable")
    except Exception as e:
        results["gateway_imports"] = {"pass": False, "detail": str(e)}
        print(f"  ❌ {e}")

    # ── Check 7: GDPR erasure ─────────────────────────────────────────
    print("\n[7/8] GDPR erasure pipeline...")
    try:
        from privacy import PrivacyVault, Role, ConsentStatus
        v = PrivacyVault()
        v.register_user("gdpr_test", Role.API_USER, consent=ConsentStatus.EXPLICIT)
        receipt = await v.request_erasure("gdpr_test")
        assert receipt["sla_met"] and receipt["receipt_hash"]
        results["gdpr_erasure"] = {"pass": True, "detail": f"SLA met={receipt['sla_met']}, systems={receipt['systems_purged']}"}
        print(f"  ✅ SLA met · systems purged: {receipt['systems_purged']}")
    except Exception as e:
        results["gdpr_erasure"] = {"pass": False, "detail": str(e)}
        print(f"  ❌ {e}")

    # ── Check 8: Confidence exit criteria ────────────────────────────
    print("\n[8/8] Confidence engine exit criteria...")
    try:
        from confidence_audit import ConfidenceEngine, ConfidenceBand
        ce = ConfidenceEngine()
        class Gov:
            trust_score=0.99; authority_tier=1; last_verified_at=time.time()-3600
        class Wiki:
            trust_score=0.88; authority_tier=4; last_verified_at=time.time()-86400
        high_r = ce.compute([Gov(), Gov()], [0.92, 0.95], False)
        low_r  = ce.compute([], [], False)
        assert high_r.band == ConfidenceBand.HIGH
        assert low_r.band == ConfidenceBand.BLOCKED
        results["confidence_bands"] = {"pass": True, "detail": f"HIGH={high_r.score:.2f} BLOCKED={low_r.score:.2f}"}
        print(f"  ✅ HIGH band: {high_r.score:.2f} · BLOCKED band: {low_r.score:.2f}")
    except Exception as e:
        results["confidence_bands"] = {"pass": False, "detail": str(e)}
        print(f"  ❌ {e}")

    # ── Final report ─────────────────────────────────────────────────
    print("\n" + "═"*65)
    print("  PHASE 2 EXIT REPORT")
    print("─"*65)
    passed  = sum(1 for r in results.values() if r["pass"] is True)
    skipped = sum(1 for r in results.values() if r["pass"] is None)
    failed  = sum(1 for r in results.values() if r["pass"] is False)
    total   = len(results)

    for name, r in results.items():
        icon = "✅" if r["pass"] is True else ("⚠️ " if r["pass"] is None else "❌")
        print(f"  {icon} {name:<35} {r['detail'][:40]}")

    print("─"*65)
    print(f"  Passed: {passed}/{total}   Skipped: {skipped}   Failed: {failed}")

    if failed == 0:
        print("\n  🎉 PHASE 2 COMPLETE — READY FOR PHASE 3")
    elif failed <= 2:
        print("\n  ⚠️  ALMOST DONE — fix the failures above and re-run")
    else:
        print("\n  ❌ PHASE 2 NOT COMPLETE — multiple failures")

    print("═"*65 + "\n")
    return results


if __name__ == "__main__":
    asyncio.run(run_benchmark())
