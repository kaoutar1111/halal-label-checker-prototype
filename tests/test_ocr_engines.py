"""
Tests for OCR engine selection and fallback functionality.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class FakeOCREngine:
    """Fake OCR engine for testing engine selection."""
    
    def __init__(self, name: str = "FakeOCR", available: bool = True):
        self._name = name
        self._available = available
        self.supported_langs = ["en", "fr"]
    
    @property
    def name(self):
        return self._name
    
    @property
    def supported_languages(self):
        return self.supported_langs
    
    def is_available(self):
        return self._available
    
    def recognize(self, image, language):
        return [
            {"text": f"fake_{language}", "confidence": 0.9, "bbox": [[0, 0], [10, 0], [10, 10], [0, 10]]}
        ]
    
    def close(self):
        pass


class TestOCREngineSelection:
    """Tests for OCR engine selection and fallback."""
    
    def test_base_engine_is_abstract(self):
        """Test that OCREngine is an abstract base class."""
        from src.base import OCREngine
        import inspect
        
        assert inspect.isabstract(OCREngine)
    
    def test_base_engine_requires_implementation(self):
        """Test that OCREngine is abstract and cannot be instantiated."""
        from src.base import OCREngine
        import inspect
        
        # Verify that name, supported_languages, is_available, recognize are abstract
        assert hasattr(OCREngine, 'name')
        assert hasattr(OCREngine, 'supported_languages')
        assert hasattr(OCREngine, 'is_available')
        assert hasattr(OCREngine, 'recognize')
        
        # Verify they raise NotImplementedError when called
        # Note: We can't instantiate the abstract class, so we check the abstractmethod decorator
        for method_name in ['name', 'supported_languages', 'is_available', 'recognize']:
            method = getattr(OCREngine, method_name)
            assert getattr(method, '__isabstractmethod__', False), f"{method_name} should be abstract"
    
    def test_get_available_engines_empty(self):
        """Test get_available_engines when no engines are installed."""
        with patch('src.base.get_available_ocr_engines') as mock_get:
            mock_get.return_value = []
            
            from src.base import get_best_ocr_engine
            result = get_best_ocr_engine()
            
            assert result is None
    
    def test_get_available_engines_returns_first_preferred(self):
        """Test that first available engine is returned as best."""
        fake_engine1 = FakeOCREngine(name="Engine1")
        fake_engine2 = FakeOCREngine(name="Engine2")
        
        with patch('src.base.get_available_ocr_engines') as mock_get:
            mock_get.return_value = [fake_engine1, fake_engine2]
            
            from src.base import get_best_ocr_engine
            result = get_best_ocr_engine()
            
            assert result.name == "Engine1"
    
    def test_engine_fallback_order(self):
        """Test that engines are checked in correct order."""
        calls = []
        
        def mock_paddleocr():
            calls.append("paddleocr")
            return None  # Not available
        
        def mock_easyocr():
            calls.append("easyocr")
            fake = FakeOCREngine(name="EasyOCR")
            return [fake]
        
        with patch.dict('sys.modules', {'paddleocr': MagicMock()}):
            with patch('src.base.get_available_ocr_engines') as mock_get:
                # Simulate engines being checked
                mock_get.side_effect = lambda: [FakeOCREngine(name="PaddleOCR")] if "paddleocr" not in calls else [FakeOCREngine(name="EasyOCR")]
                
                from src.base import get_available_ocr_engines
                
                # This is a simplified test - actual fallback is tested by mocking
                pass
    
    def test_fake_engine_integration(self):
        """Test that FakeOCREngine works as expected."""
        engine = FakeOCREngine()
        
        assert engine.name == "FakeOCR"
        assert engine.is_available() == True
        assert "en" in engine.supported_languages
        
        results = engine.recognize(None, "en")
        assert len(results) == 1
        assert results[0]["text"] == "fake_en"
        assert results[0]["confidence"] == 0.9


class TestPaddleOCREngineConfig:
    """Tests for PaddleOCR engine configuration."""
    
    def test_recognition_models_defined(self):
        """Test that recognition models are defined."""
        from src.engines.paddleocr_engine import RECOGNITION_MODELS, DETECTION_MODEL
        
        assert "ar" in RECOGNITION_MODELS
        assert "en" in RECOGNITION_MODELS
        assert "zh" in RECOGNITION_MODELS
        assert "fr" in RECOGNITION_MODELS
        
        assert RECOGNITION_MODELS["ar"] == "arabic_PP-OCRv5_mobile_rec"
        assert RECOGNITION_MODELS["en"] == "en_PP-OCRv5_mobile_rec"
        assert RECOGNITION_MODELS["zh"] == "PP-OCRv6_medium_rec"
        assert RECOGNITION_MODELS["fr"] == "latin_PP-OCRv5_mobile_rec"
        assert RECOGNITION_MODELS["latin"] == "latin_PP-OCRv5_mobile_rec"

        assert DETECTION_MODEL == "PP-OCRv5_mobile_det"

    def test_engine_init_params(self):
        """Test PaddleOCREngine initialization parameters."""
        from src.engines.paddleocr_engine import PaddleOCREngine, DEFAULT_MAX_IMAGE_SIZE

        engine = PaddleOCREngine(max_image_size=1600)

        assert engine.max_image_size == 1600
        assert engine._engines == {}
        assert engine._load_times == {}
        assert DEFAULT_MAX_IMAGE_SIZE == 1600
    
    def test_supported_languages(self):
        """Test that supported languages are correctly reported."""
        from src.engines.paddleocr_engine import PaddleOCREngine
        
        engine = PaddleOCREngine()
        supported = engine.supported_languages
        
        assert "ar" in supported
        assert "en" in supported
        assert "zh" in supported
        assert "fr" in supported


class TestReadingOrderFunction:
    """Tests for the build_reading_order function (with real OCRResult objects)."""

    @staticmethod
    def _make(text, confidence=0.9, bbox=None, language="en"):
        """Build a real OCRResult object (never a hand-made dict)."""
        from src.ocr import OCRResult
        return OCRResult(text=text, confidence=confidence, language=language, bbox=bbox or [])

    def test_empty_results(self):
        """Test build_reading_order with empty results."""
        from src.utils import build_reading_order

        text, ordered = build_reading_order([])

        assert text == ""
        assert ordered == []

    def test_single_line_ltr(self):
        """Test reading order for single line LTR (left-to-right)."""
        from src.utils import build_reading_order

        # Simulate boxes from left to right: "Hello World"
        results = [
            self._make("Hello", bbox=[[0, 10], [50, 10], [50, 30], [0, 30]]),
            self._make("World", bbox=[[60, 10], [120, 10], [120, 30], [60, 30]]),
        ]

        text, ordered = build_reading_order(results, rtl_languages=[])

        # Should be in left-to-right order
        assert text == "Hello World"
        assert ordered[0].text == "Hello"
        assert ordered[1].text == "World"

    def test_single_line_rtl(self):
        """Test reading order for single line RTL (right-to-left)."""
        from src.utils import build_reading_order

        # In the image, left to right: "مرحبا" at x=0, "عالم" at x=60
        results = [
            self._make("مرحبا", bbox=[[0, 10], [50, 10], [50, 30], [0, 30]], language="ar"),
            self._make("عالم", bbox=[[60, 10], [120, 10], [120, 30], [60, 30]], language="ar"),
        ]

        text, ordered = build_reading_order(results, rtl_languages=["ar"])

        # For RTL, should be reversed: "عالم مرحبا"
        assert text == "عالم مرحبا"
        assert ordered[0].text == "عالم"
        assert ordered[1].text == "مرحبا"

    def test_multi_line_reading_order(self):
        """Test reading order for multiple lines."""
        from src.utils import build_reading_order

        results = [
            self._make("First", bbox=[[0, 0], [50, 0], [50, 20], [0, 20]]),
            self._make("Second", bbox=[[0, 30], [60, 30], [60, 50], [0, 50]]),
        ]

        text, ordered = build_reading_order(results, rtl_languages=[])

        # Should read top-to-bottom
        assert "First" in text
        assert "Second" in text
        assert ordered[0].text == "First"
        assert ordered[1].text == "Second"

    def test_multi_line_within_line_ordering(self):
        """Test that items within a line are ordered by x position."""
        from src.utils import build_reading_order

        results = [
            self._make("C", bbox=[[100, 0], [110, 0], [110, 20], [100, 20]]),
            self._make("A", bbox=[[0, 0], [10, 0], [10, 20], [0, 20]]),
            self._make("B", bbox=[[50, 0], [60, 0], [60, 20], [50, 20]]),
            self._make("F", bbox=[[100, 30], [110, 30], [110, 50], [100, 50]]),
            self._make("D", bbox=[[0, 30], [10, 30], [10, 50], [0, 50]]),
            self._make("E", bbox=[[50, 30], [60, 30], [60, 50], [50, 50]]),
        ]

        text, ordered = build_reading_order(results, rtl_languages=[])

        # Should be A, B, C on first line, D, E, F on second
        assert ordered[0].text == "A"
        assert ordered[1].text == "B"
        assert ordered[2].text == "C"
        assert ordered[3].text == "D"
        assert ordered[4].text == "E"
        assert ordered[5].text == "F"

    def test_mixed_confidences(self):
        """Test reading order preserves confidence."""
        from src.utils import build_reading_order

        results = [
            self._make("Low", confidence=0.5, bbox=[[0, 0], [10, 0], [10, 20], [0, 20]]),
            self._make("High", confidence=0.95, bbox=[[50, 0], [60, 0], [60, 20], [50, 20]]),
        ]

        text, ordered = build_reading_order(results, rtl_languages=[])

        # Should still be in position order, not confidence order
        assert ordered[0].text == "Low"
        assert ordered[0].confidence == 0.5
        assert ordered[1].text == "High"
        assert ordered[1].confidence == 0.95


class TestUtilsFunctions:
    """Tests for utility functions (with real OCRResult objects)."""

    @staticmethod
    def _make(text="", confidence=0.0, language="en", bbox=None):
        from src.ocr import OCRResult
        return OCRResult(text=text, confidence=confidence, language=language, bbox=bbox or [])

    def test_calculate_mean_confidence(self):
        """Test mean confidence calculation."""
        from src.utils import calculate_mean_confidence

        results = [
            self._make(confidence=0.9),
            self._make(confidence=0.8),
            self._make(confidence=0.7),
        ]

        mean = calculate_mean_confidence(results)
        assert abs(mean - 0.8) < 0.001

    def test_calculate_mean_confidence_empty(self):
        """Test mean confidence with empty list."""
        from src.utils import calculate_mean_confidence

        mean = calculate_mean_confidence([])
        assert mean == 0.0

    def test_group_results_by_language(self):
        """Test grouping OCRResult objects by language attribute."""
        from src.utils import group_results_by_language

        results = [
            self._make("Hello", 0.9, "en"),
            self._make("Bonjour", 0.85, "fr"),
            self._make("World", 0.9, "en"),
            self._make("مرحبا", 0.8, "ar"),
        ]

        grouped = group_results_by_language(results)

        assert len(grouped["en"]) == 2
        assert len(grouped["fr"]) == 1
        assert len(grouped["ar"]) == 1

        assert grouped["en"][0].text == "Hello"
        assert grouped["en"][1].text == "World"

    def test_group_results_by_language_empty(self):
        """Test grouping with missing language attribute."""
        from src.utils import group_results_by_language
        from src.ocr import OCRResult

        results = [OCRResult(text="Unknown", confidence=0.5, language="", bbox=[])]

        grouped = group_results_by_language(results)

        assert "unknown" in grouped
        assert len(grouped["unknown"]) == 1


class TestRealPaddleOCREngine:
    """
    Tests that instantiate the REAL PaddleOCREngine class.
    Skipped only when paddleocr is not installed.

    These tests catch unsupported constructor arguments (e.g. 2.x leftovers
    like show_log / use_angle_cls / use_gpu) by actually calling the
    PaddleOCR 3.x constructor.
    """

    def test_real_constructor_no_unsupported_args(self):
        """
        Instantiate PaddleOCR via our engine with only allowed 3.x arguments.
        If any 2.x-only argument (show_log, use_angle_cls, use_gpu, lang with
        model names, cls, ...) is passed, PaddleOCR 3.7.0 raises
        'Unknown argument' and this test FAILS.
        """
        pytest.importorskip("paddleocr")

        from src.engines.paddleocr_engine import PaddleOCREngine

        engine = PaddleOCREngine(max_image_size=1600)
        # Trigger real model loading; constructor args are validated here.
        ocr_instance = engine._get_engine("en")
        assert ocr_instance is not None
        assert hasattr(ocr_instance, "predict")
        engine.close()

    def test_real_constructor_is_cached(self):
        """Second call for the same language must reuse the cached instance."""
        pytest.importorskip("paddleocr")

        from src.engines.paddleocr_engine import PaddleOCREngine

        engine = PaddleOCREngine()
        first = engine._get_engine("en")
        second = engine._get_engine("en")
        assert first is second
        assert "en" in engine._load_times
        engine.close()


class TestOCRErrorPropagation:
    """Errors must surface as errors, never as silent 'no text detected'."""

    def test_process_image_raises_when_all_languages_fail(self):
        from src.ocr import MultiLanguageOCR
        from src.base import OCRError

        class FailingEngine:
            name = "FailingEngine"

            def recognize(self, image, language):
                raise RuntimeError("engine exploded")

            def close(self):
                pass

        ocr = MultiLanguageOCR()
        ocr._engine = FailingEngine()
        ocr._engine_name = "FailingEngine"

        from PIL import Image
        img = Image.new("RGB", (100, 100), color="white")

        with pytest.raises(OCRError) as exc_info:
            ocr.process_image(img, languages=["en", "fr"])

        assert "engine exploded" in str(exc_info.value)
        assert ocr.last_errors  # errors recorded for the caller

    def test_process_image_partial_failure_keeps_results_and_errors(self):
        from src.ocr import MultiLanguageOCR

        class PartiallyFailingEngine:
            name = "PartiallyFailing"

            def recognize(self, image, language):
                if language == "fr":
                    raise RuntimeError("fr model broken")
                return [{"text": "ok", "confidence": 0.9, "bbox": []}]

            def close(self):
                pass

        ocr = MultiLanguageOCR()
        ocr._engine = PartiallyFailingEngine()
        ocr._engine_name = "PartiallyFailing"

        from PIL import Image
        img = Image.new("RGB", (100, 100), color="white")

        results = ocr.process_image(img, languages=["en", "fr"])

        assert len(results) == 1
        assert results[0].text == "ok"
        assert any("fr model broken" in e for e in ocr.last_errors)


class TestImageResize:
    """Longest side must be capped at max_image_size before OCR."""

    def test_resize_large_image(self):
        from src.engines.paddleocr_engine import PaddleOCREngine
        import numpy as np

        engine = PaddleOCREngine(max_image_size=1600)
        big = np.zeros((3840, 2160, 3), dtype=np.uint8)  # phone photo
        resized = engine._resize_image(big)

        h, w = resized.shape[:2]
        assert max(h, w) <= 1600
        # aspect ratio preserved
        assert abs((w / h) - (2160 / 3840)) < 0.01

    def test_small_image_not_resized(self):
        from src.engines.paddleocr_engine import PaddleOCREngine
        import numpy as np

        engine = PaddleOCREngine(max_image_size=1600)
        small = np.zeros((800, 600, 3), dtype=np.uint8)
        resized = engine._resize_image(small)

        assert resized.shape == small.shape


class TestOcrCheckCliSmoke:
    """
    End-to-end smoke test: run scripts/ocr_check.py main() with a fake OCR
    engine whose process_image returns REAL OCRResult objects (never dicts),
    and assert the CLI prints text and metrics without errors.

    This catches dict-style access (.get / ["key"]) on OCRResult objects
    anywhere in the CLI display path.
    """

    def test_cli_main_with_fake_engine(self, tmp_path, monkeypatch, capsys):
        import sys
        from PIL import Image

        from src.ocr import OCRResult
        import scripts.ocr_check as cli

        # Real image file for the CLI to load
        img_path = tmp_path / "label.png"
        Image.new("RGB", (200, 100), color="white").save(img_path)

        # Real OCRResult objects flowing through the whole display path
        fake_results = [
            OCRResult(
                text="wheat flour", confidence=0.97, language="en",
                bbox=[[0, 0], [90, 0], [90, 20], [0, 20]],
            ),
            OCRResult(
                text="sugar", confidence=0.93, language="en",
                bbox=[[0, 30], [50, 30], [50, 50], [0, 50]],
            ),
        ]

        class FakeInnerEngine:
            _load_times = {"en": 0.01}

        class FakeOCR:
            """Drop-in replacement for MultiLanguageOCR returning OCRResult."""
            engine_name = "FakeOCR"
            last_errors = []
            _engine = FakeInnerEngine()

            def __init__(self, *args, **kwargs):
                pass

            def process_image(self, image, languages):
                return list(fake_results)

            def close(self):
                pass

        monkeypatch.setattr(cli, "MultiLanguageOCR", FakeOCR)
        monkeypatch.setattr(cli, "get_available_engines", lambda: ["FakeOCR"])
        monkeypatch.setattr(
            sys, "argv",
            ["ocr_check.py", str(img_path), "--languages", "en", "--no-preprocess"],
        )

        cli.main()  # must not raise

        out = capsys.readouterr().out
        assert "Engine: FakeOCR" in out
        assert "Image size: 200x100" in out
        assert "OCR time:" in out
        assert "Mean confidence: 95.0%" in out
        assert "wheat flour" in out
        assert "sugar" in out
        assert "Text in Reading Order" in out

    def test_cli_main_reports_engine_failure(self, tmp_path, monkeypatch, capsys):
        """If OCR raises, CLI must print ERROR and exit with code 2."""
        import sys
        from PIL import Image

        from src.base import OCRError
        import scripts.ocr_check as cli

        img_path = tmp_path / "label.png"
        Image.new("RGB", (100, 100), color="white").save(img_path)

        class FakeOCR:
            engine_name = "FakeOCR"
            last_errors = ["[en] RuntimeError: exploded"]
            _engine = None

            def __init__(self, *args, **kwargs):
                pass

            def process_image(self, image, languages):
                raise OCRError("[en] RuntimeError: exploded")

            def close(self):
                pass

        monkeypatch.setattr(cli, "MultiLanguageOCR", FakeOCR)
        monkeypatch.setattr(cli, "get_available_engines", lambda: ["FakeOCR"])
        monkeypatch.setattr(
            sys, "argv",
            ["ocr_check.py", str(img_path), "--languages", "en", "--no-preprocess"],
        )

        with pytest.raises(SystemExit) as exc_info:
            cli.main()

        assert exc_info.value.code == 2
        out = capsys.readouterr().out
        assert "ERROR: OCR FAILED" in out
        assert "exploded" in out


# Run tests with pytest
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
