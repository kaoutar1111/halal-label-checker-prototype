"""
Phase 2 tests: matcher + verdict on the four real OCR fixtures.

Last rule of the phase: every section-extraction / matching behaviour is tested
on the real fixtures, not only on hand-made boxes.
"""

import json
from pathlib import Path

import pytest

from src.matcher import (
    IngredientMatcher,
    extract_e_numbers,
    is_negated_alcohol,
    normalize_text,
    prefix_additive_codes,
    split_ingredients,
)
from src.ocr import OCRResult
from src.sections import extract_ingredient_sections
from src.verdict import (
    DISCLAIMER,
    NOT_EVALUATED_LABEL,
    VERDICT_CLEAR,
    VERDICT_INCOMPATIBLE,
    VERDICT_TO_VERIFY,
    VerdictGenerator,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
REFERENCE_PATH = Path(__file__).parent.parent / "data" / "reference.json"

ALCOHOL_IDS = {4, 36}


def load_fixture(name: str) -> list:
    data = json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return [
        OCRResult(
            text=item["text"],
            confidence=float(item["confidence"]),
            language=item["language"],
            bbox=item["bbox"],
        )
        for item in data
    ]


def sections_for(name: str) -> list:
    return extract_ingredient_sections(load_fixture(name))


def report_and_verdict(name: str, index: int = 0):
    matcher = IngredientMatcher()
    generator = VerdictGenerator()
    section = sections_for(name)[index]
    report = matcher.match_section(section)
    verdict = generator.assess(section, report, section_index=index)
    return section, report, verdict


class FakeSection:
    """Minimal section stand-in for verdict unit tests."""

    def __init__(self, text: str, flag=None, confidence: float = 0.99):
        self.text = text
        self.flag = flag
        self.heading = None
        self.language = "en"
        self.blocks = (
            [OCRResult(text="x", confidence=confidence, language="en", bbox=[0, 0, 10, 10])]
            if text else []
        )


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------


def test_created_reference_entries_are_marked_for_review():
    data = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    entries = {entry["id"]: entry for entry in data["ingredients"]}

    # Only the entries still awaiting supervisor confirmation stay unreviewed.
    unreviewed = {entry["id"] for entry in data["ingredients"]
                  if entry.get("reviewed") is False}
    assert unreviewed == {43, 44, 45, 209, 210, 211, 212, 213, 214, 215, 216}
    assert all(entries[entry_id]["reviewed"] is True
               for entry_id in entries if 101 <= entry_id <= 208)
    # Entry 42 "preservative" was removed: it is a function word (fw5),
    # not an ingredient.
    assert 42 not in entries
    assert all(entry["status"] in {"incompatible", "depends_on_origin", "compatible"}
               for entry in data["ingredients"])


def test_traditional_and_simplified_chinese_aliases_both_match():
    matcher = IngredientMatcher()
    for term in ("明膠", "明胶"):  # traditional and simplified
        report = matcher.match_text(term)
        # Reviewed resolution: gelatin (id 1) depends on its origin.
        assert any(f.matched_id == 1 and f.status == "depends_on_origin"
                   for f in report.findings), term


@pytest.mark.parametrize("text, entry_id, status", [
    ("食用香精", 41, "depends_on_origin"),
    ("食品用香精", 41, "depends_on_origin"),
    ("香精", 41, "depends_on_origin"),
    ("食用香精香料", 41, "depends_on_origin"),
    ("白砂糖", 20, "compatible"),
    ("砂糖", 20, "compatible"),
    ("食用盐", 22, "compatible"),
    ("食盐", 22, "compatible"),
    ("食用油脂制品", 208, "depends_on_origin"),
    ("bile acid", 15, "depends_on_origin"),
    ("硬脂酰乳酸钠", 109, "depends_on_origin"),
    ("硬脂酰乳酸钙", 109, "depends_on_origin"),
    ("乙酰磺胺酸钾", 203, "compatible"),
    ("氧化锌", 209, "compatible"),
    ("盐酸吡哆醇", 210, "compatible"),
    ("硝酸硫胺素", 211, "compatible"),
    ("烟酰胺", 212, "compatible"),
    ("还原铁", 213, "compatible"),
    ("食用植物油", 29, "compatible"),
])
def test_requested_reference_aliases_resolve(text, entry_id, status):
    findings = IngredientMatcher().match_text(text).findings
    assert any(f.matched_id == entry_id and f.status == status for f in findings)


def test_white_sugar_and_edible_salt_stay_recognized_together():
    report = IngredientMatcher().match_text("白砂糖，食用盐")
    findings = {finding.original_text: finding for finding in report.findings}

    assert findings["白砂糖"].matched_id == 20
    assert findings["白砂糖"].status == "compatible"
    assert findings["食用盐"].matched_id == 22
    assert findings["食用盐"].status == "compatible"
    assert report.unrecognized == []


def test_specific_soy_lecithin_wins_over_generic_lecithin():
    report = IngredientMatcher().match_text("大豆磷脂")
    matched = [finding for finding in report.findings if finding.is_matched]

    assert len(matched) == 1
    assert matched[0].matched_id == 31
    assert matched[0].status == "compatible"
    assert matched[0].reason == "Plant origin stated: soy."


@pytest.mark.parametrize("text", [
    "食用干酪",
    "干酪制品",
    "再制干酪",
    "芝士复合",
    "芝士风味",
    "芝士调味料",
])
def test_cjk_leftover_modifiers_are_not_unrecognized(text):
    report = IngredientMatcher().match_text(text)

    assert any(finding.matched_id == 127 for finding in report.findings)
    assert report.unrecognized == []


@pytest.mark.parametrize("text, expected_id", [
    ("食品添加剂（碳酸氢铵）", 214),
    ("additifs : lécithine de soja", 31),
    ("additives: soy lecithin", 31),
])
def test_additive_group_labels_are_dropped_but_contents_match(text, expected_id):
    report = IngredientMatcher().match_text(text)

    assert any(finding.status == "function_word" for finding in report.findings)
    assert any(finding.matched_id == expected_id for finding in report.findings)
    assert report.unrecognized == []


def test_parenthetical_vitamin_annotation_does_not_become_unrecognized():
    report = IngredientMatcher().match_text(
        "Niacinamide (Vitamin B3), Zinc Oxide (Vitamin B6), Thiamin Mononitrate (Vitamin B1)"
    )
    unrecognized = [u.original_text for u in report.unrecognized]
    assert not any(
        "vitamin" in text.lower() or text.strip("() ,.") in {"B3", "B6", "B1"}
        for text in unrecognized
    )
    assert {209, 210, 211, 212} <= {
        f.matched_id for f in report.findings if f.is_matched}

    zh_report = IngredientMatcher().match_text("烟酰胺（维生素B3）、氧化锌")
    assert {209, 212} <= {f.matched_id for f in zh_report.findings if f.is_matched}
    assert not any("维生素B3" in u.original_text for u in zh_report.unrecognized)


def test_umbrella_entries_added_without_overlapping_aliases():
    data = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    entries = {entry["id"]: entry for entry in data["ingredients"]}

    # Entry 30 "emulsifiers" was retired: it is a function word (fw6).
    assert 30 not in entries
    # The six umbrella drafts were added, overlapping aliases left off.
    for umbrella_id in (109, 113, 199, 201, 202, 204):
        assert umbrella_id in entries
    assert "monoglycerides" not in entries[109]["aliases"]
    assert "diglycerides" not in entries[109]["aliases"]
    # Entry 35 was retired; its generic codes belong to the umbrella entries.
    assert 35 not in entries
    assert "E100" in entries[199]["aliases"]
    assert "E200" in entries[201]["aliases"]
    assert "E400" in entries[202]["aliases"]


def test_e_numbers_resolve_to_their_new_owners():
    matcher = IngredientMatcher()

    def e_hit(text):
        return next(f for f in matcher.match_text(text).findings
                    if f.method == "e-number")

    assert e_hit("E471").matched_id == 109
    assert e_hit("E471").status == "depends_on_origin"
    assert e_hit("E322").matched_id == 113
    assert e_hit("E400").matched_id == 202
    assert e_hit("E400").status == "compatible"
    assert e_hit("E171").matched_id == 199
    assert e_hit("E171").status == "compatible"
    assert e_hit("E172").matched_id == 199


@pytest.mark.parametrize(
    "text", ["lecithin", "lécithine", "ليسيثين", "卵磷脂", "E322"],
)
def test_bare_lecithin_is_origin_dependent(text):
    """Bare lecithin resolves to draft 113 (origin not stated), not id 31."""
    matcher = IngredientMatcher()
    findings = [f for f in matcher.match_text(text).findings if f.is_matched]
    assert findings, text
    assert all(f.matched_id == 113 for f in findings), text
    assert all(f.status == "depends_on_origin" for f in findings)


@pytest.mark.parametrize(
    "text",
    ["lécithine de soja", "soy lecithin", "大豆磷脂", "大豆卵磷脂",
     "ليسيثين الصويا", "sunflower lecithin", "lécithine de tournesol"],
)
def test_named_origin_lecithin_stays_compatible(text):
    """Soy and sunflower lecithin stay compatible under id 31."""
    matcher = IngredientMatcher()
    findings = [f for f in matcher.match_text(text).findings if f.is_matched]
    assert any(f.matched_id == 31 and f.status == "compatible"
               for f in findings), text


def test_carmine_keeps_zh_chong_hong_and_plain_yan_zhi_hong_is_colours():
    data = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    entries = {entry["id"]: entry for entry in data["ingredients"]}

    # Id 2 keeps 胭脂虫红 / carmine / E120; 胭脂红 belongs to colours (199).
    assert entries[2]["names"]["zh"] == "胭脂虫红"
    assert "胭脂红" not in entries[2]["aliases"]

    matcher = IngredientMatcher()
    plain = [f for f in matcher.match_text("胭脂红").findings if f.is_matched]
    assert any(f.matched_id == 199 and f.status == "compatible" for f in plain)
    carmine = [f for f in matcher.match_text("胭脂虫红").findings if f.is_matched]
    assert any(f.matched_id == 2 for f in carmine)


# ---------------------------------------------------------------------------
# Normalization / splitting / E-numbers
# ---------------------------------------------------------------------------


def test_normalization_folds_accents_and_arabic_variants():
    assert normalize_text("INGRÉDIENTS") == "ingredients"
    assert normalize_text("أحمد") == normalize_text("احمد")
    assert "，" not in normalize_text("成分：蔗糖，植物油")
    assert normalize_text("Ｅ４７１") == "e471"


def test_split_arabic_and_chinese_punctuation():
    arabic = "سكر، ملح؛ ماء"
    assert split_ingredients(arabic) == ["سكر", "ملح", "ماء"]

    chinese = "蔗糖、植物油（棕櫚油）"
    assert split_ingredients(chinese) == ["蔗糖", "植物油", "棕櫚油"]


def test_extract_e_numbers():
    assert extract_e_numbers("Colorant : E171, E172 - E471.") == ["E171", "E172", "E471"]


# Real en/06 lines: the label prints the additive code without the E prefix.
EN06_COLOUR = "TEA EXTRACT, COLOUR (101)."
EN06_FLAVOUR = "FLAVOUR ENHANCER (627, 631), GLUCOSE, MUSHROOM, COLOUR (150C)."
EN06_ANTIOXIDANT = "ANTIOXIDANT (307B)), SEASONING (YEAST EXTRACT, SOY SAUCE,"


def test_bare_codes_after_function_word_become_e_numbers():
    """'COLOUR (101)' / 'FLAVOUR ENHANCER (627, 631)' -> E101 / E627, E631."""
    matcher = IngredientMatcher()

    assert prefix_additive_codes(EN06_FLAVOUR, matcher.function_words) == \
        "FLAVOUR ENHANCER (E627, E631), GLUCOSE, MUSHROOM, COLOUR (E150C)."
    assert prefix_additive_codes(EN06_COLOUR, matcher.function_words) == \
        "TEA EXTRACT, COLOUR (E101)."

    assert {"E627", "E631", "E150C"} <= set(matcher.match_text(EN06_FLAVOUR).e_numbers)
    assert "E101" in matcher.match_text(EN06_COLOUR).e_numbers
    assert "E307B" in matcher.match_text(EN06_ANTIOXIDANT).e_numbers


def test_mineral_salts_code_list_is_split_into_additives():
    """MINERAL SALTS (339, 452, 500, 501) -> four separate additive codes."""
    matcher = IngredientMatcher()
    text = "MINERAL SALTS (339, 452, 500, 501), GREEN TEA EXTRACT"

    assert prefix_additive_codes(text, matcher.function_words) == \
        "MINERAL SALTS (E339, E452, E500, E501), GREEN TEA EXTRACT"

    report = matcher.match_text(text)
    assert report.e_numbers == ["E339", "E452", "E500", "E501"]
    additives = [f for f in report.findings
                 if f.original_text in {"E339", "E452", "E500", "E501"}]
    assert len(additives) == 4
    assert all(f.is_matched for f in additives)


def test_bare_codes_without_function_word_are_left_alone():
    """A bracketed list after a non-function word is not turned into E-codes."""
    matcher = IngredientMatcher()
    text = "PREMIX (339, 452, 500, 501), GREEN TEA EXTRACT"

    assert prefix_additive_codes(text, matcher.function_words) == text
    assert "E339" not in matcher.match_text(text).e_numbers


def test_e_number_matching():
    matcher = IngredientMatcher()

    gelatin = [f for f in matcher.match_text("E441").findings if f.method == "e-number"][0]
    # Reviewed resolution: gelatin (id 1) depends on its origin.
    assert gelatin.status == "depends_on_origin"
    assert gelatin.matched_id == 1

    emulsifier = [f for f in matcher.match_text("E471").findings if f.method == "e-number"][0]
    assert emulsifier.status == "depends_on_origin"

    unknown = matcher.match_text("E999")
    assert any(f.original_text == "E999" and f.status == "unrecognized" for f in unknown.findings)


# ---------------------------------------------------------------------------
# Negation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Sans alcool",
        "Alcohol free",
        "Alcohol-free",
        "خالي من الكحول",
        "不含酒精",
    ],
)
def test_alcohol_negation_does_not_match_alcohol_entry(text):
    matcher = IngredientMatcher()
    report = matcher.match_text(text)

    assert is_negated_alcohol(text)
    assert not any(f.matched_id in ALCOHOL_IDS for f in report.findings)
    assert not any(f.status == "incompatible" for f in report.findings)


def test_negation_mixed_with_real_ingredients():
    matcher = IngredientMatcher()
    report = matcher.match_text("Sans alcool, sucre, gélatine de porc")

    assert not any(f.matched_id in ALCOHOL_IDS for f in report.findings)
    assert any(f.matched_name == "sucre" for f in report.findings)
    assert any(f.status == "incompatible" for f in report.findings)


def test_fr_fixture_has_no_alcohol_finding():
    section = sections_for("label-fr")[0]
    report = IngredientMatcher().match_section(section)

    assert "Sans alcool" not in section.text
    assert not any(f.matched_id in ALCOHOL_IDS for f in report.findings)


# ---------------------------------------------------------------------------
# Verdict rules
# ---------------------------------------------------------------------------


def test_clear_verdict_only_compatible():
    matcher = IngredientMatcher()
    section = FakeSection("sel")
    verdict = VerdictGenerator().assess(section, matcher.match_section(section))

    assert verdict.verdict == VERDICT_CLEAR
    assert verdict.reasons
    assert verdict.reasons[-1] == "No incompatible ingredient found in the reference"
    assert verdict.disclaimer == DISCLAIMER


def test_incompatible_verdict():
    matcher = IngredientMatcher()
    section = FakeSection("gélatine de porc")
    verdict = VerdictGenerator().assess(section, matcher.match_section(section))

    assert verdict.verdict == VERDICT_INCOMPATIBLE
    assert any("Incompatible ingredient" in reason for reason in verdict.reasons)
    assert verdict.incompatible_ingredients


def test_depends_on_origin_verdict():
    matcher = IngredientMatcher()
    section = FakeSection("glycérol")
    verdict = VerdictGenerator().assess(section, matcher.match_section(section))

    assert verdict.verdict == VERDICT_TO_VERIFY
    assert any("Depends on origin" in reason for reason in verdict.reasons)


def test_cheese_is_compatible_but_animal_rennet_still_needs_verification():
    matcher = IngredientMatcher()

    cheese = FakeSection("fromage")
    cheese_report = matcher.match_section(cheese)
    assert [f.status for f in cheese_report.findings] == ["compatible"]
    assert VerdictGenerator().assess(cheese, cheese_report).verdict == VERDICT_CLEAR

    mixed = FakeSection("fromage, présure animale")
    mixed_report = matcher.match_section(mixed)
    assert {f.status for f in mixed_report.findings} == {
        "compatible", "depends_on_origin",
    }
    assert VerdictGenerator().assess(mixed, mixed_report).verdict == VERDICT_TO_VERIFY

    enzymes = FakeSection("enzymes")
    assert {f.status for f in matcher.match_section(enzymes).findings} == {
        "depends_on_origin",
    }


def test_inline_heading_section_is_readable_not_empty():
    from types import SimpleNamespace

    matcher = IngredientMatcher()
    section = SimpleNamespace(
        text="fromage frais, sel", blocks=[],
        heading=SimpleNamespace(confidence=0.94), flag=None, language="fr")

    verdict = VerdictGenerator().assess(section, matcher.match_section(section))

    assert verdict.verdict == VERDICT_CLEAR
    assert "Empty ingredients section" not in verdict.reasons
    assert verdict.overall_confidence == 0.94


def test_unrecognized_real_ingredient_forces_to_verify():
    matcher = IngredientMatcher()
    section = FakeSection("sel, xyzabc")
    report = matcher.match_section(section)
    verdict = VerdictGenerator().assess(section, report)

    # Salt is compatible but xyzabc is a real ingredient not in the reference.
    assert verdict.verdict == VERDICT_TO_VERIFY
    assert "xyzabc" in verdict.unrecognized_ingredients
    assert any("Not in the reference: xyzabc" in reason for reason in verdict.reasons)
    assert NOT_EVALUATED_LABEL == "Not in the reference (not evaluated)"


def test_function_word_and_group_label_do_not_count_as_unrecognized():
    matcher = IngredientMatcher()
    section = FakeSection("食品添加剂（碳酸氢铵）")
    report = matcher.match_section(section)
    verdict = VerdictGenerator().assess(section, report)

    assert report.unrecognized == []
    assert verdict.verdict == VERDICT_CLEAR
    assert not any("Not in the reference" in reason for reason in verdict.reasons)


def test_incompatible_wins_over_unrecognized():
    matcher = IngredientMatcher()
    section = FakeSection("gélatine de porc, xyzabc")
    report = matcher.match_section(section)
    verdict = VerdictGenerator().assess(section, report)

    assert verdict.verdict == VERDICT_INCOMPATIBLE
    assert "xyzabc" in verdict.unrecognized_ingredients


def test_low_confidence_verdict():
    matcher = IngredientMatcher()
    section = FakeSection("sel", confidence=0.50)
    verdict = VerdictGenerator(confidence_threshold=0.85).assess(section, matcher.match_section(section))

    assert verdict.verdict == VERDICT_TO_VERIFY
    assert any("Low OCR confidence" in reason for reason in verdict.reasons)


def test_no_heading_and_multiple_products_flags():
    matcher = IngredientMatcher()

    no_heading = FakeSection("sel", flag="no_heading")
    verdict = VerdictGenerator().assess(no_heading, matcher.match_section(no_heading))
    assert verdict.verdict == VERDICT_TO_VERIFY
    assert "Ingredients list not found or unreadable — retake the photo" in verdict.reasons

    # Multiple products is reported, but the verdict still follows the
    # reference (salt is compatible -> clear).
    multiple = FakeSection("sel", flag="multiple_products")
    verdict = VerdictGenerator().assess(multiple, matcher.match_section(multiple))
    assert verdict.verdict == VERDICT_CLEAR
    assert "Multiple products detected" in verdict.reasons


def test_empty_section_verdict():
    matcher = IngredientMatcher()
    section = FakeSection("")
    verdict = VerdictGenerator().assess(section, matcher.match_section(section))

    assert verdict.verdict == VERDICT_TO_VERIFY
    assert "Empty ingredients section" in verdict.reasons


def test_all_ingredients_recognised_is_clear():
    matcher = IngredientMatcher()
    # sucre / sel / fromage are all in the reference -> coverage 1.0.
    section = FakeSection("sucre, sel, fromage")
    verdict = VerdictGenerator().assess(section, matcher.match_section(section))

    assert verdict.verdict == VERDICT_CLEAR
    assert not any("are in the reference" in reason for reason in verdict.reasons)


def test_low_coverage_triggers_a_verifier():
    matcher = IngredientMatcher()
    # Only 1 of 4 segments is in the reference -> coverage 0.25 < 0.50.
    section = FakeSection("sel, aaa, bbb, ccc")
    report = matcher.match_section(section)
    verdict = VerdictGenerator().assess(section, report)

    assert verdict.verdict == VERDICT_TO_VERIFY
    assert "Only 1 of 4 ingredients are in the reference" in verdict.reasons


def test_incompatible_wins_over_low_coverage():
    matcher = IngredientMatcher()
    # Only 1 of 4 recognised, but that one is incompatible -> incompatible wins.
    section = FakeSection("gélatine de porc, aaa, bbb, ccc")
    report = matcher.match_section(section)
    verdict = VerdictGenerator().assess(section, report)

    assert verdict.verdict == VERDICT_INCOMPATIBLE
    assert any("Incompatible ingredient" in reason for reason in verdict.reasons)
    assert verdict.incompatible_ingredients


def test_verdict_never_claims_halal_or_certification():
    matcher = IngredientMatcher()
    section = FakeSection("sel")
    verdict = VerdictGenerator().assess(section, matcher.match_section(section))

    for message in [verdict.verdict] + verdict.reasons:
        assert "halal" not in message.lower()
        assert "certified" not in message.lower() and "certification" not in message.lower()
    assert verdict.disclaimer == "Aid to verification, not a halal certification."


# ---------------------------------------------------------------------------
# Real fixtures
# ---------------------------------------------------------------------------


def test_label_fr_verdict_and_reasons():
    section, report, verdict = report_and_verdict("label-fr")

    assert len(sections_for("label-fr")) == 1
    assert verdict.verdict == VERDICT_TO_VERIFY
    assert verdict.disclaimer == DISCLAIMER
    assert section.flag is None

    reasons = "\n".join(verdict.reasons)
    assert "E471" in reasons
    assert "Glycérol" in reasons
    assert "Arômes" in reasons

    assert not any(f.status == "incompatible" for f in report.findings)
    assert any(f.matched_name == "E471" and f.method == "e-number"
               for f in report.findings)
    assert any(f.matched_name == "glycérol" and f.status == "depends_on_origin"
               for f in report.findings)
    assert any(f.matched_name == "arômes" and f.status == "depends_on_origin"
               for f in report.findings)


def test_label_zh_verdict_and_reasons():
    section, report, verdict = report_and_verdict("label-zh")

    assert verdict.verdict == VERDICT_TO_VERIFY
    reasons = "\n".join(verdict.reasons)

    # 乳化劑 is a function word (fw6), not an ingredient: it introduces the
    # substances that follow and is judged through them.
    emulsifier = next((f for f in report.findings if f.original_text == "乳化劑"), None)
    assert emulsifier is not None
    assert emulsifier.status == "function_word"
    # Substances are named in this section, so no verification reason for it.
    assert not emulsifier.needs_verification
    assert "乳化劑" not in reasons

    for ingredient in ("香料", "乳清粉"):
        finding = next((f for f in report.findings if f.original_text == ingredient), None)
        assert finding is not None, ingredient
        assert finding.status == "depends_on_origin", ingredient
        assert finding.method == "substring", ingredient
        assert ingredient in reasons

    # The product-name line ("品名...") must not leak into the match report.
    assert "品名" not in report.text
    assert not any("品名" in f.original_text for f in report.findings)


def test_label_ar_verdict_and_reasons():
    section, report, verdict = report_and_verdict("label-ar")

    assert verdict.verdict == VERDICT_TO_VERIFY
    reasons = "\n".join(verdict.reasons)

    flavour = next((f for f in report.findings if f.matched_name == "نكهات"), None)
    # OCR glues the function word to the substance: "حمض الستريك مادة حافظة".
    preservative = next(
        (f for f in report.findings
         if f.status == "function_word" and "حافظ" in f.original_text), None)

    assert flavour is not None and flavour.status == "depends_on_origin"
    assert "نكهات" in reasons

    # مادة حافظة is a function word (fw5), not an ingredient: with named
    # substances on the label it stays silent.
    assert preservative is not None
    assert not preservative.needs_verification
    assert "مادة حافظة" not in reasons

    # Same status vocabulary as the English sections for the same kind of entry.
    assert {f.status for f in report.findings} <= {
        "incompatible", "depends_on_origin", "compatible", "unrecognized", "negated",
        "function_word", "allergen_note",
    }


def test_label_en_three_sections_one_verdict_each():
    sections = sections_for("label-en")
    matcher = IngredientMatcher()
    generator = VerdictGenerator()

    assert len(sections) == 3
    verdicts = [
        generator.assess(section, matcher.match_section(section), section_index=index)
        for index, section in enumerate(sections)
    ]

    assert len(verdicts) == 3
    for index, (section, verdict) in enumerate(zip(sections, verdicts)):
        assert section.flag == "multiple_products"
        assert verdict.verdict == VERDICT_TO_VERIFY
        assert "Multiple products detected" in verdict.reasons
        assert verdict.section_index == index
        assert verdict.reasons
        assert any(f.status == "depends_on_origin" for f in matcher.match_section(section).findings)


class TestSegmentCoverage:
    """A segment explained by only a small share of matches keeps its leftovers.

    PaddleOCR drops the commas of space-delimited scripts, so several
    ingredients arrive fused into one segment; a single alias match ("ملح")
    must not hide the unknown words next to it.
    """

    def test_fused_arabic_segment_reports_leftovers(self):
        report = IngredientMatcher().match_text(
            "حبات الخريل خل المائدة ملح مادة حافظة E224 ومضاد الأكسدة E330")

        assert report.unrecognized, "the garbled ingredient must not be hidden"
        assert any("حبات" in f.original_text for f in report.unrecognized)

    @pytest.mark.parametrize("text", [
        "sel de Guérande",
        "huile de palme",
        "sea salt",
        "palm oil",
    ])
    def test_known_segment_with_qualifier_stays_recognized(self, text):
        report = IngredientMatcher().match_text(text)

        assert report.unrecognized == []
        assert any(f.is_matched for f in report.findings)

    def test_fused_latin_segment_reports_leftovers(self):
        report = IngredientMatcher().match_text(
            "salt sugar dragonfruit lychee extract")

        assert any("dragonfruit" in f.original_text for f in report.unrecognized)

    def test_fully_matched_long_segment_stays_recognized(self):
        report = IngredientMatcher().match_text("wheat flour, sugar, salt, palm oil")

        assert report.unrecognized == []

    def test_mustard_seed_is_in_the_reference(self):
        report = IngredientMatcher().match_text("حبات الخردل")

        assert report.unrecognized == []
        assert any(f.matched_id == 216 for f in report.findings)
