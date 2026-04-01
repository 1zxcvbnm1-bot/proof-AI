"""
Fact-Check Pipeline — Demo + Hallucination Tests
Run: python fact_check_demo.py
Tests all 3 provider hallucination patterns.
"""

import asyncio, os, time
from fact_checker import FactCheckPipeline, KnowledgeChunk, Verdict, HalluType


def print_verdict(v):
    icons = {
        "VERIFIED":  "✅",
        "UNCERTAIN": "⚠️ ",
        "BLOCKED":   "🚫",
        "CONFLICT":  "⚡",
    }
    icon = icons.get(v.verdict.value, "?")
    conf_bar = "█" * int(v.confidence * 10) + "░" * (10 - int(v.confidence * 10))
    print(f"\n  {icon} [{v.verdict.value:<10}] conf: {conf_bar} {v.confidence:.2f}")
    print(f"     Claim: {v.claim.text[:90]}")
    print(f"     Type:  {v.claim.claim_type.value} | Halluc: {v.halluc_type.value}")
    print(f"     ↳ {v.explanation[:110]}")
    if v.conflicts:
        print(f"     ⚡ CONFLICT: {v.conflicts[0].source_a_url} vs {v.conflicts[0].source_b_url}")


async def main():
    print("\n" + "═"*65)
    print("  REAL-TIME FACT-CHECK PIPELINE — DEMO")
    print("═"*65)

    from dotenv import load_dotenv; load_dotenv()
    api_key = os.environ.get("GROQ_API_KEY", "gsk_P1ac3h0ld3rGr0qK3yT0B3R3plac3dByR3alOn3")
    if not api_key:
        print("  ⚠️  GROQ_API_KEY not set — cannot run fact-check demo")
        print("  Set it with: $env:GROQ_API_KEY = 'gsk_...'")
        return
    pipeline = FactCheckPipeline(api_key=api_key)

    # Load corpus
    corpus = [
        KnowledgeChunk("KC001", "OpenAI was founded in December 2015 in San Francisco.",
            "https://en.wikipedia.org/wiki/OpenAI", "en.wikipedia.org", 4, 0.88),
        KnowledgeChunk("KC002", "Anthropic was founded in 2021 by former OpenAI researchers.",
            "https://en.wikipedia.org/wiki/Anthropic", "en.wikipedia.org", 4, 0.92),
        KnowledgeChunk("KC003", "Python was created by Guido van Rossum and released in 1991.",
            "https://en.wikipedia.org/wiki/Python_(programming_language)", "wikipedia.org", 4, 0.91),
        KnowledgeChunk("KC004", "RAG was proposed by Lewis et al. at Facebook AI Research in 2020.",
            "https://arxiv.org/abs/2005.11401", "arxiv.org", 2, 0.97),
        KnowledgeChunk("KC005", "GDPR Article 17 gives the right to erasure of personal data.",
            "https://gdpr-info.eu/art-17-gdpr/", "gdpr-info.eu", 1, 0.99),
    ]
    pipeline.load_corpus(corpus)

    # ──────────────────────────────────────────────────────────────────────
    # TEST 1: Normal verified text
    print("\n\n─── TEST 1: Normal text (should be mostly VERIFIED) ─────────────")
    text1 = "OpenAI was founded in 2015. Python was created by Guido van Rossum. RAG was proposed in 2020."
    result1 = await pipeline.check(text1)
    print(f"  Claims: {result1.total_claims} | Verified: {result1.verified} | Blocked: {result1.blocked}")
    for v in result1.verdicts:
        print_verdict(v)

    # ──────────────────────────────────────────────────────────────────────
    # TEST 2: GPT-5 pattern — parametric confabulation
    print("\n\n─── TEST 2: GPT-5 PARAMETRIC CONFABULATION ───────────────────────")
    print("  Input contains facts NOT in our verified corpus")
    text2 = "The first Mars colony was established in 2031 with 50 settlers. The colony uses fusion reactors for energy."
    result2 = await pipeline.check(text2)
    print(f"  Claims: {result2.total_claims} | BLOCKED: {result2.blocked} (should be high)")
    for v in result2.verdicts:
        print_verdict(v)
    if result2.blocked == result2.total_claims:
        print("\n  ✅ PASS — GPT-5 parametric confabulation blocked correctly")
    else:
        print("\n  ⚠️  PARTIAL — some unverified claims passed through")

    # ──────────────────────────────────────────────────────────────────────
    # TEST 3: Gemini pattern — conflict synthesis (add conflicting chunks)
    print("\n\n─── TEST 3: GEMINI CONFLICT SYNTHESIS ────────────────────────────")
    print("  Adding two contradicting sources about Python's creation year")
    conflict_corpus = corpus + [
        KnowledgeChunk("CONFLICT_A", "Python was first released in 1989 by Guido van Rossum.",
            "https://source-a-incorrect.com/python", "source-a.com", 4, 0.80),
        KnowledgeChunk("CONFLICT_B", "Python version 1.0 was released in January 1994.",
            "https://source-b-different.com/python", "source-b.com", 4, 0.80),
    ]
    pipeline.load_corpus(conflict_corpus)

    text3 = "Python was created by Guido van Rossum."
    result3 = await pipeline.check(text3)
    print(f"  Claims: {result3.total_claims} | CONFLICT: {result3.conflicts}")
    for v in result3.verdicts:
        print_verdict(v)
    if result3.conflicts > 0 or any(v.halluc_type == HalluType.SENTENCE_CONTRADICTION for v in result3.verdicts):
        print("\n  ✅ PASS — Gemini synthesis pattern detected correctly")
    else:
        print("\n  ℹ️  No conflict detected — sources may not contradict strongly enough")

    # ──────────────────────────────────────────────────────────────────────
    # TEST 4: Streaming real-time output
    print("\n\n─── TEST 4: REAL-TIME STREAMING ──────────────────────────────────")
    pipeline.load_corpus(corpus)  # restore clean corpus
    text4 = "Anthropic was founded in 2021. The company makes Claude AI."

    print("  Streaming verdicts as they arrive:\n")
    async for event in pipeline.check_stream(text4):
        if event.event_type == "claims_extracted":
            print(f"  → Extracted {event.data['count']} claims")
        elif event.event_type == "verdict":
            d = event.data
            icon = {"VERIFIED": "✅", "UNCERTAIN": "⚠️", "BLOCKED": "🚫", "CONFLICT": "⚡"}.get(d["verdict"], "?")
            print(f"  → {icon} {d['verdict']:<10} | {d['claim'][:60]} | conf: {d['confidence']:.2f}")
        elif event.is_final:
            d = event.data
            print(f"\n  Complete: {d['verified']} verified, {d['blocked']} blocked | score: {d['overall_score']} | {d['latency_ms']}ms")

    # ──────────────────────────────────────────────────────────────────────
    # FINAL STATS
    print("\n\n─── PIPELINE STATS ───────────────────────────────────────────────")
    stats = pipeline.stats()
    for k, v in stats.items():
        print(f"  {k:<30} {v}")

    print("\n─── AUDIT TRAIL (last 4 checks) ──────────────────────────────────")
    for entry in pipeline.audit._log[-4:]:
        print(f"  {entry.result_id[:12]}... | {entry.verified}✅ {entry.blocked}🚫 {entry.conflicts}⚡ | {entry.halluc_rate} halluc | {entry.latency_ms}ms")

    print("\n" + "═"*65 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
