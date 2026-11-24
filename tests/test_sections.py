"""
Tests for src/sections.py - ingredients section extraction.

All tests use hand-made OCRResult objects with bboxes (never dicts).

bbox convention used here: 4-corner polygons
    [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ocr import OCRResult
from src.sections import (
    extract_ingredient_sections,
    is_heading,
    is_stop_keyword,
    detect_heading_language,
    normalize_text,
)
from src.verdict import section_bounds, unreadable_in_section


def mk(text, x0, y0, x1, y1, lang="en", conf=0.95):
    """Build an OCRResult with a 4-corner bbox."""
    bbox = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    return OCRResult(text=text, confidence=conf, language=lang, bbox=bbox)


# ---------------------------------------------------------------------------
# Normalization / keyword detection
# ---------------------------------------------------------------------------

class TestNormalization:
    def test_french_accents_removed(self):
        assert normalize_text("Ingrédients") == "ingredients"

    def test_arabic_diacritics_removed(self):
        # الْمُكَوِّنَات with diacritics should equal plain المكونات
        assert normalize_text("المُكَوِّنَات") == normalize_text("المكونات")

    def test_lowercase(self):
        assert normalize_text("INGREDIENTS") == "ingredients"


class TestGroupSubheading:
    """A short colon sub-heading is dropped; its list stays in the section."""

    @pytest.mark.parametrize("heading, subheading, items, lang", [
        ("INGREDIENTS", "Vitamins and Minerals:", "Niacinamide, Zinc Oxide.", "en"),
        ("INGRÉDIENTS", "Vitamines et minéraux :", "Niacinamide, oxyde de zinc.", "fr"),
        ("配料", "维生素和矿物质：", "烟酰胺、氧化锌", "zh"),
        ("المكونات", "الفيتامينات والمعادن:", "نياسيناميد، أكسيد الزنك", "ar"),
    ])
    def test_subheading_dropped_and_list_kept(self, heading, subheading, items, lang):
        blocks = [
            mk(heading, 10, 10, 300, 30, lang=lang),
            mk(subheading, 10, 35, 300, 55, lang=lang),
            mk(items, 10, 60, 300, 80, lang=lang),
        ]
        section = extract_ingredient_sections(blocks)[0]

        assert subheading not in section.text
        assert items in section.text

    def test_long_colon_segment_is_not_a_subheading(self):
        blocks = [
            mk("INGREDIENTS", 10, 10, 300, 30),
            mk("This product contains the following:", 10, 35, 300, 55),
            mk("Sugar, salt.", 10, 60, 300, 80),
        ]
        section = extract_ingredient_sections(blocks)[0]
        assert "contains the following" in section.text


class TestHeadingDetection:
    @pytest.mark.parametrize("text", [
        "INGREDIENTS", "Ingredients:", "Ingrédients", "ingredients",
        "Composition", "المكونات", "配料", "成分", "配料表",
    ])
    def test_headings_detected(self, text):
        assert is_heading(mk(text, 0, 0, 50, 20))

    @pytest.mark.parametrize("text", [
        "wheat flour", "sugar", "Nutrition facts", "السكر",
    ])
    def test_non_headings_rejected(self, text):
        assert not is_heading(mk(text, 0, 0, 50, 20))

    def test_fuzzy_heading_with_ocr_typo(self):
        # OCR misread: "INGRED1ENTS" (1 instead of I)
        assert is_heading(mk("INGRED1ENTS", 0, 0, 50, 20))

    def test_heading_language_detected(self):
        assert detect_heading_language(mk("المكونات", 0, 0, 50, 20)) == "ar"
        assert detect_heading_language(mk("Ingrédients", 0, 0, 50, 20)) == "fr"
        assert detect_heading_language(mk("配料", 0, 0, 50, 20)) == "zh"

    def test_stop_keywords_detected(self):
        assert is_stop_keyword(mk("Nutrition facts", 0, 0, 150, 20))
        assert is_stop_keyword(mk("Valeur nutritionnelle", 0, 0, 150, 20))
        assert is_stop_keyword(mk("Best before:", 0, 0, 150, 20))
        assert is_stop_keyword(mk("Allergènes", 0, 0, 150, 20))
        assert is_stop_keyword(mk("营养成分表", 0, 0, 150, 20))
        assert not is_stop_keyword(mk("wheat flour", 0, 0, 150, 20))


# ---------------------------------------------------------------------------
# Section extraction scenarios
# ---------------------------------------------------------------------------

class TestSingleColumn:
    def test_single_column_with_stop_keyword(self):
        """Classic label: heading, 3 ingredient lines, then nutrition block."""
        results = [
            mk("INGREDIENTS", 10, 0, 110, 20),
            mk("wheat flour, sugar,", 10, 30, 200, 50),
            mk("palm oil, salt,", 10, 55, 190, 75),
            mk("raising agent E500", 10, 80, 200, 100),
            mk("Nutrition facts", 10, 130, 200, 150),   # stop keyword
            mk("Energy 450 kcal", 10, 160, 200, 180),   # after stop: excluded
        ]

        sections = extract_ingredient_sections(results)

        assert len(sections) == 1
        s = sections[0]
        assert s.flag is None
        assert s.heading.text == "INGREDIENTS"
        assert s.language == "en"
        assert len(s.blocks) == 3
        assert "wheat flour" in s.text
        assert "raising agent" in s.text
        assert "Nutrition" not in s.text
        assert "Energy" not in s.text

    def test_large_vertical_gap_ends_section(self):
        """A big gap below the ingredients ends the section even without
        a stop keyword."""
        results = [
            mk("INGREDIENTS", 10, 0, 110, 20),
            mk("wheat flour", 10, 30, 110, 50),
            mk("sugar", 10, 55, 70, 75),
            # gap of 200 px (median height = 20) -> section ends here
            mk("random footer text", 10, 300, 200, 320),
        ]

        sections = extract_ingredient_sections(results)

        assert len(sections) == 1
        texts = [b.text for b in sections[0].blocks]
        assert "wheat flour" in texts
        assert "sugar" in texts
        assert "random footer text" not in texts

    def test_inline_ingredients_right_of_heading(self):
        """Inline format: 'Ingredients: wheat flour, sugar' on one line."""
        results = [
            mk("Ingredients:", 10, 30, 110, 50),
            mk("wheat flour, sugar, salt", 120, 30, 400, 50),
        ]

        sections = extract_ingredient_sections(results)

        assert len(sections) == 1
        assert "wheat flour" in sections[0].text


class TestTwoColumns:
    def test_two_columns_bilingual_label(self):
        """EN ingredients in left column, FR ingredients in right column."""
        results = [
            # left column (EN)
            mk("INGREDIENTS", 10, 0, 110, 20),
            mk("wheat flour, water,", 10, 30, 180, 50),
            mk("salt, yeast", 10, 55, 130, 75),
            # right column (FR)
            mk("INGRÉDIENTS", 300, 0, 420, 20, lang="fr"),
            mk("farine de blé, eau,", 300, 30, 480, 50, lang="fr"),
            mk("sel, levure", 300, 55, 420, 75, lang="fr"),
        ]

        sections = extract_ingredient_sections(results)

        assert len(sections) == 2
        assert all(s.flag == "multiple_products" for s in sections)

        en = next(s for s in sections if any("wheat flour" in b.text for b in s.blocks))
        fr = next(s for s in sections if any("farine de blé" in b.text for b in s.blocks))

        # Heading matching is accent-insensitive; the section language follows
        # the language already assigned to the image/OCR blocks.
        assert en.language == "en"
        assert fr.language == "fr"

        assert "wheat flour" in en.text and "yeast" in en.text
        assert "farine" not in en.text
        assert "farine de blé" in fr.text and "levure" in fr.text
        assert "wheat" not in fr.text


class TestThreeProducts:
    def test_three_products_side_by_side(self):
        """Three products on one photo: 3 headings, 3 columns."""
        results = [
            # product 1 (left)
            mk("INGREDIENTS", 10, 0, 110, 20),
            mk("cocoa, sugar", 10, 30, 140, 50),
            # product 2 (middle)
            mk("INGREDIENTS", 210, 0, 310, 20),
            mk("milk, honey", 210, 30, 340, 50),
            # product 3 (right)
            mk("INGREDIENTS", 410, 0, 510, 20),
            mk("dates, peanuts", 410, 30, 560, 50),
        ]

        sections = extract_ingredient_sections(results)

        assert len(sections) == 3
        assert all(s.flag == "multiple_products" for s in sections)

        texts = sorted(s.text for s in sections)
        assert any("cocoa" in t for t in texts)
        assert any("honey" in t for t in texts)
        assert any("dates" in t for t in texts)

        # each section must contain only its own product
        for s in sections:
            if "cocoa" in s.text:
                assert "honey" not in s.text and "dates" not in s.text


class TestArabicRTL:
    def test_arabic_section_reading_order(self):
        """Arabic label: words of one line must come out right-to-left."""
        results = [
            mk("المكونات", 300, 0, 400, 25, lang="ar"),     # heading on the right
            mk("سكر", 350, 40, 400, 62, lang="ar"),          # rightmost word (1st in RTL)
            mk("دقيق القمح", 200, 40, 330, 62, lang="ar"),   # middle word
            mk("ملح", 100, 40, 180, 62, lang="ar"),          # leftmost word (last in RTL)
        ]

        sections = extract_ingredient_sections(results)

        assert len(sections) == 1
        s = sections[0]
        assert s.language == "ar"
        # RTL: rightmost block first
        assert s.blocks[0].text == "سكر"
        assert s.blocks[1].text == "دقيق القمح"
        assert s.blocks[2].text == "ملح"
        assert s.text == "سكر دقيق القمح ملح"


class TestMissingHeading:
    def test_no_heading_returns_empty_section_with_flag(self):
        results = [
            mk("wheat flour, sugar", 10, 30, 200, 50),
            mk("palm oil, salt", 10, 55, 180, 75),
            mk("some other text", 10, 200, 200, 220),
        ]

        sections = extract_ingredient_sections(results)

        assert len(sections) == 1
        s = sections[0]
        assert s.flag == "no_heading"
        assert s.heading is None
        # Without a heading the panel is NOT analysed as ingredients: the
        # blocks are dropped and the section stays empty.
        assert s.blocks == []
        assert s.text == ""

    def test_empty_results(self):
        sections = extract_ingredient_sections([])
        assert len(sections) == 1
        assert sections[0].flag == "no_heading"
        assert sections[0].blocks == []


class TestENumberExtraction:
    def test_e_numbers_extracted_by_regex(self):
        results = [
            mk("INGREDIENTS", 10, 0, 110, 20),
            mk("sugar, E471, colour E120a,", 10, 30, 300, 50),
            mk("emulsifier E 322", 10, 55, 250, 75),
        ]

        sections = extract_ingredient_sections(results)
        e = sections[0].e_numbers

        assert "E471" in e
        assert "E120A" in e          # suffix uppercased
        assert "E322" in e           # "E 322" normalized

    def test_no_e_numbers(self):
        results = [
            mk("INGREDIENTS", 10, 0, 110, 20),
            mk("wheat flour, water, salt", 10, 30, 300, 50),
        ]

        sections = extract_ingredient_sections(results)
        assert sections[0].e_numbers == []


class TestHeadingPriority:
    def test_nutrition_heading_is_not_an_ingredients_heading(self):
        for text in ("营养成分表", "营养成分", "Nutrition Facts",
                     "Valeurs nutritionnelles", "القيم الغذائية"):
            results = [mk(text, 10, 0, 220, 22), mk("sugar, salt", 10, 30, 300, 50)]
            sections = extract_ingredient_sections(results)
            assert sections[0].flag == "no_heading", text
            assert sections[0].text == "", text

    def test_pei_liao_preferred_over_cheng_fen(self):
        results = [
            mk("成分", 10, 0, 80, 20),
            mk("蔗糖、植物油", 10, 30, 300, 50),
            mk("配料", 10, 80, 80, 100),
            mk("小麦粉、食盐", 10, 110, 300, 130),
        ]

        sections = extract_ingredient_sections(results)

        assert len(sections) == 1
        assert sections[0].heading.text == "配料"
        assert "小麦粉" in sections[0].text
        assert "蔗糖" not in sections[0].text


class TestColumnIsolation:
    def test_neighbour_column_is_not_merged(self):
        results = [
            mk("INGREDIENTS", 10, 0, 150, 20),
            mk("sugar, salt", 10, 30, 280, 50),
            mk("palm oil", 10, 55, 260, 75),
            # second product column, same page
            mk("INGREDIENTS", 400, 0, 540, 20),
            mk("water, maize", 400, 30, 660, 50),
        ]

        sections = extract_ingredient_sections(results)

        assert len(sections) == 2
        assert "sugar" in sections[0].text
        assert "water" not in sections[0].text
        assert "water" in sections[1].text
        assert "sugar" not in sections[1].text

    def test_stop_phrase_ends_the_section(self):
        results = [
            mk("INGREDIENTS", 10, 0, 150, 20),
            mk("sugar, salt", 10, 30, 280, 50),
            mk("Allergy advice: contains milk", 10, 55, 300, 75),
            mk("Manufactured by ACME", 10, 80, 300, 100),
        ]

        sections = extract_ingredient_sections(results)

        assert "sugar" in sections[0].text
        assert "Allergy" not in sections[0].text
        assert "Manufactured" not in sections[0].text


class TestRealLabelFixture:
    """
    eval/en/06.jpg replayed from its recorded OCR blocks.

    The label has two columns: INGREDIENTS on the left, a NUTRITION /
    INFORMATION table on the right. Only the left column may be read.
    """

    @staticmethod
    def _blocks():
        import json

        path = Path(__file__).parent / "fixtures" / "eval-en-06.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return [
            OCRResult(
                text=item["text"],
                confidence=item["confidence"],
                language=item.get("language"),
                bbox=item["bbox"],
            )
            for item in data
        ]

    def test_ingredients_column_is_found(self):
        sections = extract_ingredient_sections(self._blocks())

        assert len(sections) == 1
        section = sections[0]
        assert section.flag is None
        assert section.heading is not None
        assert "INGREDIENTS" in section.heading.text.upper()
        assert section.blocks, "ingredients column must not be empty"
        assert "NOODLES: WHEAT FLOUR" in section.text

    def test_neighbour_column_is_not_merged(self):
        section = extract_ingredient_sections(self._blocks())[0]
        text = section.text.upper()

        assert "NUTRITION" not in text
        assert "SERVINGS PER PACKAGE" not in text
        assert "ALLERGY" not in text
        assert "STORAGE" not in text
        # Every kept block still starts in the left (ingredients) column.
        assert all(float(block.bbox[0]) < 650 for block in section.blocks)

    def test_parenthesized_contains_does_not_end_the_list(self):
        """
        The list runs "... (CONTAINS SOY), YEAST EXTRACT ..." and must not stop
        at a stop keyword that sits inside parentheses mid-segment.
        """
        section = extract_ingredient_sections(self._blocks())[0]
        text = section.text.upper()

        assert "(CONTAINS SOY)" in text
        assert "YEAST EXTRACT" in text
        assert "DRIED MUSHROOM." in text
        # The section must end at the allergy statement, not before it.
        assert "ALLERGY" not in text

    def test_full_list_is_kept(self):
        """Every left-column line survives, up to DRIED MUSHROOM."""
        text = extract_ingredient_sections(self._blocks())[0].text

        assert text.rstrip().endswith("DRIED MUSHROOM.")
        for line in [
            "POTATO STARCH", "(CONTAINS SOY)", "YEAST EXTRACT",
            "FLAVOUR ENHANCER (627, 631)", "COLOUR (150C)", "COLOUR (101).",
            "DRIED VEGETABLES", "TEXTURED VEGETABLE PROTEIN",
        ]:
            assert line in text


class TestStopTiers:
    """Strong stops cut anywhere; weak keywords only at a segment start."""

    def test_strong_stop_ends_section_mid_segment(self):
        results = [
            mk("INGREDIENTS", 10, 0, 110, 20),
            mk("sugar, palm oil, salt store in a cool dry place",
               10, 30, 400, 50),
            mk("Energy 450 kcal", 10, 55, 400, 75),
        ]

        sections = extract_ingredient_sections(results)

        assert len(sections) == 1
        text = sections[0].text
        assert text.startswith("sugar, palm oil, salt")
        assert "store" not in text.lower()
        assert "Energy" not in text

    def test_strong_nutrition_phrase_ends_section_mid_segment(self):
        results = [
            mk("INGRÉDIENTS", 10, 0, 150, 20),
            mk("sucre, huile de palme valeurs nutritionnelles énergie 450",
               10, 30, 400, 50),
        ]

        text = extract_ingredient_sections(results)[0].text

        assert text.startswith("sucre, huile de palme")
        assert "nutritionnelles" not in text.lower()

    def test_weak_contains_mid_segment_is_kept(self):
        """'contains' not at a segment start is ingredient text, not a stop."""
        results = [
            mk("INGREDIENTS", 10, 0, 110, 20),
            mk("sugar, glucose syrup contains sulphites, salt", 10, 30, 400, 50),
        ]

        text = extract_ingredient_sections(results)[0].text

        assert "contains sulphites" in text.lower()
        assert "salt" in text.lower()

    def test_weak_contains_at_segment_start_ends_section(self):
        results = [
            mk("INGREDIENTS", 10, 0, 110, 20),
            mk("sugar, salt", 10, 30, 300, 50),
            mk("CONTAINS WHEAT AND SOY", 10, 55, 400, 75),
            mk("Energy 450 kcal", 10, 80, 400, 100),
        ]

        text = extract_ingredient_sections(results)[0].text

        assert "sugar" in text.lower()
        assert "contains" not in text.lower()
        assert "Energy" not in text


class TestAllergenDeclarations:
    """Allergen / "may contain" statements end the list in all four languages.

    They only count at a segment start and outside parentheses, so an allergen
    note inside an ingredient ("Farine de blé (contient Gluten)") is kept.
    """

    @pytest.mark.parametrize("lang,heading,allergen", [
        ("zh", "配料", "含有麸质的谷物及其制品，大豆及其制品，此生产线也加工含有蛋类及其制品，"),
        ("zh", "配料", "本品含有大豆及其制品。"),
        ("zh", "配料", "可能含有坚果及其果仁类制品。"),
        ("en", "INGREDIENTS", "Contains milk and soy."),
        ("en", "INGREDIENTS", "May contain traces of peanuts."),
        ("en", "INGREDIENTS", "Processed in a facility that also handles nuts."),
        ("fr", "INGRÉDIENTS", "Peut contenir des traces de fruits à coque."),
        ("fr", "INGRÉDIENTS", "Fabriqué dans un atelier utilisant du gluten."),
        ("ar", "المكونات", "قد يحتوي على الحليب."),
    ])
    def test_allergen_statement_ends_the_section(self, lang, heading, allergen):
        results = [
            mk(heading, 10, 0, 150, 20),
            mk("sugar, salt, wheat flour", 10, 30, 400, 50),
            mk(allergen, 10, 55, 400, 75),
            mk("Energy 450 kcal", 10, 80, 400, 100),
        ]

        text = extract_ingredient_sections(results)[0].text.lower()

        assert "sugar" in text
        assert "energy" not in text
        head = allergen.lower()[:4]
        assert head not in text

    def test_allergen_after_sentence_end_cuts_but_keeps_ingredients(self):
        results = [
            mk("INGREDIENTS", 10, 0, 110, 20),
            mk("sugar, salt. Contains milk", 10, 30, 400, 50),
        ]

        text = extract_ingredient_sections(results)[0].text

        assert "sugar, salt" in text
        assert "Contains milk" not in text

    def test_parenthesized_allergen_note_is_kept(self):
        results = [
            mk("INGREDIENTS", 10, 0, 110, 20),
            mk("wheat flour (contains gluten), sugar", 10, 30, 400, 50),
        ]

        text = extract_ingredient_sections(results)[0].text.lower()

        assert "(contains gluten)" in text
        assert "sugar" in text

    def test_chinese_han_you_inside_ingredient_name_is_kept(self):
        """'含有' mid-segment is part of the ingredient text, not a stop."""
        results = [
            mk("配料", 10, 0, 110, 20),
            mk("小麦粉，富含维生素的谷物，白砂糖", 10, 30, 400, 50),
        ]

        text = extract_ingredient_sections(results)[0].text

        assert "白砂糖" in text


class TestNutritionRows:
    def test_quantity_dense_row_ends_section(self):
        results = [
            mk("INGREDIENTS", 10, 0, 110, 20),
            mk("sugar, palm oil, salt", 10, 30, 300, 50),
            mk("Energy 450 kJ / 107 kcal", 10, 55, 400, 75),
            mk("Fat 10 g", 10, 80, 400, 100),
        ]

        text = extract_ingredient_sections(results)[0].text

        assert "sugar, palm oil, salt" in text
        assert "kJ" not in text
        assert "Fat" not in text

    @pytest.mark.parametrize("row", [
        "Nutritionnelles pour 100 g",
        "Pour 100 g : énergie 450 kJ",
        "Par portion : 107 kcal",
    ])
    def test_nutrition_row_start_ends_section(self, row):
        results = [
            mk("INGRÉDIENTS", 10, 0, 150, 20),
            mk("sucre, huile de palme", 10, 30, 300, 50),
            mk(row, 10, 55, 400, 75),
            mk("sucre 10 g", 10, 80, 400, 100),
        ]

        text = extract_ingredient_sections(results)[0].text

        assert text == "sucre, huile de palme"

    def test_single_quantity_is_not_a_nutrition_row(self):
        results = [
            mk("INGREDIENTS", 10, 0, 110, 20),
            mk("sugar, salt 2 g", 10, 30, 300, 50),
        ]

        text = extract_ingredient_sections(results)[0].text

        assert "salt 2 g" in text


class TestInlineHeadingContinuation:
    """An inline heading must continue over following blocks until a stop."""

    def test_inline_heading_collects_continuation_lines(self):
        """Heading block carries inline text; 2 continuation lines follow in
        the same column; a nutrition stop ends the section."""
        results = [
            mk("配料：燕麦片", 10, 100, 300, 130, lang="zh"),   # inline heading + first item
            mk("椰子脆片、椰子油", 10, 140, 300, 170, lang="zh"),  # continuation 1
            mk("蜂蜜、扁", 10, 180, 300, 210, lang="zh"),         # continuation 2
            mk("营养成分表", 10, 240, 300, 270, lang="zh"),       # stop phrase
            mk("能量 450 kJ", 10, 280, 300, 310, lang="zh"),      # after stop -> excluded
        ]
        section = extract_ingredient_sections(results)[0]

        assert section.heading.text == "配料"
        # Inline remainder + both continuation lines are in the text.
        assert "燕麦片" in section.text
        assert "椰子脆片" in section.text
        assert "蜂蜜" in section.text
        assert len(section.blocks) >= 2
        # Stop phrase and everything after it are excluded.
        assert "营养成分表" not in section.text
        assert "能量" not in section.text

    def test_inline_heading_alone_still_works(self):
        """fr/02-style: the whole list sits inline on the heading block, with
        no follow-up blocks. The section is NOT empty and blocks may be 0."""
        results = [
            mk("Ingrédients : sucre, farine de blé, sel", 10, 100, 500, 130,
               lang="fr"),
        ]
        section = extract_ingredient_sections(results)[0]

        assert section.flag is None
        assert section.blocks == []
        assert section.text.strip() == "sucre, farine de blé, sel"
        # Not flagged "empty": text came from the heading block itself.
        assert section.text != ""

    def test_dropped_continuation_in_column_is_seen(self):
        """A dropped (engine-level) block below an inline heading widens the
        section region so unreadable_in_section flags it."""
        results = [
            mk("配料：燕麦片", 10, 100, 300, 130, lang="zh"),
        ]
        unreadable = [{
            "bbox": [10, 150, 300, 180],  # flat [x0,y0,x1,y1], same column, below heading
            "text": "GB19640",
            "confidence": 0.99,
            "reason": "script mismatch for model zh",
        }]
        section = extract_ingredient_sections(results, unreadable=unreadable)[0]

        # The dropped block never contributes text.
        assert section.text == "燕麦片"
        assert section.blocks == []
        # But its geometry extends the region bounds below the heading box.
        assert len(section.region_unreadable) == 1
        bounds = section_bounds(section)
        assert bounds is not None and bounds[3] >= 180  # covers the dropped block
        seen = unreadable_in_section(section, unreadable)
        assert len(seen) == 1
        assert seen[0]["text"] == "GB19640"


class TestReadingOrderStageC:
    """Stage-C text ordering: line grouping by y-centre (0.5x median height),
    x-sort within line, RTL for mostly-Arabic lines, column isolation kept."""

    def test_same_line_words_with_slightly_different_top_y(self):
        """Three words of one printed line have slightly different top-y (OCR
        jitter); they must come out left-to-right, not top-y order."""
        results = [
            mk("INGREDIENTS", 10, 0, 360, 20),
            mk("sugar", 130, 30, 200, 52),    # cy 41
            mk("salt", 210, 32, 260, 54),     # cy 43
            mk("pepper", 270, 28, 340, 50),   # cy 39  (top-y would sort this first)
        ]
        text = extract_ingredient_sections(results)[0].text
        assert text == "sugar salt pepper"

    def test_two_lines_with_large_text_stay_separate(self):
        """Two tall lines are grouped separately (centres far apart relative to
        0.5x the median box height) and kept top-to-bottom."""
        results = [
            mk("INGREDIENTS", 10, 0, 360, 20),
            mk("LineOne", 10, 40, 300, 90),    # cy 65, height 50
            mk("LineTwo", 10, 140, 300, 190),  # cy 165, height 50
        ]
        text = extract_ingredient_sections(results)[0].text
        assert text == "LineOne LineTwo"

    def test_arabic_line_stays_right_to_left(self):
        """A line whose text is mostly Arabic is reversed (right-to-left)."""
        results = [
            mk("المكونات", 300, 0, 400, 25, lang="ar"),
            mk("سكر", 350, 40, 400, 62, lang="ar"),    # rightmost
            mk("دقيق", 200, 40, 330, 62, lang="ar"),   # middle
            mk("ملح", 100, 40, 180, 62, lang="ar"),    # leftmost
        ]
        text = extract_ingredient_sections(results)[0].text
        assert text == "سكر دقيق ملح"

    @pytest.mark.parametrize("left, right, expected", [
        ("乳", "清粉", "乳清粉"),
        ("抗坏", "血酸钠", "抗坏血酸钠"),
        ("soy", "lecithin", "soy lecithin"),
    ])
    def test_line_fragment_join_spacing(self, left, right, expected):
        """CJK fragments join directly; Latin fragments keep a word space."""
        results = [
            mk("INGREDIENTS", 10, 0, 360, 20),
            mk(left, 10, 30, 100, 52),
            mk(right, 110, 30, 220, 52),
        ]
        text = extract_ingredient_sections(results)[0].text
        assert text == expected

    def test_two_columns_are_not_interleaved(self):
        """Two side-by-side products stay in two sections; each section's text
        contains only its own column in order (no interleaving)."""
        results = [
            mk("INGREDIENTS", 10, 0, 110, 20),
            mk("sugar", 10, 30, 100, 50),
            mk("salt", 10, 55, 90, 75),
            mk("INGREDIENTS", 300, 0, 400, 20),
            mk("milk", 300, 30, 380, 50),
            mk("honey", 300, 55, 390, 75),
        ]
        sections = extract_ingredient_sections(results)
        assert len(sections) == 2
        texts = sorted(s.text for s in sections)
        assert texts == ["milk honey", "sugar salt"]
        # No section mixes both columns.
        for s in sections:
            assert not (("sugar" in s.text) and ("milk" in s.text))


class TestGrowingColumnExtent:
    """Right-side word-level boxes are pulled into the section once the
    section's horizontal extent has grown, while a real gutter still separates
    two columns. Coordinates are taken from the en/07 preprocessing-on matrix.
    """

    def test_word_level_boxes_reconstruct_full_width_paragraph(self):
        # Heading spans x18..409; the first line grows the section extent to
        # x913. The right-hand words on the next line (Salt, Dried, Yeast) lie
        # outside the heading band and must still be included, in order.
        results = [
            mk("INGREDIENTS", 18, 7, 409, 111),
            mk("Whole", 399, 20, 573, 94),
            mk("Grain", 577, 17, 728, 97),
            mk("Wheat,", 724, 12, 913, 102),
            mk("Malted", 21, 112, 203, 196),
            mk("Barley", 187, 112, 363, 204),
            mk("Flour,", 327, 116, 500, 202),
            mk("Salt,", 500, 113, 620, 199),
            mk("Dried", 618, 113, 768, 196),
            mk("Yeast.", 761, 113, 919, 188),
        ]
        text = extract_ingredient_sections(results)[0].text
        assert text == "Whole Grain Wheat, Malted Barley Flour, Salt, Dried Yeast."

    def test_full_line_boxes_give_the_same_text(self):
        results = [
            mk("INGREDIENTS", 18, 7, 409, 111),
            mk("Whole Grain Wheat,", 399, 20, 913, 102),
            mk("Malted Barley Flour, Salt, Dried Yeast.", 21, 112, 919, 204),
        ]
        text = extract_ingredient_sections(results)[0].text
        assert text == "Whole Grain Wheat, Malted Barley Flour, Salt, Dried Yeast."

    def test_two_columns_with_gutter_are_not_merged(self):
        # med_h ~= 20 -> line-continuation threshold 30 px; the gutter is
        # ~250 px, well above it, so the right column stays separate.
        results = [
            mk("INGREDIENTS", 10, 0, 110, 20),
            mk("sugar", 10, 30, 100, 50),
            mk("salt", 10, 55, 90, 75),
            mk("INGREDIENTS", 360, 0, 460, 20),
            mk("milk", 360, 30, 450, 50),
            mk("honey", 360, 55, 450, 75),
        ]
        sections = extract_ingredient_sections(results)
        assert len(sections) == 2
        texts = sorted(s.text for s in sections)
        assert texts == ["milk honey", "sugar salt"]

    def test_right_hand_nutrition_table_is_not_pulled_in(self):
        # Ingredients stay in the left column; the section extent does not
        # reach the nutrition table on the right, so it is excluded.
        results = [
            mk("INGREDIENTS", 10, 0, 110, 20),
            mk("sugar", 10, 30, 120, 50),
            mk("salt", 10, 55, 120, 75),
            mk("Energy 450 kcal", 400, 30, 600, 50),
            mk("Fat 20 g", 400, 55, 600, 75),
        ]
        sections = extract_ingredient_sections(results)
        assert len(sections) == 1
        text = sections[0].text
        assert "sugar" in text and "salt" in text
        assert "Energy" not in text and "Fat" not in text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
