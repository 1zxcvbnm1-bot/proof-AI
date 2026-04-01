"""
Semantic Precision Validator (Type 4: SEMANTIC_HALLUCINATION)

Detects:
  - POLYSEMY_CONFUSION: wrong meaning of ambiguous words
  - TERM_MISUSE: incorrect domain terminology
  - NEGATION_FAILURE: reversed polarity or mishandled negation
"""

from __future__ import annotations
import re
import time
from typing import List, Optional
# Detectors use ClaimProtocol (duck typing)

from .base import BaseDetector, HallucinationFlag
from hallucination_types import HallucinationType, Severity


class SemanticPrecisionValidator(BaseDetector):
    """
    Validates semantic precision: word meanings, domain terms, negation.

    Supported types:
      - POLYSEMY_CONFUSION
      - TERM_MISUSE
      - NEGATION_FAILURE
    """

    # Domain-specific controlled vocabularies (expand per enterprise domain)
    DOMAIN_GLOSSARIES = {
        "tech": {
            "API": "Application Programming Interface - a set of protocols for building software",
            "RAG": "Retrieval-Augmented Generation - combines retrieval with generation",
            "LLM": "Large Language Model - neural net trained on text",
            "token": "basic unit of text for LLM processing",
            "embedding": "numerical vector representation of text",
            "latency": "time delay between request and response",
            "throughput": "number of requests processed per unit time",
            "SLA": "Service Level Agreement - guaranteed performance metrics",
        },
        "finance": {
            "ROI": "Return on Investment - profit divided by cost",
            "EPS": "Earnings Per Share - net income divided by outstanding shares",
            "bull market": "extended period of rising stock prices",
            "bear market": "extended period of falling stock prices",
        },
        "healthcare": {
            "HIPAA": "Health Insurance Portability and Accountability Act - US privacy law",
            "EHR": "Electronic Health Record - digital patient record",
            "ICD-10": "International Classification of Diseases, 10th revision",
        },
    }

    # Polysemous words and their context-specific meanings
    POLYSEMY_MAP = {
        "bank": {
            "river": ["river", "water", "flow", "stream", "shore"],
            "financial": ["money", "account", "deposit", "loan", "credit", "investment"],
        },
        "python": {
            "snake": ["snake", "reptile", "zoo", "wild", "venomous"],
            "programming": ["code", "programming", "language", "guido", "development"],
        },
        "java": {
            "island": ["island", "indonesia", "sumatra", "java", "coffee"],
            "programming": ["programming", "oracle", "code", "jvm", "sdk"],
        },
        "apple": {
            "fruit": ["fruit", "eat", "tasty", "orchard", "healthy"],
            "company": ["iphone", "macbook", "tim cook", "tech", "stock"],
        },
        "chrome": {
            "browser": ["browser", "google", "internet", "web", "extension"],
            "material": ["metal", "shiny", "polished", "fender", "car"],
        },
    }

    # Negation cues and their correct scopes
    NEGATION_CUES = {
        'not', "n't", 'never', 'no', 'none', 'nobody', 'nothing',
        'neither', 'nor', 'nowhere', 'hardly', 'scarcely', 'barely'
    }

    @property
    def supported_hallucination_types(self) -> List[HallucinationType]:
        return [
            HallucinationType.POLYSEMY_CONFUSION,
            HallucinationType.TERM_MISUSE,
            HallucinationType.NEGATION_FAILURE,
        ]

    async def detect(
        self,
        claim: AtomicClaim,
        context: Optional[dict] = None,
    ) -> List[HallucinationFlag]:
        """
        Detect semantic precision errors.

        Args:
            claim: The claim to validate
            context: May include 'domain' key to select appropriate glossary

        Returns:
            Flags for any detected semantic errors
        """
        t_start = time.time()
        cache_key = self._cache_key(claim.text, context.get('domain', '') if context else '')

        if cache_key in self._cache:
            return self._cache[cache_key]

        flags: List[HallucinationFlag] = []
        text = claim.text
        domain = context.get('domain', 'tech') if context else 'tech'

        # 1. Check for polysemy confusion
        polysemy_flag = self._check_polysemy(text, domain)
        if polysemy_flag:
            flags.append(polysemy_flag)

        # 2. Check for domain term misuse
        term_flag = await self._check_term_misuse(text, domain)
        if term_flag:
            flags.append(term_flag)

        # 3. Check for negation failures
        neg_flag = self._check_negation(text)
        if neg_flag:
            flags.append(neg_flag)

        for flag in flags:
            flag.latency_ms = (time.time() - t_start) * 1000 / len(flags) if flags else 0.0

        self._cache[cache_key] = flags
        return flags

    def _check_polysemy(self, text: str, domain: str) -> Optional[HallucinationFlag]:
        """Detect wrong sense of ambiguous words."""
        text_lower = text.lower()

        for ambiguous_word, sense_dict in self.POLYSEMY_MAP.items():
            if ambiguous_word not in text_lower:
                continue

            # Count context words for each sense
            sense_scores = {}
            for sense, context_words in sense_dict.items():
                score = sum(1 for cw in context_words if cw in text_lower)
                sense_scores[sense] = score

            # If significant context suggests non-default sense, check
            expected_sense = self._guess_expected_sense(domain, ambiguous_word)
            actual_sense = max(sense_scores, key=sense_scores.get) if sum(sense_scores.values()) > 0 else None

            if actual_sense and actual_sense != expected_sense:
                # Polysemy confusion detected
                return self._create_flag(
                    claim_id="",  # will be filled by caller
                    claim_text=text,
                    hallucination_type=HallucinationType.POLYSEMY_CONFUSION,
                    confidence=0.80,
                    evidence=f"Word '{ambiguous_word}' used in '{actual_sense}' sense but context suggests '{expected_sense}'",
                    metadata={
                        "ambiguous_word": ambiguous_word,
                        "detected_sense": actual_sense,
                        "expected_sense": expected_sense,
                        "context_indicators": [w for w in text_lower.split() if any(cw in w for cw in sense_dict[actual_sense])],
                    }
                )

        return None

    def _guess_expected_sense(self, domain: str, word: str) -> str:
        """Guess the expected sense based on domain."""
        domain = domain.lower()

        if word == "bank":
            if domain in ["finance", "fintech", "banking", "economics"]:
                return "financial"
            return "river"  # default geographic

        if word == "python":
            if domain in ["tech", "programming", "cs", "software", "ai", "ml"]:
                return "programming"
            return "snake"

        if word == "java":
            if domain in ["tech", "programming", "software"]:
                return "programming"
            return "island"

        if word == "apple":
            if domain in ["tech", "consumer electronics"]:
                return "company"
            return "fruit"

        if word == "chrome":
            if domain in ["tech", "web", "browsers"]:
                return "browser"
            return "material"

        return "default"

    async def _check_term_misuse(self, text: str, domain: str) -> Optional[HallucinationFlag]:
        """Check if domain terminology is used incorrectly."""
        glossary = self.DOMAIN_GLOSSARIES.get(domain, {})
        if not glossary:
            return None

        text_lower = text.lower()

        for term, definition in glossary.items():
            if term.lower() in text_lower:
                # Term is used - check if it's in appropriate context
                # This is simplified: production would parse the claim to see HOW term is used
                context_words = text_lower.split()

                # Check if term appears in definition-like statement
                # e.g., "An API is a way to order food" ← misuse (API not about food)
                # We need to validate the relational semantics

                # For now, use LLM to check
                return await self._llm_check_term_misuse(text, term, definition)

        return None

    async def _llm_check_term_misuse(self, text: str, term: str, correct_def: str) -> Optional[HallucinationFlag]:
        """Use LLM to detect term misuse."""
        prompt = f"""Does this sentence use the term "{term}" correctly?

Term definition: {correct_def}

Sentence: "{text}"

Return JSON: {{"misused": bool, "reason": "...", "confidence": 0.0-1.0}}
"""

        if not self._client:
            return None

        try:
            resp = await self._client.chat.completions.create(
                model=self._model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
            )
            result_text = resp.choices[0].message.content.strip()
            import json
            result = json.loads(result_text.replace("```json", "").replace("```", "").strip())

            if result.get('misused'):
                return self._create_flag(
                    claim_id="",
                    claim_text=text,
                    hallucination_type=HallucinationType.TERM_MISUSE,
                    confidence=result.get('confidence', 0.7),
                    evidence=f"Term '{term}' misused: {result.get('reason', 'Incorrect application')}",
                    metadata={"term": term, "correct_definition": correct_def}
                )
        except Exception:
            pass

        return None

    def _check_negation(self, text: str) -> Optional[HallucinationFlag]:
        """Detect negation handling errors."""
        text_lower = text.lower()
        words = text_lower.split()

        # Count negation cues
        negation_count = sum(1 for cue in self.NEGATION_CUES if cue in words)

        if negation_count == 0:
            return None

        # Check for double negatives (e.g., "not unimportant" = "important"?)
        double_negative_patterns = [
            (r'not\s+(un\w+|in\w+|dis\w+)', 'not' + ' _1'),  # not unclear, not irrelevant
            (r"n't\s+(un\w+|in\w+|dis\w+)", "n't _1"),
            (r'never\s+(not\s+|no\s+)', 'never not'),
        ]

        for pattern in double_negative_patterns:
            if re.search(pattern[0], text_lower):
                return self._create_flag(
                    claim_id="",
                    claim_text=text,
                    hallucination_type=HallucinationType.NEGATION_FAILURE,
                    confidence=0.75,
                    evidence="Double negative detected - may invert intended meaning",
                    metadata={"error_type": "double_negative", "pattern": pattern[0]}
                )

        # Check for negation scope mismatch (simplified)
        # E.g., "The system is not insecure" parsed as "insecure" (misinterpreting double negative as single)
        # This is complex - defer to LLM for nuanced cases

        return None
