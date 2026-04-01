"""
╔══════════════════════════════════════════════════════════════════════════╗
║          COMPREHENSIVE HALLUCINATION TAXONOMY & DETECTION              ║
║          7 Categories · 15+ Sub-types · Severity-weighted              ║
╚══════════════════════════════════════════════════════════════════════════╝

This module defines the complete hallucination detection system for the
anti-hallucination RAG platform. All 7 hallucination types from the
framework are covered with specific detection strategies.

Category Legend:
  🔴 Type 1: FACTUAL FABRICATION  - Information contradicting established facts
  🟡 Type 2: CONTEXTUAL DRIFT      - Information beyond provided context
  🟢 Type 3: LOGICAL HALLUCINATION - Invalid reasoning patterns
  🔵 Type 4: SEMANTIC HALLUCINATION - Word meaning distortions
  🟣 Type 5: STRUCTURAL HALLUCINATION - Relationship/structure errors
  🟠 Type 6: CONFIDENCE HALLUCINATION - Misplaced certainty
  🟤 Type 7: MULTIMODAL HALLUCINATION - Cross-modal mismatches
"""

from __future__ import annotations
from enum import Enum
from dataclasses import dataclass
from typing import Optional


# ═════════════════════════════════════════════════════════════════════════════
# SEVERITY LEVELS
# ═════════════════════════════════════════════════════════════════════════════

class Severity(str, Enum):
    """Severity of hallucination for confidence penalty weighting."""
    CRITICAL = "CRITICAL"   # 0.50 penalty - fabrication, contradiction
    HIGH     = "HIGH"       # 0.35 penalty - logical fallacy, authority fabrication
    MEDIUM   = "MEDIUM"     # 0.20 penalty - scope creep, semantic drift
    LOW      = "LOW"         # 0.10 penalty - minor precision issues
    NONE     = "NONE"        # 0.00 penalty - no hallucination


# ═════════════════════════════════════════════════════════════════════════════
# COMPREHENSIVE HALLUCINATION TYPE ENUM
# ═════════════════════════════════════════════════════════════════════════════

class HallucinationType(str, Enum):
    """
    Complete enumeration of hallucination types.

    Category grouping:
      TYPE_1_FABRICATION:
        - ENTITY_FABRICATION         (non-existent person/org/place)
        - EVENT_FABRICATION         (non-existent event/meeting/date)
        - NUMERIC_FABRICATION       (false stats/dates/quantities)
        - ATTRIBUTION_FABRICATION   (wrong quote/action attribution)

      TYPE_2_CONTEXTUAL_DRIFT:
        - SCOPE_CREEP               (adding unsolicited info beyond query)
        - ASSUMPTION_INJECTION      (inserting unstated assumptions as facts)
        - TEMPORAL_DISPLACEMENT     (using info from wrong time period)

      TYPE_3_LOGICAL_HALLUCINATION:
        - NON_SEQUITUR              (conclusion unrelated to premises)
        - CIRCULAR_REASONING        (using conclusion as its own evidence)
        - FALSE_CAUSATION           (asserting causality without evidence)
        - CONTRADICTION_GENERATION  (self-negating statements)

      TYPE_4_SEMANTIC_HALLUCINATION:
        - POLYSEMY_CONFUSION        (wrong meaning of ambiguous word)
        - TERM_MISUSE               (incorrect domain terminology)
        - NEGATION_FAILURE          (reversing negative statement meaning)

      TYPE_5_STRUCTURAL_HALLUCINATION:
        - RELATIONSHIP_INVERSION     (swapping subject/object)
        - HIERARCHY_DISTORTION      (misrepresenting parent-child/part-whole)
        - SEQUENCE_CORRUPTION       (correct steps in wrong order)

      TYPE_6_CONFIDENCE_HALLUCINATION:
        - FALSE_CERTAINTY           (overstating confidence without evidence)
        - FALSE_HEDGING             (unnecessary uncertainty about established facts)
        - AUTHORITY_FABRICATION     (citing non-existent sources/experts)

      TYPE_7_MULTIMODAL_HALLUCINATION:
        - VISUAL_TEXTUAL_MISMATCH   (description doesn't match image)
        - AUDIO_TEXTUAL_MISMATCH   (transcription/content mismatch)
        - CROSS_MODAL_FABRICATION  (generating one modality that contradicts another)

    Meta-type for "no hallucination detected":
        - NONE
    """

    # ── TYPE 1: FACTUAL FABRICATION ───────────────────────────────────────────
    ENTITY_FABRICATION       = "entity_fabrication"        # 🔴 Invented entities
    EVENT_FABRICATION        = "event_fabrication"         # 🔴 Invented events
    NUMERIC_FABRICATION      = "numeric_fabrication"       # 🔴 False numbers/dates
    ATTRIBUTION_FABRICATION  = "attribution_fabrication"   # 🔴 Wrong source attribution

    # ── TYPE 2: CONTEXTUAL DRIFT ─────────────────────────────────────────────
    SCOPE_CREEP             = "scope_creep"               # 🟡 Beyond asked scope
    ASSUMPTION_INJECTION    = "assumption_injection"      # 🟡 Unstated assumptions as facts
    TEMPORAL_DISPLACEMENT   = "temporal_displacement"     # 🟡 Wrong time period

    # ── TYPE 3: LOGICAL HALLUCINATION ────────────────────────────────────────
    NON_SEQUITUR            = "non_sequitur"              # 🟢 Invalid inference
    CIRCULAR_REASONING      = "circular_reasoning"        # 🟢 Self-referential logic
    FALSE_CAUSATION         = "false_causation"           # 🟢 Correlation≠causation
    CONTRADICTION_GENERATION = "contradiction_generation" # 🟢 Self-negating

    # ── TYPE 4: SEMANTIC HALLUCINATION ───────────────────────────────────────
    POLYSEMY_CONFUSION      = "polysemy_confusion"        # 🔵 Wrong word sense
    TERM_MISUSE             = "term_misuse"               # 🔵 Incorrect terminology
    NEGATION_FAILURE        = "negation_failure"          # 🔵 Reversed polarity

    # ── TYPE 5: STRUCTURAL HALLUCINATION ─────────────────────────────────────
    RELATIONSHIP_INVERSION  = "relationship_inversion"    # 🟣 Subject↔object swap
    HIERARCHY_DISTORTION    = "hierarchy_distortion"      # 🟣 Parent-child wrong
    SEQUENCE_CORRUPTION     = "sequence_corruption"       # 🟣 Wrong order

    # ── TYPE 6: CONFIDENCE HALLUCINATION ─────────────────────────────────────
    FALSE_CERTAINTY         = "false_certainty"           # 🟠 Overstated confidence
    FALSE_HEDGING           = "false_hedging"             # 🟠 Unnecessary uncertainty
    AUTHORITY_FABRICATION   = "authority_fabrication"     # 🟠 Fake citations

    # ── TYPE 7: MULTIMODAL HALLUCINATION ─────────────────────────────────────
    VISUAL_TEXTUAL_MISMATCH = "visual_textual_mismatch"   # 🟤 Image≠description
    AUDIO_TEXTUAL_MISMATCH  = "audio_textual_mismatch"    # 🟤 Audio≠transcript
    CROSS_MODAL_FABRICATION = "cross_modal_fabrication"   # 🟤 Modal contradiction

    # ── LEGACY / META ─────────────────────────────────────────────────────────
    FACTUAL_CONTRADICTION   = "factual_contradiction"     # legacy
    PROMPT_CONTRADICTION    = "prompt_contradiction"      # legacy
    SENTENCE_CONTRADICTION  = "sentence_contradiction"    # legacy
    NON_SENSIBLE            = "non_sensible"              # legacy
    NONE                    = "none"                       # 🟢 No hallucination


# ═════════════════════════════════════════════════════════════════════════════
# HALLUCINATION TYPE METADATA
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class HallucinationInfo:
    """Metadata for each hallucination type."""
    type: HallucinationType
    category: str               # e.g., "FABRICATION", "CONTEXTUAL_DRIFT"
    description: str            # human-readable explanation
    detection_strategy: str     # how to detect this
    severity: Severity          # default severity weight
    examples: list[str]         # example triggers
    llm_prompt_template: str   # template for LLM-based detection (if applicable)


HALLUCINATION_INFO: dict[HallucinationType, HallucinationInfo] = {
    # ── TYPE 1: FACTUAL FABRICATION ───────────────────────────────────────────
    HallucinationType.ENTITY_FABRICATION: HallucinationInfo(
        type=HallucinationType.ENTITY_FABRICATION,
        category="FABRICATION",
        description="Claims about non-existent entities (people, organizations, locations)",
        detection_strategy="Cross-reference NER entities against knowledge base + web search fallback",
        severity=Severity.CRITICAL,
        examples=[
            "Dr. Sarah Chen won the 2019 Nobel Prize in Physics",
            "The city of New Atlantis was founded in 1650",
            "Microsoft's CEO is John Smith (real name: Satya Nadella)"
        ],
        llm_prompt_template="""
Check if this claim mentions entities that don't exist in the verified knowledge base.

Claim: "{claim}"

Known entities from corpus: {known_entities}

Respond JSON: {{"is_fabricated": bool, "entities": ["entity1", ...], "explanation": "..."}}
"""
    ),

    HallucinationType.EVENT_FABRICATION: HallucinationInfo(
        type=HallucinationType.EVENT_FABRICATION,
        category="FABRICATION",
        description="Claims about events that never occurred",
        detection_strategy="Extract events (verb-centered) + temporal expressions; validate against known timeline",
        severity=Severity.CRITICAL,
        examples=[
            "The 2024 Summer Olympics were held in Chicago",
            "In 1995, IBM acquired Google",
            "Next month's conference will be in Tokyo (no such conference scheduled)"
        ],
        llm_prompt_template="""
Does this claim describe an event that likely never happened?

Claim: "{claim}"
Context from corpus: {context}

Respond JSON: {{"is_fabricated": bool, "reason": "...", "confidence": 0.0-1.0}}
"""
    ),

    HallucinationType.NUMERIC_FABRICATION: HallucinationInfo(
        type=HallucinationType.NUMERIC_FABRICATION,
        category="FABRICATION",
        description="False statistics, dates, counts, measurements, percentages",
        detection_strategy="Extract numbers + units; check range plausibility + corpus comparison",
        severity=Severity.CRITICAL,
        examples=[
            "95% of developers use Python as their primary language",
            "The meeting was on January 32nd, 2023",
            "The population of Earth is 50 billion"
        ],
        llm_prompt_template="""
Is this numeric claim plausible and supported?

Claim: "{claim}"
Corpus facts: {corpus_numbers}

Respond JSON: {{"is_fabricated": bool, "expected_range": "...", "deviation_pct": float}}
"""
    ),

    HallucinationType.ATTRIBUTION_FABRICATION: HallucinationInfo(
        type=HallucinationType.ATTRIBUTION_FABRICATION,
        category="FABRICATION",
        description="Wrongly attributing quotes, actions, or discoveries to entities",
        detection_strategy="Extract (subject, attribution) pairs; verify against authoritative sources",
        severity=Severity.CRITICAL,
        examples=[
            "Einstein said, 'God does not play dice' (actually: he did say it, but context differs)",
            "Python was created by James Gosling (wrong: Guido van Rossum)",
            "The theory of relativity was proposed by Isaac Newton"
        ],
        llm_prompt_template="""
Does this attribution match known facts?

Claim: "{claim}"
Authority records: {authorities}

Respond JSON: {{"misattributed": bool, "correct_attribution": "...", "reason": "..."}}
"""
    ),

    # ── TYPE 2: CONTEXTUAL DRIFT ─────────────────────────────────────────────
    HallucinationType.SCOPE_CREEP: HallucinationInfo(
        type=HallucinationType.SCOPE_CREEP,
        category="CONTEXTUAL_DRIFT",
        description="Adding information beyond the user's query scope",
        detection_strategy="Compare generated text against query intent; detect unsolicited expansions",
        severity=Severity.MEDIUM,
        examples=[
            "User asks: 'What is RAG?' → Response explains LLMs, transformers, attention, plus RAG",
            "User asks: 'Python's creator' → Response includes full biography, unrelated projects"
        ],
        llm_prompt_template="""
Does the response contain information NOT directly addressing the query?

Query: "{query}"
Response: "{response}"

Respond JSON: {{"has_scope_creep": bool, "off_topic_segments": ["..."], "scope_violation_score": 0.0-1.0}}
"""
    ),

    HallucinationType.ASSUMPTION_INJECTION: HallucinationInfo(
        type=HallucinationType.ASSUMPTION_INJECTION,
        category="CONTEXTUAL_DRIFT",
        description="Inserting unstated assumptions as if they were facts",
        detection_strategy="Detect unverified presuppositions, counterfactual conditionals",
        severity=Severity.MEDIUM,
        examples=[
            "Since everyone knows Python is fastest, we'll use it (assuming 'everyone knows' and 'fastest')",
            "Obviously the meeting went poorly because... (assuming meeting quality)",
            "Given that the client is unhappy, we should... (assuming client state not in context)",
        ],
        llm_prompt_template="""
Does this text assume facts not in the provided context or query?

Text: "{text}"
Known facts: {context}

Respond JSON: {{"has_assumptions": bool, "assumed_facts": ["..."], "confidence": 0.0-1.0}}
"""
    ),

    HallucinationType.TEMPORAL_DISPLACEMENT: HallucinationInfo(
        type=HallucinationType.TEMPORAL_DISPLACEMENT,
        category="CONTEXTUAL_DRIFT",
        description="Applying information from the wrong time period",
        detection_strategy="Extract temporal expressions + events; compare against valid time ranges",
        severity=Severity.MEDIUM,
        examples=[
            "In 2020, COVID-19 vaccines were widely available (actually: late 2020/2021)",
            "Barack Obama was president during the 2008 financial crisis (actually: Bush)",
            "Python 2 is the current stable version (wrong: EOL 2020)"
        ],
        llm_prompt_template="""
Does this claim attach a fact to the wrong time period?

Claim: "{claim}"
Temporal facts in corpus: {temporal_facts}

Respond JSON: {{"temporal_mismatch": bool, "correct_timeframe": "...", "error_years": int}}
"""
    ),

    # ── TYPE 3: LOGICAL HALLUCINATION ────────────────────────────────────────
    HallucinationType.NON_SEQUITUR: HallucinationInfo(
        type=HallucinationType.NON_SEQUITUR,
        category="LOGICAL_HALLUCINATION",
        description="Conclusion does not follow from stated premises",
        detection_strategy="Logical form extraction + entailment verification (premise→conclusion)",
        severity=Severity.HIGH,
        examples=[
            "Sales increased last quarter. Therefore, our marketing team is excellent.",
            "It's raining. Hence, the stock market will crash.",
            "The cat is black. So, all cats are mammals."
        ],
        llm_prompt_template="""
Is the conclusion a logical consequence of the premise?

Premise: "{premise}"
Conclusion: "{conclusion}"

Respond JSON: {{"is_valid_inference": bool, "gap": "...", "required_premises": ["..."]}}
"""
    ),

    HallucinationType.CIRCULAR_REASONING: HallucinationInfo(
        type=HallucinationType.CIRCULAR_REASONING,
        category="LOGICAL_HALLUCINATION",
        description="Using the conclusion as evidence for itself",
        detection_strategy="Detect circular dependency in premise→conclusion chains",
        severity=Severity.HIGH,
        examples=[
            "The Bible is true because it says so, and we know it says so because the Bible is true",
            "This policy is effective because it works well",
            "He is trustworthy because he is honest"
        ],
        llm_prompt_template="""
Does this argument assume what it's trying to prove (circular)?

Argument: "{argument}"

Respond JSON: {{"is_circular": bool, "circular_element": "...", "fallacy_type": "..."}}
"""
    ),

    HallucinationType.FALSE_CAUSATION: HallucinationInfo(
        type=HallucinationType.FALSE_CAUSATION,
        category="LOGICAL_HALLUCINATION",
        description="Asserting causality without sufficient evidence (correlation≠causation)",
        detection_strategy="Detect causal language (causes, leads to, results in) without causal evidence",
        severity=Severity.HIGH,
        examples=[
            "Ice cream sales cause drowning incidents (both correlated with summer)",
            "The astrology app increased user engagement because we changed the UI (ignoring seasonality)",
            "Vaccination rates rose, then autism diagnoses rose → vaccines cause autism"
        ],
        llm_prompt_template="""
Does this claim assert causation without establishing causal mechanism or ruling out confounders?

Claim: "{claim}"
Available evidence: {evidence}

Respond JSON: {{"false_causation": bool, "correlation_only": bool, "confounders": ["..."], "needed_studies": "..."}}
"""
    ),

    HallucinationType.CONTRADICTION_GENERATION: HallucinationInfo(
        type=HallucinationType.CONTRADICTION_GENERATION,
        category="LOGICAL_HALLUCINATION",
        description="Generating text that contains self-contradictory statements",
        detection_strategy="Cross-check claims within same text for logical negation",
        severity=Severity.HIGH,
        examples=[
            "Allbirds shoes are 100% recycled. Allbirds shoes contain new materials.",
            "Python was released in 1991. Actually, Python's first release was 2005.",
            "The system is fully secure. However, there are no security measures in place."
        ],
        llm_prompt_template="""
Find explicit contradictions within this text.

Text: "{text}"

Respond JSON: {{"has_contradiction": bool, "conflicting_pairs": [[sent1, sent2], ...], "negation_indicators": ["..."]}}
"""
    ),

    # ── TYPE 4: SEMANTIC HALLUCINATION ───────────────────────────────────────
    HallucinationType.POLYSEMY_CONFUSION: HallucinationInfo(
        type=HallucinationType.POLYSEMY_CONFUSION,
        category="SEMANTIC_HALLUCINATION",
        description="Using wrong sense of an ambiguous word (e.g., 'bank' as river vs financial)",
        detection_strategy="Word Sense Disambiguation + context consistency check",
        severity=Severity.MEDIUM,
        examples=[
            "The Python language is fast like a snake (confusing python≠reptile)",
            "We need to debug the code at the river bank (bank≠financial/River bank)",
            "The Java applet ran smoothly (Java≠island/java≠programming)"
        ],
        llm_prompt_template="""
Does this word use an incorrect sense given the context?

Ambiguous word: "{word}"
Context: "{context}"
Expected domain: {domain}

Respond JSON: {{"sense_error": bool, "correct_sense": "...", "domain_mismatch": bool}}
"""
    ),

    HallucinationType.TERM_MISUSE: HallucinationInfo(
        type=HallucinationType.TERM_MISUSE,
        category="SEMANTIC_HALLUCINATION",
        description="Using domain-specific terms incorrectly or nonsensically",
        detection_strategy="Check term definitions against domain ontologies/glossaries",
        severity=Severity.MEDIUM,
        examples=[
            "The API endpoint returned a database cursor (actually: JSON response)",
            "The neural network's gradient clipping was set to 0.5 FPS (mixing optimization with framerate)",
            "We deployed the Docker container to Kubernetes using a pandas DataFrame"
        ],
        llm_prompt_template="""
Is this technical term used correctly in context?

Term: "{term}"
Usage: "{sentence}"
Domain: {domain}
Definition: {definition}

Respond JSON: {{"misused": bool, "correct_usage": "...", "violation": "..."}}
"""
    ),

    HallucinationType.NEGATION_FAILURE: HallucinationInfo(
        type=HallucinationType.NEGATION_FAILURE,
        category="SEMANTIC_HALLUCINATION",
        description="Reversing or mishandling negation (double negative errors, scope errors)",
        detection_strategy="Negation scope parsing + polarity consistency check",
        severity=Severity.MEDIUM,
        examples=[
            "The system is not insecure interpreted as insecure (double negative confusion)",
            "No students failed the exam parsed as all students failed",
            "I don't have no money → interpreted as I have some money (should be I have no money)",
        ],
        llm_prompt_template="""
Check for negation mishandling or polarity reversal.

Text: "{text}"

Respond JSON: {{"negation_error": bool, "error_type": "scope_mismatch|double_negative|polarity_flip", "correct_interpretation": "..."}}
"""
    ),

    # ── TYPE 5: STRUCTURAL HALLUCINATION ─────────────────────────────────────
    HallucinationType.RELATIONSHIP_INVERSION: HallucinationInfo(
        type=HallucinationType.RELATIONSHIP_INVERSION,
        category="STRUCTURAL_HALLUCINATION",
        description="Swapping subject/object or reversing directional relationships",
        detection_strategy="Extract subject-predicate-object triples; validate directionality",
        severity=Severity.HIGH,
        examples=[
            "OpenAI acquired Microsoft (should be: Microsoft invested in OpenAI)",
            "Python was created by Apple (wrong subject/object)",
            "The customer returns the product (should be: The product is returned by the customer)",
        ],
        llm_prompt_template="""
Is the relationship direction correct in this claim?

Claim: "{claim}"
Known facts: {known_relationships}

Respond JSON: {{"inverted": bool, "correct_relation": "X→Y", "current_relation": "Y→X", "entities": ["X", "Y"]}}
"""
    ),

    HallucinationType.HIERARCHY_DISTORTION: HallucinationInfo(
        type=HallucinationType.HIERARCHY_DISTORTION,
        category="STRUCTURAL_HALLUCINATION",
        description="Misrepresenting parent-child, part-whole, type-subtype hierarchies",
        detection_strategy="Validate containment/part-of relationships against knowledge graph",
        severity=Severity.HIGH,
        examples=[
            "A poodle is a type of cat (wrong: poodle is a subtype of dog, not cat)",
            "France is a city in Germany (wrong: France is a country)",
            "The API is part of the SDK (actually: SDK includes API)",
        ],
        llm_prompt_template="""
Does this violate the known hierarchy or part-whole structure?

Claim: "{claim}"
Ontology/graph: {hierarchy_data}

Respond JSON: {{"hierarchy_error": bool, "error_type": "parent_child_swap|level_mismatch", "correct_structure": "..."}}
"""
    ),

    HallucinationType.SEQUENCE_CORRUPTION: HallucinationInfo(
        type=HallucinationType.SEQUENCE_CORRUPTION,
        category="STRUCTURAL_HALLUCINATION",
        description="Correct steps in wrong temporal or procedural order",
        detection_strategy="Extract process/event sequences; validate order constraints",
        severity=Severity.HIGH,
        examples=[
            "To bake a cake: 1) eat it, 2) mix ingredients, 3) preheat oven (wrong order)",
            "First, commit the code. Then, write the code. (reversed)",
            "The user signed up after they logged in (impossible sequence)",
        ],
        llm_prompt_template="""
Are these events/process steps in an incorrect order?

Steps: "{steps}"
Dependencies: {known_dependencies}

Respond JSON: {{"sequence_error": bool, "violated_order": "..."}}
"""
    ),

    # ── TYPE 6: CONFIDENCE HALLUCINATION ─────────────────────────────────────
    HallucinationType.FALSE_CERTAINTY: HallucinationInfo(
        type=HallucinationType.FALSE_CERTAINTY,
        category="CONFIDENCE_HALLUCINATION",
        description="Overstating confidence without sufficient evidence (definitive language with weak support)",
        detection_strategy="Track confidence words (definitely, certainly, undoubtedly) vs. evidence quality",
        severity=Severity.MEDIUM,
        examples=[
            "The answer is unequivocally 42 (with only weak evidence)",
            "This is absolutely the best approach (with no comparative data)",
            "No one disputes this fact (when disagreements exist in corpus)",
        ],
        llm_prompt_template="""
Is the level of certainty justified by the evidence?

Text: "{text}"
Evidence quality: {evidence_quality}

Respond JSON: {{"overconfident": bool, "certainty_words": ["..."], "evidence_ratio": 0.0-1.0}}
"""
    ),

    HallucinationType.FALSE_HEDGING: HallucinationInfo(
        type=HallucinationType.FALSE_HEDGING,
        category="CONFIDENCE_HALLUCINATION",
        description="Unnecessary uncertainty about well-established facts (may indicate hedging due to weak RAG)",
        detection_strategy="Detect hedging words (might, possibly, could) against highly confident evidence",
        severity=Severity.LOW,
        examples=[
            "The Earth might be round (when corpus says it's definitively spherical)",
            "Water possibly freezes at 0°C (well-established fact)",
            "It's arguably true that fire is hot (unnecessary hedging)",
        ],
        llm_prompt_template="""
Is this hedging unjustified given the strength of evidence?

Statement: "{statement}"
Evidence strength: {strength}  # HIGH|MEDIUM|LOW

Respond JSON: {{"unnecessary_hedging": bool, "boundary_words": ["..."], "recommended_confidence": 0.0-1.0}}
"""
    ),

    HallucinationType.AUTHORITY_FABRICATION: HallucinationInfo(
        type=HallucinationType.AUTHORITY_FABRICATION,
        category="CONFIDENCE_HALLUCINATION",
        description="Citing non-existent sources, fake experts, or fabricated papers",
        detection_strategy="Verify all cited sources, authors, papers against known databases",
        severity=Severity.CRITICAL,
        examples=[
            "According to Dr. Jane Smith at Harvard University (no such professor)",
            "As stated in the Journal of Advanced AI, Vol 42, 2025 (non-existent journal/volume)",
            "A study by MIT researchers found... (no such study in corpus)"
        ],
        llm_prompt_template="""
Do the cited sources actually exist and match the claim?

Citations: "{citations}"
Known sources: {source_database}

Respond JSON: {{"fabricated_source": bool, "fake_sources": ["..."], "verifiable": bool}}
"""
    ),

    # ── TYPE 7: MULTIMODAL HALLUCINATION ─────────────────────────────────────
    HallucinationType.VISUAL_TEXTUAL_MISMATCH: HallucinationInfo(
        type=HallucinationType.VISUAL_TEXTUAL_MISMATCH,
        category="MULTIMODAL_HALLUCINATION",
        description="Text description doesn't match actual image content (for multimodal inputs)",
        detection_strategy="Cross-verify image caption/description against image features (CLIP similarity)",
        severity=Severity.CRITICAL,
        examples=[
            "A red car (when image shows blue truck)",
            "People are smiling (when they are frowning)",
            "The text says 'hello' (when image shows 'goodbye')",
        ],
        llm_prompt_template="""
Does this description match the visual content?

Description: "{description}"
Image features: {image_features}

Respond JSON: {{"mismatch": bool, "mismatch_score": 0.0-1.0, "true_elements": ["..."]}}
"""
    ),

    HallucinationType.AUDIO_TEXTUAL_MISMATCH: HallucinationInfo(
        type=HallucinationType.AUDIO_TEXTUAL_MISMATCH,
        category="MULTIMODAL_HALLUCINATION",
        description="Transcript/content summary doesn't match actual audio",
        detection_strategy="Compare transcription against audio features (speaker diarization, word timestamps)",
        severity=Severity.CRITICAL,
        examples=[
            "Speaker said 'I agree' (when audio says 'I disagree')",
            "Music playing: jazz (when it's clearly classical)",
            "Background noise: traffic (when it's actually silence)",
        ],
        llm_prompt_template="""
Does this transcript match the audio content?

Transcript: "{transcript}"
Audio features: {audio_features}

Respond JSON: {{"mismatch": bool, "errors": ["..."], "confidence": 0.0-1.0}}
"""
    ),

    HallucinationType.CROSS_MODAL_FABRICATION: HallucinationInfo(
        type=HallucinationType.CROSS_MODAL_FABRICATION,
        category="MULTIMODAL_HALLUCINATION",
        description="Generating a description in one modality that contradicts another modality",
        detection_strategy="Cross-modal consistency: image+text, audio+text, etc.",
        severity=Severity.CRITICAL,
        examples=[
            "Image shows a medical chart, but text says 'no chart visible'",
            "Audio says 'silence please' but text describes 'loud crowd noise'",
            "Video transcript is about cooking, but generated summary discusses politics"
        ],
        llm_prompt_template="""
Does the {modality_a} content contradict the {modality_b} content?

Modality A: "{content_a}"
Modality B: "{content_b}"

Respond JSON: {{"contradiction": bool, "type": "...", "explanation": "..."}}
"""
    ),

    # ── LEGACY TYPES (backward compatibility) ─────────────────────────────────
    HallucinationType.FACTUAL_CONTRADICTION: HallucinationInfo(
        type=HallucinationType.FACTUAL_CONTRADICTION,
        category="LEGACY",
        description="Legacy: factual contradiction with verified sources",
        detection_strategy="NLI contradiction detection",
        severity=Severity.CRITICAL,
        examples=[],
        llm_prompt_template=""
    ),

    HallucinationType.PROMPT_CONTRADICTION: HallucinationInfo(
        type=HallucinationType.PROMPT_CONTRADICTION,
        category="LEGACY",
        description="Legacy: sycophancy / agreeing with false premise",
        detection_strategy="Prompt alignment checker",
        severity=Severity.HIGH,
        examples=[],
        llm_prompt_template=""
    ),

    HallucinationType.SENTENCE_CONTRADICTION: HallucinationInfo(
        type=HallucinationType.SENTENCE_CONTRADICTION,
        category="LEGACY",
        description="Legacy: internal sentence-level contradictions",
        detection_strategy="Internal consistency analyzer",
        severity=Severity.HIGH,
        examples=[],
        llm_prompt_template=""
    ),

    HallucinationType.NON_SENSIBLE: HallucinationInfo(
        type=HallucinationType.NON_SENSIBLE,
        category="LEGACY",
        description="Legacy: gibberish or semantically incoherent text",
        detection_strategy="Coherence analyzer",
        severity=Severity.HIGH,
        examples=[],
        llm_prompt_template=""
    ),

    HallucinationType.NONE: HallucinationInfo(
        type=HallucinationType.NONE,
        category="META",
        description="No hallucination detected",
        detection_strategy="N/A - this is the clean baseline",
        severity=Severity.NONE,
        examples=[],
        llm_prompt_template=""
    ),
}


# ═════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═════════════════════════════════════════════════════════════════════════════

def get_types_by_category(category: str) -> list[HallucinationType]:
    """Return all hallucination types in a given category."""
    return [
        htype for htype, info in HALLUCINATION_INFO.items()
        if info.category == category
    ]


def get_severity_weight(severity: Severity) -> float:
    """Convert severity level to confidence penalty weight."""
    weights = {
        Severity.CRITICAL: 0.50,
        Severity.HIGH: 0.35,
        Severity.MEDIUM: 0.20,
        Severity.LOW: 0.10,
        Severity.NONE: 0.00,
    }
    return weights.get(severity, 0.10)


def get_llm_prompt(hallucination_type: HallucinationType, **kwargs) -> str:
    """Get the LLM detection prompt template for a hallucination type."""
    info = HALLUCINATION_INFO.get(hallucination_type)
    if not info or not info.llm_prompt_template:
        return ""
    return info.llm_prompt_template.format(**kwargs)


# Category grouping for easier validation
CATEGORY_GROUPS = {
    "FABRICATION": get_types_by_category("FABRICATION"),
    "CONTEXTUAL_DRIFT": get_types_by_category("CONTEXTUAL_DRIFT"),
    "LOGICAL_HALLUCINATION": get_types_by_category("LOGICAL_HALLUCINATION"),
    "SEMANTIC_HALLUCINATION": get_types_by_category("SEMANTIC_HALLUCINATION"),
    "STRUCTURAL_HALLUCINATION": get_types_by_category("STRUCTURAL_HALLUCINATION"),
    "CONFIDENCE_HALLUCINATION": get_types_by_category("CONFIDENCE_HALLUCINATION"),
    "MULTIMODAL_HALLUCINATION": get_types_by_category("MULTIMODAL_HALLUCINATION"),
}

# All hallucination types (exclude NONE and LEGACY)
ACTIVE_HALLUCINATION_TYPES = [
    htype for htype, info in HALLUCINATION_INFO.items()
    if info.category not in ["LEGACY", "META"]
]

print(f"[HallucinationTypes] Loaded {len(ACTIVE_HALLUCINATION_TYPES)} active hallucination detectors")
print(f"  Categories: {list(CATEGORY_GROUPS.keys())}")
