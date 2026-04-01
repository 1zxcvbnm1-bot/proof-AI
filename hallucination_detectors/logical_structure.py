"""
Logical Structure Analyzer (Type 3: LOGICAL_HALLUCINATION)

Detects:
  - NON_SEQUITUR: conclusions that don't follow from premises
  - CIRCULAR_REASONING: using conclusion as its own evidence
  - FALSE_CAUSATION: asserting causality without evidence
  - CONTRADICTION_GENERATION: self-negating statements
"""

from __future__ import annotations
import time
import re
from typing import List, Optional, Tuple
# Detectors use ClaimProtocol (duck typing)

from .base import BaseDetector, HallucinationFlag
from hallucination_types import HallucinationType, Severity


class LogicalStructureAnalyzer(BaseDetector):
    """
    Analyzes logical structure of claims to detect reasoning fallacies.

    Supported types:
      - NON_SEQUITUR
      - CIRCULAR_REASONING
      - FALSE_CAUSATION
      - CONTRADICTION_GENERATION
    """

    # Causal language indicators
    CAUSAL_TRIGGERS = {
        'causes', 'caused', 'cause', 'leads to', 'led to', 'results in',
        'results in', 'therefore', 'hence', 'thus', 'so', 'consequently',
        'as a result', 'due to', 'because of', 'thanks to',
        'triggers', 'triggered', 'trigger', 'induces', 'induced',
        'makes', 'making', 'forces', 'forcing'
    }

    # Contradiction indicators within text
    CONTRADICTION_PAIRS = [
        ('is', 'is not'),
        ('is', "isn't"),
        ('can', 'cannot'),
        ('can', 'can not'),
        ('always', 'never'),
        ('all', 'none'),
        ('every', 'no'),
        ('must', 'must not'),
    ]

    # Hedging/uncertainty vs certainty language
    CERTAINTY_WORDS = {
        'definitely', 'certainly', 'undoubtedly', 'clearly', 'obviously',
        'proves', 'proven', 'confirmed', 'conclusively', 'absolutely'
    }

    @property
    def supported_hallucination_types(self) -> List[HallucinationType]:
        return [
            HallucinationType.NON_SEQUITUR,
            HallucinationType.CIRCULAR_REASONING,
            HallucinationType.FALSE_CAUSATION,
            HallucinationType.CONTRADICTION_GENERATION,
        ]

    async def detect(
        self,
        claim: AtomicClaim,
        context: Optional[dict] = None,
    ) -> List[HallucinationFlag]:
        """
        Detect logical fallacies in the claim text.

        Args:
            claim: The atomic claim to analyze
            context: Should include 'evidence_chunks' for verifying causal claims

        Returns:
            List of flags for any detected logical fallacies
        """
        t_start = time.time()
        cache_key = self._cache_key(claim.text, str(hash(str(context))))

        if cache_key in self._cache:
            return self._cache[cache_key]

        text = claim.text.lower()
        flags: List[HallucinationFlag] = []

        # 1. Check for contradiction generation (self-contradiction in same sentence/claim)
        contradiction_flag = self._check_contradiction(text, claim)
        if contradiction_flag:
            flags.append(contradiction_flag)

        # 2. Check for circular reasoning
        circular_flag = self._check_circular_reasoning(text, claim)
        if circular_flag:
            flags.append(circular_flag)

        # 3. Check for false causation
        if context and 'evidence_chunks' in context:
            causation_flag = await self._check_false_causation(claim, context)
            if causation_flag:
                flags.append(causation_flag)

        # 4. Check for non sequitur (requires context with query/premise)
        if context and 'query' in context:
            non_seq_flag = await self._check_non_sequitur(claim, context)
            if non_seq_flag:
                flags.append(non_seq_flag)

        # 5. Check for excessive certainty markers (false certainty)
        if self._has_excessive_certainty(text):
            # This is more confidence hallucination - let ConfidenceCalibrator handle it
            pass

        for flag in flags:
            flag.latency_ms = (time.time() - t_start) * 1000 / len(flags) if flags else 0.0

        self._cache[cache_key] = flags
        return flags

    def _check_contradiction(self, text: str, claim: AtomicClaim) -> Optional[HallucinationFlag]:
        """Detect explicit contradictions within the text."""
        # Check for concurrent positive and negative statements about same subject
        sentences = re.split(r'[.!?;]', text)

        for i, sent1 in enumerate(sentences):
            sent1_lower = sent1.strip().lower()
            if not sent1_lower:
                continue

            for j, sent2 in enumerate(sentences[i+1:], i+1):
                sent2_lower = sent2.strip().lower()
                if not sent2_lower:
                    continue

                # Check for shared subject with contradictory predicates
                if self._sentences_contradict(sent1_lower, sent2_lower):
                    return self._create_flag(
                        claim_id=claim.claim_id,
                        claim_text=claim.text,
                        hallucination_type=HallucinationType.CONTRADICTION_GENERATION,
                        confidence=0.85,
                        evidence=f"Contradictory statements: \"{sent1.strip()}\" vs \"{sent2.strip()}\"",
                        metadata={
                            "sentence1": sent1.strip(),
                            "sentence2": sent2.strip(),
                            "contradiction_type": "direct_negation"
                        }
                    )

        return None

    def _sentences_contradict(self, s1: str, s2: str) -> bool:
        """Heuristic to detect direct contradictions between sentences."""
        # Split into subject + predicate (simplified)
        words1 = set(s1.split())
        words2 = set(s2.split())

        # Check for known contradiction pairs
        for pos, neg in self.CONTRADICTION_PAIRS:
            if pos in words1 and neg in words2:
                # Same subject context?
                if self._similar_subject(s1, s2):
                    return True
            if neg in words1 and pos in words2:
                if self._similar_subject(s1, s2):
                    return True

        return False

    def _similar_subject(self, s1: str, s2: str) -> bool:
        """Check if two sentences likely share the same subject."""
        # Simplified: check for overlapping nouns / named entities
        # In production, use dependency parsing to extract subjects
        overlap = len(set(s1.split()) & set(s2.split()))
        return overlap >= 2  # at least 2 common words (probably same topic)

    def _check_circular_reasoning(self, text: str, claim: AtomicClaim) -> Optional[HallucinationFlag]:
        """Detect circular reasoning patterns."""
        # Pattern 1: "X is true because X is true" / "X because X"
        # Look for repeated phrases
        words = text.split()
        if len(words) < 6:
            return None

        # Check for "A is B because A is B" pattern
        text_clean = re.sub(r'[^\w\s]', '', text).strip()
        if ' because ' in text_clean:
            parts = text_clean.split(' because ', 1)
            if len(parts) == 2:
                before, after = parts
                # If the reason essentially restates the claim
                before_simple = self._simplify_phrase(before)
                after_simple = self._simplify_phrase(after)
                if before_simple and after_simple:
                    similarity = self._phrase_similarity(before_simple, after_simple)
                    if similarity > 0.7:
                        return self._create_flag(
                            claim_id=claim.claim_id,
                            claim_text=claim.text,
                            hallucination_type=HallucinationType.CIRCULAR_REASONING,
                            confidence=0.80,
                            evidence=f"Circular: \"{before}\" ↔ \"{after}\"",
                            metadata={"similarity_score": similarity}
                        )

        return None

    def _simplify_phrase(self, phrase: str) -> Optional[str]:
        """Simplify phrase by removing common words, stemming."""
        # Very simplified - production would use lemmatization
        stopwords = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'to', 'of', 'and', 'or'}
        words = [w for w in phrase.lower().split() if w not in stopwords]
        return ' '.join(words) if words else None

    def _phrase_similarity(self, p1: str, p2: str) -> float:
        """Simple word overlap similarity."""
        if not p1 or not p2:
            return 0.0
        set1, set2 = set(p1.split()), set(p2.split())
        intersection = set1 & set2
        union = set1 | set2
        return len(intersection) / len(union) if union else 0.0

    async def _check_false_causation(
        self,
        claim: AtomicClaim,
        context: dict,
    ) -> Optional[HallucinationFlag]:
        """Detect unwarranted causal assertions."""
        text_lower = claim.text.lower()

        # Check for causal language
        has_causal_word = any(trigger in text_lower for trigger in self.CAUSAL_TRIGGERS)
        if not has_causal_word:
            return None

        # Extract the causal relationship
        # Pattern: X causes Y / X leads to Y / because X, Y
        # Extract X (cause) and Y (effect)

        # For now, use LLM to assess if causal claim is supported by evidence
        evidence_chunks = context.get('evidence_chunks', [])
        if not evidence_chunks:
            return None

        prompt = f"""Check if this causal claim is SUPPORTED by the evidence.

Causal claim: "{claim.text}"

Evidence:
{chr(10).join(f"- {chunk.text[:200]}" for chunk in evidence_chunks[:5])}

Does the evidence actually demonstrate a causal relationship (not just correlation)?
Return JSON: {{"false_causation": bool, "reason": "...", "correlation_only": bool}}
"""

        try:
            if hasattr(self._client, 'chat'):
                resp = await self._client.chat.completions.create(
                    model=self._model_name,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=150,
                )
                result_text = resp.choices[0].message.content.strip()
                import json
                result = json.loads(result_text.replace("```json", "").replace("```", "").strip())

                if result.get('false_causation'):
                    return self._create_flag(
                        claim_id=claim.claim_id,
                        claim_text=claim.text,
                        hallucination_type=HallucinationType.FALSE_CAUSATION,
                        confidence=0.75,
                        evidence=result.get('reason', 'Causal claim not supported by evidence'),
                        metadata={"correlation_only": result.get('correlation_only', False)}
                    )
        except Exception:
            pass

        return None

    async def _check_non_sequitur(
        self,
        claim: AtomicClaim,
        context: dict,
    ) -> Optional[HallucinationFlag]:
        """Check if conclusion doesn't follow from the query/premise."""
        query = context.get('query', '')
        if not query:
            return None

        prompt = f"""Does this conclusion logically follow from the question/query?

Query: "{query}"
Conclusion/response: "{claim.text}"

Return JSON: {{"is_valid_inference": bool, "gap": "explain missing link if invalid"}}
"""

        try:
            if hasattr(self._client, 'chat'):
                resp = await self._client.chat.completions.create(
                    model=self._model_name,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=100,
                )
                result_text = resp.choices[0].message.content.strip()
                import json
                result = json.loads(result_text.replace("```json", "").replace("```", "").strip())

                if not result.get('is_valid_inference'):
                    return self._create_flag(
                        claim_id=claim.claim_id,
                        claim_text=claim.text,
                        hallucination_type=HallucinationType.NON_SEQUITUR,
                        confidence=0.70,
                        evidence=f"Conclusion doesn't follow from query: {result.get('gap', 'No logical connection')}",
                        metadata={"query": query}
                    )
        except Exception:
            pass

        return None

    def _has_excessive_certainty(self, text: str) -> bool:
        """Check for words of excessive certainty."""
        words = set(text.split())
        return any(word in words for word in self.CERTAINTY_WORDS)
