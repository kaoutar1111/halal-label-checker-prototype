"""
Regression guard: the OCR pipeline must stay within 3% CER of the fixtures.

Fixtures in tests/fixtures were produced by the original per-language
PaddleOCR full pipeline; the shared-detection path must not read worse.
Run from the project root (the samples/ images live next to tests/).
"""

import pytest
from PIL import Image
from pathlib import Path

from src.evaluate import canonical_error_rate, canonical_text, load_fixture, missing_lines

ROOT = Path(__file__).resolve().parent.parent
TARGET_CER = 0.03

CASES = [
    ("label-en.jpg", "en", "label-en.json"),
    ("label-fr.jpg", "fr", "label-fr.json"),
    ("label_ar.jpg", "ar", "label-ar.json"),
    ("label_zh.jpg", "zh", "label-zh.json"),
]


@pytest.fixture(scope="module")
def ocr():
    from src.ocr import MultiLanguageOCR
    return MultiLanguageOCR()


@pytest.mark.parametrize("image_name,lang,fixture_name", CASES)
def test_sample_cer_within_target(ocr, image_name, lang, fixture_name):
    """Each sample must read within 3% CER of its fixture."""
    image_path = ROOT / "samples" / image_name
    fixture_path = ROOT / "tests" / "fixtures" / fixture_name
    if not image_path.exists() or not fixture_path.exists():
        pytest.skip(f"missing sample or fixture: {image_name}")

    image = Image.open(image_path).convert("RGB")
    results = ocr.process_image(image, [lang], auto=False)
    hypothesis = [result.text for result in results]
    blocks = load_fixture(fixture_path)
    reference = [str(block.get("text", "")) for block in blocks]

    cer = canonical_error_rate(reference, hypothesis)
    details = (
        f"\nimage={image_name} lang={lang}"
        f"\nblocks read={len(hypothesis)} fixture={len(reference)}"
        f"\nCER={cer:.2%} (target <= {TARGET_CER:.0%})"
        f"\ndropped={getattr(ocr, 'last_dropped', [])}"
        f"\nmissing={missing_lines(blocks, hypothesis)}"
        f"\nreference={canonical_text(reference)!r}"
        f"\nhypothesis={canonical_text(hypothesis)!r}"
    )
    assert cer <= TARGET_CER, details


@pytest.mark.parametrize("image_name,lang,fixture_name", CASES)
def test_image_language_is_single(ocr, image_name, lang, fixture_name):
    """Language is decided per image, so every block carries the same language."""
    image_path = ROOT / "samples" / image_name
    if not image_path.exists():
        pytest.skip(f"missing sample: {image_name}")

    image = Image.open(image_path).convert("RGB")
    results = ocr.process_image(image, [lang], auto=False)
    languages = {result.language for result in results}
    assert languages == {lang}, f"{image_name}: expected {{{lang}}}, got {languages}"


def test_unreadable_block_inside_region_forces_verify():
    """A dropped block inside the ingredients region must yield À vérifier."""
    from src.ocr import OCRResult
    from src.sections import IngredientsSection
    from src.matcher import IngredientMatcher
    from src.verdict import UNREADABLE_REASON, VERDICT_TO_VERIFY, VerdictGenerator

    heading = OCRResult("INGREDIENTS", 0.95, "en", bbox=[100, 100, 400, 120])
    block = OCRResult("Sugar", 0.92, "en", bbox=[100, 130, 400, 150])
    section = IngredientsSection(heading, [block], language="en")
    report = IngredientMatcher().match_section(section)

    inside = [{"bbox": [250, 132, 320, 148], "text": "", "confidence": 0.2,
               "reason": "empty recognition"}]
    verdict = VerdictGenerator().assess(section, report, unreadable=inside)
    assert verdict.verdict == VERDICT_TO_VERIFY
    assert UNREADABLE_REASON in verdict.reasons
    assert verdict.unreadable_blocks == inside

    outside = [{"bbox": [250, 400, 320, 420], "text": "noise", "confidence": 0.1,
                "reason": "script mismatch"}]
    verdict = VerdictGenerator().assess(section, report, unreadable=outside)
    assert UNREADABLE_REASON not in verdict.reasons
