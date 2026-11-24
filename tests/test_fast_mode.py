"""
Tests for FAST_MODE: language-first probe, batched recognition, image cache.

No real model is loaded: a stub engine answers the probe and the full pass.
"""

import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.engines.paddleocr_engine import PaddleOCREngine
from src.ocr import FAST_MODE, MultiLanguageOCR


class StubEngine:
    """Polygon engine returning fixed texts per language."""

    name = "StubOCR"
    supported_languages = ["ar", "fr", "zh"]

    def __init__(self, reads, confidences=None):
        self.reads = reads
        self.confidences = confidences or {}
        self.detect_calls = 0
        self.recognize_calls = []

    def is_available(self):
        return True

    def detect_polygons(self, image):
        self.detect_calls += 1
        return [_polygon_for(i) for i in range(12)]

    def recognize_polygons(self, image, polygons, language):
        self.recognize_calls.append((language, len(polygons)))
        texts = self.reads.get(language, [])
        confidence = self.confidences.get(language, 0.9)
        reads = []
        for poly in polygons:
            # Keyed by the box position, so a probe subset and the full page
            # return the same read for the same box (like the real engine).
            index = int(round(float(poly[0][0]) / 40))
            reads.append({
                "text": texts[index] if index < len(texts) else "",
                "confidence": confidence,
                "bbox": [0.0, 0.0, 30.0, 20.0],
            })
        return reads


def make_ocr(reads, confidences=None, **kwargs):
    # The no-heading retry is covered by its own tests; the stub pages here have
    # no label, so keep it off to count the fast-mode calls exactly.
    kwargs.setdefault("retry_no_heading", False)
    ocr = MultiLanguageOCR(fast_mode=True, **kwargs)
    ocr._engine = StubEngine(reads, confidences)
    ocr._engine_name = "StubOCR"
    return ocr


def blank_image():
    return Image.new("RGB", (120, 60), "white")


class TestFastModeSetting:
    def test_default_is_on(self):
        assert MultiLanguageOCR().fast_mode is FAST_MODE
        assert FAST_MODE is True  # env var not set in the test environment

    def test_can_be_disabled_per_instance(self):
        assert MultiLanguageOCR(fast_mode=True).fast_mode is True
        assert MultiLanguageOCR(fast_mode=False).fast_mode is False


class TestLanguageProbe:
    def test_clear_winner_runs_one_model(self):
        ocr = make_ocr({
            "fr": ["Lait", "Sucre", "Sel", "Eau"],
            "ar": ["", "", "", ""],
        })

        results = ocr.process_image(blank_image(), auto=True)

        assert ocr.last_probe_language == "fr"
        assert ocr.last_strategy == "language_first:fr"
        # Probe: every model on 6 boxes. Full pass: fr on the other 6 only.
        assert ("ar", 6) in ocr._engine.recognize_calls
        assert ("zh", 6) in ocr._engine.recognize_calls
        assert ("fr", 6) in ocr._engine.recognize_calls
        # The probed boxes are reused: fr reads 12 boxes in two calls of 6.
        fr_boxes = sum(size for lang, size in ocr._engine.recognize_calls
                       if lang == "fr")
        assert fr_boxes == 12
        assert [r.text for r in results] == ["Lait", "Sucre", "Sel", "Eau"]

    def test_bilingual_label_keeps_both_scripts(self):
        ocr = make_ocr({
            "ar": ["حليب", "سكر", "ملح", "ماء"],
            "fr": ["Lait", "Sucre", "Sel", "Eau"],
            "zh": ["", "", "", ""],
        })

        ocr.process_image(blank_image(), auto=True)

        # Both scripts read >= 2 probe boxes: keep both, drop the silent one.
        assert ocr.last_probe_language == "ar+fr"
        assert ocr.last_strategy == "language_first:ar+fr"
        for lang in ("ar", "fr"):
            boxes = sum(size for name, size in ocr._engine.recognize_calls
                        if name == lang)
            assert boxes == 12  # 6 probe + 6 remaining
        # zh only ran the probe, never the full page.
        assert all(size == 6 for lang, size in ocr._engine.recognize_calls
                   if lang == "zh")

    def test_no_confident_probe_reads_falls_back(self):
        ocr = make_ocr({"ar": [""] * 4, "fr": [""] * 4, "zh": [""] * 4})

        ocr.process_image(blank_image(), auto=True)

        assert ocr.last_strategy == "language_first:all"

    def test_probe_reads_at_most_six_boxes(self):
        ocr = make_ocr(
            {"fr": ["Lait"] * 6, "ar": [""] * 6, "zh": [""] * 6},
            probe_boxes=3,
        )

        ocr.process_image(blank_image(), auto=True)

        probe_sizes = [size for lang, size in ocr._engine.recognize_calls if size == 3]
        assert probe_sizes, "probe must run on at most probe_boxes boxes"

    def test_small_page_skips_probe(self):
        # 12 boxes <= probe_boxes(10) + 2 -> probing would cost a full pass.
        ocr = make_ocr(
            {"fr": ["Lait"] * 12, "ar": [""] * 12, "zh": [""] * 12},
            probe_boxes=10,
        )

        ocr.process_image(blank_image(), auto=True)

        assert ocr.last_strategy == "language_first:all"
        assert all(size == 12 for _, size in ocr._engine.recognize_calls)


    def test_single_foreign_box_does_not_force_all(self):
        ocr = make_ocr(
            {
                "fr": ["Lait", "Sucre", "Sel", "Eau"],
                "ar": ["حليب"],  # one confident Arabic box, not a bilingual label
                "zh": [""],
            },
            confidences={"ar": 0.7},
        )

        ocr.process_image(blank_image(), auto=True)

        assert ocr.last_strategy == "language_first:fr"


class TestBatchedRecognition:
    def test_batches_preserve_crop_order(self):
        class FakeRecognizer:
            def __init__(self):
                self.batch_sizes = []

            def predict(self, crops):
                self.batch_sizes.append(len(crops))
                return [
                    {"rec_text": str(crop.shape[1]), "rec_score": 0.9}
                    for crop in crops
                ]

        widths = [10, 200, 30, 40, 5]
        crops = [np.zeros((4, width, 3), dtype=np.uint8) for width in widths]

        engine = PaddleOCREngine()
        engine.recognition_batch_size = 2
        recognizer = FakeRecognizer()

        results = engine._run_recognizer(recognizer, crops, "fr")

        assert [item["text"] for item in results] == ["10", "200", "30", "40", "5"]
        assert recognizer.batch_sizes == [2, 2, 1]

    def test_batch_size_zero_keeps_one_call(self):
        class FakeRecognizer:
            def __init__(self):
                self.calls = 0

            def predict(self, crops):
                self.calls += 1
                return [{"rec_text": "x", "rec_score": 0.9} for _ in crops]

        recognizer = FakeRecognizer()
        engine = PaddleOCREngine()
        crops = [np.zeros((4, 10, 3), dtype=np.uint8) for _ in range(5)]

        engine._run_recognizer(recognizer, crops, "fr")

        assert recognizer.calls == 1


class TestImageCache:
    def test_second_call_uses_cache(self):
        ocr = make_ocr({"fr": ["Lait", "Sucre", "Sel", "Eau"]})
        image = blank_image()

        first = ocr.process_image(image, auto=True)
        strategy_first = ocr.last_strategy
        calls_after_first = len(ocr._engine.recognize_calls)
        second = ocr.process_image(image, auto=True)

        assert ocr._engine.detect_calls == 1
        assert len(ocr._engine.recognize_calls) == calls_after_first
        assert strategy_first == "language_first:fr"
        assert ocr.last_strategy == "cache:language_first:fr"
        assert [r.text for r in first] == [r.text for r in second]

    def test_cached_results_are_copies(self):
        ocr = make_ocr({"fr": ["Lait", "Sucre", "Sel", "Eau"]})
        image = blank_image()

        first = ocr.process_image(image, auto=True)
        first[0].text = "MUTATED"
        second = ocr.process_image(image, auto=True)

        assert second[0].text == "Lait"

    def test_cache_is_off_when_fast_mode_is_off(self):
        ocr = MultiLanguageOCR(fast_mode=False, retry_no_heading=False)
        stub = StubEngine({"fr": ["Lait"] * 4})
        ocr._engine = stub
        ocr._engine_name = "StubOCR"
        image = blank_image()

        ocr.process_image(image, auto=True)
        ocr.process_image(image, auto=True)

        assert stub.detect_calls == 2


def _polygon_for(index: int):
    """Distinct polygons so a stub can return the text that belongs to a box."""
    x = index * 40
    return np.array([[x, 0], [x + 30, 0], [x + 30, 20], [x, 20]], dtype=np.float32)


class _TextEngine:
    """Answers with the text list of the most recent detection."""

    name = "StubOCR"
    supported_languages = ["ar", "fr", "zh"]

    def __init__(self):
        self.current = []

    def is_available(self):
        return True

    def _reads(self, polygons, language):
        reads = []
        for poly in polygons:
            index = int(round(float(poly[0][0]) / 40))
            text = self.current[index] if index < len(self.current) else ""
            if language != "fr":
                text = ""
            reads.append({
                "text": text, "confidence": 0.95,
                "bbox": [0.0, 0.0, 30.0, 20.0],
            })
        return reads

    def recognize_polygons(self, image, polygons, language):
        return self._reads(polygons, language)


class WideStubEngine(_TextEngine):
    """First detection misses the heading; the tiled retry finds it."""

    def __init__(self, first, tiled):
        super().__init__()
        self.first = first
        self.tiled = tiled
        self.tiled_calls = 0

    def detect_polygons(self, image):
        self.current = self.first
        return [_polygon_for(i) for i in range(len(self.first))]

    def detect_polygons_tiled(self, image):
        self.tiled_calls += 1
        self.current = self.tiled
        return [_polygon_for(i) for i in range(len(self.tiled))]


class SmallStubEngine(_TextEngine):
    """The upscaled retry image returns a different read."""

    def __init__(self, first, upscaled):
        super().__init__()
        self.first = first
        self.upscaled = upscaled

    def detect_polygons(self, image):
        self.current = self.first if image.size[0] < 500 else self.upscaled
        return [_polygon_for(i) for i in range(len(self.current))]


class TestNoHeadingRetry:
    def _ocr(self, stub):
        ocr = MultiLanguageOCR(retry_no_heading=True)
        ocr._engine = stub
        ocr._engine_name = "StubOCR"
        return ocr

    def test_wide_image_retries_with_tiles(self):
        stub = WideStubEngine(first=["blah"], tiled=["INGREDIENTS", "sugar"])
        ocr = self._ocr(stub)

        results = ocr.process_image(
            Image.new("RGB", (2400, 500), "white"), ["fr"], auto=False)

        assert ocr.last_retry["mode"] == "tiled"
        assert ocr.last_retry["used"] is True
        assert stub.tiled_calls == 1
        assert [r.text for r in results] == ["INGREDIENTS", "sugar"]

    def test_small_image_retries_upscaled(self):
        stub = SmallStubEngine(first=["blah"], upscaled=["INGREDIENTS", "sugar"])
        ocr = self._ocr(stub)

        results = ocr.process_image(
            Image.new("RGB", (300, 200), "white"), ["fr"], auto=False)

        assert ocr.last_retry["mode"] == "upscale_x2"
        assert ocr.last_retry["used"] is True
        assert "INGREDIENTS" in [r.text for r in results]

    def test_no_retry_when_heading_is_found(self):
        stub = WideStubEngine(first=["INGREDIENTS", "sugar"], tiled=["x"])
        ocr = self._ocr(stub)

        ocr.process_image(Image.new("RGB", (2400, 500), "white"), ["fr"], auto=False)

        assert ocr.last_retry == {}
        assert stub.tiled_calls == 0

    def test_retry_results_are_discarded_without_a_heading(self):
        stub = SmallStubEngine(first=["blah"], upscaled=["still no heading"])
        ocr = self._ocr(stub)

        results = ocr.process_image(
            Image.new("RGB", (300, 200), "white"), ["fr"], auto=False)

        assert ocr.last_retry["mode"] == "upscale_x2"
        assert ocr.last_retry["used"] is False
        assert [r.text for r in results] == ["blah"]

    def test_no_retry_for_a_normal_sized_page(self):
        stub = WideStubEngine(first=["blah"], tiled=["INGREDIENTS"])
        ocr = self._ocr(stub)

        ocr.process_image(Image.new("RGB", (1000, 700), "white"), ["fr"], auto=False)

        assert ocr.last_retry == {}
        assert stub.tiled_calls == 0
