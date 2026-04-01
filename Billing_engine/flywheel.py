"""
╔══════════════════════════════════════════════════════════════════════════╗
║  FEEDBACK FLYWHEEL — Phase 4                                            ║
║  User corrections → RLHF pairs → Fine-tune queue → Corpus update       ║
╚══════════════════════════════════════════════════════════════════════════╝

Every user correction becomes training signal.
The more pilots correct the agent, the better it gets.
This is the compounding data moat.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CorrectionType(str, Enum):
    FACTUAL_ERROR    = "factual_error"       # wrong fact stated
    HALLUCINATION    = "hallucination"        # fabricated information
    MISSING_CITATION = "missing_citation"     # no source provided
    SYCOPHANCY       = "sycophancy"           # agreed with false premise
    CONFLICT_MISSED  = "conflict_missed"      # contradicting sources not surfaced
    INCOMPLETE       = "incomplete"           # correct but missing important detail
    STYLE            = "style"                # format/tone issue (low priority)


class CorrectionPriority(str, Enum):
    CRITICAL = "critical"   # hallucination / factual error — fix immediately
    HIGH     = "high"       # missing citation / sycophancy
    MEDIUM   = "medium"     # incomplete answer
    LOW      = "low"        # style / format


PRIORITY_MAP = {
    CorrectionType.FACTUAL_ERROR:    CorrectionPriority.CRITICAL,
    CorrectionType.HALLUCINATION:    CorrectionPriority.CRITICAL,
    CorrectionType.SYCOPHANCY:       CorrectionPriority.HIGH,
    CorrectionType.MISSING_CITATION: CorrectionPriority.HIGH,
    CorrectionType.CONFLICT_MISSED:  CorrectionPriority.HIGH,
    CorrectionType.INCOMPLETE:       CorrectionPriority.MEDIUM,
    CorrectionType.STYLE:            CorrectionPriority.LOW,
}


@dataclass
class UserCorrection:
    correction_id:   str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    tenant_id:       str = ""
    session_id:      str = ""
    query:           str = ""
    agent_response:  str = ""           # what the agent said
    correct_response:str = ""           # what it should have said
    correction_type: CorrectionType = CorrectionType.FACTUAL_ERROR
    priority:        CorrectionPriority = CorrectionPriority.HIGH
    source_url:      str = ""           # user-provided correct source
    timestamp:       float = field(default_factory=time.time)
    validated:       bool = False       # human review completed
    incorporated:    bool = False       # added to training data


@dataclass
class RLHFPair:
    """A (prompt, chosen, rejected) triplet for RLHF fine-tuning."""
    pair_id:    str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    prompt:     str = ""
    chosen:     str = ""     # correct/preferred response
    rejected:   str = ""     # original incorrect response
    source:     str = ""     # correction_id that generated this pair
    created_at: float = field(default_factory=time.time)


@dataclass
class CorpusUpdate:
    """A new verified fact to add to the knowledge corpus."""
    update_id:       str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    claim_text:      str = ""
    source_url:      str = ""
    authority_tier:  int = 4
    trust_score:     float = 0.80
    from_correction: str = ""     # correction_id
    created_at:      float = field(default_factory=time.time)


class FeedbackFlywheel:
    """
    Turns every user correction into compounding training value.

    Pipeline:
      1. User submits correction (wrong fact + correct fact + source)
      2. Triage: classify type, assign priority
      3. Validate: human or automated source check
      4. Build RLHF pair: (query, correct_response, wrong_response)
      5. Add to fine-tune queue (daily batch)
      6. Update corpus with new verified fact
      7. Re-run eval harness to confirm improvement

    This is the data moat:
      More pilots → more corrections → better model → better product → more pilots
    """

    def __init__(self):
        self._corrections:    list[UserCorrection] = []
        self._rlhf_pairs:     list[RLHFPair]       = []
        self._corpus_updates: list[CorpusUpdate]   = []
        self._fine_tune_queue:list[str]             = []   # pair_ids

    def submit(
        self,
        tenant_id:       str,
        session_id:      str,
        query:           str,
        agent_response:  str,
        correct_response:str,
        correction_type: CorrectionType = CorrectionType.FACTUAL_ERROR,
        source_url:      str = "",
    ) -> UserCorrection:
        """Accept a correction from a pilot user."""
        correction = UserCorrection(
            tenant_id=       tenant_id,
            session_id=      session_id,
            query=           query,
            agent_response=  agent_response,
            correct_response=correct_response,
            correction_type= correction_type,
            priority=        PRIORITY_MAP[correction_type],
            source_url=      source_url,
        )
        self._corrections.append(correction)

        # Auto-validate low-risk corrections with a source URL
        if source_url and correction_type != CorrectionType.STYLE:
            self._auto_validate(correction)

        return correction

    def _auto_validate(self, correction: UserCorrection) -> None:
        """
        Lightweight automated validation:
        - Source URL provided → tentatively validate
        - CRITICAL priority → flag for human review regardless
        Production: call NLI verifier to check source supports correct_response.
        """
        if correction.priority == CorrectionPriority.CRITICAL:
            return   # Always human-review critical corrections
        correction.validated = True
        self._build_rlhf_pair(correction)
        if correction.source_url:
            self._queue_corpus_update(correction)

    def human_validate(self, correction_id: str, approved: bool, reviewer_note: str = "") -> dict:
        """Human reviewer approves or rejects a correction."""
        correction = next((c for c in self._corrections if c.correction_id == correction_id), None)
        if not correction:
            return {"error": "Correction not found"}
        if approved:
            correction.validated = True
            self._build_rlhf_pair(correction)
            if correction.source_url:
                self._queue_corpus_update(correction)
        return {
            "correction_id": correction_id,
            "approved":      approved,
            "rlhf_pairs":    len(self._rlhf_pairs),
            "corpus_updates":len(self._corpus_updates),
        }

    def _build_rlhf_pair(self, correction: UserCorrection) -> RLHFPair:
        """Build a (prompt, chosen, rejected) RLHF training pair."""
        pair = RLHFPair(
            prompt=   correction.query,
            chosen=   correction.correct_response,
            rejected= correction.agent_response,
            source=   correction.correction_id,
        )
        self._rlhf_pairs.append(pair)
        self._fine_tune_queue.append(pair.pair_id)
        correction.incorporated = True
        return pair

    def _queue_corpus_update(self, correction: UserCorrection) -> CorpusUpdate:
        """Queue the correct answer as a new verified corpus fact."""
        update = CorpusUpdate(
            claim_text=     correction.correct_response[:500],
            source_url=     correction.source_url,
            authority_tier= 3,       # user-provided — medium trust until verified
            trust_score=    0.75,
            from_correction=correction.correction_id,
        )
        self._corpus_updates.append(update)
        return update

    def export_rlhf_dataset(self) -> str:
        """Export RLHF pairs as JSONL for fine-tuning."""
        lines = []
        for pair in self._rlhf_pairs:
            lines.append(json.dumps({
                "messages": [
                    {"role": "user",      "content": pair.prompt},
                    {"role": "assistant", "content": pair.chosen},
                ],
                "rejected": pair.rejected,
                "pair_id":  pair.pair_id,
            }))
        return "\n".join(lines)

    def pending_corpus_updates(self) -> list[dict]:
        """Return verified corpus updates ready to ingest."""
        return [
            {
                "update_id":      u.update_id,
                "claim_text":     u.claim_text,
                "source_url":     u.source_url,
                "authority_tier": u.authority_tier,
                "trust_score":    u.trust_score,
            }
            for u in self._corpus_updates
        ]

    def flywheel_stats(self) -> dict:
        total = len(self._corrections)
        validated = sum(1 for c in self._corrections if c.validated)
        by_type = {}
        for c in self._corrections:
            by_type[c.correction_type.value] = by_type.get(c.correction_type.value, 0) + 1
        return {
            "total_corrections":   total,
            "validated":           validated,
            "rlhf_pairs":          len(self._rlhf_pairs),
            "corpus_updates":      len(self._corpus_updates),
            "fine_tune_queue_size":len(self._fine_tune_queue),
            "by_type":             by_type,
            "validation_rate":     f"{validated/max(1,total):.0%}",
        }
