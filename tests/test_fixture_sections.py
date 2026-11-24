"""
Section extraction tests on REAL OCR output fixtures.

Fixtures are generated with:
    python scripts/ocr_check.py <image> --languages <lang> --json tests/fixtures/<name>.json

Each fixture is a JSON list of:
    {"text": str, "confidence": float, "language": str, "bbox": [x0, y0, x1, y1]}
which is what PaddleOCR returns (`rec_boxes` are flat [x0, y0, x1, y1]).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ocr import OCRResult
from src.sections import extract_ingredient_sections

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURE_FILES = sorted(FIXTURES_DIR.glob("*.json"))


def load_fixture(path: Path):
    """Load a fixture JSON file into real OCRResult objects."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        OCRResult(
            text=item["text"],
            confidence=float(item["confidence"]),
            language=item["language"],
            bbox=item["bbox"],
        )
        for item in data
    ]


@pytest.mark.skipif(not FIXTURE_FILES, reason="no OCR fixtures generated yet")
@pytest.mark.parametrize("path", FIXTURE_FILES, ids=[p.stem for p in FIXTURE_FILES])
def test_fixture_loads_as_ocr_results(path):
    results = load_fixture(path)
    assert results
    assert all(isinstance(r, OCRResult) for r in results)
    assert all(isinstance(r.bbox, list) and len(r.bbox) == 4 for r in results)


@pytest.mark.skipif(not FIXTURE_FILES, reason="no OCR fixtures generated yet")
@pytest.mark.parametrize("path", FIXTURE_FILES, ids=[p.stem for p in FIXTURE_FILES])
def test_sections_extracted_from_fixture(path):
    sections = extract_ingredient_sections(load_fixture(path))

    assert sections, "at least one section (even 'no_heading') must be returned"
    for section in sections:
        assert isinstance(section.text, str)
        assert isinstance(section.e_numbers, list)
        assert section.flag in (None, "multiple_products", "no_heading")


def test_label_en_three_products():
    """label-en.jpg shows three products side by side -> 3 sections."""
    sections = extract_ingredient_sections(load_fixture(FIXTURES_DIR / "label-en.json"))

    assert len(sections) == 3
    assert all(s.flag == "multiple_products" for s in sections)
    assert all(len(s.blocks) > 0 for s in sections)
    assert all(s.language == "en" for s in sections)

    # The heading is only the matched keyword; the list starts right after it.
    assert all(s.heading.text == "INGREDIENTS" for s in sections)
    assert all(s.text.startswith("Sugar") for s in sections)

    # Each product keeps its own ingredient list (no cross-contamination).
    texts = [s.text.lower() for s in sections]
    assert any("tomato paste" in t for t in texts)
    assert any("maltodextrin" in t for t in texts)
    assert any("skim milk powder" in t for t in texts)

    # E-numbers extracted separately per section.
    all_e = [e for s in sections for e in s.e_numbers]
    assert {"E627", "E631", "E330", "E551", "E626", "E630"} <= set(all_e)
    assert all(e.startswith("E") for e in all_e)


def test_label_fr_heading_and_section_boundaries():
    """
    label-fr.json (real OCR output).

    The fixture block is
    "au chocolat blanc INGRÉDIENTS Sucre · Masse de cacao - ...":
      - heading = only the matched word INGRÉDIENTS, language fr (the accented
        raw token decides, not the whole block);
      - "au chocolat blanc" is dropped, "Sucre ..." starts the section;
      - the following full-width paragraph lines are collected;
      - the section stops at "Huile de citron." (sentence boundary) and never
        reaches the allergen / "Sans alcool" text.
    """
    sections = extract_ingredient_sections(load_fixture(FIXTURES_DIR / "label-fr.json"))

    assert len(sections) == 1
    section = sections[0]
    assert section.flag is None

    # Heading keyword only, accented token decides the language.
    assert section.heading is not None
    assert section.heading.text == "INGRÉDIENTS"
    assert section.language == "fr"

    # Blocks were actually collected (full-width paragraph, not a column).
    assert section.blocks
    # Stray OCR stub "F" (1 char, confidence 0.858) is dropped.
    assert all(b.text.strip() != "F" for b in section.blocks)

    text = section.text
    # Text before the keyword is dropped; the text after it starts the list.
    assert text.startswith("Sucre")
    assert "au chocolat blanc" not in text.lower()

    # The list ends at the sentence boundary "Huile de citron."
    assert text.rstrip().endswith("Huile de citron.")

    # Nothing from the allergen paragraph must leak into the section.
    assert "chocolat noir contient" not in text.lower()
    assert "contient cacao" not in text.lower()
    assert "pour les allergènes" not in text.lower()
    assert "ne convient pas" not in text.lower()
    assert "sans alcool" not in text.lower()

    # E-numbers extracted separately (sorted + unique).
    assert section.e_numbers == ["E171", "E172", "E471"]


@pytest.mark.skipif(
    not (FIXTURES_DIR / "label-ar.json").exists(),
    reason="label-ar.json fixture not generated (image missing on this machine)",
)
def test_label_ar_rtl_and_scripts():
    """Arabic fixture: RTL reading order, script-tagged results."""
    results = load_fixture(FIXTURES_DIR / "label-ar.json")

    # Merged mixed-script output must keep each box's script.
    for r in results:
        if r.language == "ar":
            assert any("\u0600" <= c <= "\u06ff" for c in r.text)

    sections = extract_ingredient_sections(results)
    assert sections
    assert len(sections) == 1
    section = sections[0]
    assert section.language == "ar"

    # The list ends at the Arabic preservative phrase and never reaches the
    # marketing claims below it ("non-GMO product" / "plant product").
    assert section.text.rstrip().endswith("مادة حافظة")
    assert "منتج نباتي" not in section.text


@pytest.mark.skipif(
    not (FIXTURES_DIR / "label-zh.json").exists(),
    reason="label-zh.json fixture not generated (image missing on this machine)",
)
def test_label_zh():
    sections = extract_ingredient_sections(load_fixture(FIXTURES_DIR / "label-zh.json"))
    assert sections
    assert len(sections) == 1
    section = sections[0]
    assert section.language == "zh"

    # Heading is only the keyword, even without spaces (CJK).
    assert section.heading.text == "成分"

    # The list starts right after the heading and ends at "cocoa butter";
    # the product-name line ("品名...") must be excluded.
    assert section.text.startswith("蔗糖")
    assert section.text.rstrip().endswith("可可脂")
    assert "品名" not in section.text
