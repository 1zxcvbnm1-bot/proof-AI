"""
╔══════════════════════════════════════════════════════════════════════════╗
║  AGENTIC LOOP — Phase 3 Core                                            ║
║  Plan → Act → Verify → Cite → Stream                                   ║
║  Multi-turn memory · Tool registry · Self-verification · Re-plan        ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator, Optional

from anthropic import AsyncAnthropic


# ════════════════════════════════════════════════════════════════════════════
# ENUMS + MODELS
# ════════════════════════════════════════════════════════════════════════════

class StepStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    DONE      = "done"
    FAILED    = "failed"
    SKIPPED   = "skipped"


class AgentEvent(str, Enum):
    PLAN_CREATED   = "plan_created"
    STEP_START     = "step_start"
    STEP_DONE      = "step_done"
    TOOL_CALL      = "tool_call"
    TOOL_RESULT    = "tool_result"
    VERIFY_START   = "verify_start"
    VERIFY_DONE    = "verify_done"
    REPLAN         = "replan"
    CITE_START     = "cite_start"
    TOKEN          = "token"
    COMPLETE       = "complete"
    ERROR          = "error"


@dataclass
class AgentStep:
    step_id:     str
    description: str
    tool:        str                    # which tool to call
    tool_input:  dict
    status:      StepStatus = StepStatus.PENDING
    result:      Optional[str] = None
    confidence:  float = 0.0
    citations:   list[dict] = field(default_factory=list)
    latency_ms:  float = 0.0


@dataclass
class AgentPlan:
    plan_id:   str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    goal:      str = ""
    steps:     list[AgentStep] = field(default_factory=list)
    iteration: int = 1                  # re-plan increments this
    max_iter:  int = 3


@dataclass
class AgentStreamEvent:
    event:      AgentEvent
    data:       dict = field(default_factory=dict)
    is_final:   bool = False


# ════════════════════════════════════════════════════════════════════════════
# TOOL REGISTRY
# ════════════════════════════════════════════════════════════════════════════

class ToolRegistry:
    """
    Registry of all tools available to the agent.
    Each tool is an async callable that returns a string result.
    Tools are selected by the planner and executed by the act stage.
    """

    def __init__(
        self,
        rag_engine=None,
        fact_pipeline=None,
        vault=None,
    ):
        self._rag     = rag_engine
        self._fact    = fact_pipeline
        self._vault   = vault
        self._tools   = self._register()

    def _register(self) -> dict:
        return {
            "rag_query":      self._rag_query,
            "fact_check":     self._fact_check,
            "web_search":     self._web_search,
            "calculate":      self._calculate,
            "summarise":      self._summarise,
        }

    def available(self) -> list[dict]:
        """OpenAI-style tool definitions for LLM function calling."""
        return [
            {
                "name": "rag_query",
                "description": "Retrieve verified facts from the knowledge corpus. Use for any factual question.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The factual question to answer"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "fact_check",
                "description": "Verify a specific claim or piece of text against verified sources.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The text or claim to verify"},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "web_search",
                "description": "Search the live web for recent or real-time information.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "calculate",
                "description": "Evaluate a mathematical expression safely.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "expression": {"type": "string", "description": "Math expression to evaluate"},
                    },
                    "required": ["expression"],
                },
            },
            {
                "name": "summarise",
                "description": "Summarise a long piece of text into key points.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text":     {"type": "string"},
                        "max_words": {"type": "integer", "default": 100},
                    },
                    "required": ["text"],
                },
            },
        ]

    async def execute(self, tool_name: str, tool_input: dict, session_id: str = "") -> str:
        fn = self._tools.get(tool_name)
        if not fn:
            return f"[ERROR] Unknown tool: {tool_name}"
        try:
            return await fn(tool_input, session_id)
        except Exception as e:
            return f"[ERROR] {tool_name} failed: {e}"

    async def _rag_query(self, inp: dict, session_id: str) -> str:
        if not self._rag:
            return "[RAG_UNAVAILABLE] RAG engine not connected"
        query = inp.get("query", "")
        chunks = []
        async for token in self._rag.query(query, session_id):
            if not token.is_final:
                chunks.append(token.text)
        return "".join(chunks)

    async def _fact_check(self, inp: dict, session_id: str) -> str:
        if not self._fact:
            return "[FACTCHECK_UNAVAILABLE] Fact-check pipeline not connected"
        text = inp.get("text", "")
        result = await self._fact.check(text, session_id)
        return json.dumps({
            "verified":    result.verified,
            "blocked":     result.blocked,
            "score":       result.overall_score,
            "halluc_rate": result.halluc_rate,
            "verdicts": [
                {
                    "claim":      v.claim.text[:80],
                    "verdict":    v.verdict.value,
                    "confidence": round(v.confidence, 3),
                }
                for v in result.verdicts
            ],
        })

    async def _web_search(self, inp: dict, session_id: str) -> str:
        # Production: Tavily / Serper API
        # from tavily import TavilyClient
        # results = TavilyClient(api_key=KEY).search(inp["query"])
        return f"[WEB] Live search results for: {inp.get('query', '')} — connect Tavily API key"

    async def _calculate(self, inp: dict, _: str) -> str:
        expr = inp.get("expression", "")
        allowed = set("0123456789+-*/().,% ")
        if not all(c in allowed for c in expr):
            return "[CALC_ERROR] Unsafe expression"
        try:
            result = eval(expr, {"__builtins__": {}})  # noqa: S307
            return str(result)
        except Exception as e:
            return f"[CALC_ERROR] {e}"

    async def _summarise(self, inp: dict, _: str) -> str:
        text = inp.get("text", "")
        max_w = inp.get("max_words", 100)
        words = text.split()
        if len(words) <= max_w:
            return text
        return " ".join(words[:max_w]) + "..."


# ════════════════════════════════════════════════════════════════════════════
# MEMORY STORE
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class MemoryEntry:
    role:       str       # user | assistant | tool
    content:    str
    timestamp:  float = field(default_factory=time.time)
    metadata:   dict = field(default_factory=dict)


class MemoryStore:
    """
    Per-session conversation memory with sliding window.
    Production: store in Redis with TTL, or Postgres.
    """

    MAX_TURNS = 20          # keep last 20 turns
    MAX_CHARS = 16_000      # context window budget

    def __init__(self):
        self._sessions: dict[str, list[MemoryEntry]] = {}

    def add(self, session_id: str, role: str, content: str, metadata: dict = None) -> None:
        if session_id not in self._sessions:
            self._sessions[session_id] = []
        self._sessions[session_id].append(
            MemoryEntry(role=role, content=content, metadata=metadata or {})
        )
        # Trim to window
        if len(self._sessions[session_id]) > self.MAX_TURNS:
            self._sessions[session_id] = self._sessions[session_id][-self.MAX_TURNS:]

    def get_messages(self, session_id: str) -> list[dict]:
        """Return Anthropic messages format for context injection."""
        entries = self._sessions.get(session_id, [])
        messages = []
        total_chars = 0
        for entry in reversed(entries):
            total_chars += len(entry.content)
            if total_chars > self.MAX_CHARS:
                break
            messages.insert(0, {"role": entry.role, "content": entry.content})
        return messages

    def clear(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def session_count(self) -> int:
        return len(self._sessions)


# ════════════════════════════════════════════════════════════════════════════
# SELF VERIFIER
# ════════════════════════════════════════════════════════════════════════════

class SelfVerifier:
    """
    Post-tool verification before composing final response.
    Checks: confidence gate · sycophancy · hallucination markers.
    If verification fails → signal re-plan.
    """

    CONFIDENCE_GATE = 0.40
    HALLUC_MARKERS  = [
        "i think", "i believe", "probably", "likely", "i'm not sure",
        "as far as i know", "i cannot be certain", "it might be",
    ]

    def __init__(self, client: AsyncAnthropic):
        self._client = client

    async def verify(
        self,
        step_result: str,
        original_query: str,
        tool_name: str,
    ) -> tuple[bool, str, float]:
        """
        Returns (should_replan, reason, confidence).
        should_replan=True means the result is insufficient.
        """
        # Fast checks first
        result_lower = step_result.lower()

        # Tool error
        if result_lower.startswith("[error]") or result_lower.startswith("[rag_unavailable]"):
            return True, f"Tool {tool_name} returned error", 0.0

        # Hallucination markers in result
        found_markers = [m for m in self.HALLUC_MARKERS if m in result_lower]
        if len(found_markers) >= 2:
            return True, f"Uncertainty markers detected: {found_markers}", 0.2

        # Fact-check results with high block rate
        if tool_name == "fact_check":
            try:
                parsed = json.loads(step_result)
                score = parsed.get("score", 1.0)
                blocked = parsed.get("blocked", 0)
                total  = max(1, parsed.get("verified", 1) + blocked)
                if blocked / total > 0.5:
                    return True, f"Fact-check blocked {blocked}/{total} claims", score
                return False, "fact-check passed", score
            except json.JSONDecodeError:
                pass

        # Insufficient result
        if len(step_result.strip()) < 20:
            return True, "Result too short — insufficient information", 0.1

        # Quick LLM relevance check for non-trivial steps
        if len(step_result) > 100:
            prompt = f"""Does this tool result adequately answer the query?
Query: "{original_query[:200]}"
Result: "{step_result[:400]}"
Respond ONLY with JSON: {{"adequate": true/false, "confidence": 0.0-1.0}}"""
            try:
                resp = await self._client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=60,
                    messages=[{"role": "user", "content": prompt}]
                )
                raw = resp.content[0].text.strip().replace("```json", "").replace("```", "")
                parsed = json.loads(raw)
                adequate   = parsed.get("adequate", True)
                confidence = float(parsed.get("confidence", 0.7))
                if not adequate or confidence < self.CONFIDENCE_GATE:
                    return True, f"LLM verifier: adequate={adequate} conf={confidence:.2f}", confidence
                return False, "verified", confidence
            except Exception:
                pass

        return False, "passed", 0.75


# ════════════════════════════════════════════════════════════════════════════
# CITATION ENGINE
# ════════════════════════════════════════════════════════════════════════════

class CitationEngine:
    """
    Attaches inline citations and confidence badges to the final response.
    Every factual claim gets a [cite:source_url] marker.
    Confidence badges are encoded as [CONF:0.88:HIGH] inline.
    """

    def __init__(self, client: AsyncAnthropic):
        self._client = client

    async def attach(
        self,
        text:          str,
        tool_results:  list[dict],   # [{tool, result, confidence}]
    ) -> tuple[str, list[dict]]:
        """
        Returns (cited_text, citations_list).
        citations_list = [{claim, source, confidence, band}]
        """
        if not tool_results:
            return text, []

        sources = []
        for tr in tool_results:
            if tr.get("tool") == "rag_query" and tr.get("result"):
                sources.append({"type": "rag", "content": tr["result"][:300], "confidence": tr.get("confidence", 0.7)})
            elif tr.get("tool") == "fact_check" and tr.get("result"):
                try:
                    fc = json.loads(tr["result"])
                    for v in fc.get("verdicts", []):
                        if v.get("verdict") == "VERIFIED":
                            sources.append({
                                "type": "factcheck",
                                "content": v["claim"],
                                "confidence": v["confidence"],
                            })
                except json.JSONDecodeError:
                    pass

        if not sources:
            return text, []

        prompt = f"""You have verified sources below. For each factual claim in the TEXT, 
append a citation marker [cite:N] where N is the source index.
Only cite claims that are directly supported by a source.
Return the annotated text only — no explanation.

TEXT: {text[:800]}

SOURCES:
{chr(10).join(f"[{i+1}] {s['content'][:150]}" for i, s in enumerate(sources))}"""

        try:
            resp = await self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )
            cited_text = resp.content[0].text.strip()
        except Exception:
            cited_text = text

        citations = [
            {
                "index":      i + 1,
                "type":       s["type"],
                "content":    s["content"][:100],
                "confidence": s["confidence"],
                "band":       self._band(s["confidence"]),
            }
            for i, s in enumerate(sources)
        ]

        return cited_text, citations

    def _band(self, score: float) -> str:
        if score >= 0.85: return "HIGH"
        if score >= 0.60: return "MEDIUM"
        if score >= 0.40: return "LOW"
        return "BLOCKED"


# ════════════════════════════════════════════════════════════════════════════
# TRUST UI COMPOSER
# ════════════════════════════════════════════════════════════════════════════

class TrustUIComposer:
    """
    Formats the final response with trust UI metadata.
    Produces structured output the frontend renders as:
      - Inline confidence badges on claims
      - Yellow conflict banners
      - Red blocked-claim notices
      - Source attribution cards
    """

    @staticmethod
    def compose(
        text:          str,
        citations:     list[dict],
        overall_score: float,
        has_conflict:  bool,
        blocked_count: int,
    ) -> dict:
        """Returns structured trust UI payload."""
        band = TrustUIComposer._band(overall_score)

        banners = []
        if has_conflict:
            banners.append({
                "type":    "conflict",
                "color":   "#BA7517",
                "message": "Sources disagree on some claims — see citations for details.",
            })
        if blocked_count > 0:
            banners.append({
                "type":    "blocked",
                "color":   "#A32D2D",
                "message": f"{blocked_count} claim(s) suppressed — insufficient verified data.",
            })

        return {
            "text":          text,
            "citations":     citations,
            "trust": {
                "overall_score": round(overall_score, 3),
                "band":          band,
                "color":         TrustUIComposer._color(band),
                "label":         TrustUIComposer._label(band),
            },
            "banners":       banners,
            "citation_count": len(citations),
        }

    @staticmethod
    def _band(score: float) -> str:
        if score >= 0.85: return "HIGH"
        if score >= 0.60: return "MEDIUM"
        if score >= 0.40: return "LOW"
        return "BLOCKED"

    @staticmethod
    def _color(band: str) -> str:
        return {"HIGH": "#1D9E75", "MEDIUM": "#185FA5", "LOW": "#BA7517", "BLOCKED": "#A32D2D"}.get(band, "#888")

    @staticmethod
    def _label(band: str) -> str:
        return {"HIGH": "Verified", "MEDIUM": "Likely accurate", "LOW": "Limited sources", "BLOCKED": "Insufficient data"}.get(band, "Unknown")


# ════════════════════════════════════════════════════════════════════════════
# TASK PLANNER
# ════════════════════════════════════════════════════════════════════════════

class TaskPlanner:
    """
    Decomposes user query into ordered steps with tool assignments.
    Uses Claude with tool definitions to produce a structured plan.
    """

    SYSTEM = """You are a task planner for a verified-fact AI agent.
Given a user query, produce an ordered execution plan.
Each step must use exactly one tool from the available list.

Rules:
1. Always start with rag_query or fact_check for factual questions
2. Use web_search only for real-time or recent information
3. Use calculate for any math
4. Keep plans to 1-3 steps — simpler is better
5. Each step must be independently executable

Return ONLY valid JSON — no markdown, no explanation:
{
  "goal": "one sentence goal",
  "steps": [
    {
      "step_id": "S001",
      "description": "what this step does",
      "tool": "tool_name",
      "tool_input": {"key": "value"}
    }
  ]
}"""

    def __init__(self, client: AsyncAnthropic, tool_registry: ToolRegistry):
        self._client   = client
        self._registry = tool_registry

    async def plan(
        self,
        query:    str,
        history:  list[dict],
        attempt:  int = 1,
    ) -> AgentPlan:
        """Generate execution plan for a query."""
        tool_list = json.dumps([{"name": t["name"], "description": t["description"]}
                                for t in self._registry.available()], indent=2)

        user_msg = f"""Available tools:
{tool_list}

User query: "{query}"
{"Attempt: " + str(attempt) + " — previous plan failed, try a different approach." if attempt > 1 else ""}

Produce the execution plan:"""

        messages = history[-4:] + [{"role": "user", "content": user_msg}]

        try:
            resp = await self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=600,
                system=self.SYSTEM,
                messages=messages,
            )
            raw = resp.content[0].text.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(raw)

            steps = [
                AgentStep(
                    step_id=s.get("step_id", f"S{i+1:03d}"),
                    description=s.get("description", ""),
                    tool=s.get("tool", "rag_query"),
                    tool_input=s.get("tool_input", {}),
                )
                for i, s in enumerate(data.get("steps", []))
            ]

            return AgentPlan(
                goal=data.get("goal", query[:100]),
                steps=steps,
                iteration=attempt,
            )

        except (json.JSONDecodeError, KeyError, Exception):
            # Fallback: single rag_query step
            return AgentPlan(
                goal=query[:100],
                steps=[AgentStep(
                    step_id="S001",
                    description="Retrieve verified information",
                    tool="rag_query",
                    tool_input={"query": query},
                )],
                iteration=attempt,
            )


# ════════════════════════════════════════════════════════════════════════════
# RESPONSE COMPOSER
# ════════════════════════════════════════════════════════════════════════════

class ResponseComposer:
    """
    Composes the final natural language response from tool results.
    Constrained: only uses verified tool outputs — never invents.
    """

    SYSTEM = """You are a verified-fact AI assistant.
Compose a clear, helpful response using ONLY the information in [VERIFIED RESULTS] below.
Rules:
1. Do NOT add facts not present in the results
2. If results are insufficient, say so clearly
3. Be concise — one paragraph unless detail is needed
4. Reference which step provided each key fact"""

    def __init__(self, client: AsyncAnthropic):
        self._client = client

    async def compose_stream(
        self,
        query:        str,
        steps:        list[AgentStep],
        history:      list[dict],
    ) -> AsyncIterator[str]:
        """Stream composed response tokens."""
        results_block = "\n".join(
            f"[STEP {s.step_id} — {s.tool}]: {s.result[:500] if s.result else 'No result'}"
            for s in steps if s.status == StepStatus.DONE
        )

        messages = history[-4:] + [{
            "role": "user",
            "content": f"Query: {query}\n\n[VERIFIED RESULTS]\n{results_block}\n\nCompose response:"
        }]

        try:
            async with self._client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=1000,
                system=self.SYSTEM,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except Exception:
            yield "\n\n[Mock Output: Simulated API response for demo purposes ("
            for s in steps:
                if s.status == StepStatus.DONE:
                    yield f"used tool {s.tool}, "
            yield ")]"


# ════════════════════════════════════════════════════════════════════════════
# AGENT LOOP — ORCHESTRATOR
# ════════════════════════════════════════════════════════════════════════════

class AgentLoop:
    """
    Production agentic loop: Plan → Act → Verify → Cite → Stream.

    Features:
      - Multi-turn conversation memory
      - Tool registry with RAG + fact-check + web + calc
      - Self-verification with automatic re-planning (max 3 attempts)
      - Citation attachment on every factual claim
      - Trust UI payload for frontend rendering
      - Full SSE streaming throughout

    Usage:
        loop = AgentLoop(api_key=KEY, rag_engine=rag, fact_pipeline=fact)
        async for event in loop.run("Who founded Anthropic?", session_id="s-001"):
            print(event.event, event.data)
    """

    MAX_REPLAN = 3

    def __init__(
        self,
        api_key:       str,
        rag_engine=None,
        fact_pipeline=None,
        vault=None,
    ):
        self._client   = AsyncAnthropic(api_key=api_key)
        self.memory    = MemoryStore()
        self.tools     = ToolRegistry(rag_engine, fact_pipeline, vault)
        self.planner   = TaskPlanner(self._client, self.tools)
        self.verifier  = SelfVerifier(self._client)
        self.citer     = CitationEngine(self._client)
        self.composer  = ResponseComposer(self._client)
        self.trust_ui  = TrustUIComposer()

    async def run(
        self,
        query:      str,
        session_id: str,
        user_id:    str = "default",
    ) -> AsyncIterator[AgentStreamEvent]:
        """
        Full agentic loop with SSE streaming.
        Yields AgentStreamEvent at every significant stage.
        """
        t_start    = time.time()
        history    = self.memory.get_messages(session_id)
        attempt    = 1
        plan       = None
        all_results: list[dict] = []

        # ── Store user turn ──────────────────────────────────────────────
        self.memory.add(session_id, "user", query)

        # ── PLAN ────────────────────────────────────────────────────────
        while attempt <= self.MAX_REPLAN:
            plan = await self.planner.plan(query, history, attempt)

            yield AgentStreamEvent(
                event=AgentEvent.PLAN_CREATED,
                data={
                    "plan_id":   plan.plan_id,
                    "goal":      plan.goal,
                    "steps":     [{"step_id": s.step_id, "tool": s.tool, "description": s.description}
                                  for s in plan.steps],
                    "iteration": attempt,
                }
            )

            # ── ACT ──────────────────────────────────────────────────────
            replan_needed = False
            for step in plan.steps:
                step.status = StepStatus.RUNNING
                step_start  = time.time()

                yield AgentStreamEvent(
                    event=AgentEvent.STEP_START,
                    data={"step_id": step.step_id, "tool": step.tool}
                )

                # Execute tool
                yield AgentStreamEvent(
                    event=AgentEvent.TOOL_CALL,
                    data={"tool": step.tool, "input": step.tool_input}
                )

                result = await self.tools.execute(step.tool, step.tool_input, session_id)
                step.latency_ms = (time.time() - step_start) * 1000

                yield AgentStreamEvent(
                    event=AgentEvent.TOOL_RESULT,
                    data={"tool": step.tool, "result_length": len(result), "latency_ms": round(step.latency_ms)}
                )

                # ── VERIFY ───────────────────────────────────────────────
                yield AgentStreamEvent(event=AgentEvent.VERIFY_START, data={"step_id": step.step_id})

                should_replan, reason, confidence = await self.verifier.verify(result, query, step.tool)
                step.confidence = confidence

                yield AgentStreamEvent(
                    event=AgentEvent.VERIFY_DONE,
                    data={
                        "step_id":       step.step_id,
                        "should_replan": should_replan,
                        "reason":        reason,
                        "confidence":    round(confidence, 3),
                    }
                )

                if should_replan and attempt < self.MAX_REPLAN:
                    step.status = StepStatus.FAILED
                    replan_needed = True
                    yield AgentStreamEvent(
                        event=AgentEvent.REPLAN,
                        data={"reason": reason, "attempt": attempt + 1}
                    )
                    break

                step.status = StepStatus.DONE
                step.result = result
                all_results.append({
                    "tool":       step.tool,
                    "result":     result,
                    "confidence": confidence,
                    "step_id":    step.step_id,
                })

                yield AgentStreamEvent(
                    event=AgentEvent.STEP_DONE,
                    data={"step_id": step.step_id, "confidence": round(confidence, 3)}
                )

            if not replan_needed:
                break

            attempt += 1
            history = self.memory.get_messages(session_id)

        if not plan or not any(s.status == StepStatus.DONE for s in plan.steps):
            yield AgentStreamEvent(
                event=AgentEvent.ERROR,
                data={"message": "All plan attempts failed — insufficient verified data available."},
                is_final=True,
            )
            return

        # ── CITE ────────────────────────────────────────────────────────
        yield AgentStreamEvent(event=AgentEvent.CITE_START, data={})

        # Stream composed response
        full_response = ""
        async for token_text in self.composer.compose_stream(query, plan.steps, history):
            full_response += token_text
            yield AgentStreamEvent(
                event=AgentEvent.TOKEN,
                data={"text": token_text}
            )

        # Attach citations
        cited_text, citations = await self.citer.attach(full_response, all_results)

        # Trust UI payload
        avg_conf      = sum(r.get("confidence", 0) for r in all_results) / max(1, len(all_results))
        blocked_count = sum(1 for s in plan.steps if s.status == StepStatus.FAILED)
        trust_payload = self.trust_ui.compose(
            cited_text, citations, avg_conf,
            has_conflict=False,
            blocked_count=blocked_count,
        )

        # Store assistant response in memory
        self.memory.add(session_id, "assistant", cited_text, {"confidence": avg_conf})

        yield AgentStreamEvent(
            event=AgentEvent.COMPLETE,
            data={
                "response":       cited_text,
                "trust":          trust_payload["trust"],
                "citations":      citations,
                "banners":        trust_payload["banners"],
                "plan_id":        plan.plan_id,
                "steps_executed": len([s for s in plan.steps if s.status == StepStatus.DONE]),
                "attempts":       attempt,
                "latency_ms":     round((time.time() - t_start) * 1000),
            },
            is_final=True,
        )

    def stats(self) -> dict:
        return {
            "active_sessions": self.memory.session_count(),
            "tools_available": len(self.tools.available()),
        }
