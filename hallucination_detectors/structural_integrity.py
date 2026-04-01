"""
Structural Integrity Checker (Type 5: STRUCTURAL_HALLUCINATION)

Detects:
  - RELATIONSHIP_INVERSION: swapping subject/object or reversing relationships
  - HIERARCHY_DISTORTION: misrepresenting parent-child, part-whole hierarchies
  - SEQUENCE_CORRUPTION: correct steps in wrong temporal/procedural order

Validates the structural correctness of relationships and sequences in claims.
"""

import time
from __future__ import annotations
import re
from typing import List, Optional, Tuple
# Detectors use ClaimProtocol (duck typing)

from .base import BaseDetector, HallucinationFlag
from hallucination_types import HallucinationType, Severity


class StructuralIntegrityChecker(BaseDetector):
    """
    Checks claim structure for relationship errors, hierarchy violations, sequence errors.

    Supported types:
      - RELATIONSHIP_INVERSION
      - HIERARCHY_DISTORTION
      - SEQUENCE_CORRUPTION
    """

    # Known directional relationships (subject → object)
    # "X Y Z" means "X [verb] Z" is correct direction
    DIRECTIONAL_RELATIONS = {
        # Corporate relationships
        'acquired': ('company', 'acquired', 'company'),      # A acquired B (A→B)
        'founded': ('founder', 'founded', 'company'),        # Person founded Company
        'owns': ('owner', 'owns', 'asset'),                  # Owner owns Asset
        'subsidiary': ('parent', 'subsidiary', 'company'),  # Parent has subsidiary
        'invested in': ('investor', 'invested in', 'target'),
        'partnered with': ('company_a', 'partnered with', 'company_b'),  # symmetric

        # Hierarchical relationships
        'part of': ('part', 'part of', 'whole'),             # Part ⊂ Whole
        'includes': ('container', 'includes', 'item'),       # Container ⊃ Item
        'subtype of': ('subtype', 'subtype of', 'supertype'),
        'type of': ('instance', 'type of', 'class'),
        'parent of': ('parent', 'parent of', 'child'),
        'child of': ('child', 'child of', 'parent'),

        # Causal/process (typically directional)
        'causes': ('cause', 'causes', 'effect'),
        'leads to': ('antecedent', 'leads to', 'consequent'),
        'precedes': ('earlier', 'precedes', 'later'),
        'follows': ('later', 'follows', 'earlier'),
    }

    # Common entity type hierarchies (supertype → subtypes)
    TYPE_HIERARCHIES = {
        'animal': ['mammal', 'bird', 'reptile', 'amphibian', 'fish'],
        'mammal': ['dog', 'cat', 'horse', 'cow', 'elephant'],
        'bird': ['sparrow', 'eagle', 'penguin'],
        'company': ['tech_company', 'retail_company', 'manufacturer'],
        'tech_company': ['ai_company', 'hardware_company', 'software_company'],
        'programming_language': ['compiled_language', 'interpreted_language', 'scripting_language'],
        'vehicle': ['car', 'truck', 'motorcycle', 'bicycle'],
        'fruit': ['apple', 'banana', 'orange', 'grape'],
    }

    # Known procedural sequences (steps that must occur in order)
    SEQUENCE_CONSTRAINTS = {
        # Software development lifecycle
        ('plan', 'design', 'develop', 'test', 'deploy', 'maintain'),
        # Legal process
        ('file', 'review', 'approve', 'sign', 'enforce'),
        # Manufacturing
        ('design', 'prototype', 'test', 'manufacture', 'distribute'),
        # Academic research
        ('hypothesis', 'experiment', 'data_collection', 'analysis', 'paper'),
        # Purchase process
        ('need', 'search', 'select', 'purchase', 'receive', 'use'),
    }

    @property
    def supported_hallucination_types(self) -> List[HallucinationType]:
        return [
            HallucinationType.RELATIONSHIP_INVERSION,
            HallucinationType.HIERARCHY_DISTORTION,
            HallucinationType.SEQUENCE_CORRUPTION,
        ]

    async def detect(
        self,
        claim: AtomicClaim,
        context: Optional[dict] = None,
    ) -> List[HallucinationFlag]:
        """
        Check claim for structural errors.

        Args:
            claim: The claim to validate
            context: Optional corpus with relationship/hierarchy data

        Returns:
            Flags for any structural issues
        """
        t_start = time.time()
        cache_key = self._cache_key(claim.text, str(hash(str(context))))

        if cache_key in self._cache:
            return self._cache[cache_key]

        flags: List[HallucinationFlag] = []

        # 1. Check relationship directionality
        rel_flag = self._check_relationship_inversion(claim.text)
        if rel_flag:
            flags.append(rel_flag)

        # 2. Check hierarchy violations
        hier_flag = self._check_hierarchy(claim.text)
        if hier_flag:
            flags.append(hier_flag)

        # 3. Check sequence corruption
        seq_flag = self._check_sequence(claim.text)
        if seq_flag:
            flags.append(seq_flag)

        # 4. LLM-based structural analysis for complex claims
        if not flags and len(claim.text.split()) > 10:
            llm_flag = await self._llm_structural_check(claim)
            if llm_flag:
                flags.append(llm_flag)

        for flag in flags:
            flag.latency_ms = (time.time() - t_start) * 1000 / len(flags) if flags else 0.0

        self._cache[cache_key] = flags
        return flags

    def _check_relationship_inversion(self, text: str) -> Optional[HallucinationFlag]:
        """Detect inverted directional relationships."""
        text_lower = text.lower()

        for rel, (subj_type, rel_phrase, obj_type) in self.DIRECTIONAL_RELATIONS.items():
            if rel not in text_lower and rel_phrase not in text_lower:
                continue

            # Try to extract subject and object
            # Pattern: X <rel> Y
            pattern = rf'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:{rel}|{rel_phrase})\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)'
            match = re.search(pattern, text)

            if match:
                subject, object_ = match.groups()

                # Check against known correct direction
                # For symmetric relations, skip
                if rel in ['partnered with', 'collaborates with']:
                    continue

                # Check if (subject, object) matches known correct pattern
                # This is a simplified heuristic - production would use knowledge graph
                if self._is_known_wrong_direction(subject, object_, rel):
                    return self._create_flag(
                        claim_id="",
                        claim_text=text,
                        hallucination_type=HallucinationType.RELATIONSHIP_INVERSION,
                        confidence=0.80,
                        evidence=f"Relationship inversion: '{subject} {rel} {object_}' should be '{object_} {rel} {subject}'",
                        metadata={
                            "relationship": rel,
                            "subject": subject,
                            "object": object_,
                            "correct_direction": f"{object_} {rel} {subject}",
                        }
                    )

        return None

    def _is_known_wrong_direction(self, subj: str, obj: str, rel: str) -> bool:
        """Check if this subject-object pair is known to be inverted."""
        # Known inversions from common sense
        known_inversions = {
            ('OpenAI', 'Microsoft', 'acquired'): False,  # Microsoft invested in OpenAI, not vice versa
            ('employee', 'company', 'owns'): False,  # company owns employee relationship? no
            ('customer', 'product', 'buys'): False,  # customer buys product - correct
        }

        key = (subj, obj, rel)
        if key in known_inversions:
            return known_inversions[key]

        # Heuristic: if object is typically larger/powerful entity, inversion likely
        powerful_entities = {
            'microsoft', 'google', 'apple', 'amazon', 'meta', 'ibm', 'oracle',
            'united states', 'china', 'eu', 'government'
        }

        if obj.lower() in powerful_entities and rel in ['acquired', 'owns', 'controls']:
            return True  # Big entity unlikely to be object of acquisition by small entity

        return False

    def _check_hierarchy(self, text: str) -> Optional[HallucinationFlag]:
        """Check for hierarchy distortion (type-subtype, part-whole errors)."""
        text_lower = text.lower()

        for hierarchy_name, subtypes in self.TYPE_HIERARCHIES.items():
            # Check if claim says "X is a Y" where X is subtype but Y is not the supertype
            for subtype in subtypes:
                if subtype in text_lower:
                    # Find sentence containing this
                    sentences = re.split(r'[.!?]', text_lower)
                    for sent in sentences:
                        if subtype in sent:
                            # Extract type assertion pattern: "X is a Y" or "X is type of Y"
                            match = re.search(rf'{subtype}\s+(?:is|are)\s+(?:a|an|the|type of|kind of)\s+(\w+)', sent)
                            if match:
                                declared_type = match.group(1)
                                # Check if declared_type is NOT the correct supertype
                                if declared_type != hierarchy_name and declared_type not in subtypes:
                                    return self._create_flag(
                                        claim_id="",
                                        claim_text=text,
                                        hallucination_type=HallucinationType.HIERARCHY_DISTORTION,
                                        confidence=0.75,
                                        evidence=f"'{subtype}' is a {hierarchy_name}, not a {declared_type}",
                                        metadata={
                                            "subtype": subtype,
                                            "incorrect_supertype": declared_type,
                                            "correct_supertype": hierarchy_name,
                                            "hierarchy": hierarchy_name,
                                        }
                                    )

        return None

    def _check_sequence(self, text: str) -> Optional[HallucinationFlag]:
        """Check for incorrect sequence of steps/events."""
        text_lower = text.lower()

        # Extract ordered lists or sequential steps
        # Patterns:
        #   "first X, then Y, finally Z"
        #   "X before Y"
        #   "X after Y"
        #   "X, Y, and Z in that order"

        # Normalize step indicators
        text_clean = re.sub(r'\bfirst\b', '1.', text_lower)
        text_clean = re.sub(r'\bsecond\b', '2.', text_clean)
        text_clean = re.sub(r'\bthird\b', '3.', text_clean)
        text_clean = re.sub(r'\bthen\b', '->', text_clean)
        text_clean = re.sub(r'\bafter\b', '->', text_clean)
        text_clean = re.sub(r'\bbefore\b', '<-', text_clean)
        text_clean = re.sub(r'\bfinally\b', '->', text_clean)

        # Extract sequence of items (nouns)
        sequence = re.findall(r'\b([a-z]+)\b(?:\s+(?:\.|,|->|<-|and|or|then|after|before)\s+|\s+)', text_clean)

        if len(sequence) >= 3:
            # Check against known sequence templates
            for template in self.SEQUENCE_CONSTRAINTS:
                # Check if extracted sequence contains template items
                matching = [step for step in sequence if any(t in step for t in template)]

                if len(matching) >= 3:
                    # Are they in correct order?
                    template_indices = []
                    for step in matching:
                        for i, t in enumerate(template):
                            if t in step:
                                template_indices.append(i)
                                break

                    if template_indices != sorted(template_indices):
                        # Order violation!
                        return self._create_flag(
                            claim_id="",
                            claim_text=text,
                            hallucination_type=HallucinationType.SEQUENCE_CORRUPTION,
                            confidence=0.70,
                            evidence=f"Steps out of order: expected {' → '.join(template[:len(template_indices)])}, got different sequence",
                            metadata={
                                "detected_sequence": matching,
                                "expected_template": template,
                                "detected_indices": template_indices,
                            }
                        )

        # Also check explicit "before/after" relationships
        before_pattern = r'(\w+)\s+before\s+(\w+)'
        after_pattern = r'(\w+)\s+after\s+(\w+)'

        for match in re.finditer(before_pattern, text_lower):
            first, second = match.groups()
            # Check if this order contradicts known template
            if self._order_contradicts_template(first, second, 'before'):
                return self._create_flag(
                    claim_id="",
                    claim_text=text,
                    hallucination_type=HallucinationType.SEQUENCE_CORRUPTION,
                    confidence=0.65,
                    evidence=f"Impossible ordering: '{first}' before '{second}'",
                    metadata={"relation": "before", "first": first, "second": second}
                )

        for match in re.finditer(after_pattern, text_lower):
            first, second = match.groups()  # X after Y means Y before X
            # X after Y → Y before X
            if self._order_contradicts_template(second, first, 'before'):
                return self._create_flag(
                    claim_id="",
                    claim_text=text,
                    hallucination_type=HallucinationType.SEQUENCE_CORRUPTION,
                    confidence=0.65,
                    evidence=f"Impossible ordering: '{first}' after '{second}'",
                    metadata={"relation": "after", "first": second, "second": first}
                )

        return None

    def _order_contradicts_template(self, earlier: str, later: str, relation: str) -> bool:
        """Check if claimed order violates known sequence templates."""
        # Simplified: check if both items appear in a template in opposite order
        for template in self.SEQUENCE_CONSTRAINTS:
            try:
                idx_earlier = next(i for i, t in enumerate(template) if t in earlier or earlier in t)
                idx_later = next(i for i, t in enumerate(template) if t in later or later in t)
                if idx_earlier > idx_later:
                    return True
            except StopIteration:
                continue
        return False

    async def _llm_structural_check(self, claim: AtomicClaim) -> Optional[HallucinationFlag]:
        """Use LLM to detect complex structural issues not caught by rules."""
        prompt = f"""Check this claim for structural errors:
- Relationship inversion (X [verb] Y should be Y [verb] X)
- Hierarchy distortion (subtype presented as supertype or vice versa)
- Sequence corruption (steps in wrong order)

Claim: "{claim.text}"

Respond JSON: {{"has_error": bool, "type": "relationship_inversion|hierarchy_distortion|sequence_corruption|null", "explanation": "...", "confidence": 0.0-1.0}}
"""

        try:
            resp = await self._client.chat.completions.create(
                model=self._model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
            )
            result_text = resp.choices[0].message.content.strip()
            import json
            result = json.loads(result_text.replace("```json", "").replace("```", "").strip())

            if result.get('has_error'):
                h_type_str = result.get('type', 'none')
                try:
                    h_type = getattr(HallucinationType, h_type_str.upper())
                except (AttributeError, TypeError):
                    h_type = None

                if h_type and h_type in self.supported_hallucination_types:
                    return self._create_flag(
                        claim_id=claim.claim_id,
                        claim_text=claim.text,
                        hallucination_type=h_type,
                        confidence=result.get('confidence', 0.7),
                        evidence=result.get('explanation', 'Structural error detected'),
                        metadata={"llm_check": True}
                    )
        except Exception:
            pass

        return None
