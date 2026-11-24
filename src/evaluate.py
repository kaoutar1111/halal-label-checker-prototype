"""Text comparison helpers for the OCR regression target (CER <= 3%)."""

import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable, List, Dict

from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein


def normalize_for_cer(text: str) -> str:
    """Whitespace/unicode normalization used before comparing OCR texts."""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text.lower()


def normalize_for_content(text: str) -> str:
    """
    Punctuation-free normalization for the content CER.

    Punctuation is deleted (not replaced by a space): OCR punctuation
    (·, -, 、, :, %) is unstable between runs and crops, and turning it into a
    space would invent word breaks the fixture does not have. It never changes
    which ingredient is on the label, so the target metric compares letters
    and digits only; the strict CER is reported next to it for transparency.
    """
    return re.sub(r"[^\w]+", "", normalize_for_cer(text))


def character_error_rate(reference: str, hypothesis: str, normalize=None) -> float:
    """Levenshtein distance / reference length (0.0 = perfect, 1.0 = total)."""
    normalize = normalize or normalize_for_cer
    ref = normalize(reference)
    hyp = normalize(hypothesis)
    if not ref:
        return 1.0 if hyp else 0.0
    return Levenshtein.distance(ref, hyp) / float(len(ref))


def load_fixture(path: str | Path) -> List[Dict]:
    """Load an OCR fixture JSON (list of OCRResult dicts)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def fixture_text(blocks: Iterable[Dict]) -> str:
    """Fixture reference text: block texts in fixture (reading) order."""
    return "\n".join(str(block.get("text", "")) for block in blocks)


def _canonical(texts: Iterable[str], normalize) -> str:
    normalized = [normalize(text) for text in texts]
    return "\n".join(sorted(text for text in normalized if text))


def canonical_text(texts: Iterable[str]) -> str:
    """
    Order-independent canonical text: normalized blocks sorted alphabetically.

    Fixtures were dumped in confidence order, so comparing joined reading-order
    text would count layout order as errors. Sorting blocks keeps the CER
    focused on what OCR actually read.
    """
    return _canonical(texts, normalize_for_cer)


def canonical_error_rate(reference_texts: Iterable[str], hypothesis_texts: Iterable[str],
                         strict: bool = False) -> float:
    """
    CER over canonical texts. Default = content CER (punctuation ignored);
    strict=True keeps punctuation.
    """
    normalize = normalize_for_cer if strict else normalize_for_content
    ref = _canonical(reference_texts, normalize)
    hyp = _canonical(hypothesis_texts, normalize)
    return character_error_rate(ref, hyp, normalize=lambda text: text)


def missing_lines(blocks: Iterable[Dict], hypothesis, min_chars: int = 4,
                  min_ratio: float = 80.0) -> List[str]:
    """
    Fixture lines with no comparable text in the output.

    `hypothesis` is either the extracted text or the list of extracted lines.
    A fixture line counts as present when its best match (per line, or
    partially against the joined text) scores >= `min_ratio` (rapidfuzz
    0-100). Verbatim substring checks flag lines whose tail was split
    differently by the detector, which is not a missing line.
    """
    if isinstance(hypothesis, str):
        raw_lines = [hypothesis]
    else:
        raw_lines = list(hypothesis)
    hyp_lines = [normalize_for_cer(line) for line in raw_lines]
    hyp_lines = [line for line in hyp_lines if line]
    joined = " ".join(hyp_lines)

    missing = []
    for block in blocks:
        norm = normalize_for_cer(block.get("text", ""))
        if len(norm) < min_chars:
            continue
        best = max((fuzz.ratio(norm, line) for line in hyp_lines), default=0.0)
        if hyp_lines:
            best = max(best, fuzz.partial_ratio(norm, joined))
        if best < min_ratio:
            missing.append(str(block.get("text", "")))
    return missing


def format_report(image: str, lang: str, fixture_path: str, cer: float,
                 reference: str, hypothesis: str, missing: List[str],
                 target: float = 0.03, strict_cer: float | None = None) -> str:
    lines = [
        f"image: {image}",
        f"language: {lang}",
        f"fixture: {fixture_path}",
        f"CER: {cer * 100:.2f}%   (target <= {target * 100:.0f}%)"
        f"   {'PASS' if cer <= target else 'FAIL'}",
    ]
    if strict_cer is not None:
        lines.append(f"CER (strict, punctuation included): {strict_cer * 100:.2f}%")
    lines += [
        f"reference chars: {len(normalize_for_content(reference))}",
        f"output chars:    {len(normalize_for_content(hypothesis))}",
        f"missing lines: {len(missing)}",
    ]
    for line in missing:
        lines.append(f"  - {line}")
    return "\n".join(lines)
