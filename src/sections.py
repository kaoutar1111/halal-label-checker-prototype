"""
Ingredients section extraction for Halal Label Checker.

Works on OCRResult objects (with bboxes), NOT dicts.

Detects the ingredients heading in ar/fr/en/zh, collects the blocks that
belong to the ingredients section (same column / region, in reading order),
and extracts E-numbers separately with a regex.

Flags:
    "multiple_products" - more than one ingredients heading was found
    "no_heading"        - no heading found; the section is left EMPTY (the
                          full panel is never analysed as ingredients)
"""

import copy
import re
import logging
from typing import List, Optional

from rapidfuzz import fuzz

from .utils import build_reading_order

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

# Ingredients headings per language (variants included; matching is fuzzy)
HEADINGS = {
    "en": ["ingredients"],
    "fr": ["ingredients", "ingrédients", "composition"],
    "ar": ["المكونات", "المقادير"],
    "zh": ["配料", "配料表", "成分", "成份"],
}

# Nutrition-declaration headings. They are never the ingredients heading, even
# when they contain one ("营养成分表" contains "成分"; "Nutrition Facts" contains
# "nutrition"). Checked before any heading token is accepted.
NUTRITION_HEADINGS = {
    "en": ["nutrition facts", "nutritional information", "nutrition declaration",
           "nutrition"],
    "fr": ["valeurs nutritionnelles", "valeur nutritionnelle",
           "informations nutritionnelles", "déclaration nutritionnelle",
           "declaration nutritionnelle", "nutrition"],
    "ar": ["القيم الغذائية", "القيمة الغذائية", "المعلومات الغذائية",
           "البيانات الغذائية"],
    "zh": ["营养成分", "营养成分表", "營養成分", "營養成分表", "营养", "營養"],
}

# When several headings of the same language coexist, the higher value wins.
# 配料/配料表 is the ingredients heading on Chinese labels; 成分/成份 alone is
# usually a nutrition-table fragment or a sub-heading.
HEADING_PRIORITY = {
    "zh": {"配料": 2, "配料表": 2, "成分": 1, "成份": 1},
}

# Two-tier stop phrases.
#
# STRONG stops are unambiguous end-of-list markers (nutrition declaration,
# storage, "best before", manufacturer/address/website). They end the section
# ANYWHERE in a segment, so the ingredient text before them is kept while the
# nutrition table or company block that follows is not.
STRONG_STOP_KEYWORDS = [
    # English
    "nutrition facts", "nutrition", "nutritional information",
    "allergen", "allergens", "allergy information", "allergy advice",
    "allergen advice",
    "store", "storage", "store in a cool", "best before",
    "keep refrigerated", "net weight", "net content",
    "manufactured by", "produced by", "packed by", "distributed by",
    "imported by",
    # French
    "valeur nutritionnelle", "valeurs nutritionnelles",
    "informations nutritionnelles", "declaration nutritionnelle",
    "déclaration nutritionnelle", "allergenes", "allergènes",
    "conseils allergenes", "conseils allergènes",
    "a conserver", "à conserver", "mode de conservation",
    "conditions de conservation", "a consommer de preference", "à consommer",
    "poids net", "fabrique par", "fabriqué par", "conditionne par",
    "conditionné par", "distribue par", "distribué par", "importe par",
    "importé par",
    # Arabic
    "القيمة الغذائية", "المعلومات الغذائية", "يحفظ", "التخزين",
    "يفضل استهلاكها", "الوزن الصافي", "نصائح الحساسية", "المنتج من قبل",
    "تم التعبئة", "التوزيع", "الإنتاج",
    # Chinese
    "营养成分", "营养成分表", "营养", "致敏原", "贮存", "保质期",
    "净含量", "致敏物质", "过敏原信息", "生产商", "制造商", "经销商",
    # Address / website
    "www.", "http://", "https://", "address", "adresse", "العنوان", "地址",
]

# WEAK keywords ("contains", allergen / "may contain" declarations) are
# ambiguous: "contains" also appears inside an ingredient list ("(CONTAINS
# SOY), YEAST EXTRACT..."). They end the section only when they begin a
# segment (block start, or after a sentence end) and sit outside parentheses.
# That way an allergen statement such as
# "含有麸质的谷物及其制品，…，此生产线也加工含有蛋类及其制品" ends the list,
# while "Farine de blé (contient Gluten)" inside the list does not.
WEAK_STOP_KEYWORDS = [
    # English
    "contains", "may contain", "processed in a facility",
    "manufactured in a facility",
    # French (accents are stripped by normalize_text)
    "contient", "peut contenir", "traces", "fabrique dans un atelier",
    "fabriqué dans un atelier",
    # Arabic
    "يحتوي", "يحتوي على", "قد يحتوي",
    # Chinese
    "含有", "本品含有", "可能含有", "此生产线也加工含有", "过敏原",
]

STOP_KEYWORDS = STRONG_STOP_KEYWORDS + WEAK_STOP_KEYWORDS

# Phrases that end an ingredient list mid-block (sentence boundaries on labels)
STOP_PHRASES = [
    "contient cacao",
    "minimum",
    "pour les allergènes",
    "pour les allergenes",
    "ne convient pas",
    "important",
    # Arabic product claims ("non-GMO product", "plant product")
    "منتج غير معدل",
    "منتج نباتي",
]

# CJK text has no spaces, so whitespace tokens cannot delimit a heading word
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff]")
ARABIC_RE = re.compile(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]")

# A full stop followed by a new capitalized sentence ends the list
SENTENCE_BREAK_RE = re.compile(r"\.\s+[A-ZÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ]")

# Nutrition-table rows are dense with quantities ("450 kJ", "107 kcal",
# "5,2 g", "10 %"). Two or more in one OCR segment mean the ingredients have
# ended; a single quantity can still be an ingredient annotation.
NUTRITION_VALUE_RE = re.compile(
    r"(?<![\w.])\d+(?:[.,]\d+)?\s*(?:kcal|kj|mg|g|%)(?![a-z])",
    re.IGNORECASE,
)
NUTRITION_DENSE_MIN_VALUES = 2
NUTRITION_START_RE = re.compile(
    r"^(?:nutritionnelles\b|pour\s+100\s*g\b|par\s+portion\b)",
    re.IGNORECASE,
)

# Stray OCR stubs ("F") to discard
STUB_MAX_CHARS = 2
STUB_MIN_CONFIDENCE = 0.9

# Fuzzy thresholds (0-100)
HEADING_THRESHOLD = 70
STOP_THRESHOLD = 75

# Section walk tuning
GAP_FACTOR = 2.2        # stop when vertical gap > GAP_FACTOR * median height
COLUMN_CENTER_BAND = 0.25  # block centre may sit this far outside the heading x-range

# E-numbers like E471, E120a (extracted separately from fuzzy matching)
E_NUMBER_RE = re.compile(r"\bE\s?\d{3}[a-z]?\b", re.IGNORECASE)

RTL_LANGUAGES = ["ar"]


# ---------------------------------------------------------------------------
# Normalization (self-contained; no matcher dependency)
# ---------------------------------------------------------------------------

_ARABIC_DIACRITICS = re.compile("[ً-ٰٟـ]")
_ALEF_VARIANTS = {"آ": "ا", "أ": "ا", "إ": "ا", "ٱ": "ا"}


def normalize_text(text: str) -> str:
    """Lowercase, strip Latin accents and Arabic diacritics, unify alefs."""
    import unicodedata

    text = text.lower()
    # Latin accents -> base letters
    text = "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )
    # Arabic diacritics + alef variants
    text = _ARABIC_DIACRITICS.sub("", text)
    for variant, base in _ALEF_VARIANTS.items():
        text = text.replace(variant, base)
    return text


def _clean(text: str) -> str:
    """Normalized text without punctuation/colons, for keyword matching."""
    cleaned = re.sub(r"[^\w\s]", " ", normalize_text(text))
    return re.sub(r"\s+", " ", cleaned).strip()


def _normalize_with_map(text: str) -> tuple:
    """
    Normalize `text` and keep, for every normalized character, the index of
    the original character it came from.

    Dropping Arabic diacritics shortens the string, so a match found in the
    normalized text cannot be used directly to cut the original one.
    """
    normalized: List[str] = []
    index_map: List[int] = []
    for index, char in enumerate(text):
        for piece in normalize_text(char):
            normalized.append(piece)
            index_map.append(index)
    return "".join(normalized), index_map


def _strong_stop_index(text: str) -> Optional[int]:
    """Index in `text` of the first strong stop keyword anywhere, or None."""
    if not text:
        return None
    normalized, index_map = _normalize_with_map(text)
    best = None
    for keyword in STRONG_STOP_KEYWORDS:
        kw = normalize_text(keyword)
        if not kw:
            continue
        start = 0
        while True:
            index = normalized.find(kw, start)
            if index == -1:
                break
            start = index + 1
            if not _word_boundary_ok(normalized, index, kw):
                continue
            original = index_map[index]
            if best is None or original < best:
                best = original
            break
    return best


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

def _best_score(text: str, keywords: List[str]) -> int:
    """Max fuzzy score of text against keywords (partial + full ratio)."""
    cleaned = _clean(text)
    if not cleaned:
        return 0
    best = 0
    for kw in keywords:
        kw_clean = _clean(kw)
        best = max(
            best,
            fuzz.ratio(cleaned, kw_clean),
            fuzz.partial_ratio(cleaned, kw_clean),
        )
    return int(best)


def _heading_score(text: str, variants: List[str]) -> int:
    """
    Strict heading score.

    A heading must either contain the keyword, or be within a few characters
    of it (OCRed typo). `partial_ratio` alone is not allowed to match a long
    unrelated phrase — e.g. "Spices & Condiments" must NOT match "ingredients".
    """
    cleaned = _clean(text)
    if not cleaned:
        return 0
    best = 0
    for kw in variants:
        kw_clean = _clean(kw)
        if not kw_clean:
            continue
        if kw_clean in cleaned:
            best = max(best, 100)
        elif len(cleaned) >= 0.75 * len(kw_clean) and cleaned in kw_clean:
            best = max(best, 100)  # truncated heading, e.g. "ingredien"
        elif abs(len(cleaned) - len(kw_clean)) <= 4:
            best = max(best, int(fuzz.ratio(cleaned, kw_clean)))
    return best


def is_heading(result) -> bool:
    """True if the OCRResult text looks like an ingredients heading."""
    all_headings = [h for variants in HEADINGS.values() for h in variants]
    return _heading_score(result.text, all_headings) >= HEADING_THRESHOLD


def is_nutrition_heading(text: str) -> bool:
    """
    True when the text is a nutrition-declaration heading in any language.

    "营养成分表" contains "成分" and "Nutrition Facts" contains "nutrition":
    without this check both would be accepted as the ingredients heading.
    """
    cleaned = _clean(text)
    if not cleaned:
        return False
    compact = cleaned.replace(" ", "")
    for variants in NUTRITION_HEADINGS.values():
        for keyword in variants:
            kw_clean = _clean(keyword)
            if not kw_clean:
                continue
            if kw_clean in cleaned or kw_clean.replace(" ", "") in compact:
                return True
    return False


def heading_priority(token: str, language: Optional[str]) -> int:
    """Priority of a heading token within its language (higher wins)."""
    if not language:
        return 1
    return HEADING_PRIORITY.get(language, {}).get(token.strip(), 1)


def is_stop_keyword(result) -> bool:
    """True if the OCRResult text looks like a stop keyword."""
    return _best_score(result.text, STOP_KEYWORDS) >= STOP_THRESHOLD


def detect_heading_language(result) -> Optional[str]:
    """
    Language whose heading vocabulary best matches the text, or None.

    Ties (e.g. "INGRÉDIENTS" normalizes to "ingredients", which exists in
    both en and fr) are broken by an exact match on the RAW text, so the
    accented French form resolves to "fr".
    """
    raw = re.sub(r"[^\w\s]", "", result.text.strip().lower())
    best_lang, best_score, best_raw = None, 0, False
    for lang, variants in HEADINGS.items():
        score = _heading_score(result.text, variants)
        raw_hit = raw in variants
        if score > best_score or (score == best_score and raw_hit and not best_raw):
            best_lang, best_score, best_raw = lang, score, raw_hit
    return best_lang if best_score >= HEADING_THRESHOLD else None


_ALL_HEADINGS = [h for variants in HEADINGS.values() for h in variants]


def _token_language(token: str) -> Optional[str]:
    """Language of a single heading token (raw accent decides, not the block)."""
    raw = re.sub(r"[^\w\s]", "", token.strip().lower())
    best_lang, best_score, best_raw = None, 0, False
    for lang, variants in HEADINGS.items():
        score = _heading_score(token, variants)
        raw_hit = raw in variants
        if score > best_score or (score == best_score and raw_hit and not best_raw):
            best_lang, best_score, best_raw = lang, score, raw_hit
    return best_lang if best_score >= HEADING_THRESHOLD else None


def find_heading_token(result):
    """
    Locate the heading keyword INSIDE a block.

    A block may contain other text before/after the keyword, e.g.
    "au chocolat blanc INGRÉDIENTS Sucre ...". Only the matched word is the
    heading; text before it is dropped and text after it starts the section.

    Returns:
        (token_text, end_offset, language) or None.
    """
    text = result.text or ""

    for match in re.finditer(r"\S+", text):
        token = match.group(0)
        if CJK_RE.search(token):
            continue  # CJK has no spaces: handled by the substring fallback below
        if _heading_score(token, _ALL_HEADINGS) >= HEADING_THRESHOLD:
            window = text[max(0, match.start() - 12): match.end() + 12]
            if is_nutrition_heading(window):
                continue  # e.g. "nutrition" inside "Nutrition Facts"
            return (token, match.end(), _token_language(token))

    # CJK headings can be glued to the following characters (no spaces).
    # 成分 inside 营养成分表 is a nutrition heading, not an ingredients heading.
    for lang, variants in HEADINGS.items():
        for variant in variants:
            for match in re.finditer(re.escape(variant), text):
                idx = match.start()
                window = text[max(0, idx - 6): idx + len(variant) + 6]
                if is_nutrition_heading(window):
                    continue
                return (variant, idx + len(variant), lang)

    return None


def is_stub(result) -> bool:
    """True for useless OCR stubs: <= 2 chars with low confidence (e.g. "F")."""
    text = (result.text or "").strip()
    return len(text) <= STUB_MAX_CHARS and result.confidence < STUB_MIN_CONFIDENCE


def _is_nutrition_segment(text: str) -> bool:
    """True for a nutrition-table row rather than an ingredient segment."""
    stripped = re.sub(r"^[\s:;,.•\-–—]+", "", normalize_text(text or ""))
    if not stripped:
        return False
    if NUTRITION_START_RE.match(stripped):
        return True
    return len(NUTRITION_VALUE_RE.findall(stripped)) >= NUTRITION_DENSE_MIN_VALUES


# A group sub-heading inside the ingredients list ("Vitamins and Minerals:",
# "Vitamines et minéraux :", "维生素和矿物质：", "الفيتامينات والمعادن:").
SUBHEADING_MAX_WORDS = 4
_HAS_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)


def _is_group_subheading(text: str) -> bool:
    """
        True for a short segment ending with a colon that introduces a list.

        The heading itself is not an ingredient, but the blocks that follow it
        stay in the section. A long sentence ending with a colon, or a segment
        without a colon, is left untouched.
    """
    stripped = (text or "").strip()
    if not stripped or stripped[-1] not in ":：":
        return False
    words = re.findall(r"\S+", stripped[:-1].strip())
    if not words or len(words) > SUBHEADING_MAX_WORDS:
        return False
    return bool(_HAS_LETTER_RE.search(stripped))


def _stop_cut(text: str) -> tuple:
    """
    Cut a text segment at the first stop phrase, strong stop keyword or
    sentence boundary. A segment that is itself a nutrition row (dense with
    quantities, or starting with "nutritionnelles" / "pour 100 g" /
    "par portion") is dropped whole and ends the section.

    Strong stops (nutrition, storage, "best before", address, website) cut
    anywhere in the segment. Returns:
        (kept_text, stopped). `stopped` is True when the segment (and therefore
        the whole section) must end after `kept_text`.
    """
    low = text.lower()
    cut = len(text)

    if _is_nutrition_segment(text):
        return "", True

    strong = _strong_stop_index(text)
    if strong is not None:
        cut = min(cut, strong)

    for phrase in STOP_PHRASES:
        idx = low.find(phrase)
        if idx != -1 and idx < cut:
            cut = idx

    # Weak stops (allergen / "may contain" declarations) end the list only
    # when they begin a segment and sit outside parentheses; the text before
    # the declaration is kept.
    weak = _weak_stop_index(text)
    if weak is not None and weak < cut:
        cut = weak

    # "Huile de citron. Chocolat noir contient ..." -> keep the full stop
    m = SENTENCE_BREAK_RE.search(text)
    if m and m.start() < cut:
        cut = m.start() + 1

    kept = text[:cut]
    return kept, cut < len(text)


# Punctuation that begins a new segment inside one OCR block. A stop keyword
# ends the section only when it starts one of these segments.
SEGMENT_SEPARATORS = ".。;；:：•|!?！？*·\n"

_OPEN_PARENS = "([{（【"
_CLOSE_PARENS = ")]}）】"


def _parenthesized_spans(text: str) -> List[tuple]:
    """Character spans (start, end) that sit inside parentheses/brackets."""
    spans: List[tuple] = []
    stack: List[int] = []
    for index, char in enumerate(text):
        if char in _OPEN_PARENS:
            stack.append(index)
        elif char in _CLOSE_PARENS and stack:
            spans.append((stack.pop(), index + 1))
    if stack:  # unclosed bracket runs to the end of the block
        spans.append((stack[0], len(text)))
    return spans


def _starts_segment(text: str, index: int) -> bool:
    """True when `index` begins a segment (block start or after a separator)."""
    prefix = text[:index].rstrip()
    return not prefix or prefix[-1] in SEGMENT_SEPARATORS


def _word_boundary_ok(text: str, index: int, keyword: str) -> bool:
    """True when `keyword` at `index` is not glued to Latin letters/digits."""
    before = text[index - 1] if index > 0 else ""
    after_index = index + len(keyword)
    after = text[after_index] if after_index < len(text) else ""
    if before.isascii() and before.isalnum():
        return False  # "restore" contains "store"
    if keyword.isascii() and after.isascii() and after.isalnum():
        return False
    return True


def _weak_stop_index(text: str) -> Optional[int]:
    """Index of the first WEAK stop keyword that begins a segment, or None.

    Weak keywords are the ambiguous list ("contains", "may contain", allergen
    statements). They count only at a segment start (block start, or after
    . 。 ; ： • | ! ? and newlines), outside parentheses and on a word boundary,
    so "(CONTAINS SOY), YEAST EXTRACT..." stays ingredient text while an
    allergen declaration ends the list.
    """
    low = normalize_text(text)
    if not low:
        return None

    inside = _parenthesized_spans(low)
    best: Optional[int] = None
    for keyword in WEAK_STOP_KEYWORDS:
        kw = normalize_text(keyword)
        if not kw:
            continue
        start = 0
        while True:
            index = low.find(kw, start)
            if index == -1:
                break
            start = index + 1
            if not _starts_segment(low, index):
                continue
            if any(begin <= index < end for begin, end in inside):
                continue
            if not _word_boundary_ok(low, index, kw):
                continue
            if best is None or index < best:
                best = index
            break
    return best


def _heading_copy(heading, token: str, language: Optional[str]):
    """Shallow copy of the heading block whose text is only the keyword."""
    obj = copy.copy(heading)
    obj.text = token
    if language:
        obj.language = language
    return obj


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _bbox_x_range(bbox) -> tuple:
    """(x_min, x_max) of a bbox.

    Supports both PaddleOCR `rec_boxes` (flat [x0, y0, x1, y1]) and 4-corner
    polygons [[x0, y0], [x1, y0], [x1, y1], [x0, y1]].
    """
    if not bbox:
        return (0.0, 0.0)
    if isinstance(bbox[0], (list, tuple)) or hasattr(bbox[0], "__len__"):
        xs = [float(p[0]) for p in bbox]
        return (min(xs), max(xs))
    # Flat [x0, y0, x1, y1]
    return (float(bbox[0]), float(bbox[2]) if len(bbox) > 2 else float(bbox[0]))


def _bbox_y_range(bbox) -> tuple:
    """(y_min, y_max) of a bbox (flat [x0, y0, x1, y1] or 4-corner polygon)."""
    if not bbox:
        return (0.0, 0.0)
    if isinstance(bbox[0], (list, tuple)) or hasattr(bbox[0], "__len__"):
        ys = [float(p[1]) for p in bbox]
        return (min(ys), max(ys))
    return (float(bbox[1]), float(bbox[3]) if len(bbox) > 3 else float(bbox[1]))


def _bbox_center(bbox) -> tuple:
    """(x_center, y_center) of a bbox."""
    x0, x1 = _bbox_x_range(bbox)
    y0, y1 = _bbox_y_range(bbox)
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


def _median_height(results) -> float:
    heights = []
    for r in results:
        y_min, y_max = _bbox_y_range(r.bbox)
        if y_max > y_min:
            heights.append(y_max - y_min)
    if not heights:
        return 20.0
    heights.sort()
    return heights[len(heights) // 2]


# ---------------------------------------------------------------------------
# Section object
# ---------------------------------------------------------------------------

class IngredientsSection:
    """One ingredients section: heading + its blocks, in reading order."""

    def __init__(self, heading, blocks, language: str = "", flag: Optional[str] = None,
                 region_blocks=None, region_unreadable=None):
        self.heading = heading            # OCRResult or None
        self.blocks = blocks              # List[OCRResult], kept blocks used in text
        self.language = language
        self.flag = flag                  # "multiple_products" | "no_heading" | None
        self._text = None
        # Geometry-only region: every block walked in the section's column
        # (kept blocks plus engine-dropped blocks that fell inside the column).
        # They never contribute text, but they extend `section_bounds` so the
        # verdict can flag a list whose continuation was dropped/uncertain.
        self.region_blocks = list(region_blocks or [])
        self.region_unreadable = list(region_unreadable or [])

    @property
    def text(self) -> str:
        """Section text in reading order (cached)."""
        if self._text is None:
            self._text, _ = build_reading_order(
                self.blocks, rtl_languages=RTL_LANGUAGES
            )
        return self._text

    @property
    def e_numbers(self) -> List[str]:
        """E-numbers found in the section text (regex, not fuzzy), sorted+unique."""
        found = E_NUMBER_RE.findall(self.text)
        # Normalize: remove internal space, uppercase letter suffix
        return sorted({re.sub(r"\s+", "", m).upper() for m in found})

    def __repr__(self):
        return (f"IngredientsSection(blocks={len(self.blocks)}, "
                f"lang='{self.language}', flag={self.flag})")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _same_column(a, b) -> bool:
    """True if two boxes mostly share the same horizontal extent."""
    ax0, ax1 = _bbox_x_range(a.bbox)
    bx0, bx1 = _bbox_x_range(b.bbox)
    overlap = min(ax1, bx1) - max(ax0, bx0)
    if overlap <= 0:
        return False
    narrower = min(ax1 - ax0, bx1 - bx0)
    return overlap / narrower >= 0.5 if narrower > 0 else False


def _best_heading_for(block, heading_results, med_h: float):
    """Pick the heading whose column `block` belongs to, or None.

    A block qualifies when it is inline with a heading (same line,
    horizontally adjacent) or in the heading's column and below it. Among
    matching headings the one with the most overlap / nearest centre wins.
    Shared by kept-block assignment and the dropped-block region scan, so both
    use the identical column rule.
    """
    bx0, bx1 = _bbox_x_range(block.bbox)
    bx, by = _bbox_center(block.bbox)
    by_min, by_max = _bbox_y_range(block.bbox)
    best_heading, best_key = None, None
    for h in heading_results:
        hx0, hx1 = _bbox_x_range(h.bbox)
        hy0, hy1 = _bbox_y_range(h.bbox)
        hcx = (hx0 + hx1) / 2.0
        hcy = (hy0 + hy1) / 2.0
        hw = max(hx1 - hx0, 1.0)
        overlap = min(hx1, bx1) - max(hx0, bx0)
        is_rtl = bool(ARABIC_RE.search(h.text or ""))
        if is_rtl:
            in_column = overlap > 0 or bx <= hx1 + COLUMN_CENTER_BAND * hw
        else:
            in_column = (
                overlap > 0
                or (hx0 - COLUMN_CENTER_BAND * hw) <= bx <= (hx1 + COLUMN_CENTER_BAND * hw)
            )
        below = by_min >= hy0
        same_line = abs(by - hcy) <= med_h * 0.8
        gap = max(hx0 - bx1, bx0 - hx1, 0.0)
        starts_on_heading_line = by_min >= hy0 - med_h * 0.5
        inline_ok = (same_line and starts_on_heading_line
                     and gap <= max(hw, med_h * 3))
        if not inline_ok and not (in_column and below):
            continue
        key = (-overlap, abs(bx - hcx), by_max)
        if best_key is None or key < best_key:
            best_heading, best_key = h, key
    return best_heading


def _join_reading_order(pieces, fallback_med_h: float = 20.0) -> str:
    """Join (bbox, text) pieces into reading-ordered text.

    Stage-C ordering for the section text. Groups pieces into lines by
    y-centre with a tolerance of 0.5x the median box height of the section
    (not a fixed pixel value), sorts by x within a line, and reverses lines
    whose text is mostly Arabic. Lines stay top-to-bottom, so two columns
    (which land in separate sections) are never interleaved.
    """
    if not pieces:
        return ""
    items = []
    heights = []
    for bbox, text in pieces:
        y0, y1 = _bbox_y_range(bbox)
        x0, x1 = _bbox_x_range(bbox)
        h = y1 - y0
        if h > 0:
            heights.append(h)
        items.append({"cx": (x0 + x1) / 2.0, "cy": (y0 + y1) / 2.0,
                      "text": text or ""})
    heights.sort()
    median = heights[len(heights) // 2] if heights else fallback_med_h
    tol = 0.5 * (median if median > 0 else fallback_med_h)
    tol = max(tol, 1.0)

    items.sort(key=lambda it: it["cy"])
    lines = []
    cur = []
    cur_mean = None
    for it in items:
        if cur_mean is None or abs(it["cy"] - cur_mean) <= tol:
            cur.append(it)
            cur_mean = sum(i["cy"] for i in cur) / len(cur)
        else:
            lines.append(cur)
            cur = [it]
            cur_mean = it["cy"]
    if cur:
        lines.append(cur)

    ordered = []
    for line in lines:
        line.sort(key=lambda it: it["cx"])
        joined = "".join(it["text"] for it in line)
        letters = _HAS_LETTER_RE.findall(joined)
        arabic = ARABIC_RE.findall(joined)
        if letters and len(arabic) * 2 > len(letters):
            line = list(reversed(line))
        ordered.extend(it["text"] for it in line)
    text = ""
    for fragment in ordered:
        if not fragment:
            continue
        cjk_boundary = bool(
            text and CJK_RE.fullmatch(text[-1]) and CJK_RE.fullmatch(fragment[0])
        )
        text += ("" if cjk_boundary or not text else " ") + fragment
    return text


def _group_blocks_into_lines(blocks, tol: float) -> List[List]:
    """Group blocks into lines by y-centre within `tol`, top to bottom."""
    items = []
    for block in blocks:
        y0, y1 = _bbox_y_range(block.bbox)
        items.append((block, (y0 + y1) / 2.0))
    items.sort(key=lambda it: it[1])
    lines: List[List] = []
    cur: List = []
    cur_mean = None
    for block, cy in items:
        if cur_mean is None or abs(cy - cur_mean) <= tol:
            cur.append(block)
            cur_mean = sum(
                (_bbox_y_range(b.bbox)[0] + _bbox_y_range(b.bbox)[1]) / 2.0
                for b in cur
            ) / len(cur)
        else:
            lines.append(cur)
            cur = [block]
            cur_mean = cy
    if cur:
        lines.append(cur)
    return lines


# A block continues an assigned line when its vertical overlap with that line
# is high and the horizontal gap to the nearest assigned block of the line is
# at most this many median box heights. A real gutter above this threshold
# still separates two columns.
LINE_CONTINUATION_GAP_FACTOR = 1.5

# Rule (b) only bridges from a *fragment* block: a box whose width is at most
# this many times its height. A full-line box (an entire ingredient line in one
# OCR segment) already spans the whole text line in its column, so a box beyond
# it on the same line sits in a different column -- a gutter, however narrow --
# and must not be merged in. Word- and phrase-level boxes (the en/07 case) stay
# well below this threshold and still continue each other.
MAX_CONTINUABLE_RATIO = 10


def _block_continues_section(block, heading, assigned, med_h: float) -> bool:
    """Growing-extent column rule (expansion pass only).

    A block belongs to the section when (a) its centre lies within the
    horizontal extent built so far -- which grows with every assigned line and
    is not limited to the heading width -- or (b) it continues a line already
    in the section: vertical overlap with that line is high and the horizontal
    gap to the nearest assigned block of that line is at most
    LINE_CONTINUATION_GAP_FACTOR x the median box height of the section.

    The strict heading-column anchors (overlap, heading band, inline with the
    heading) are checked by the caller before this; this only decides whether
    an otherwise-unassigned block should be pulled in.
    """
    all_blocks = [heading] + assigned
    if not all_blocks:
        return False

    # Only pull in blocks at or below the heading line. Blocks above the
    # heading (a demoted sub-heading, marketing copy, or a product-name line)
    # must never be merged into the section -- that could end the walk before
    # any ingredient is read, or prepend non-ingredient text.
    #
    # Vertical eligibility mirrors pass 1's `starts_on_heading_line` / `below`
    # rule: a block qualifies when its TOP is no more than half a median height
    # above the heading top (the heading line, with OCR jitter) or below it.
    # The block's centre alone is not enough: two tall, closely-spaced lines
    # can overlap vertically and have centres within 0.8 x the median height,
    # yet the upper line is still a separate line above the heading.
    hy0, _ = _bbox_y_range(heading.bbox)
    by0, by1 = _bbox_y_range(block.bbox)
    if by0 < hy0 - 0.5 * med_h:
        return False

    x_ranges = [_bbox_x_range(b.bbox) for b in all_blocks]
    extent_x0 = min(x0 for x0, _ in x_ranges)
    extent_x1 = max(x1 for _, x1 in x_ranges)
    bx0, bx1 = _bbox_x_range(block.bbox)
    cx, _ = _bbox_center(block.bbox)
    pad = max(1.0, 0.1 * med_h)
    if extent_x0 - pad <= cx <= extent_x1 + pad:
        return True

    heights = []
    for b in all_blocks:
        y0, y1 = _bbox_y_range(b.bbox)
        if y1 - y0 > 0:
            heights.append(y1 - y0)
    heights.sort()
    section_med = heights[len(heights) // 2] if heights else med_h
    tol = 0.5 * max(section_med, 1.0)

    by0, by1 = _bbox_y_range(block.bbox)
    bh = max(by1 - by0, 1.0)
    for line in _group_blocks_into_lines(all_blocks, tol):
        # Only fragment boxes can anchor a continuation: a full-line box already
        # spans the line in its column, so a box beyond it on the same line is a
        # different column and must not be merged (see MAX_CONTINUABLE_RATIO).
        fragments = []
        for b in line:
            fx0, fx1 = _bbox_x_range(b.bbox)
            fy0, fy1 = _bbox_y_range(b.bbox)
            fw = fx1 - fx0
            fh = max(fy1 - fy0, 1.0)
            if fw / fh <= MAX_CONTINUABLE_RATIO:
                fragments.append(b)
        if not fragments:
            continue
        line_y0 = min(_bbox_y_range(b.bbox)[0] for b in fragments)
        line_y1 = max(_bbox_y_range(b.bbox)[1] for b in fragments)
        overlap = min(by1, line_y1) - max(by0, line_y0)
        if overlap <= 0:
            continue
        line_h = max(line_y1 - line_y0, 1.0)
        if overlap / min(bh, line_h) < 0.5:
            continue
        gaps = [
            max(bx0 - _bbox_x_range(b.bbox)[1],
                _bbox_x_range(b.bbox)[0] - bx1, 0.0)
            for b in fragments
        ]
        if min(gaps) <= LINE_CONTINUATION_GAP_FACTOR * med_h:
            return True
    return False


def _expanding_best_heading(block, heading_results, sections_blocks, med_h: float):
    """Pick the heading whose growing section accepts `block`, or None."""
    candidates = []
    for h in heading_results:
        assigned = sections_blocks[id(h)]
        if not _block_continues_section(block, h, assigned, med_h):
            continue
        hx0, hx1 = _bbox_x_range(h.bbox)
        bx0, bx1 = _bbox_x_range(block.bbox)
        bx, _ = _bbox_center(block.bbox)
        hcx = (hx0 + hx1) / 2.0
        overlap = min(hx1, bx1) - max(hx0, bx0)
        key = (-overlap, abs(bx - hcx), _bbox_y_range(block.bbox)[1])
        candidates.append((key, h))
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])
    return candidates[0][1]


def extract_ingredient_sections(results: List,
                                unreadable=None) -> List[IngredientsSection]:
    """
    Split OCR results into ingredients sections.

    Args:
        results: List of OCRResult objects with bboxes.
        unreadable: Optional list of dropped/uncertain OCR entries (dicts with
            bbox/text/confidence/reason). They never contribute text, but their
            geometry is walked per section so `section_bounds` covers dropped
            continuation blocks and the verdict can flag them.

    Returns:
        List of IngredientsSection. If several headings are found, one section
        per heading, all flagged "multiple_products". If no heading is found,
        one section with all blocks, flagged "no_heading".
    """
    # Stray OCR stubs ("F") carry no information
    results = [r for r in results if not is_stub(r)]

    if not results:
        return [IngredientsSection(None, [], flag="no_heading")]

    headings_info = []
    for r in results:
        hit = find_heading_token(r)
        if hit:
            headings_info.append((r, hit))

    # --- No heading: never analyse the whole panel as ingredients ----------
    # Without a heading there is no way to tell ingredients from marketing text,
    # so the section stays empty and the verdict asks for a retake.
    if not headings_info:
        return [IngredientsSection(None, [], flag="no_heading")]

    # --- Heading priority (zh): 配料/配料表 beats 成分/成份 ------------------
    preferred = [
        item for item in headings_info
        if heading_priority(item[1][0], item[1][2]) >= 2
    ]
    if preferred:
        headings_info = [
            item for item in headings_info
            if not (item[1][2] == "zh"
                    and heading_priority(item[1][0], item[1][2]) < 2)
        ]

    # --- One product per horizontal column ---------------------------------
    # Headings stacked in the same column (e.g. a French panel below the
    # English one) are sub-headings of the same product: keep the highest
    # priority, then the topmost.
    headings_info.sort(key=lambda item: _bbox_y_range(item[0].bbox)[0])
    columns: List[List] = []
    for item in headings_info:
        for col in columns:
            if any(_same_column(item[0], other[0]) for other in col):
                col.append(item)
                break
        else:
            columns.append([item])
    headings_info = [
        max(
            col,
            key=lambda it: (
                heading_priority(it[1][0], it[1][2]),
                -_bbox_y_range(it[0].bbox)[0],
            ),
        )
        for col in columns
    ]
    headings_info.sort(key=lambda item: _bbox_x_range(item[0].bbox)[0])

    heading_results = [h for h, _ in headings_info]

    # --- Assign each block to a heading ------------------------------------
    # Pass 1: strict heading-column anchors (horizontal overlap, heading band,
    # or inline on the heading line). A block in a neighbouring column (another
    # product, or a nutrition table) is never merged in by this pass.
    med_h = _median_height(results)
    sections_blocks = {id(h): [] for h in heading_results}
    non_heading = [r for r in results if r not in heading_results]

    remaining = []
    for block in non_heading:
        best_heading = _best_heading_for(block, heading_results, med_h)
        if best_heading is not None:
            sections_blocks[id(best_heading)].append(block)
        else:
            remaining.append(block)

    # Pass 2: grow each section's horizontal extent. A block is pulled in when
    # its centre lies in the extent built so far (which grows with every
    # assigned line, not limited to the heading width) or when it continues an
    # assigned line within a small horizontal gap. A real gutter (gap above
    # 1.5 x the median box height) still separates two columns. Blocks are
    # processed top-to-bottom, left-to-right, and the pass repeats until no
    # block can be pulled in.
    changed = True
    while changed and remaining:
        changed = False
        remaining.sort(
            key=lambda r: (_bbox_y_range(r.bbox)[0], _bbox_x_range(r.bbox)[0])
        )
        still = []
        for block in remaining:
            best_heading = _expanding_best_heading(
                block, heading_results, sections_blocks, med_h)
            if best_heading is not None:
                sections_blocks[id(best_heading)].append(block)
                changed = True
            else:
                still.append(block)
        remaining = still

    # --- Build each section's text -----------------------------------------
    # Dropped/uncertain blocks (engine-level) are geometry-only: they never
    # contribute text, but when they sit in a section's column they extend the
    # region bounds so the verdict can flag the list as partly unreadable.
    drop_standins: List = []
    if unreadable:
        from .ocr import OCRResult
        for entry in unreadable:
            if not isinstance(entry, dict) or not entry.get("bbox"):
                continue
            try:
                stand = OCRResult(
                    text=entry.get("text") or "",
                    confidence=float(entry.get("confidence") or 0.0),
                    language=entry.get("language"),
                    bbox=entry.get("bbox"),
                )
            except Exception:
                continue
            drop_standins.append(stand)

    sections = []
    for h, (token, token_end, token_lang) in headings_info:
        blocks = sections_blocks[id(h)]
        blocks.sort(key=lambda r: _bbox_y_range(r.bbox)[0])  # top to bottom

        # Unified walk: kept blocks and dropped blocks in the heading's column,
        # top to bottom. Dropped blocks carry geometry only (region bounds),
        # never text. An inline heading continues over the following blocks
        # until a stop phrase / large gap, exactly like a heading on its own
        # line.
        candidates = [(r, False) for r in blocks]
        for stand in drop_standins:
            if _best_heading_for(stand, heading_results, med_h) is h:
                candidates.append((stand, True))
        candidates.sort(key=lambda t: _bbox_y_range(t[0].bbox)[0])

        ordered_pieces: List = []      # (bbox, text) -> reordered by reading order
        kept_blocks = []
        region_blocks = []             # geometry of walked kept blocks
        region_unreadable = []         # geometry of walked dropped blocks
        stopped = False

        # Text after the keyword in the heading block starts the section;
        # text before it ("au chocolat blanc") is dropped.
        heading_remainder = (h.text or "")[token_end:].lstrip(" :-·,;：")
        if heading_remainder.strip():
            kept_text, stopped = _stop_cut(heading_remainder)
            if kept_text.strip():
                ordered_pieces.append((h.bbox, kept_text.strip()))

        prev_bottom = _bbox_y_range(h.bbox)[1]
        if not stopped:
            for position, (block, is_drop) in enumerate(candidates):
                y_min, y_max = _bbox_y_range(block.bbox)
                if (y_min - prev_bottom) > GAP_FACTOR * med_h:
                    break  # large vertical gap -> end of ingredients

                if is_drop:
                    # Geometry only: a dropped block inside the list region
                    # widens the bounds; its low-confidence text is never used.
                    _, did_stop = _stop_cut(block.text or "")
                    if did_stop:
                        break
                    region_unreadable.append(block)
                    prev_bottom = y_max
                    continue

                segment = (block.text or "").strip().lstrip(" :-·,;：")
                # A group sub-heading introduces the list that follows it; it
                # is not an ingredient, so its text is dropped while the next
                # blocks stay in the section.
                if _is_group_subheading(segment) and position < len(candidates) - 1:
                    region_blocks.append(block)
                    prev_bottom = y_max
                    continue
                kept_text, did_stop = _stop_cut(segment)
                if kept_text.strip():
                    ordered_pieces.append((block.bbox, kept_text.strip()))
                    kept_blocks.append(block)
                    region_blocks.append(block)
                prev_bottom = y_max
                if did_stop:
                    break

        # Language belongs to the IMAGE (dominant script + image words), so the
        # heading keeps the image language instead of re-deriving it from the
        # heading spelling. Keyword matching itself is accent-insensitive.
        image_language = (getattr(h, "language", "") or "").strip()
        language = image_language or token_lang or detect_heading_language(h) or ""
        section = IngredientsSection(
            _heading_copy(h, token, language or None),
            kept_blocks,
            language=language,
            region_blocks=region_blocks,
            region_unreadable=region_unreadable,
        )
        # Stage-C text: line-group by y-centre (tolerance 0.5x the section's
        # median box height), sort by x within a line, reverse mostly-Arabic
        # lines. Mid-block stop cuts are already applied to each piece.
        section._text = _join_reading_order(ordered_pieces, fallback_med_h=med_h)
        sections.append(section)

    # --- Flags ---------------------------------------------------------------
    if len(sections) > 1:
        for s in sections:
            s.flag = "multiple_products"

    return sections
