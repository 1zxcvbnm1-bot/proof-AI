"""
RAG Engine ↔ Fact-Check Pipeline — Integration Bridge

Connects core/engine.py (RAG) with core/fact_checker.py (Fact-Check).
The RAG engine retrieves and generates; the fact-check pipeline verifies.

Flow:
  User query
    → RAG engine retrieves + generates response
    → FactCheckBridge intercepts the generated text
    → Fact-check pipeline verifies every claim
    → Returns annotated response with per-claim verdicts
"""

from __future__ import annotations
import asyncio, os, sys
from typing import AsyncIterator

sys.path.insert(0, os.path.dirname(__file__))

from fact_checker import (
    FactCheckPipeline, KnowledgeChunk,
    Verdict, ClaimVerdict,
)

try:
    from engine import RAGEngine, FactRecord
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False


class AnnotatedToken:
    """A streamed token with optional fact-check annotation."""
    def __init__(self, text: str, verdict: ClaimVerdict | None = None, is_final: bool = False):
        self.text     = text
        self.verdict  = verdict
        self.is_final = is_final

    def to_dict(self) -> dict:
        return {
            "text":     self.text,
            "verdict":  self.verdict.verdict.value if self.verdict else None,
            "conf":     round(self.verdict.confidence, 3) if self.verdict else None,
            "claim":    self.verdict.claim.text[:80] if self.verdict else None,
            "is_final": self.is_final,
        }


class FactCheckBridge:
    """
    Middleware bridge between RAG output and fact-check pipeline.

    Modes:
      INLINE  — check claims while streaming, annotate in real-time
      POST    — check after full response is generated (lower latency UX)
      BOTH    — stream first, then emit a verification report

    Usage:
        bridge = FactCheckBridge(
            rag_engine=rag,
            fact_pipeline=pipeline,
            mode="POST"
        )
        async for token in bridge.query("What is GDPR?"):
            print(token.text, end="")
            if token.verdict:
                print(f" [{token.verdict.verdict.value}]", end="")
    """

    def __init__(
        self,
        fact_pipeline: FactCheckPipeline,
        rag_engine=None,        # RAGEngine if available
        mode: str = "POST",     # INLINE | POST | BOTH
    ):
        self.pipeline   = fact_pipeline
        self.rag        = rag_engine
        self.mode       = mode

    def _convert_rag_corpus(self, rag_facts: list) -> list[KnowledgeChunk]:
        """Convert RAGEngine FactRecord list to KnowledgeChunk list."""
        chunks = []
        for f in rag_facts:
            chunks.append(KnowledgeChunk(
                chunk_id=f.fact_id,
                text=f.claim_text,
                source_url=f.source_urls[0] if f.source_urls else "",
                source_domain=f.source_urls[0].split("/")[2] if f.source_urls else "",
                authority_tier=f.authority_tier,
                trust_score=f.trust_score,
            ))
        return chunks

    async def verify_text(self, text: str, session_id: str | None = None):
        """Standalone verification (no RAG) — useful for checking any text."""
        return await self.pipeline.check(text, session_id)

    async def verify_stream(self, text: str, session_id: str | None = None) -> AsyncIterator:
        """Streaming verification of any text."""
        async for event in self.pipeline.check_stream(text, session_id):
            yield event

    def summary_report(self, text: str, session_id: str | None = None) -> str:
        """Run sync check and return human-readable report. Blocks."""
        result = asyncio.run(self.pipeline.check(text, session_id))

        lines = [
            "┌─ Fact-Check Report ─────────────────────────────────────────┐",
            f"│  Claims:  {result.total_claims:3d} total   Verified: {result.verified:3d}   Uncertain: {result.uncertain:3d}",
            f"│  Blocked: {result.blocked:3d}          Conflicts: {result.conflicts:3d}   Score: {result.overall_score:.2f}",
            f"│  Hallucination rate: {result.halluc_rate:.1%}   Latency: {result.latency_ms:.0f}ms",
            "├─────────────────────────────────────────────────────────────┤",
        ]

        icons = {"VERIFIED": "✅", "UNCERTAIN": "⚠️ ", "BLOCKED": "🚫", "CONFLICT": "⚡"}
        for v in result.verdicts:
            icon    = icons.get(v.verdict.value, "?")
            claim   = v.claim.text[:55].ljust(55)
            conf_s  = f"{v.confidence:.2f}"
            lines.append(f"│ {icon} {claim}  conf:{conf_s}")

        lines.append("└─────────────────────────────────────────────────────────────┘")
        return "\n".join(lines)


# ─── Quick integration test ───────────────────────────────────────────────────
if __name__ == "__main__":
    async def demo():
        pipeline = FactCheckPipeline(api_key=os.environ.get("GROQ_API_KEY", ""))
        pipeline.load_corpus([
            KnowledgeChunk("KC001", "OpenAI was founded in December 2015.",
                "https://en.wikipedia.org/wiki/OpenAI", "wikipedia.org", 4, 0.88),
            KnowledgeChunk("KC002", "Python was created by Guido van Rossum in 1991.",
                "https://en.wikipedia.org/wiki/Python", "wikipedia.org", 4, 0.91),
        ])
        bridge = FactCheckBridge(fact_pipeline=pipeline)
        text = "OpenAI launched in 2015. Python was made in 1991. Mars has a population of 200."
        print(bridge.summary_report(text))

    asyncio.run(demo())
