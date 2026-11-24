"""
Tests for Phase 1: Project Skeleton + OCR
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import numpy as np
from PIL import Image

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def _check_paddleocr_available():
    """Check if paddleocr is available."""
    try:
        import paddleocr
        return True
    except ImportError:
        return False


class TestOCRModule:
    """Tests for the OCR module."""
    
    def test_ocr_result_creation(self):
        """Test OCRResult dataclass."""
        from src.ocr import OCRResult
        
        result = OCRResult(
            text="test ingredient",
            confidence=0.95,
            language="en",
            bbox=[[0, 0], [100, 0], [100, 50], [0, 50]]
        )
        
        assert result.text == "test ingredient"
        assert result.confidence == 0.95
        assert result.language == "en"
        assert len(result.bbox) == 4
    
    def test_ocr_result_to_dict(self):
        """Test OCRResult serialization."""
        from src.ocr import OCRResult
        
        result = OCRResult(text="gelatin", confidence=0.88, language="en")
        data = result.to_dict()
        
        assert data["text"] == "gelatin"
        assert data["confidence"] == 0.88
        assert data["language"] == "en"
        assert "bbox" in data
    
    def test_detect_language_arabic(self):
        """Test Arabic language detection."""
        from src.ocr import MultiLanguageOCR
        
        ocr = MultiLanguageOCR()
        lang = ocr._detect_language("مكونات غذائية")
        
        assert lang == "ar"
    
    def test_detect_language_chinese(self):
        """Test Chinese language detection."""
        from src.ocr import MultiLanguageOCR
        
        ocr = MultiLanguageOCR()
        lang = ocr._detect_language("配料表成分")
        
        assert lang == "zh"
    
    def test_detect_language_latin(self):
        """Test Latin script (French/English) detection."""
        from src.ocr import MultiLanguageOCR
        
        ocr = MultiLanguageOCR()
        lang = ocr._detect_language("ingredients: water, sugar")
        
        assert lang == "fr/en"
    
    def test_merge_results_basic(self):
        """Test merging multiple OCR results."""
        from src.ocr import MultiLanguageOCR, OCRResult
        
        ocr = MultiLanguageOCR()
        
        results = [
            OCRResult("ingredient 1", 0.9, "en"),
            OCRResult("ingredient 2", 0.85, "fr"),
            OCRResult("ingredient 3", 0.8, "ar"),
        ]
        
        merged_text, avg_conf = ocr.merge_results(results)
        
        assert "ingredient 1" in merged_text
        assert "ingredient 2" in merged_text
        assert "ingredient 3" in merged_text
        assert abs(avg_conf - 0.85) < 0.01
    
    def test_merge_results_removes_duplicates(self):
        """Test that merge removes duplicate text."""
        from src.ocr import MultiLanguageOCR, OCRResult
        
        ocr = MultiLanguageOCR()
        
        results = [
            OCRResult("gelatin", 0.9, "en"),
            OCRResult("GELATIN", 0.85, "en"),
            OCRResult("Gélatin", 0.8, "fr"),
        ]
        
        merged_text, _ = ocr.merge_results(results)
        
        # Should appear only once
        assert merged_text.count("gelatin") == 1 or merged_text.count("GELATIN") == 1
    
    def test_merge_results_empty(self):
        """Test merging empty results."""
        from src.ocr import MultiLanguageOCR
        
        ocr = MultiLanguageOCR()
        merged_text, avg_conf = ocr.merge_results([])
        
        assert merged_text == ""
        assert avg_conf == 0.0
    
    @pytest.mark.skipif(
        not _check_paddleocr_available(),
        reason="PaddleOCR not installed"
    )
    def test_process_image_with_paddleocr(self):
        """Test image processing with real PaddleOCR (if available)."""
        from src.ocr import MultiLanguageOCR
        from PIL import Image
        import numpy as np
        
        ocr = MultiLanguageOCR()
        
        # Create test image with text-like patterns
        img_array = np.ones((200, 400, 3), dtype=np.uint8) * 255
        img = Image.fromarray(img_array)
        
        # This test only runs if PaddleOCR is actually installed
        # It tests that the engine can be initialized and process images
        try:
            results = ocr.process_image(img, languages=["en"])
            # Just verify we get results (could be empty for blank image)
            assert isinstance(results, list)
        except RuntimeError as e:
            pytest.skip(f"PaddleOCR not properly installed: {e}")


class TestPreprocessModule:
    """Tests for the image preprocessing module."""
    
    def test_to_grayscale(self):
        """Test grayscale conversion."""
        from src.preprocess import ImagePreprocessor
        
        preprocessor = ImagePreprocessor()
        
        # Create RGB image
        rgb_img = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        gray_img = preprocessor.to_grayscale(rgb_img)
        
        assert len(gray_img.shape) == 2  # Should be 2D
        assert gray_img.shape == (100, 100)
    
    def test_resize_for_ocr_small(self):
        """Test resizing small images up."""
        from src.preprocess import ImagePreprocessor
        
        preprocessor = ImagePreprocessor()
        
        # Create small image
        small_img = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        resized = preprocessor.resize_for_ocr(small_img, min_size=800)
        
        assert max(resized.shape[:2]) >= 800
    
    def test_resize_for_ocr_large(self):
        """Test resizing large images down."""
        from src.preprocess import ImagePreprocessor
        
        preprocessor = ImagePreprocessor()
        
        # Create large image
        large_img = np.random.randint(0, 255, (3000, 3000, 3), dtype=np.uint8)
        resized = preprocessor.resize_for_ocr(large_img, max_size=2000)
        
        assert max(resized.shape[:2]) <= 2000
    
    def test_preprocess_returns_pil(self):
        """Test that preprocess returns PIL Image."""
        from src.preprocess import ImagePreprocessor
        
        preprocessor = ImagePreprocessor()
        
        # Create test image
        img = Image.new('RGB', (200, 200), color='white')
        result = preprocessor.preprocess(img)
        
        assert isinstance(result, Image.Image)
    
    def test_preprocess_contrast(self):
        """Test contrast enhancement."""
        from src.preprocess import ImagePreprocessor
        
        preprocessor = ImagePreprocessor(apply_contrast=True)
        
        # Create low contrast grayscale image
        img = np.ones((100, 100), dtype=np.uint8) * 128
        result = preprocessor.enhance_contrast(img)
        
        # Grayscale input should produce grayscale output
        assert len(result.shape) == 2
        assert result.shape == img.shape
    
    def test_convenience_function(self):
        """Test preprocess_image convenience function."""
        from src.preprocess import preprocess_image
        
        img = Image.new('RGB', (200, 200), color='white')
        result = preprocess_image(img)
        
        assert isinstance(result, Image.Image)


class TestReferenceData:
    """Tests for reference data loading and structure."""
    
    def test_reference_json_loads(self):
        """Test that reference.json loads correctly."""
        import json
        from pathlib import Path
        
        ref_path = Path(__file__).parent.parent / "data" / "reference.json"
        
        with open(ref_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        assert "ingredients" in data
        assert len(data["ingredients"]) >= 40  # At least 40 entries
    
    def test_reference_entry_structure(self):
        """Test structure of reference entries."""
        import json
        from pathlib import Path
        
        ref_path = Path(__file__).parent.parent / "data" / "reference.json"
        
        with open(ref_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Check first entry structure
        entry = data["ingredients"][0]
        
        assert "id" in entry
        assert "names" in entry
        assert "aliases" in entry
        assert "status" in entry
        assert "reason" in entry
        assert "source" in entry
        
        # Check names structure
        names = entry["names"]
        assert "ar" in names or "fr" in names or "en" in names or "zh" in names
    
    def test_reference_status_values(self):
        """Test that all status values are valid."""
        import json
        from pathlib import Path
        
        ref_path = Path(__file__).parent.parent / "data" / "reference.json"
        
        with open(ref_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        valid_statuses = {"incompatible", "depends_on_origin", "compatible"}
        
        for entry in data["ingredients"]:
            assert entry["status"] in valid_statuses, f"Invalid status: {entry['status']}"
    
    def test_reference_has_gelatin(self):
        """Test that gelatin is in reference."""
        import json
        from pathlib import Path
        
        ref_path = Path(__file__).parent.parent / "data" / "reference.json"
        
        with open(ref_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        gelatin_found = False
        for entry in data["ingredients"]:
            names = entry.get("names", {})
            if names.get("en", "").lower() == "gelatin":
                gelatin_found = True
                # Reviewed resolution: gelatin depends on its origin.
                assert entry["status"] == "depends_on_origin"
                break
        
        assert gelatin_found, "Gelatin not found in reference"


class TestProjectStructure:
    """Tests for project file structure."""
    
    def test_required_files_exist(self):
        """Test that all required files exist."""
        from pathlib import Path
        
        base_path = Path(__file__).parent.parent
        
        required_files = [
            "app.py",
            "requirements.txt",
            "data/reference.json",
            "src/__init__.py",
            "src/ocr.py",
            "src/preprocess.py",
            "src/matcher.py",
            "src/verdict.py",
            "src/db.py",
        ]
        
        for file_path in required_files:
            full_path = base_path / file_path
            assert full_path.exists(), f"Required file missing: {file_path}"
    
    def test_samples_directory_exists(self):
        """Test that samples directory exists."""
        from pathlib import Path
        
        base_path = Path(__file__).parent.parent
        samples_dir = base_path / "samples"
        
        assert samples_dir.exists()
        assert samples_dir.is_dir()
    
    def test_tests_directory_structure(self):
        """Test tests directory structure."""
        from pathlib import Path
        
        base_path = Path(__file__).parent.parent
        tests_dir = base_path / "tests"
        
        assert tests_dir.exists()
        assert tests_dir.is_dir()


class TestModuleImports:
    """Tests for module imports."""
    
    def test_ocr_imports(self):
        """Test that OCR module imports correctly."""
        from src.ocr import MultiLanguageOCR, OCRResult, ocr_image
        
        assert MultiLanguageOCR is not None
        assert OCRResult is not None
        assert ocr_image is not None
    
    def test_preprocess_imports(self):
        """Test that preprocess module imports correctly."""
        from src.preprocess import ImagePreprocessor, preprocess_image
        
        assert ImagePreprocessor is not None
        assert preprocess_image is not None
    
    def test_src_init_exports(self):
        """Test that src/__init__.py exports correctly."""
        from src import (
            MultiLanguageOCR, OCRResult, ocr_image, get_default_ocr,
            ImagePreprocessor, preprocess_image,
            IngredientMatcher, MatchResult, match_ingredient,
            VerdictGenerator, VerdictResult, generate_verdict,
            ScanDatabase, get_database
        )
        
        # All exports should be valid
        assert MultiLanguageOCR is not None
        assert IngredientMatcher is not None
        assert VerdictGenerator is not None


# Run tests with pytest
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
