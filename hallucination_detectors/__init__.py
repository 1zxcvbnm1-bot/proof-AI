"""
Hallucination Detection Package

Exports:
  - All detector classes
  - HallucinationDetectorAggregator (runs all detectors in parallel)
"""

from typing import List, Optional
from .base import BaseDetector, HallucinationFlag, run_detectors_parallel
from .entity_verification import EntityVerificationDetector
import time
from .logical_structure import LogicalStructureAnalyzer
from .temporal_consistency import TemporalConsistencyChecker
from .semantic_precision import SemanticPrecisionValidator
from .structural_integrity import StructuralIntegrityChecker
from .drift_detection import ScopeCreepDetector
from .confidence_calibrator import ConfidenceCalibrator

__all__ = [
    'BaseDetector',
    'HallucinationFlag',
    'run_detectors_parallel',
    'EntityVerificationDetector',
    'LogicalStructureAnalyzer',
    'TemporalConsistencyChecker',
    'SemanticPrecisionValidator',
    'StructuralIntegrityChecker',
    'ScopeCreepDetector',
    'ConfidenceCalibrator',
]


class HallucinationDetectorAggregator:
    """
    Aggregates all hallucination detectors and runs them in parallel.

    Usage:
        aggregator = HallucinationDetectorAggregator(client, model_name)
        flags = await aggregator.detect_all(claim, context)

    Returns combined list of all flags from all detectors.
    """

    def __init__(self, client, model_name: str = ""):
        self._client = client
        self._model_name = model_name

        # Initialize all detectors
        self._detectors = [
            EntityVerificationDetector(client, model_name),
            LogicalStructureAnalyzer(client, model_name),
            TemporalConsistencyChecker(client, model_name),
            SemanticPrecisionValidator(client, model_name),
            StructuralIntegrityChecker(client, model_name),
            ScopeCreepDetector(client, model_name),
            ConfidenceCalibrator(client, model_name),
        ]

        print(f"[HallucinationAggregator] Initialized {len(self._detectors)} detectors")

    def update_corpus_entities(self, corpus_chunks: List[str]) -> None:
        """Update entity cache in detectors that need it."""
        for detector in self._detectors:
            if hasattr(detector, 'update_corpus_entities'):
                detector.update_corpus_entities(corpus_chunks)

    async def detect_all(
        self,
        claim,
        context: Optional[dict] = None,
    ) -> List[HallucinationFlag]:
        """
        Run all detectors in parallel and collect flags.

        Args:
            claim: The claim to check
            context: Optional shared context (corpus, query, etc.)

        Returns:
            Flat list of all detection flags
        """
        return await run_detectors_parallel(self._detectors, claim, context)

    @property
    def detectors(self) -> List[BaseDetector]:
        """List of all detector instances."""
        return self._detectors.copy()
