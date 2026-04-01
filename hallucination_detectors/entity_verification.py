"""
Entity Verification Detector (Type 1a: ENTITY_FABRICATION)

Detects claims about non-existent entities (people, organizations, locations).
Cross-references named entities against:
  - The provided knowledge corpus
  - LLM-based plausibility check for entities not in corpus
"""

from __future__ import annotations
import re
import time
import time
from typing import List, Optional, Set
# No direct import of fact_checker to avoid circular dependency
# Detectors use ClaimProtocol (duck typing: any object with claim_id and text)

from .base import BaseDetector, HallucinationFlag
from hallucination_types import HallucinationType, Severity


class EntityVerificationDetector(BaseDetector):
    """
    Detects fabricated entities named in claims.

    Strategy:
      1. Extract named entities using NER (spaCy or regex fallback)
      2. Check against known entities from corpus
      3. For unknown entities, use LLM to assess plausibility
      4. Flag entity types that are highly specific (person names, org names)

    Supported types:
      - ENTITY_FABRICATION
    """

    def __init__(self, client, model_name: str = ""):
        super().__init__(client, model_name)
        self._known_entities: Set[str] = set()

    def update_corpus_entities(self, corpus_chunks: List[str]) -> None:
        """Extract and cache all named entities from corpus for fast lookup."""
        import re

        self._known_entities.clear()

        # Simple NER using regex patterns (production: use spaCy)
        for text in corpus_chunks:
            # Extract capitalized proper nouns (names, orgs, places)
            # This is a simplified heuristic - use proper NER in production
            words = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text)
            self._known_entities.update(word.lower() for word in words)

            # Extract ALL-CAPS acronyms (orgs, agencies)
            acronyms = re.findall(r'\b[A-Z]{2,}\b', text)
            self._known_entities.update(acr.lower() for acr in acronyms)

        print(f"[EntityVerification] Cached {len(self._known_entities)} entities")

    @property
    def supported_hallucination_types(self) -> List[HallucinationType]:
        return [HallucinationType.ENTITY_FABRICATION]

    async def detect(
        self,
        claim: AtomicClaim,
        context: Optional[dict] = None,
    ) -> List[HallucinationFlag]:
        """
        Detect fabricated entities in the claim text.

        Args:
            claim: The claim to analyze
            context: Should include 'corpus_chunks' list for entity extraction

        Returns:
            List with 1 flag if fabrication detected, else empty
        """
        t_start = time.time()
        cache_key = self._cache_key(claim.text, str(len(self._known_entities)))

        if cache_key in self._cache:
            return self._cache[cache_key]

        flags: List[HallucinationFlag] = []

        # Step 1: Extract potential named entities from claim
        entities = self._extract_entities(claim.text)

        if not entities:
            self._cache[cache_key] = flags
            return flags

        # Step 2: Check against known corpus entities
        unknown_entities = [
            ent for ent in entities
            if ent.lower() not in self._known_entities
        ]

        if not unknown_entities:
            # All entities are in corpus - likely not fabricated
            self._cache[cache_key] = flags
            return flags

        # Step 3: Assess plausibility of unknown entities using LLM
        # Only flag high-confidence fabrications
        plausibility_scores = await self._check_entity_plausibility(unknown_entities, claim.text)

        for entity, (is_plausible, reason, score) in plausibility_scores.items():
            if not is_plausible and score < 0.3:  # High confidence it's fake
                flag = self._create_flag(
                    claim_id=claim.claim_id,
                    claim_text=claim.text,
                    hallucination_type=HallucinationType.ENTITY_FABRICATION,
                    confidence=1.0 - score,  # inverted: low plausibility = high hallucination confidence
                    evidence=f"Unknown entity: '{entity}'. {reason}",
                    metadata={
                        "entity": entity,
                        "all_unknown": unknown_entities,
                        "plausibility_score": score,
                    },
                    latency_ms=(time.time() - t_start) * 1000,
                )
                flags.append(flag)

        self._cache[cache_key] = flags
        return flags

    def _extract_entities(self, text: str) -> List[str]:
        """Extract named entities from text using regex heuristics."""
        entities = []

        # Pattern 1: Proper nouns (capitalized sequences)
        proper = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text)
        entities.extend(proper)

        # Pattern 2: Acronyms (2+ uppercase letters)
        acronyms = re.findall(r'\b[A-Z]{2,}\b', text)
        entities.extend(acronyms)

        # Pattern 3: Quoted names (e.g., "Dr. Sarah Chen")
        quoted = re.findall(r'"([A-Z][a-zA-Z\s.]+)"', text)
        entities.extend(quoted)

        # Filter out common non-entity capitalized words (start of sentence, etc.)
        # In production, use spaCy NER: nlp(text).ents
        filtered = []
        sentence_starters = {'The', 'A', 'An', 'In', 'On', 'At', 'By', 'For', 'It'}
        for ent in entities:
            if ent not in sentence_starters and len(ent) > 1:
                filtered.append(ent)

        return list(set(filtered))  # deduplicate

    async def _check_entity_plausibility(
        self,
        entities: List[str],
        claim_text: str,
    ) -> dict[str, tuple[bool, str, float]]:
        """
        Use LLM to assess if unknown entities are plausible or fabricated.

        Returns:
            Dict mapping entity → (is_plausible, reason, plausibility_score)
        """
        if not self._client:
            # No client - assume all unknown are potentially fabricated
            return {ent: (False, "Not in corpus and no LLM for verification", 0.0) for ent in entities}

        # Batch entities to reduce API calls
        results = {}
        for entity in entities[:5]:  # Limit to top 5 to avoid rate limits
            prompt = f"""Evaluate whether this named entity is PL AUSIBLE (could exist) or FABRICATED (made up).

Entity: "{entity}"
From claim: "{claim_text}"

Consider:
- Does it follow naming conventions for its type? (person names, org names, place names)
- Is it similar to known entities but with slight misspelling? (e.g., "Googol" vs "Google")
- Does it appear in any known context or is it completely novel?

Return JSON only: {{"plausible": bool, "reason": "brief", "score": 0.0-1.0}}
  - plausible=True, score=0.9: clearly could exist (e.g., "John Smith")
  - plausible=False, score=0.1: clearly fake (e.g., "Xyzabc Corp")
  - score around 0.5: uncertain
"""

            try:
                if hasattr(self._client, 'chat'):
                    resp = await self._client.chat.completions.create(
                        model=self._model_name,
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=100,
                    )
                    text = resp.choices[0].message.content.strip()
                else:
                    # Fallback for non-chat client
                    text = '{"plausible": false, "reason": "client not available", "score": 0.0}'
            except Exception as e:
                text = '{"plausible": false, "reason": "error", "score": 0.0}'

            try:
                import json
                parsed = json.loads(text.replace("```json", "").replace("```", "").strip())
                is_plausible = parsed.get("plausible", True)
                reason = parsed.get("reason", "")
                score = float(parsed.get("score", 0.5))
                results[entity] = (is_plausible, reason, score)
            except Exception:
                results[entity] = (False, "LLM parse error", 0.0)

        return results
