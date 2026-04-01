"""
Drift Detection Module (Type 2: CONTEXTUAL_DRIFT)

Detects:
  - SCOPE_CREEP: adding unsolicited information beyond the query scope
  - ASSUMPTION_INJECTION: inserting unstated assumptions as facts

Also includes detector for ASSUMPTION_INJECTION which overlaps with logical issues.
"""

from __future__ import annotations
import time
import re
from typing import List, Optional
# Detectors use ClaimProtocol (duck typing)

from .base import BaseDetector, HallucinationFlag
from hallucination_types import HallucinationType, Severity


class ScopeCreepDetector(BaseDetector):
    """
    Detects when generated content drifts beyond the scope of the user's query.

    Supported types:
      - SCOPE_CREEP
      - ASSUMPTION_INJECTION
    """

    # Indicators of unsolicited information
    OFF_TOPIC_TRIGGERS = {
        'additionally', 'furthermore', 'moreover', 'by the way',
        'incidentally', "it's also worth noting", "while we're at it",
        'speaking of', 'on another note',
    }

    # Assumption markers
    ASSUMPTION_MARKERS = {
        'obviously', 'clearly', 'of course', 'as we know',
        "it's well known", 'everyone knows', "it's understood",
        'naturally', 'presumably', 'supposedly',
        'given that', 'since', 'as', 'because'  # (when introducing unverified premise)
    }

    # Questionable expansions: broad claims when specific asked
    SCOPE_EXPANSION_PATTERNS = [
        (r'what is X', [r'X is.*because.*', r'X.*originated.*', r'history of X']),  # asking "what is" gets full history
        (r'how to X', [r'X can also be used for', r'alternatives to X', r'drawbacks of X']),  # getting unrelated info
    ]

    @property
    def supported_hallucination_types(self) -> List[HallucinationType]:
        return [
            HallucinationType.SCOPE_CREEP,
            HallucinationType.ASSUMPTION_INJECTION,
        ]

    async def detect(
        self,
        claim: AtomicClaim,
        context: Optional[dict] = None,
    ) -> List[HallucinationFlag]:
        """
        Detect scope creep and assumption injection.

        Args:
            claim: The claim (or sentence) to evaluate
            context: Should include 'original_query' to compare against

        Returns:
            Flags for scope violations
        """
        t_start = time.time()
        cache_key = self._cache_key(claim.text, context.get('query', '') if context else '')

        if cache_key in self._cache:
            return self._cache[cache_key]

        flags: List[HallucinationFlag] = []
        text = claim.text
        query = context.get('query', '') if context else ''

        # 1. Check for SCOPE_CREEP if we have query context
        if query:
            scope_flag = self._check_scope_creep(text, query)
            if scope_flag:
                flags.append(scope_flag)

        # 2. Check for ASSUMPTION_INJECTION
        assumption_flag = self._check_assumption_injection(text)
        if assumption_flag:
            flags.append(assumption_flag)

        # 3. LLM check for subtle drift
        if not flags and query:
            llm_flag = await self._llm_drift_check(claim, query)
            if llm_flag:
                flags.append(llm_flag)

        for flag in flags:
            flag.latency_ms = (time.time() - t_start) * 1000 / len(flags) if flags else 0.0

        self._cache[cache_key] = flags
        return flags

    def _check_scope_creep(self, claim_text: str, query: str) -> Optional[HallucinationFlag]:
        """Detect information that expands beyond the query's stated intent."""
        claim_lower = claim_text.lower()
        query_lower = query.lower()

        # Check for off-topic transitions
        for trigger in self.OFF_TOPIC_TRIGGERS:
            if trigger in claim_lower:
                # This sentence likely introduces new topic
                return self._create_flag(
                    claim_id="",
                    claim_text=claim_text,
                    hallucination_type=HallucinationType.SCOPE_CREEP,
                    confidence=0.70,
                    evidence=f"Off-topic expansion using phrase: '{trigger}'",
                    metadata={"trigger_phrase": trigger}
                )

        # Check query specificity vs response breadth
        # If query is narrow (e.g., "capital of France") but claim is broad ("France is a country in Europe...")
        query_words = set(query_lower.split())
        claim_words = set(claim_lower.split())

        # Simple heuristic: if claim has many words not semantically related to query
        if self._is_narrow_query(query_lower) and self._is_broad_claim(claim_lower, query_words):
            # Compute word overlap
            overlap = len(query_words & claim_words) / len(query_words) if query_words else 0
            if overlap < 0.3:  # very low overlap
                return self._create_flag(
                    claim_id="",
                    claim_text=claim_text,
                    hallucination_type=HallucinationType.SCOPE_CREEP,
                    confidence=0.60,
                    evidence=f"Claim has low topical overlap ({overlap:.0%}) with query",
                    metadata={"query": query, "overlap": overlap}
                )

        return None

    def _is_narrow_query(self, query: str) -> bool:
        """Check if query seeks specific factual answer."""
        narrow_indicators = {
            'what is', 'who is', 'when did', 'where is',
            'capital of', 'population of', 'date of',
            'how many', 'how much', 'definition of'
        }
        return any(indicator in query for indicator in narrow_indicators)

    def _is_broad_claim(self, claim: str, query_words: set[str]) -> bool:
        """Check if claim is providing broad background vs answering query."""
        broad_indicators = {
            'history', 'background', 'origin', 'founded', 'created',
            'additionally', 'furthermore', 'moreover', 'incidentally',
            'also known as', 'originally', 'previously', 'formerly'
        }
        return any(indicator in claim for indicator in broad_indicators)

    def _check_assumption_injection(self, text: str) -> Optional[HallucinationFlag]:
        """Detect unstated assumptions being presented as facts."""
        text_lower = text.lower()

        # Look for assumption markers
        for marker in self.ASSUMPTION_MARKERS:
            if marker in text_lower:
                # Extract the clause containing the marker
                # Simplified: just flag the presence
                return self._create_flag(
                    claim_id="",
                    claim_text=text,
                    hallucination_type=HallucinationType.ASSUMPTION_INJECTION,
                    confidence=0.65,
                    evidence=f"Unstated assumption introduced via '{marker}'",
                    metadata={"assumption_marker": marker}
                )

        # Check for "given that" patterns that introduce premises
        given_that_pattern = r'given that\s+([^,.;]+)[,.;]'
        for match in re.finditer(given_that_pattern, text_lower):
            premise = match.group(1).strip()
            # Check if this premise is actually in the query or context
            # Without context, we can't verify - flag for review
            return self._create_flag(
                claim_id="",
                claim_text=text,
                hallucination_type=HallucinationType.ASSUMPTION_INJECTION,
                confidence=0.55,
                evidence=f"Premise introduced with 'given that': '{premise}'",
                metadata={"premise": premise}
            )

        return None

    async def _llm_drift_check(
        self,
        claim: AtomicClaim,
        query: str,
    ) -> Optional[HallucinationFlag]:
        """Use LLM to detect subtle scope/assumption drift."""
        prompt = f"""Does this response contain information beyond what was asked in the query?

Query: "{query}"
Response: "{claim.text}"

Check for:
1. SCOPE CREEP: Adding extra facts/topics not needed
2. ASSUMPTION INJECTION: Inserting unstated assumptions

Return JSON: {{"has_drift": bool, "type": "scope_creep|assumption_injection|null", "explanation": "...", "confidence": 0.0-1.0}}
"""

        try:
            resp = await self._client.chat.completions.create(
                model=self._model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=120,
            )
            result_text = resp.choices[0].message.content.strip()
            import json
            result = json.loads(result_text.replace("```json", "").replace("```", "").strip())

            if result.get('has_drift'):
                drift_type_str = result.get('type', 'none')
                try:
                    drift_type = getattr(HallucinationType, drift_type_str.upper())
                except (AttributeError, TypeError, ValueError):
                    drift_type = None

                if drift_type and drift_type in self.supported_hallucination_types:
                    return self._create_flag(
                        claim_id=claim.claim_id,
                        claim_text=claim.text,
                        hallucination_type=drift_type,
                        confidence=result.get('confidence', 0.7),
                        evidence=result.get('explanation', 'Contextual drift detected'),
                        metadata={"llm_drift_check": True}
                    )
        except Exception:
            pass

        return None
