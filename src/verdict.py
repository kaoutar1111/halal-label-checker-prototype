"""
Verdict generation for Halal Label Checker.

The verdict is an aid to verification, never a halal certification.
It never says "halal" or "certified" about the product.

Rules
-----
* "Incompatible ingredient detected" if any incompatible ingredient matched.
* "À vérifier" if ANY of:
    - a real ingredient not in the reference remains after function words,
      modifiers, group labels and allergen notes are removed,
    - a depends_on_origin ingredient,
    - mean OCR confidence of the section below a threshold,
    - a dropped/uncertain OCR block inside the ingredients region,
    - fewer than MIN_COVERAGE of the ingredient segments are in the
      reference,
    - no_heading flag,
    - multiple_products flag,
    - empty section.
* An incompatible ingredient always wins: it is returned even when
  coverage is low or an ingredient is not in the reference.
* The coverage guard remains a secondary reason but no longer decides the
  verdict on its own; any unrecognized real ingredient already forces
  "À vérifier".
* Otherwise "No incompatible ingredient found in the reference".

The verdict always carries the list of reasons and the disclaimer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .matcher import (
    MatchReport,
    STATUS_ALLERGEN_NOTE,
    STATUS_COMPATIBLE,
    STATUS_DEPENDS_ON_ORIGIN,
    STATUS_FUNCTION_WORD,
    STATUS_INCOMPATIBLE,
    STATUS_NEGATED,
    STATUS_UNRECOGNIZED,
)

VERDICT_INCOMPATIBLE = "Incompatible ingredient detected"
VERDICT_TO_VERIFY = "À vérifier"
VERDICT_CLEAR = "No incompatible ingredient found in the reference"

DISCLAIMER = "Aid to verification, not a halal certification."

UNREADABLE_REASON = "Part of the ingredients list unreadable or uncertain"

# Header for the informational list. These entries never change the verdict.
NOT_EVALUATED_LABEL = "Not in the reference (not evaluated)"

# Shown instead of an ingredient analysis when no ingredients heading was found.
NO_INGREDIENTS_MESSAGE = (
    "Ingredients list not found or unreadable — retake the photo"
)

DEFAULT_CONFIDENCE_THRESHOLD = 0.85

# Coverage guard: if fewer than this fraction of the ingredient segments
# found in the section are recognised by the reference, a secondary reason
# is added ("Only X of Y ingredients are in the reference"). Any unrecognized
# real ingredient already forces "À vérifier"; the coverage guard is kept for
# explainability. An incompatible ingredient still takes precedence.
MIN_COVERAGE = 0.50


@dataclass
class VerdictResult:
    """Verdict for one ingredients section."""

    verdict: str
    reasons: List[str] = field(default_factory=list)
    incompatible_ingredients: List[str] = field(default_factory=list)
    needs_verification: List[str] = field(default_factory=list)
    compatible_ingredients: List[str] = field(default_factory=list)
    unrecognized_ingredients: List[str] = field(default_factory=list)
    overall_confidence: float = 0.0
    warnings: List[str] = field(default_factory=list)
    unreadable_blocks: List[Dict] = field(default_factory=list)
    disclaimer: str = DISCLAIMER
    section_index: Optional[int] = None

    @property
    def is_incompatible(self) -> bool:
        return self.verdict == VERDICT_INCOMPATIBLE

    @property
    def needs_verification_flag(self) -> bool:
        return self.verdict == VERDICT_TO_VERIFY

    def to_dict(self) -> Dict:
        return {
            "verdict": self.verdict,
            "reasons": list(self.reasons),
            "incompatible_ingredients": list(self.incompatible_ingredients),
            "needs_verification": list(self.needs_verification),
            "compatible_ingredients": list(self.compatible_ingredients),
            "unrecognized_ingredients": list(self.unrecognized_ingredients),
            "overall_confidence": round(self.overall_confidence, 4),
            "disclaimer": self.disclaimer,
            "section_index": self.section_index,
            "unreadable_blocks": list(self.unreadable_blocks),
        }


def section_confidence(section) -> float:
    """Mean OCR confidence of the blocks kept in the section.

    A section whose whole text was read inline on the heading block has no
    follow-up blocks; its text is still readable, so the heading's confidence
    is used instead of reporting 0%.
    """
    blocks = getattr(section, "blocks", None) or []
    if blocks:
        confidences = [float(getattr(block, "confidence", 0.0) or 0.0)
                       for block in blocks]
        return sum(confidences) / len(confidences) if confidences else 0.0
    heading = getattr(section, "heading", None)
    if heading is not None and (getattr(section, "text", "") or "").strip():
        return float(getattr(heading, "confidence", 0.0) or 0.0)
    return 0.0


def _bounds(bbox) -> Optional[List[float]]:
    """[x0, y0, x1, y1] from a flat box or a 4-corner polygon, or None."""
    if not bbox:
        return None
    try:
        if isinstance(bbox[0], (list, tuple)) or hasattr(bbox[0], "__len__"):
            xs = [float(point[0]) for point in bbox]
            ys = [float(point[1]) for point in bbox]
            return [min(xs), min(ys), max(xs), max(ys)]
        return [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
    except (IndexError, TypeError, ValueError):
        return None


def section_bounds(section) -> Optional[List[float]]:
    """Union box of the heading and every block walked in the section region.

    Covers the kept blocks (``section.blocks``) plus the geometry-only region
    blocks: kept blocks walked but not retained (e.g. group sub-headings) and
    engine-dropped blocks that fell inside the section's column
    (``section.region_unreadable``). This lets ``unreadable_in_section`` see a
    dropped/uncertain continuation of the list even when the heading was inline
    and the kept blocks alone do not reach that far down the column.
    """
    boxes = []
    heading = getattr(section, "heading", None)
    if heading is not None:
        box = _bounds(getattr(heading, "bbox", None))
        if box:
            boxes.append(box)
    for attr in ("blocks", "region_blocks", "region_unreadable"):
        for block in getattr(section, attr, None) or []:
            box = _bounds(getattr(block, "bbox", None))
            if box:
                boxes.append(box)
    if not boxes:
        return None
    return [
        min(box[0] for box in boxes), min(box[1] for box in boxes),
        max(box[2] for box in boxes), max(box[3] for box in boxes),
    ]


def unreadable_in_section(section, unreadable: Optional[Sequence[Dict]]) -> List[Dict]:
    """
    Drops/uncertain OCR blocks that fall inside the section's ingredients region.

    `unreadable` entries come from OCR (bbox, text, confidence, reason). A "no
    heading" section covers the whole image, so every entry counts there.
    """
    pending = [entry for entry in (unreadable or []) if entry]
    if not pending:
        return []
    if getattr(section, "flag", None) == "no_heading":
        return pending
    bounds = section_bounds(section)
    if bounds is None:
        return pending  # region unknown -> cannot exclude anything

    x0, y0, x1, y1 = bounds
    margin_x = max((x1 - x0) * 0.05, 2.0)
    margin_y = max((y1 - y0) * 0.05, 2.0)
    inside = []
    for entry in pending:
        box = _bounds(entry.get("bbox"))
        if box is None:
            continue  # no geometry: cannot place it in a region
        cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
        if x0 - margin_x <= cx <= x1 + margin_x and y0 - margin_y <= cy <= y1 + margin_y:
            inside.append(entry)
    return inside


def ingredient_coverage(report: MatchReport):
    """(recognised, total) ingredient segments found in the section.

    `total` counts the real ingredients the matcher found: matched plus
    unrecognized findings. Function words, allergen notes and negated
    claims are excluded (they are not ingredients). `recognised` is how
    many of those matched a reference entry with a valid status.

    A section with no ingredient findings at all returns (0, 0); callers
    treat that as "no coverage issue" because the empty / no-heading rules
    already flag such sections.
    """
    ingredients = report.ingredients
    total = len(ingredients)
    recognised = sum(1 for f in ingredients if f.is_matched)
    return recognised, total


def _finding_reason(prefix: str, finding) -> str:
    """One reason line, without repeating the same text twice ("蔗糖 (蔗糖)")."""
    matched = (finding.matched_name or "").strip()
    original = (finding.original_text or "").strip()
    if not matched or matched.casefold() == original.casefold():
        return f"{prefix}: {original or matched}"
    return f"{prefix}: {matched} ({original})"


class VerdictGenerator:
    """Generate verdicts from a section and its MatchReport."""

    def __init__(self, confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD):
        self.confidence_threshold = float(confidence_threshold)

    def assess(
        self,
        section,
        report: MatchReport,
        ocr_confidence: Optional[float] = None,
        section_index: Optional[int] = None,
        unreadable: Optional[Sequence[Dict]] = None,
    ) -> VerdictResult:
        findings = [
            f for f in report.findings
            if f.status not in (STATUS_NEGATED, STATUS_ALLERGEN_NOTE)
        ]
        incompatible = [f for f in findings if f.status == STATUS_INCOMPATIBLE]
        depends = [f for f in findings if f.status == STATUS_DEPENDS_ON_ORIGIN]
        compatible = [f for f in findings if f.status == STATUS_COMPATIBLE]
        unrecognized = [f for f in findings if f.status == STATUS_UNRECOGNIZED]
        # Function words that named no substance anywhere in the section.
        unnamed_function_words = [
            f for f in findings
            if f.status == STATUS_FUNCTION_WORD and f.needs_verification
        ]

        if ocr_confidence is None:
            ocr_confidence = section_confidence(section)
        ocr_confidence = float(ocr_confidence)

        flag = getattr(section, "flag", None)
        text = (getattr(section, "text", "") or "").strip()
        # Empty means no readable text at all. A section can have zero blocks
        # when the list was read inline on the heading block, and that is not
        # an empty (unreadable) section.
        empty = not text

        low_confidence = ocr_confidence < self.confidence_threshold
        unreadable_blocks = unreadable_in_section(section, unreadable)
        recognised_segments, total_segments = ingredient_coverage(report)
        low_coverage = (
            total_segments > 0
            and recognised_segments / total_segments < MIN_COVERAGE
        )

        # No heading: there is no ingredients list to analyse. Ask for a retake
        # and return no per-ingredient lists at all.
        if flag == "no_heading":
            return VerdictResult(
                verdict=VERDICT_TO_VERIFY,
                reasons=[NO_INGREDIENTS_MESSAGE],
                overall_confidence=ocr_confidence,
                warnings=[NO_INGREDIENTS_MESSAGE],
                disclaimer=DISCLAIMER,
                section_index=section_index,
            )

        reasons: List[str] = []

        for finding in incompatible:
            reasons.append(_finding_reason("Incompatible ingredient", finding))
        for finding in depends:
            reasons.append(_finding_reason("Depends on origin", finding))
        unrecognized_names: List[str] = []
        for finding in unrecognized:
            name = (finding.original_text or finding.matched_name or "").strip()
            if name and name not in unrecognized_names:
                unrecognized_names.append(name)
        if unrecognized_names:
            reasons.append(
                "Not in the reference: " + ", ".join(unrecognized_names)
            )
        for finding in unnamed_function_words:
            reasons.append(
                f"Function word without named substance: {finding.original_text}"
            )

        if low_confidence:
            reasons.append(
                f"Low OCR confidence: {ocr_confidence:.0%} "
                f"(threshold {self.confidence_threshold:.0%})"
            )
        if unreadable_blocks:
            reasons.append(UNREADABLE_REASON)
            for entry in unreadable_blocks[:3]:
                label = (entry.get("text") or "").strip()[:40] or "(empty)"
                reasons.append(
                    f"Uncertain OCR block {entry.get('bbox')}: '{label}' "
                    f"(confidence {float(entry.get('confidence') or 0.0):.2f}, "
                    f"{entry.get('reason') or 'unknown reason'})"
                )
        if flag == "multiple_products":
            reasons.append("Multiple products detected")
        if empty:
            reasons.append("Empty ingredients section")
        if low_coverage:
            reasons.append(
                f"Only {recognised_segments} of {total_segments} ingredients "
                f"are in the reference"
            )

        # The verdict follows the reference only:
        # incompatible > unrecognized / depends_on_origin / low coverage /
        # unreadable / low confidence / empty > clear. An incompatible
        # ingredient always wins, even when an ingredient is not in the
        # reference.
        if incompatible:
            verdict = VERDICT_INCOMPATIBLE
        elif (unrecognized or depends or low_confidence or empty
                or unreadable_blocks or low_coverage):
            verdict = VERDICT_TO_VERIFY
        else:
            verdict = VERDICT_CLEAR
            reasons.append(VERDICT_CLEAR)

        return VerdictResult(
            verdict=verdict,
            reasons=reasons,
            incompatible_ingredients=[f.original_text for f in incompatible],
            needs_verification=[f.original_text for f in depends],
            compatible_ingredients=[f.original_text for f in compatible],
            unrecognized_ingredients=[f.original_text for f in unrecognized],
            overall_confidence=ocr_confidence,
            warnings=list(reasons),
            unreadable_blocks=list(unreadable_blocks),
            disclaimer=DISCLAIMER,
            section_index=section_index,
        )

    def assess_sections(
        self,
        sections: Sequence,
        reports: Optional[Sequence[MatchReport]] = None,
        confidences: Optional[Sequence[float]] = None,
        unreadable: Optional[Sequence[Dict]] = None,
    ) -> List[VerdictResult]:
        if reports is None:
            reports = [getattr(section, "match_report", None) for section in sections]
        results: List[VerdictResult] = []
        for index, section in enumerate(sections):
            report = reports[index]
            if report is None:
                continue
            confidence = confidences[index] if confidences is not None else None
            results.append(self.assess(
                section, report, ocr_confidence=confidence,
                section_index=index, unreadable=unreadable,
            ))
        return results


class _TextSection:
    """Section stand-in for plain ingredients text (no OCR blocks)."""

    def __init__(self, text: str):
        self.text = text or ""
        self.blocks = [self.text] if self.text.strip() else []
        self.flag = None
        self.heading = None
        self.language = ""


def verdict_for_text(
    text: str,
    matcher,
    generator: Optional[VerdictGenerator] = None,
) -> VerdictResult:
    """Verdict for hand-written ingredients text, never for OCR output."""
    report = matcher.match_text(text or "")
    generator = generator or VerdictGenerator()
    return generator.assess(
        _TextSection(text or ""), report, ocr_confidence=1.0,
    )


def generate_verdict(
    section,
    report: MatchReport,
    ocr_confidence: Optional[float] = None,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    unreadable: Optional[Sequence[Dict]] = None,
) -> VerdictResult:
    """Module-level convenience wrapper."""
    return VerdictGenerator(confidence_threshold).assess(
        section, report, ocr_confidence=ocr_confidence, unreadable=unreadable,
    )
