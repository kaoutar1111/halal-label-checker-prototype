"""
Tests for mixed-script merging (Arabic + Latin passes over one image).

All OCRResults are hand-made with bboxes in the PaddleOCR `rec_boxes` format:
    [x0, y0, x1, y1]
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ocr import (
    OCRResult,
    bbox_iou,
    bbox_to_rect,
    detect_script,
    merge_multiscript_results,
)


def mk(text, x0, y0, x1, y1, lang="ar", conf=0.9):
    """Build an OCRResult with a flat [x0, y0, x1, y1] bbox."""
    return OCRResult(text=text, confidence=conf, language=lang, bbox=[x0, y0, x1, y1])


class TestScriptDetection:
    def test_arabic(self):
        assert detect_script("سكر") == "ar"

    def test_latin(self):
        assert detect_script("Sugar") == "latin"

    def test_digits_only_is_other(self):
        assert detect_script("12345") == "other"

    def test_mixed_mostly_arabic(self):
        # 12 Arabic letters vs 5 Latin letters -> Arabic wins
        assert detect_script("المكونات سكر") == "ar"


class TestBboxGeometry:
    def test_flat_bbox_is_xyxy(self):
        # NOT [x, y, w, h]: y1=60 must stay a coordinate, not a height
        assert bbox_to_rect([10, 20, 110, 60]) == (10.0, 20.0, 110.0, 60.0)

    def test_four_corner_bbox(self):
        bbox = [[10, 20], [110, 20], [110, 60], [10, 60]]
        assert bbox_to_rect(bbox) == (10.0, 20.0, 110.0, 60.0)

    def test_iou_identical(self):
        assert bbox_iou([10, 20, 110, 60], [10, 20, 110, 60]) == pytest.approx(1.0)

    def test_iou_disjoint(self):
        assert bbox_iou([0, 0, 10, 10], [20, 20, 30, 30]) == pytest.approx(0.0)


class TestMerge:
    def test_keeps_arabic_over_latin_garbage(self):
        ar = [mk("سكر", 0, 0, 100, 40, lang="ar", conf=0.92)]
        latin = [mk("ouds", 1, 1, 99, 41, lang="latin", conf=0.55)]

        merged = merge_multiscript_results(ar, latin)

        assert len(merged) == 1
        assert merged[0].text == "سكر"
        assert merged[0].language == "ar"

    def test_keeps_latin_over_arabic_garbage(self):
        ar = [mk("ىىىى", 300, 0, 400, 40, lang="ar", conf=0.50)]
        latin = [mk("Sugar", 300, 0, 400, 40, lang="latin", conf=0.95)]

        merged = merge_multiscript_results(ar, latin)

        assert len(merged) == 1
        assert merged[0].text == "Sugar"
        assert merged[0].language == "latin"

    def test_disjoint_boxes_are_all_kept(self):
        ar = [mk("سكر", 0, 0, 100, 40, lang="ar")]
        latin = [mk("Sugar", 200, 0, 300, 40, lang="latin")]

        merged = merge_multiscript_results(ar, latin)

        assert len(merged) == 2
        assert {r.text for r in merged} == {"سكر", "Sugar"}

    def test_only_one_pass_returns_its_results(self):
        merged = merge_multiscript_results([mk("سكر", 0, 0, 100, 40)], [])
        assert len(merged) == 1

    def test_low_overlap_is_not_merged(self):
        ar = [mk("سكر", 0, 0, 100, 40, lang="ar")]
        latin = [mk("Sugar", 95, 0, 195, 40, lang="latin")]

        merged = merge_multiscript_results(ar, latin)

        assert len(merged) == 2

    def test_merged_output_is_in_reading_order(self):
        # Two Arabic boxes on the same line: rightmost must come first (RTL)
        ar = [mk("ملح", 0, 0, 100, 40, lang="ar")]
        latin = [mk("سكر", 200, 0, 300, 40, lang="ar")]

        merged = merge_multiscript_results(ar, latin)

        assert [r.text for r in merged] == ["سكر", "ملح"]
