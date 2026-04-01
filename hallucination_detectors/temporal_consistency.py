"""
Temporal Consistency Checker (Type 2c: TEMPORAL_DISPLACEMENT)

Detects claims that attach facts/information to the wrong time period.
Validates temporal expressions and event ordering.
"""

from __future__ import annotations
import re
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
import time
# Detectors use ClaimProtocol (duck typing)

from .base import BaseDetector, HallucinationFlag
from hallucination_types import HallucinationType, Severity


class TemporalConsistencyChecker(BaseDetector):
    """
    Checks temporal consistency of claims.

    Supported types:
      - TEMPORAL_DISPLACEMENT
    """

    # Temporal expression patterns
    DATE_PATTERNS = [
        r'\b(19|20)\d{2}\b',  # years 1900-2099
        r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b',  # MM/DD/YYYY
        r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+(19|20)\d{2}\b',
    ]

    RELATIVE_TIME_WORDS = {
        'now', 'today', 'currently', 'presently', 'at the moment',
        'recently', 'lately', 'these days',
        'last year', 'last month', 'last week',
        'next year', 'next month', 'next week',
        'ago', 'from now', 'in the past', 'in the future'
    }

    # Known temporal facts about entities (simplified - in production, query KG)
    TEMPORAL_KNOWLEDGE = {
        # Entity → (start_date, end_date) or specific event year
        "openai": ("2015-12-01", None),  # founded Dec 2015, still active
        "anthropic": ("2021-01-01", None),  # founded 2021
        "python": ("1991-02-20", None),  # released Feb 1991
        "claude": ("2023-03-01", None),  # launched March 2023
        "gpt-4": ("2023-03-14", None),  # released March 2023
        "covid-19": ("2019-12-01", None),  # emerged Dec 2019
        "iphone": ("2007-01-09", None),  # announced Jan 2007
        "windows xp": ("2001-10-25", "2014-04-08"),  # released to EOL
        "internet": ("1969-01-01", None),  # ARPANET
    }

    @property
    def supported_hallucination_types(self) -> List[HallucinationType]:
        return [HallucinationType.TEMPORAL_DISPLACEMENT]

    async def detect(
        self,
        claim: AtomicClaim,
        context: Optional[dict] = None,
    ) -> List[HallucinationFlag]:
        """
        Detect temporal displacement in claim.

        Args:
            claim: The claim to analyze
            context: Optional corpus with temporal facts

        Returns:
            Flag if claim misplaces event/fact in time
        """
        t_start = time.time()
        cache_key = self._cache_key(claim.text, str(context.get('corpus_timestamp') if context else 0))

        if cache_key in self._cache:
            return self._cache[cache_key]

        flags: List[HallucinationFlag] = []

        # Extract temporal expressions from claim
        temporal_exprs = self._extract_temporal_expressions(claim.text)

        # Check for anachronisms
        for expr in temporal_exprs:
            # Try to parse year/date
            year_match = re.search(r'\b(19|20)\d{2}\b', expr)
            if year_match:
                year = int(year_match.group())
                current_year = datetime.now().year

                # Future date without speculative context?
                if year > current_year + 2:
                    # Could be future planning - need context
                    continue

                # Too distant past?
                if year < 1900:
                    flag = self._create_flag(
                        claim_id=claim.claim_id,
                        claim_text=claim.text,
                        hallucination_type=HallucinationType.TEMPORAL_DISPLACEMENT,
                        confidence=0.90,
                        evidence=f"Year {year} seems implausible for this context",
                        metadata={"extracted_year": year, "expression": expr}
                    )
                    flags.append(flag)
                    continue

                # Check against known entity timelines
                entity_temporal_mismatch = self._check_entity_timeline(claim.text, year)
                if entity_temporal_mismatch:
                    entity, expected_range = entity_temporal_mismatch
                    flag = self._create_flag(
                        claim_id=claim.claim_id,
                        claim_text=claim.text,
                        hallucination_type=HallucinationType.TEMPORAL_DISPLACEMENT,
                        confidence=0.85,
                        evidence=f"'{entity}' did not exist in {year}. Expected: {expected_range}",
                        metadata={
                            "entity": entity,
                            "claim_year": year,
                            "expected_range": expected_range,
                        }
                    )
                    flags.append(flag)

        # Check for impossible sequences
        sequence_error = self._check_event_sequence(claim.text)
        if sequence_error:
            flags.append(self._create_flag(
                claim_id=claim.claim_id,
                claim_text=claim.text,
                hallucination_type=HallucinationType.TEMPORAL_DISPLACEMENT,
                confidence=0.75,
                evidence=sequence_error,
                metadata={"error_type": "impossible_sequence"}
            ))

        # Use LLM for subtle temporal logic issues
        if not flags and temporal_exprs:
            llm_flag = await self._llm_temporal_check(claim, context)
            if llm_flag:
                flags.append(llm_flag)

        for flag in flags:
            flag.latency_ms = (time.time() - t_start) * 1000 / len(flags) if flags else 0.0

        self._cache[cache_key] = flags
        return flags

    def _extract_temporal_expressions(self, text: str) -> List[str]:
        """Extract dates, times, and temporal phrases."""
        expressions = []

        # Check explicit date patterns
        for pattern in self.DATE_PATTERNS:
            expressions.extend(re.findall(pattern, text, re.IGNORECASE))

        # Check relative time words
        for word in self.RELATIVE_TIME_WORDS:
            if word in text.lower():
                expressions.append(word)

        return list(set(expressions))

    def _check_entity_timeline(self, text: str, claim_year: int) -> Optional[Tuple[str, str]]:
        """
        Check if claims about entities contradict their known timelines.

        Returns:
            (entity_name, expected_range) if mismatch found, else None
        """
        text_lower = text.lower()

        for entity, (start_str, end_str) in self.TEMPORAL_KNOWLEDGE.items():
            if entity in text_lower:
                # Parse start/end years
                start_year = int(re.search(r'\b(19|20)\d{2}\b', start_str).group()) if start_str else None

                if start_year and claim_year < start_year:
                    return (entity, f"not until {start_year}")

                if end_str:
                    end_year = int(re.search(r'\b(19|20)\d{2}\b', end_str).group())
                    if claim_year > end_year:
                        return (entity, f"ended in {end_year}")

        return None

    def _check_event_sequence(self, text: str) -> Optional[str]:
        """Check if event sequence is impossible (e.g., event B before event A when A must precede B)."""
        # Look for chronological markers
        markers = {
            'before': ['first', 'initially', 'previously', 'earlier'],
            'after': ['then', 'later', 'subsequently', 'afterward', 'next'],
        }

        text_lower = text.lower()

        # Pattern: "X before Y" but Y's known to always precede X
        # Simplified: detect impossible sequences like "died before born", "graduated before enrolled"
        pairs = [
            (r'died', r'born'),
            (r'graduated', r'enrolled'),
            (r'hired', r'applied'),
            (r'launched', r'developed'),
            (r'published', r'written'),
            (r'sold', r'bought'),
            (r'won', r'competed'),
        ]

        for before_pat, after_pat in pairs:
            if re.search(before_pat, text_lower) and re.search(after_pat, text_lower):
                # Need to check order - very simplified
                before_match = re.search(before_pat, text_lower)
                after_match = re.search(after_pat, text_lower)
                if before_match and after_match:
                    if before_match.start() < after_match.start():
                        # "died before born" pattern detected
                        return f"Impossible temporal sequence: '{before_pat}' occurs before '{after_pat}'"
                    # else: correct order

        return None

    async def _llm_temporal_check(
        self,
        claim: AtomicClaim,
        context: Optional[dict] = None,
    ) -> Optional[HallucinationFlag]:
        """Use LLM to detect subtle temporal inconsistencies."""
        prompt = f"""Check for temporal inconsistencies or anachronisms in this claim.

Claim: "{claim.text}"

Known facts from corpus:
{context.get('corpus_snippet', 'No corpus provided') if context else 'N/A'}

Respond JSON: {{"temporal_error": bool, "explanation": "...", "correct_timeframe": "..."}}
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

                if result.get('temporal_error'):
                    return self._create_flag(
                        claim_id=claim.claim_id,
                        claim_text=claim.text,
                        hallucination_type=HallucinationType.TEMPORAL_DISPLACEMENT,
                        confidence=0.70,
                        evidence=result.get('explanation', 'Temporal inconsistency detected'),
                        metadata={"correct_timeframe": result.get('correct_timeframe')}
                    )
        except Exception:
            pass

        return None
