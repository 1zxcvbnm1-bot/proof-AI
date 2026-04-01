"""
Base classes for hallucination detectors.

All detectors inherit from BaseDetector and implement the detect() method.
Detectors run in parallel and return HallucinationFlag objects.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List, Protocol, runtime_checkable
import time
import hashlib

from hallucination_types import (
    HallucinationType,
    HallucinationInfo,
    HALLUCINATION_INFO,
    Severity,
)


@runtime_checkable
class ClaimProtocol(Protocol):
    """Minimal interface required for claim objects by detectors."""
    claim_id: str
    text: str
    claim_type: Optional[str] = None
    subject: Optional[str] = None
    predicate: Optional[str] = None


@dataclass
class HallucinationFlag:
    """Output of a detector - indicates a potential hallucination."""
    detection_id:      str
    claim_id:          str
    claim_text:        str
    hallucination_type: HallucinationType
    severity:          Severity
    confidence:        float           # 0.0 - 1.0 (detector's certainty)
    evidence:          str             # supporting evidence for detection
    detector_name:     str
    latency_ms:        float = 0.0
    metadata:          dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "detection_id": self.detection_id,
            "claim_id": self.claim_id,
            "type": self.hallucination_type.value,
            "severity": self.severity.value,
            "confidence": round(self.confidence, 4),
            "evidence": self.evidence,
            "detector": self.detector_name,
            "latency_ms": round(self.latency_ms, 2),
            "metadata": self.metadata,
        }


class BaseDetector(ABC):
    """
    Abstract base class for all hallucination detectors.

    Usage:
        detector = SpecificDetector(client, model_name)
        flags = await detector.detect(claim, context)

    Implementers must:
        - Define supported_hallucination_types property
        - Implement async detect() method
        - Optionally override cache_key() for custom caching
    """

    def __init__(self, client, model_name: str = ""):
        self._client = client
        self._model_name = model_name
        self._cache: dict[str, List[HallucinationFlag]] = {}
        self._detector_name = self.__class__.__name__

    @property
    @abstractmethod
    def supported_hallucination_types(self) -> List[HallucinationType]:
        """List of hallucination types this detector can identify."""
        pass

    @abstractmethod
    async def detect(
        self,
        claim: ClaimProtocol,  # any object with claim_id, text attributes
        context: Optional[dict] = None,
    ) -> List[HallucinationFlag]:
        """
        Run detection on a single claim.

        Args:
            claim: The atomic claim to check (must have claim_id, text)
            context: Optional additional context (e.g., corpus, query, session)

        Returns:
            List of HallucinationFlag objects (empty if none detected)
        """
        pass

    def _cache_key(self, claim_text: str, context_hash: str = "") -> str:
        """Generate cache key for this detection run."""
        combined = (claim_text + "|||" + context_hash).encode()
        return hashlib.sha256(combined).hexdigest()[:24]

    def _create_flag(
        self,
        claim_id: str,
        claim_text: str,
        hallucination_type: HallucinationType,
        confidence: float,
        evidence: str = "",
        metadata: Optional[dict] = None,
        latency_ms: float = 0.0,
    ) -> HallucinationFlag:
        """Factory method to create a detection flag."""
        info = HALLUCINATION_INFO[hallucination_type]
        return HallucinationFlag(
            detection_id=f"D{len(self._cache):08d}",
            claim_id=claim_id,
            claim_text=claim_text[:200],
            hallucination_type=hallucination_type,
            severity=info.severity,
            confidence=confidence,
            evidence=evidence,
            detector_name=self._detector_name,
            latency_ms=latency_ms,
            metadata=metadata or {},
        )


# Convenience function to run multiple detectors in parallel
async def run_detectors_parallel(
    detectors: List[BaseDetector],
    claim,
    context: Optional[dict] = None,
) -> List[HallucinationFlag]:
    """
    Run multiple detectors in parallel and aggregate results.

    Args:
        detectors: List of detector instances
        claim: The claim to check
        context: Optional context dict

    Returns:
        Flattened list of all flags from all detectors
    """
    import asyncio

    tasks = [detector.detect(claim, context) for detector in detectors]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_flags: List[HallucinationFlag] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            # Log error but continue
            print(f"[{detectors[i]._detector_name}] Error: {result}")
            continue
        all_flags.extend(result)

    return all_flags
