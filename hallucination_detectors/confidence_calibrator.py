"""
Confidence Calibrator (Type 6: CONFIDENCE_HALLUCINATION)

Detects:
  - FALSE_CERTAINTY: overstated confidence with weak evidence
  - FALSE_HEDGING: unnecessary hedging about well-established facts
  - AUTHORITY_FABRICATION: citing non-existent sources/experts

Monitors the gap between claimed confidence (in language) and actual evidence quality.
"""

from __future__ import annotations
import time
import re
from typing import List, Optional

from .base import BaseDetector, HallucinationFlag
from hallucination_types import HallucinationType, Severity


class ConfidenceCalibrator(BaseDetector):
    """
    Calibrates confidence claims against evidence quality.

    Detects when the language expresses confidence/uncertainty that
    is not justified by the actual evidence available.

    Supported types:
      - FALSE_CERTAINTY
      - FALSE_HEDGING
      - AUTHORITY_FABRICATION
    """

    # Certainty language - absolute language
    CERTAINTY_PHRASES = {
        'definitely', 'certainly', 'undoubtedly', 'unquestionably',
        'absolutely', 'without a doubt', 'no doubt',
        'proves', 'proven', 'conclusively', 'confirmed',
        'is true', 'is correct', 'is accurate',
        'everyone knows', 'it is clear', 'obviously', 'evidently',
        'always', 'never', '100%', 'all', 'none',
        'must be', 'has to be'
    }

    # Hedging language - uncertainty markers
    HEDGING_PHRASES = {
        'might', 'may', 'could', 'possibly', 'perhaps',
        'probably', 'likely', 'seems', 'appears',
        'I think', 'I believe', 'I guess', 'I suspect',
        'not certain', 'not sure', 'unclear',
        'somewhat', 'rather', 'partially',
        'arguably', 'potentially', 'theoretically',
        'it seems that', 'it appears that'
    }

    @property
    def supported_hallucination_types(self) -> List[HallucinationType]:
        return [
            HallucinationType.FALSE_CERTAINTY,
            HallucinationType.FALSE_HEDGING,
            HallucinationType.AUTHORITY_FABRICATION,
        ]

    async def detect(
        self,
        claim: AtomicClaim,
        context: Optional[dict] = None,
    ) -> List[HallinationFlag]:
        """
        Calibrate confidence language against evidence.

        Args:
            claim: The claim to analyze
            context: Should include:
                - 'evidence_chunks': list of supporting evidence
                - 'evidence_quality': aggregated quality score 0-1
                - 'corpus_contains_claim': bool if claim matches corpus verbatim

        Returns:
            Flags for confidence mismatches
        """
        t_start = time.time()
        cache_key = self._cache_key(claim.text, str(hash(str(context))))

        if cache_key in self._cache:
            return self._cache[cache_key]

        flags: List[HallucinationFlag] = []
        text_lower = claim.text.lower()

        # Extract citations/references to check for authority fabrication
        citations = self._extract_citations(claim.text)

        if citations:
            auth_flag = await self._check_authority_fabrication(claim, citations, context)
            if auth_flag:
                flags.append(auth_flag)

        # Get evidence quality from context
        evidence_quality = context.get('evidence_quality', 0.5) if context else 0.5
        has_strong_corpus_match = context.get('corpus_match', False) if context else False

        # Check certainty language
        certainty_detected = self._has_certainty_language(text_lower)
        hedging_detected = self._has_hedging_language(text_lower)

        # False certainty: high certainty language + low evidence
        if certainty_detected and evidence_quality < 0.6:
            flags.append(self._create_flag(
                claim_id=claim.claim_id,
                claim_text=claim.text,
                hallucination_type=HallucinationType.FALSE_CERTAINTY,
                confidence=0.8,
                evidence=f"Definitive language used but evidence quality is only {evidence_quality:.2f}",
                metadata={
                    "certainty_words": certainty_detected,
                    "evidence_quality": evidence_quality,
                    "gap": 0.8 - evidence_quality,
                }
            ))

        # False hedging: hedging language + high evidence
        if hedging_detected and evidence_quality > 0.85:
            flags.append(self._create_flag(
                claim_id=claim.claim_id,
                claim_text=claim.text,
                hallucination_type=HallucinationType.FALSE_HEDGING,
                confidence=0.7,
                evidence=f"Hedging language used but evidence is strong ({evidence_quality:.2f})",
                metadata={
                    "hedge_words": hedging_detected,
                    "evidence_quality": evidence_quality,
                }
            ))

        # No hedging when claim verbatim in corpus
        if has_strong_corpus_match and not hedging_detected and not certainty_detected:
            # Could flag as missing certainty, but that's not a hallucination per se
            pass

        for flag in flags:
            flag.latency_ms = (time.time() - t_start) * 1000 / len(flags) if flags else 0.0

        self._cache[cache_key] = flags
        return flags

    def _has_certainty_language(self, text_lower: str) -> List[str]:
        """Detect absolute/certainty language."""
        found = []
        for phrase in self.CERTAINTY_PHRASES:
            if phrase in text_lower:
                found.append(phrase)
        return found

    def _has_hedging_language(self, text_lower: str) -> List[str]:
        """Detect hedging/uncertainty language."""
        found = []
        for phrase in self.HEDGING_PHRASES:
            if phrase in text_lower:
                found.append(phrase)
        return found

    def _extract_citations(self, text: str) -> List[str]:
        """Extract citation references (e.g., [1], (Smith, 2020), etc.)."""
        patterns = [
            r'\[([^\]]+)\]',  # [1], [Smith 2020]
            r'\(([^)]+)\)',   # (Smith, 2020)
            r'according to ([A-Za-z\s]+)',  # according to X
            r'as [A-Za-z\s]+(?:said|stated|reported|wrote)',  # as X said
        ]

        citations = []
        for pattern in patterns:
            matches = re.findall(pattern, text)
            citations.extend(matches)

        return citations

    async def _check_authority_fabrication(
        self,
        claim: AtomicClaim,
        citations: List[str],
        context: Optional[dict],
    ) -> Optional[HallucinationFlag]:
        """Check if cited authorities/sources actually exist."""
        # Get known sources from corpus/contex
        known_sources = set()
        if context and 'corpus_chunks' in context:
            for chunk in context['corpus_chunks']:
                if hasattr(chunk, 'source_url'):
                    known_sources.add(chunk.source_url.lower())
                if hasattr(chunk, 'source'):
                    known_sources.add(chunk.source.lower())

        # Check each citation
        fabricated = []
        for citation in citations:
            # Check if citation matches any known source
            if not self._citation_matches_known(citation, known_sources):
                # Use LLM to verify if this is a real authority
                is_real = await self._verify_authority_existence(citation)
                if not is_real:
                    fabricated.append(citation)

        if fabricated:
            return self._create_flag(
                claim_id=claim.claim_id,
                claim_text=claim.text,
                hallucination_type=HallucinationType.AUTHORITY_FABRICATION,
                confidence=0.85,
                evidence=f"Fabricated or unverifiable sources: {', '.join(fabricated)}",
                metadata={"fabricated_citations": fabricated}
            )

        return None

    def _citation_matches_known(self, citation: str, known_sources: set[str]) -> bool:
        """Check if citation text matches any known source."""
        citation_lower = citation.lower()

        # Exact URL match?
        for source in known_sources:
            if citation_lower in source or source in citation_lower:
                return True

        # Author name match?
        # Extract potential author names (capitalized words)
        potential_authors = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', citation)
        for author in potential_authors:
            for source in known_sources:
                if author.lower() in source.lower():
                    return True

        return False

    async def _verify_authority_existence(self, citation: str) -> bool:
        """Use LLM to check if cited person/paper/organization actually exists."""
        if not self._client:
            return True  # assume real if no client

        prompt = f"""Does this cited source/person/organization actually exist?

Citation: "{citation}"

Return JSON: {{"exists": bool, "type": "person|paper|org|other", "confidence": 0.0-1.0}}
"""

        try:
            resp = await self._client.chat.completions.create(
                model=self._model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=80,
            )
            result_text = resp.choices[0].message.content.strip()
            import json
            result = json.loads(result_text.replace("```json", "").replace("```", "").strip())
            return result.get('exists', True) and result.get('confidence', 0.5) > 0.6
        except Exception:
            return True  # assume real on error (false negative worse than false positive here?)
