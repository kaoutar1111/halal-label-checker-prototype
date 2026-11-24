"""
Pytest configuration for Halal Label Checker tests.
"""

import pytest
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture
def sample_image():
    """Fixture providing a sample PIL Image for testing."""
    from PIL import Image
    import numpy as np
    
    # Create a simple test image with text-like patterns
    img_array = np.ones((200, 400, 3), dtype=np.uint8) * 255  # White background
    return Image.fromarray(img_array)


@pytest.fixture
def sample_arabic_image():
    """Fixture providing a sample Arabic text image."""
    from PIL import Image
    import numpy as np
    
    # Create test image
    img_array = np.random.randint(200, 255, (100, 300, 3), dtype=np.uint8)
    return Image.fromarray(img_array)


@pytest.fixture
def sample_ocr_results():
    """Fixture providing sample OCR results."""
    from src.ocr import OCRResult
    
    return [
        OCRResult("Ingredients:", 0.95, "en"),
        OCRResult("Water", 0.92, "en"),
        OCRResult("Sugar", 0.88, "en"),
        OCRResult("Gelatin", 0.85, "en"),
        OCRResult("مكونات", 0.90, "ar"),
    ]


@pytest.fixture
def reference_path():
    """Fixture providing path to reference.json."""
    return str(Path(__file__).parent.parent / "data" / "reference.json")
