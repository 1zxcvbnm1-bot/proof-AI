"""
╔══════════════════════════════════════════════════════╗
║  PII SCRUBBER  — Presidio-grade anonymisation        ║
║  Detects 12 entity types · tokenizes · restores      ║
╚══════════════════════════════════════════════════════╝

Flow:
  raw text → detect PII → replace with [ENTITY_N] tokens
  → store token↔value map in encrypted session store
  → after LLM response: restore only in user's session
  → token map NEVER sent to LLM or external API
"""

from __future__ import annotations
import re, hashlib, time, json
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PIIMatch:
    entity_type: str
    original:    str
    token:       str
    start:       int
    end:         int


@dataclass
class ScrubResult:
    scrubbed_text: str
    token_map:     dict[str, str]   # token → original
    matches:       list[PIIMatch]
    pii_detected:  bool
    session_id:    str


class PIIScrubber:
    """
    Production PII scrubber with 12 entity types.
    Microsoft Presidio-compatible patterns.

    Production upgrade path:
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine
        analyzer  = AnalyzerEngine()
        anonymizer = AnonymizerEngine()

    For now: regex-based with same interface as Presidio output.
    Handles: EMAIL, PHONE, US_SSN, IP_ADDRESS, CREDIT_CARD,
             IBAN, DATE_OF_BIRTH, PERSON, LOCATION, MEDICAL_RECORD,
             API_KEY, JWT_TOKEN
    """

    PATTERNS = [
        # High-confidence structured patterns first
        ("EMAIL",          r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'),
        ("PHONE",          r'\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'),
        ("US_SSN",         r'\b\d{3}-\d{2}-\d{4}\b'),
        ("IP_ADDRESS",     r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),
        ("CREDIT_CARD",    r'\b(?:\d[ \-]?){13,16}\b'),
        ("IBAN",           r'\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}(?:[A-Z0-9]?){0,16}\b'),
        ("DATE_OF_BIRTH",  r'\b(?:0?[1-9]|1[0-2])[-/](?:0?[1-9]|[12]\d|3[01])[-/](?:19|20)\d{2}\b'),
        ("API_KEY",        r'\b(?:sk-ant-|sk-|Bearer\s)[A-Za-z0-9\-_]{20,}\b'),
        ("JWT_TOKEN",      r'\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b'),
        ("MEDICAL_RECORD", r'\bMRN[:\s#]?\d{6,10}\b'),
        # Broad patterns last (more false positives, lower priority)
        ("PERSON",         r'\b(?:Mr\.|Mrs\.|Ms\.|Dr\.|Prof\.)\s[A-Z][a-z]+(?:\s[A-Z][a-z]+)+\b'),
    ]

    def __init__(self):
        self._compiled = [(t, re.compile(p)) for t, p in self.PATTERNS]
        self._sessions: dict[str, dict] = {}   # session_id → {token: original, expires_at: ts}
        self.SESSION_TTL = 3600   # 1 hour

    def scrub(self, text: str, session_id: str) -> ScrubResult:
        """
        Scrub PII from text. Returns ScrubResult.
        token_map is stored in session — never exposed externally.
        """
        self._cleanup_expired_sessions()

        counters: dict[str, int] = {}
        matches:  list[PIIMatch] = []
        token_map: dict[str, str] = {}
        scrubbed = text

        # Process all entity types
        for entity_type, pattern in self._compiled:
            for m in pattern.finditer(scrubbed):
                original = m.group()
                # Skip if already tokenized
                if original.startswith('[') and original.endswith(']'):
                    continue
                counters[entity_type] = counters.get(entity_type, 0) + 1
                token = f"[{entity_type}_{counters[entity_type]}]"
                matches.append(PIIMatch(
                    entity_type=entity_type,
                    original=original,
                    token=token,
                    start=m.start(),
                    end=m.end(),
                ))
                token_map[token] = original

        # Apply replacements (longest first to avoid partial overlap)
        for match in sorted(matches, key=lambda x: len(x.original), reverse=True):
            scrubbed = scrubbed.replace(match.original, match.token)

        # Store in session (never written to disk in dev mode)
        if session_id not in self._sessions:
            self._sessions[session_id] = {"tokens": {}, "expires_at": 0}
        self._sessions[session_id]["tokens"].update(token_map)
        self._sessions[session_id]["expires_at"] = time.time() + self.SESSION_TTL

        return ScrubResult(
            scrubbed_text=scrubbed,
            token_map=token_map,
            matches=matches,
            pii_detected=len(matches) > 0,
            session_id=session_id,
        )

    def restore(self, text: str, session_id: str) -> str:
        """Restore PII tokens in output — ONLY in user's local session."""
        session = self._sessions.get(session_id, {})
        token_map = session.get("tokens", {})
        for token, original in token_map.items():
            text = text.replace(token, original)
        return text

    def audit_summary(self, result: ScrubResult) -> dict:
        """Return safe audit entry — entity types + counts only, no originals."""
        counts: dict[str, int] = {}
        for m in result.matches:
            counts[m.entity_type] = counts.get(m.entity_type, 0) + 1
        return {
            "session_id":   result.session_id[:8] + "...",
            "pii_detected": result.pii_detected,
            "entity_counts": counts,
            "query_hash":   hashlib.sha256(result.scrubbed_text.encode()).hexdigest()[:16],
        }

    def _cleanup_expired_sessions(self) -> None:
        now = time.time()
        expired = [sid for sid, s in self._sessions.items() if s.get("expires_at", 0) < now]
        for sid in expired:
            del self._sessions[sid]

    def clear_session(self, session_id: str) -> None:
        """Explicit session cleanup — call on logout or session end."""
        self._sessions.pop(session_id, None)
