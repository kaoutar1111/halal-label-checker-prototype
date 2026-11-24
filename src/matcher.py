"""
Ingredient matching for Halal Label Checker.

Input: text of an ingredients section (from src/sections.py) or raw text.
Reference: data/reference.json (id, names, aliases, status, reason, source).

Matching strategy
-----------------
1. Normalize: lowercase, strip Latin accents, Arabic diacritics and alef
   variants, unify full-width punctuation, collapse whitespace.
2. Split Latin/Arabic sections on , ; · - ( ) : and Arabic/Chinese punctuation.
3. Exact alias first (normalized whole-word occurrence), then fuzzy
   (rapidfuzz.ratio, configurable threshold).
4. Chinese: no reliable separators, so reference aliases are searched as
   substrings of the normalized text, longest match first.
5. E-numbers are extracted with a regex and matched against reference aliases.
6. Negated alcohol claims ("sans alcool", "alcohol free", "خالي من الكحول",
   "不含酒精") never match the alcohol entry.

The matcher returns a MatchReport with one MatchResult per ingredient
(matched entry or unrecognized) and the list of unrecognized ingredients.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)

DEFAULT_REFERENCE_PATH = Path(__file__).resolve().parent.parent / "data" / "reference.json"
DEFAULT_FUNCTION_WORDS_PATH = Path(__file__).resolve().parent.parent / "data" / "function_words.json"
DEFAULT_FUZZY_THRESHOLD = 85.0

STATUS_INCOMPATIBLE = "incompatible"
STATUS_DEPENDS_ON_ORIGIN = "depends_on_origin"
STATUS_COMPATIBLE = "compatible"
STATUS_UNRECOGNIZED = "unrecognized"
STATUS_NEGATED = "negated"
STATUS_FUNCTION_WORD = "function_word"      # "émulsifiant", "colorant": not an ingredient
STATUS_ALLERGEN_NOTE = "allergen_note"      # "(Lait)", "(contient Gluten)": not an ingredient

VALID_STATUSES = {
    STATUS_INCOMPATIBLE,
    STATUS_DEPENDS_ON_ORIGIN,
    STATUS_COMPATIBLE,
}

# Statuses that never count as ingredients.
NON_INGREDIENT_STATUSES = {STATUS_NEGATED, STATUS_FUNCTION_WORD, STATUS_ALLERGEN_NOTE}

# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

_ARABIC_DIACRITICS_RE = re.compile("[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06dc\u06df-\u06e8\u06ea-\u06ed\u0640]")
_ALEF_VARIANTS = str.maketrans({
    "\u0622": "\u0627",  # آ -> ا
    "\u0623": "\u0627",  # أ -> ا
    "\u0625": "\u0627",  # إ -> ا
    "\u0671": "\u0627",  # ٱ -> ا
})
_NON_WORD_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+", re.UNICODE)

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
ARABIC_RE = re.compile(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]")
_CJK_LEFTOVER_MODIFIERS = ("调味料", "食用", "制品", "再制", "复合", "风味")


def normalize_text(text: str) -> str:
    """
    Lowercase, strip Latin accents + Arabic diacritics, unify alef variants,
    turn every non-word character into a space, collapse whitespace.

    Full-width characters are handled by NFKC (， -> , / ： -> : / Ａ -> A).
    """
    if not text:
        return ""

    text = unicodedata.normalize("NFKC", text).lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.translate(_ALEF_VARIANTS)
    text = _ARABIC_DIACRITICS_RE.sub("", text)
    text = _NON_WORD_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def normalize_no_spaces(text: str) -> str:
    """Normalized text with all spaces removed (Chinese matching)."""
    return normalize_text(text).replace(" ", "")


def detect_script(text: str) -> str:
    """Return 'cjk', 'arabic' or 'latin' for the dominant script of text."""
    if CJK_RE.search(text):
        return "cjk"
    if ARABIC_RE.search(text):
        return "arabic"
    return "latin"


# ---------------------------------------------------------------------------
# Splitting and E-numbers
# ---------------------------------------------------------------------------

_SEPARATOR_RE = re.compile(r"[,;·•/\\()\[\]{}:，；、。：（）【】\[\]{}|!?،؛؟]+|[-–—]+|\n+")
_E_ONLY_RE = re.compile(r"^e\s?\d{3}[a-z]?$", re.IGNORECASE)
_HAS_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)
_STRIP_CHARS = " .,;:·•-–—()[]{}\"'«»"


def split_ingredients(text: str) -> List[str]:
    """Split a section into ingredient segments on label separators."""
    segments: List[str] = []
    for part in _SEPARATOR_RE.split(text or ""):
        part = part.strip().strip(_STRIP_CHARS)
        if not part or len(part) < 2:
            continue
        if _E_ONLY_RE.fullmatch(part):
            continue  # E-numbers are handled separately
        if not _HAS_LETTER_RE.search(part):
            continue  # numbers / symbols only
        segments.append(part)
    return segments


E_NUMBER_RE = re.compile(r"\bE\s?\d{3}[a-z]?\b", re.IGNORECASE)


def extract_e_numbers(text: str) -> List[str]:
    """All unique E-numbers in the text, normalized to E471 form."""
    found = []
    for match in E_NUMBER_RE.finditer(text or ""):
        value = match.group(0).replace(" ", "").upper()
        if value not in found:
            found.append(value)
    return found


# Bare additive codes inside brackets after a function word:
#   "COLOUR (101)", "FLAVOUR ENHANCER (627, 631)", "ANTIOXIDANT (307B)".
_PAREN_GROUP_RE = re.compile(r"\(([^()]*)\)")
_BARE_CODE_RE = re.compile(r"\d{3,4}[a-z]?", re.IGNORECASE)
_ADDITIVE_SPLIT_RE = re.compile(r"[,;/、，]+")
_ADDITIVE_TAIL_CHARS = 48

# "(Vitamin B3)", "(B6)", "（维生素B3）" written after an ingredient name are
# annotations of that ingredient, not separate ingredients.
_VITAMIN_ANNOTATION_RE = re.compile(
    r"[（(]\s*(?:(?:vitamin|vitamine|维生素)\s*[A-K]\d{0,2}|[A-K]\d{1,2})\s*[)）]",
    re.IGNORECASE,
)


def _is_function_word_tail(before: str, aliases) -> bool:
    """True when `before` ends with one of the function-word aliases."""
    tail = re.sub(r"[\s:;,\-–—]+$", "", before).lower()
    if not tail:
        return False
    tail_norm = normalize_text(tail)
    for alias in aliases:
        if not tail_norm.endswith(alias):
            continue
        if len(tail_norm) == len(alias):
            return True
        # Plural form ("colours", "antioxidants") and word boundary.
        if not tail_norm[-len(alias) - 1].isalnum():
            return True
        if tail_norm[-len(alias) - 1] == "s" and (
            len(tail_norm) == len(alias) + 1
            or not tail_norm[-len(alias) - 2].isalnum()
        ):
            return True
    return False


def prefix_additive_codes(text: str, function_words) -> str:
    """
    Turn bare codes in brackets into E-numbers after a function word.

    "Colour (627, 631)" -> "Colour (E627, E631)"; "Antioxidant (307B)" ->
    "Antioxidant (E307B)". Only groups that contain nothing but 3-4 digit
    codes are touched, and only when the bracket directly follows a function
    word from `function_words` (colour, antioxidant, flavour enhancer, ...).
    """
    text = text or ""
    aliases = sorted(
        {normalize_text(word).strip() for word in (function_words or []) if word},
        key=len, reverse=True,
    )
    if not text or not aliases:
        return text

    def replace(match):
        parts = [p.strip() for p in _ADDITIVE_SPLIT_RE.split(match.group(1))]
        parts = [p for p in parts if p]
        if not parts or not all(_BARE_CODE_RE.fullmatch(p) for p in parts):
            return match.group(0)
        before = text[max(0, match.start() - _ADDITIVE_TAIL_CHARS):match.start()]
        if not _is_function_word_tail(before, aliases):
            return match.group(0)
        return "(" + ", ".join(f"E{part}" for part in parts) + ")"

    return _PAREN_GROUP_RE.sub(replace, text)


def _complement_spans(spans: List[tuple], length: int) -> List[tuple]:
    """Gaps (start, end) not covered by the given spans."""
    merged: List[tuple] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    gaps: List[tuple] = []
    cursor = 0
    for start, end in merged:
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < length:
        gaps.append((cursor, length))
    return gaps


# Below this share of recognised words a segment is only partly explained:
# PaddleOCR dropped the commas and several ingredients arrived fused, so the
# unknown words must be reported instead of hidden by a single alias match.
SEGMENT_COVERAGE_MIN = 0.50

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _paren_spans(text: str) -> List[tuple]:
    """Spans of parenthesised annotations, which are never judged on their own."""
    spans: List[tuple] = []
    stack: List[int] = []
    for index, char in enumerate(text):
        if char in "([":
            stack.append(index)
        elif char in ")]" and stack:
            spans.append((stack.pop(), index + 1))
    spans.extend((start, len(text)) for start in stack)
    return spans


# ---------------------------------------------------------------------------
# Negation
# ---------------------------------------------------------------------------

_LATIN_NEGATION_RE = re.compile(
    r"\b(?:sans|without|free of|no)\s+(?:alcohol|alcool|ethanol|ethyl alcohol)\b"
)
_LATIN_NEGATION_SUFFIX_RE = re.compile(r"\b(?:alcohol|alcool)\s+free\b")
_NEGATION_PHRASES = (
    "خالي من الكحول",
    "خالية من الكحول",
    "خالى من الكحول",
    "بدون كحول",
    "لا يحتوي على الكحول",
    "不含酒精",
    "无酒精",
    "不含乙醇",
    "無酒精",
)


def is_negated_alcohol(text: str) -> bool:
    """True when text is an explicit 'no alcohol' claim."""
    normalized = normalize_text(text)
    compact = normalized.replace(" ", "")
    if _LATIN_NEGATION_RE.search(normalized):
        return True
    if _LATIN_NEGATION_SUFFIX_RE.search(normalized):
        return True
    return any(phrase in normalized or phrase in compact for phrase in _NEGATION_PHRASES)


_HYPHEN_NEGATION_RE = re.compile(
    r"\b(sans|without|no)-(?=alcohol|alcool|ethanol|ethyl alcohol)\b"
    r"|\b(alcohol|alcool)-(?=free\b)",
    re.IGNORECASE,
)


def _unhyphenate_negations(text: str) -> str:
    """
    Turn negation hyphens into spaces ("alcohol-free" -> "alcohol free") so
    the claim survives segment splitting: hyphens are ingredient separators,
    so the pieces "alcohol" / "free" would otherwise be judged on their own
    and "alcohol" would match the alcohol entry.
    """
    return _HYPHEN_NEGATION_RE.sub(lambda m: (m.group(1) or m.group(2)) + " ", text)


# ---------------------------------------------------------------------------
# Allergen annotations
# ---------------------------------------------------------------------------

# Parenthesized annotations like "(Lait)" or "(contient Gluten)" are allergen
# notes, not ingredients. A parenthesized group is an allergen note when it
# starts with a containment verb or when its whole content is an allergen word.
_PAREN_GROUP_RE = re.compile(r"[\(（]([^()（）]*)[\)）]")

_ALLERGEN_WORDS = {
    "lait", "milk", "milch", "lactoserum", "whey",
    "oeuf", "oeufs", "egg", "eggs",
    "gluten", "ble", "wheat",
    "soja", "soy", "soya",
    "arachide", "arachides", "peanut", "peanuts",
    "noix", "nuts", "noisette", "noisettes", "hazelnut", "hazelnuts",
    "sesame", "sulphites", "sulfites", "sulphite", "sulfite",
    "celeri", "celery", "moutarde", "mustard", "lupin",
    "crustaces", "mollusques", "poisson", "fish",
    "حليب", "لبن", "بيض", "جلوتين", "صويا", "فول سوداني", "سمسم", "سمك",
    "乳", "牛奶", "蛋", "雞蛋", "鸡蛋", "麩質", "麸质", "大豆", "花生", "芝麻", "魚", "鱼",
}

_ALLERGEN_PREFIXES = (
    "contient", "contains", "contiene", "enthalt", "traces",
    "peut contenir", "may contain", "avec", "with ",
)


def _is_allergen_note_content(normalized: str) -> bool:
    if not normalized:
        return False
    compact = normalized.replace(" ", "")
    if any(normalized.startswith(prefix) or compact.startswith(prefix.replace(" ", ""))
           for prefix in _ALLERGEN_PREFIXES):
        return True
    words = normalized.split()
    return all(word in _ALLERGEN_WORDS or compact in _ALLERGEN_WORDS for word in words)


def is_allergen_statement(text: str) -> bool:
    """True for non-parenthesized 'contient Gluten' style segments."""
    return _is_allergen_note_content(normalize_text(text))


def extract_allergen_notes(text: str):
    """
    Split parenthesized groups out of the text.

    Returns (cleaned_text, notes) where notes is a list of raw annotation
    strings ("(Lait)"). Allergen groups are removed; sub-ingredient groups
    ("(棕櫚油、...)") keep their content in the text so it is still judged.
    """
    notes: List[str] = []
    output: List[str] = []
    cursor = 0
    for match in _PAREN_GROUP_RE.finditer(text or ""):
        output.append(text[cursor:match.start()])
        inner = match.group(1)
        if _is_allergen_note_content(normalize_text(inner)):
            notes.append(match.group(0))
            output.append(" ")
        else:
            output.append(" " + inner + " ")  # keep substances, drop the parens
        cursor = match.end()
    output.append((text or "")[cursor:])
    return "".join(output), notes


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class MatchResult:
    """One ingredient (matched reference entry or explicitly unrecognized)."""

    original_text: str
    matched_name: str
    language: str
    status: str
    reason: str
    confidence: float
    matched_id: Optional[int] = None
    aliases: List[str] = field(default_factory=list)
    source: str = ""
    score: float = 0.0
    method: str = "exact"
    # Function words: True when no substance was named anywhere in the section
    # ("Colorant" alone) -> the verdict must be "À vérifier".
    needs_verification: bool = False

    @property
    def text(self) -> str:
        return self.original_text

    @property
    def is_matched(self) -> bool:
        return self.matched_id is not None and self.status in VALID_STATUSES

    def to_dict(self) -> Dict:
        return {
            "ingredient": self.original_text,
            "matched_name": self.matched_name,
            "matched_id": self.matched_id,
            "language": self.language,
            "status": self.status,
            "reason": self.reason,
            "confidence": round(self.confidence, 4),
            "score": round(self.score, 2),
            "method": self.method,
            "source": self.source,
            "needs_verification": self.needs_verification,
        }


@dataclass
class MatchReport:
    """Result of matching a whole ingredients section."""

    text: str
    language: str = ""
    findings: List[MatchResult] = field(default_factory=list)
    unrecognized: List[MatchResult] = field(default_factory=list)
    e_numbers: List[str] = field(default_factory=list)

    @property
    def ingredients(self) -> List[MatchResult]:
        """All real ingredient findings (matched and unrecognized)."""
        return [f for f in self.findings if f.status not in NON_INGREDIENT_STATUSES]

    def by_status(self, status: str) -> List[MatchResult]:
        return [f for f in self.findings if f.status == status]

    def to_dict(self) -> Dict:
        return {
            "text": self.text,
            "language": self.language,
            "e_numbers": list(self.e_numbers),
            "findings": [f.to_dict() for f in self.findings],
            "unrecognized": [f.original_text for f in self.unrecognized],
        }


# ---------------------------------------------------------------------------
# Reference loading and term index
# ---------------------------------------------------------------------------


def load_reference(path=DEFAULT_REFERENCE_PATH) -> List[Dict]:
    """Load the reference ingredient entries."""
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data["ingredients"]


def load_function_words(path=DEFAULT_FUNCTION_WORDS_PATH) -> Dict[str, str]:
    """
    normalized alias -> group id ("fw5"), from data/function_words.json.

    Function words ("émulsifiant", "colorant", "مادة حافظة", "乳化劑") introduce
    a list of substances; they are never ingredients themselves.
    """
    path = Path(path)
    if not path.exists():
        logger.warning("function words file not found: %s", path)
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    aliases: Dict[str, str] = {}
    for group in data.get("groups", []):
        group_id = group.get("id", "")
        for language in ("en", "fr", "ar", "zh"):
            for alias in group.get(language) or []:
                normalized = normalize_text(alias)
                if not normalized:
                    continue
                if detect_script(normalized) == "cjk":
                    normalized = normalized.replace(" ", "")
                aliases[normalized] = group_id
    return aliases


def _word_pattern(term: str) -> re.Pattern:
    return re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.UNICODE)


@dataclass
class _Term:
    text: str
    normalized: str
    entry: Dict
    language: str
    script: str
    is_alias: bool


class IngredientMatcher:
    """Match ingredients against data/reference.json."""

    def __init__(
        self,
        reference_path=DEFAULT_REFERENCE_PATH,
        fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
        function_words_path=DEFAULT_FUNCTION_WORDS_PATH,
    ):
        self.reference_path = Path(reference_path)
        self.fuzzy_threshold = float(fuzzy_threshold)
        self.entries = load_reference(self.reference_path)
        self.function_words = load_function_words(function_words_path)
        self.terms: List[_Term] = []
        self.e_index: Dict[str, _Term] = {}
        self._build_index()

    # -- index ---------------------------------------------------------------

    def _build_index(self) -> None:
        for entry in self.entries:
            for language, name in (entry.get("names") or {}).items():
                self._add_term(name, entry, language, is_alias=False)
            for alias in entry.get("aliases") or []:
                self._add_term(alias, entry, "alias", is_alias=True)

    def _add_term(self, text: str, entry: Dict, language: str, is_alias: bool) -> None:
        if not text:
            return
        normalized = normalize_text(text)
        if not normalized:
            return
        script = detect_script(normalized)
        if script == "cjk":
            normalized = normalized.replace(" ", "")
            if len(normalized) < 2:
                return  # single CJK characters match too many words
        elif len(normalized) < 2:
            return

        term = _Term(text=text, normalized=normalized, entry=entry, language=language, script=script, is_alias=is_alias)
        self.terms.append(term)

        # E-number alias index (E441, E120, ...)
        compact = normalized.replace(" ", "").upper()
        if re.fullmatch(r"E\d{3}[A-Z]?", compact):
            self.e_index[compact] = term

    # -- public API ----------------------------------------------------------

    def match_section(self, section) -> MatchReport:
        """Match the text of an extracted IngredientsSection."""
        return self.match_text(
            getattr(section, "text", "") or "",
            language=getattr(section, "language", "") or "",
        )

    def match_text(self, text: str, language: str = "") -> MatchReport:
        """Match a raw ingredients text."""
        text = text or ""
        report = MatchReport(text=text, language=language)

        # Bare codes after a function word are additive numbers:
        # "FLAVOUR ENHANCER (627, 631)" -> "FLAVOUR ENHANCER (E627, E631)".
        text = prefix_additive_codes(text, self.function_words)

        # A parenthetical vitamin annotation belongs to the ingredient before
        # it: drop the brackets so it never becomes a separate segment.
        text = _VITAMIN_ANNOTATION_RE.sub(
            lambda match: " " + match.group(0)[1:-1].strip() + " ", text)

        # Allergen annotations ("(Lait)", "(contient Gluten)") are not
        # ingredients: strip them out of the judged text and record them.
        text, notes = extract_allergen_notes(text)
        for note in notes:
            report.findings.append(self._make_allergen_note(note))

        # "alcohol-free" / "sans-alcool": hyphens are ingredient separators,
        # so the negation must be restored before the text is split.
        text = _unhyphenate_negations(text)

        if CJK_RE.search(text):
            # Chinese has no reliable separators (PaddleOCR often drops "、").
            # Aliases are searched as substrings over the whole section, longest
            # first; only the leftover text is reported as unrecognized.
            cjk_text = text
            for segment in split_ingredients(text):
                if CJK_RE.search(segment) and is_negated_alcohol(segment):
                    # "不含酒精" must not match the alcohol entry
                    report.findings.append(self._make_negated(segment))
                    cjk_text = cjk_text.replace(segment, " ")

            self._match_cjk_section(cjk_text, report)

            for segment in split_ingredients(text):
                if CJK_RE.search(segment):
                    continue  # already covered by the CJK substring scan
                self._collect(self._match_segment(segment), segment, report)
        else:
            for segment in split_ingredients(text):
                self._collect(self._match_segment(segment), segment, report)

        for e_number in extract_e_numbers(text):
            report.e_numbers.append(e_number)
            finding = self._match_e_number(e_number)
            report.findings.append(finding)
            if not finding.is_matched:
                report.unrecognized.append(finding)

        self._resolve_function_words(report)
        return report

    def _collect(self, findings: List[MatchResult], segment: str, report: MatchReport) -> None:
        """Append segment findings; empty means the segment is unrecognized."""
        if not findings:
            unrecognized = self._make_unrecognized(segment)
            report.findings.append(unrecognized)
            report.unrecognized.append(unrecognized)
            return
        report.findings.extend(findings)
        for finding in findings:
            if finding.status == STATUS_UNRECOGNIZED:
                report.unrecognized.append(finding)

    def _resolve_function_words(self, report: MatchReport) -> None:
        """
        A function word needs verification only when the section names no
        substance at all (e.g. "Colorant" alone). Substances "after the colon"
        are separate segments and are judged on their own.
        """
        has_substance = any(
            f.status not in NON_INGREDIENT_STATUSES for f in report.findings
        )
        for finding in report.findings:
            if finding.status == STATUS_FUNCTION_WORD:
                finding.needs_verification = not has_substance

    def match_ingredient(self, text: str) -> Optional[MatchResult]:
        """Legacy single-ingredient helper (first recognized match)."""
        report = self.match_text(text or "")
        for finding in report.findings:
            if finding.is_matched:
                return finding
        return None

    # -- segment matching ----------------------------------------------------

    def _match_segment(self, segment: str) -> List[MatchResult]:
        normalized = normalize_text(segment)
        if not normalized:
            return []

        if is_negated_alcohol(normalized):
            return [self._make_negated(segment)]

        if is_allergen_statement(normalized):
            return [self._make_allergen_note(segment)]

        script = detect_script(normalized)
        if script == "cjk":
            return []  # CJK is matched globally by _match_cjk_section

        # Function words are not ingredients: strip the leading function word
        # ("émulsifiant" in "émulsifiant lécithine de soja") and judge only the
        # remaining substances.
        prefix = self._strip_function_word(normalized)
        fw_findings: List[MatchResult] = []
        if prefix is not None:
            alias, remainder = prefix
            fw_findings.append(self._make_function_word(segment, alias))
            if not remainder:
                return fw_findings
            normalized = remainder

        exact, spans = self._match_exact_spans(normalized, segment, script)
        if exact:
            return fw_findings + exact + self._coverage_findings(
                normalized, spans, segment, exact)
        fuzzy = self._match_fuzzy(normalized, segment, script)
        if fuzzy:
            return fw_findings + fuzzy
        if fw_findings:
            # Substances were named but none is known -> report them.
            fw_findings.append(self._make_unrecognized(normalized))
        return fw_findings

    def _strip_function_word(self, normalized: str):
        """
        (alias, remainder) when the segment contains a function word, else
        None. Longest alias first, whole-word boundaries for Latin/Arabic.

        The word is stripped wherever it appears: OCR often glues it to a
        substance ("حمض الستريك مادة حافظة"), so prefix-only matching would
        miss it.
        """
        for alias in sorted(self.function_words, key=len, reverse=True):
            if detect_script(alias) == "cjk":
                continue  # CJK function words are handled in _match_cjk_section
            if normalized == alias:
                return alias, ""
            pattern = re.compile(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", re.UNICODE)
            match = pattern.search(normalized)
            if match:
                remainder = (normalized[:match.start()] + " " + normalized[match.end():])
                return alias, re.sub(r"\s+", " ", remainder).strip()
        return None

    def _match_exact_occurrences(self, normalized: str, segment: str, script: str) -> List[MatchResult]:
        findings, _spans = self._match_exact_spans(normalized, segment, script)
        return findings

    def _match_exact_spans(self, normalized: str, segment: str, script: str):
        """All normalized whole-word alias occurrences, plus their spans."""
        findings: List[MatchResult] = []
        occupied: List[tuple] = []

        candidates = sorted(
            (t for t in self.terms if t.script == script),
            key=lambda t: len(t.normalized),
            reverse=True,
        )
        for term in candidates:
            pattern = _word_pattern(term.normalized)
            for match in pattern.finditer(normalized):
                start, end = match.span()
                if any(start < b and end > a for a, b in occupied):
                    continue
                occupied.append((start, end))
                findings.append(self._make_matched(term, segment, 100.0, "exact"))

        return findings, occupied

    def _uncovered_words(self, normalized: str, spans: List[tuple], segment: str) -> List[str]:
        """Words left over after the matched aliases, worth judging on their own.

        Skips numbers, E-numbers, function words, allergen-note words and
        parenthetical annotations. Tokens shorter than three letters are
        ignored ("de", "of", "و").
        """
        occupied = list(spans)
        occupied.extend(m.span() for m in E_NUMBER_RE.finditer(normalized))
        parens = _paren_spans(normalized)
        tokens: List[str] = []
        for start, end in _complement_spans(occupied, len(normalized)):
            for match in _WORD_RE.finditer(normalized, start, end):
                word = match.group(0)
                if len(word) < 3:
                    continue
                if any(begin <= match.start() < finish for begin, finish in parens):
                    continue
                if self._is_function_word_token(word):
                    continue
                tokens.append(word)
        return tokens

    def _is_function_word_token(self, word: str) -> bool:
        """True when the token is (part of) a function-word alias."""
        for alias in self.function_words:
            alias_norm = normalize_text(alias)
            if not alias_norm or detect_script(alias_norm) == "cjk":
                continue
            if word == alias_norm or (len(word) >= 3 and word in alias_norm.split()):
                return True
        return False

    def _coverage_findings(self, normalized: str, spans: List[tuple], segment: str,
                           findings: List[MatchResult]) -> List[MatchResult]:
        """Flag the leftovers of a segment that matched only a small part.

        Space-delimited scripts only (Latin, Arabic): PaddleOCR often drops the
        commas there, so several ingredients arrive as one segment and a single
        alias match ("ملح" in "حبات الخريل خل المائدة ملح …") would otherwise
        hide the unknown words. CJK is handled by the global substring scan.
        """
        if any(f.status not in (STATUS_COMPATIBLE, STATUS_FUNCTION_WORD) for f in findings):
            return []
        # A single recognised name plus descriptors is a normal multi-word
        # ingredient ("sel de Guérande", "حليب طري كامل الدسم", "whole grain
        # wheat"). Only several recognised substances around unknown words
        # indicate that the separators were lost.
        if sum(1 for f in findings if f.is_matched) < 2:
            return []
        leftovers = self._uncovered_words(normalized, spans, segment)
        if not leftovers:
            return []
        covered = self._covered_word_count(normalized, spans)
        total = covered + len(leftovers)
        if total == 0 or covered / total >= SEGMENT_COVERAGE_MIN:
            return []
        unrecognized = self._make_unrecognized(" ".join(leftovers))
        return [unrecognized]

    def _covered_word_count(self, normalized: str, spans: List[tuple]) -> int:
        occupied = list(spans)
        occupied.extend(m.span() for m in E_NUMBER_RE.finditer(normalized))
        count = 0
        for begin, end in occupied:
            for match in _WORD_RE.finditer(normalized, begin, end):
                if len(match.group(0)) >= 3:
                    count += 1
        return count

    def _match_cjk_section(self, text: str, report: MatchReport) -> None:
        """
        Chinese: aliases as substrings over the whole section, longest first.

        Matched spans are removed from the text; only the leftover runs are
        reported as unrecognized, so an unmatched word never absorbs a matched
        neighbour ("脂肪酸丙二醇酯 脂肪酸山梨醇酐酯" stays two entries).
        """
        normalized = normalize_text(text)

        # Map the space-free string back to the spaced one, so leftover text
        # can be split into separate ingredients.
        compact_parts: List[str] = []
        positions: List[int] = []
        for index, char in enumerate(normalized):
            if char.isspace():
                continue
            compact_parts.append(char)
            positions.append(index)
        compact = "".join(compact_parts)
        if not compact:
            return

        occupied: List[tuple] = []
        # E-numbers are reported separately, never as leftovers
        for match in E_NUMBER_RE.finditer(compact):
            occupied.append(match.span())

        # Function words ("乳化劑", "抗氧化劑") are not ingredients: occupy
        # their spans first so they neither match the reference nor end up
        # as unrecognized leftovers.
        fw_aliases = sorted(
            (alias for alias in self.function_words if detect_script(alias) == "cjk"),
            key=len, reverse=True,
        )
        for alias in fw_aliases:
            start = compact.find(alias)
            while start != -1:
                end = start + len(alias)
                if not any(start < b and end > a for a, b in occupied):
                    occupied.append((start, end))
                    report.findings.append(
                        self._make_function_word(compact[start:end], alias)
                    )
                start = compact.find(alias, start + 1)

        candidates = sorted(
            (t for t in self.terms if t.script == "cjk"),
            key=lambda t: len(t.normalized),
            reverse=True,
        )
        for term in candidates:
            start = compact.find(term.normalized)
            while start != -1:
                end = start + len(term.normalized)
                if not any(start < b and end > a for a, b in occupied):
                    occupied.append((start, end))
                    report.findings.append(
                        self._make_matched(term, compact[start:end], 100.0, "substring")
                    )
                start = compact.find(term.normalized, start + 1)

        for start, end in _complement_spans(occupied, len(compact)):
            raw = normalized[positions[start]:positions[end - 1] + 1]
            for token in _WHITESPACE_RE.split(raw):
                token = token.strip()
                for modifier in _CJK_LEFTOVER_MODIFIERS:
                    token = token.replace(modifier, "")
                if len(token) < 2 or not _HAS_LETTER_RE.search(token):
                    continue
                unrecognized = self._make_unrecognized(token)
                report.findings.append(unrecognized)
                report.unrecognized.append(unrecognized)

    def _match_fuzzy(self, normalized: str, segment: str, script: str) -> List[MatchResult]:
        candidates = [t for t in self.terms if t.script == script]
        if not candidates:
            return []

        match = process.extractOne(
            normalized,
            [t.normalized for t in candidates],
            scorer=fuzz.ratio,
            score_cutoff=self.fuzzy_threshold,
        )
        if match is None:
            return []

        _, score, index = match
        return [self._make_matched(candidates[index], segment, float(score), "fuzzy")]

    # -- E-numbers -----------------------------------------------------------

    def _match_e_number(self, e_number: str) -> MatchResult:
        term = self.e_index.get(e_number)
        if term is None:
            return MatchResult(
                original_text=e_number,
                matched_name="",
                language="",
                status=STATUS_UNRECOGNIZED,
                reason="E-number not found in reference",
                confidence=0.0,
                method="none",
            )
        return self._make_matched(term, e_number, 100.0, "e-number")

    # -- builders ------------------------------------------------------------

    def _make_matched(self, term: _Term, original: str, score: float, method: str) -> MatchResult:
        entry = term.entry
        status = entry.get("status", STATUS_UNRECOGNIZED)
        reason = entry.get("reason", "")
        if method == "fuzzy" and status == STATUS_INCOMPATIBLE:
            # A fuzzy match can never produce "incompatible": only an exact
            # alias may. Downgrade so the verdict becomes "À vérifier".
            status = STATUS_DEPENDS_ON_ORIGIN
            reason = (f"Fuzzy match (score {score:.0f}) on an incompatible entry; "
                      f"exact confirmation required. {reason}").strip()
        return MatchResult(
            original_text=original,
            matched_name=term.text,
            language=term.language,
            status=status,
            reason=reason,
            confidence=min(max(score, 0.0), 100.0) / 100.0,
            matched_id=entry.get("id"),
            aliases=list(entry.get("aliases") or []),
            source=entry.get("source", ""),
            score=float(score),
            method=method,
        )

    def _make_function_word(self, text: str, alias: str) -> MatchResult:
        return MatchResult(
            original_text=text,
            matched_name="",
            language="",
            status=STATUS_FUNCTION_WORD,
            reason=f"Function word ({self.function_words.get(alias, '')}), not an ingredient",
            confidence=0.0,
            method="function-word",
        )

    def _make_allergen_note(self, text: str) -> MatchResult:
        return MatchResult(
            original_text=text.strip(),
            matched_name="",
            language="",
            status=STATUS_ALLERGEN_NOTE,
            reason="Allergen annotation, not an ingredient",
            confidence=0.0,
            method="allergen-note",
        )

    def _make_unrecognized(self, text: str) -> MatchResult:
        return MatchResult(
            original_text=text,
            matched_name="",
            language="",
            status=STATUS_UNRECOGNIZED,
            reason="Not found in reference",
            confidence=0.0,
            method="none",
        )

    def _make_negated(self, text: str) -> MatchResult:
        return MatchResult(
            original_text=text,
            matched_name="",
            language="",
            status=STATUS_NEGATED,
            reason="Negated alcohol claim ignored",
            confidence=0.0,
            method="negation",
        )


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

_default_matcher: Optional[IngredientMatcher] = None


def get_default_matcher() -> IngredientMatcher:
    """Shared matcher instance (reference loaded once)."""
    global _default_matcher
    if _default_matcher is None:
        _default_matcher = IngredientMatcher()
    return _default_matcher


def match_ingredient(text: str, reference_path=DEFAULT_REFERENCE_PATH) -> Optional[MatchResult]:
    """Legacy convenience: match one ingredient string."""
    return IngredientMatcher(reference_path).match_ingredient(text)


def parse_ingredient_list(text: str) -> List[str]:
    """Split an ingredients text into segments (kept for compatibility)."""
    return split_ingredients(text)
