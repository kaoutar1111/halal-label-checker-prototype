"""Regression tests for the real zh-label run: language filtering, CJK leftovers, reasons."""

import json
from pathlib import Path

import pytest
from PIL import Image

from src.matcher import IngredientMatcher, is_negated_alcohol
from src.ocr import (
    AUTO_LANGUAGES,
    MIN_RESULT_CONFIDENCE,
    MultiLanguageOCR,
    OCRResult,
    dominant_script,
    filter_results,
    is_garbage_text,
    language_for_text,
    matches_model_script,
)
from src.sections import extract_ingredient_sections
from src.verdict import VERDICT_TO_VERIFY, VerdictGenerator

FIXTURES_DIR = Path(__file__).parent / "fixtures"
REFERENCE_PATH = Path(__file__).parent.parent / "data" / "reference.json"


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


def report_and_verdict(name: str, index: int = 0):
    sections = extract_ingredient_sections(load_fixture(name))
    section = sections[index]
    report = IngredientMatcher().match_section(section)
    verdict = VerdictGenerator().assess(section, report, section_index=index)
    return section, report, verdict


class FakeSharedEngine:
    """Engine that runs detection once and returns prepared per-language reads."""

    name = "FakeShared"
    supported_languages = ["ar", "fr", "en", "zh"]

    def __init__(self, boxes, per_language):
        self.boxes = boxes
        self.per_language = per_language
        self.detect_calls = 0

    def detect_boxes(self, image):
        self.detect_calls += 1
        return [list(box) for box in self.boxes]

    def recognize_boxes(self, image, boxes, language):
        return [dict(item) for item in self.per_language.get(language, [])]


def test_detection_runs_once_and_wrong_language_garbage_is_dropped():
    boxes = [[10, 10, 300, 40], [10, 50, 300, 80]]
    per_language = {
        # Wrong-script reads (digits/punctuation only) must never be merged
        "ar": [
            {"text": "11(", "confidence": 0.97, "bbox": boxes[0]},
            {"text": "*#L", "confidence": 0.96, "bbox": boxes[1]},
        ],
        "zh": [
            {"text": "成分", "confidence": 0.93, "bbox": boxes[0]},
            {"text": "|||", "confidence": 0.95, "bbox": boxes[1]},
        ],
        "fr": [
            {"text": "##L", "confidence": 0.98, "bbox": boxes[0]},
            {"text": "Sucres, arômes", "confidence": 0.97, "bbox": boxes[1]},
        ],
    }

    fake = FakeSharedEngine(boxes, per_language)
    ocr = MultiLanguageOCR()
    ocr._get_engine = lambda: fake

    results = ocr.process_image(Image.new("RGB", (400, 120)), auto=True)

    assert fake.detect_calls == 1, "text detection must run only once"
    assert len(results) == 2
    texts = " ".join(r.text for r in results)
    assert "11(" not in texts
    assert "*#L" not in texts
    assert "##L" not in texts
    assert "|||" not in texts
    assert "成分" in texts

    languages = {r.language for r in results}
    # Language is now decided per image (dominant script + image words): the
    # CJK read stays as text but every block reports the image language.
    assert languages == {"fr"}, "one language per image"
    assert all(r.confidence >= MIN_RESULT_CONFIDENCE for r in results)


@pytest.mark.parametrize("text", ["B1),", "B3),", "(B6),", "E471"])
@pytest.mark.parametrize("language", ["en", "fr", "latin"])
def test_short_code_blocks_are_latin_not_script_mismatches(text, language):
    """Digits, punctuation and parentheses are script-neutral."""
    assert dominant_script(text) == "latin"
    assert matches_model_script(text, language) is True
    kept = filter_results([OCRResult(text, 0.95, language, [0, 0, 10, 10])])
    assert [r.text for r in kept] == [text]


def test_symbol_soup_without_readable_word_is_garbage_not_a_script_mismatch():
    for text in ("*#L", "##L", "11("):
        # Three or fewer Latin letters are never a script mismatch...
        assert matches_model_script(text, "en") is True
        # ...but symbol soup is still dropped as OCR garbage.
        assert is_garbage_text(text) is True
        assert filter_results([OCRResult(text, 0.95, "en", [0, 0, 10, 10])]) == []


def test_filter_results_rejects_wrong_script_and_low_confidence():
    results = [
        OCRResult("成分", 0.93, "zh", [0, 0, 10, 10]),
        OCRResult("11(", 0.97, "en", [0, 0, 10, 10]),
        OCRResult("*#L", 0.96, "fr", [0, 0, 10, 10]),
        OCRResult("Sugar", 0.99, "ar", [0, 0, 10, 10]),
        OCRResult("蔗糖", 0.50, "zh", [0, 0, 10, 10]),
    ]

    kept = filter_results(results)

    assert [r.text for r in kept] == ["成分"]
    assert dominant_script("11(") is None
    assert matches_model_script("Sugar", "ar") is False
    assert language_for_text("Sucres, arômes") == "fr"
    assert language_for_text("Sugar") == "en"


def test_zh_fixture_has_no_garbage_and_no_low_confidence():
    results = load_fixture("label-zh")
    garbage = [
        OCRResult("*#L", 0.96, "en", [10, 10, 120, 30]),
        OCRResult("11(", 0.97, "ar", [10, 40, 120, 60]),
    ]

    cleaned = filter_results(results + garbage)
    assert all(r.text not in {"*#L", "11("} for r in cleaned)

    sections = extract_ingredient_sections(cleaned)
    assert len(sections) == 1
    section = sections[0]
    report = IngredientMatcher().match_section(section)
    verdict = VerdictGenerator().assess(section, report)

    assert "*#L" not in section.text
    assert "11(" not in section.text
    assert verdict.verdict == VERDICT_TO_VERIFY
    assert verdict.overall_confidence >= 0.85
    assert "Low OCR confidence" not in "\n".join(verdict.reasons)


def test_zh_cjk_matching_reports_only_leftover_text():
    matcher = IngredientMatcher()
    report = matcher.match_text(
        "乳化劑 (脂肪酸丙二醇酯 脂肪酸山梨醇酐酯)抗氧化劑 (混合濃縮生育醇)"
    )

    matched_ids = {f.matched_id for f in report.findings if f.is_matched}
    assert {44, 45, 46} <= matched_ids

    unrecognized = [u.original_text for u in report.unrecognized]
    assert "脂肪酸丙二醇酯" not in unrecognized
    assert "脂肪酸山梨醇酐酯" not in unrecognized
    assert "混合濃縮生育醇" not in unrecognized
    # 抗氧化劑 is a function word (fw7), not an ingredient or a leftover.
    assert "抗氧化劑" not in unrecognized
    assert any(f.status == "function_word" and f.original_text == "抗氧化劑"
               for f in report.findings)

    # No glued unmatched strings containing a matched ingredient
    for leftover in unrecognized:
        assert not ("脂肪酸丙二醇酯" in leftover and "脂肪酸山梨醇酐酯" in leftover)
        assert "脂肪酸丙二醇酯" not in leftover
        assert "脂肪酸山梨醇酐酯" not in leftover


def test_zh_fixture_has_no_glued_unrecognized_ingredients():
    section, report, verdict = report_and_verdict("label-zh")

    leftovers = [u.original_text for u in report.unrecognized]
    assert "脂肪酸丙二醇酯 脂肪酸山梨醇酐酯" not in leftovers
    for leftover in leftovers:
        assert not ("脂肪酸丙二醇酯" in leftover and "脂肪酸山梨醇酐酯" in leftover)

    assert {f.matched_id for f in report.findings if f.is_matched} >= {41, 43, 44, 45, 46}
    assert "Low OCR confidence" not in "\n".join(verdict.reasons)


def test_reasons_do_not_repeat_the_same_text():
    section, report, verdict = report_and_verdict("label-zh")
    reasons = "\n".join(verdict.reasons)

    assert "蔗糖 (蔗糖)" not in reasons
    # Sugar is now reviewed "compatible": no reason line for it at all.
    assert "蔗糖" not in reasons
    assert "Depends on origin: 乳清粉" in reasons
    assert "乳清粉 (乳清粉)" not in reasons
    assert "乳化劑 (乳化劑)" not in reasons

    section_fr, report_fr, verdict_fr = report_and_verdict("label-fr")
    reasons_fr = "\n".join(verdict_fr.reasons)
    assert "Glycérol (Glycérol)" not in reasons_fr
    assert "glycérol (Glycérol)" not in reasons_fr
    assert "E471 (E471)" not in reasons_fr


def test_new_reference_entries_are_marked_for_review():
    data = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    entries = {entry["id"]: entry for entry in data["ingredients"]}

    # Entry 42 "preservative" was removed (function word fw5, not an ingredient).
    assert 42 not in entries
    # Phase-C creations not covered by the validated merge stay unreviewed;
    # the supervisor-approved entries (including 41) are reviewed.
    for entry_id in (43, 44, 45):
        assert entries[entry_id]["reviewed"] is False
        assert entries[entry_id]["status"] == "depends_on_origin"
    assert entries[41]["reviewed"] is True
    assert entries[41]["status"] == "depends_on_origin"

    assert entries[44]["names"]["zh"] == "脂肪酸丙二醇酯"
    assert "E477" in entries[44]["aliases"]
    assert {"E491", "E492", "E493", "E494", "E495"} <= set(entries[45]["aliases"])
    # Entry 46 was validated in the merge: compatible and reviewed.
    assert entries[46]["status"] == "compatible"
    assert entries[46]["reviewed"] is True
    assert entries[46]["names"]["zh"] == "混合濃縮生育醇"
    assert "E306" in entries[46]["aliases"]


def test_negation_still_works_in_cjk_paths():
    matcher = IngredientMatcher()

    for text in ("不含酒精", "不含乙醇", "無酒精"):
        assert is_negated_alcohol(text)
        report = matcher.match_text(text)
        assert not any(f.matched_id in {4, 36} for f in report.findings)

    # A negation next to real ingredients must not hide the real ones
    report = matcher.match_text("不含酒精、蔗糖")
    assert any(f.matched_id == 20 for f in report.findings)
