"""
EasyOCR backend for Halal Label Checker.
Fallback OCR engine when PaddleOCR is not available.
"""

import numpy as np
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)

from ..base import OCREngine


class EasyOCREngine(OCREngine):
    """
    EasyOCR implementation of OCREngine.
    Supports multiple languages including Arabic, French, English, and Chinese.
    """
    
    # EasyOCR language codes
    LANG_MAP = {
        "ar": "ar",
        "fr": "fr",
        "en": "en",
        "zh": "ch_sim",  # Simplified Chinese
        "latin": "en"
    }
    
    def __init__(self, use_gpu: bool = False):
        """
        Initialize EasyOCR engine.
        
        Args:
            use_gpu: Whether to use GPU (default: False for CPU)
        """
        self.use_gpu = use_gpu
        self._reader = None
    
    @property
    def name(self) -> str:
        return "EasyOCR"
    
    @property
    def supported_languages(self) -> List[str]:
        return ["ar", "fr", "en", "zh", "latin"]
    
    def is_available(self) -> bool:
        """Check if EasyOCR is installed."""
        try:
            import easyocr
            return True
        except ImportError:
            return False
    
    def _get_reader(self, language: str):
        """Get or create EasyOCR reader for specific language."""
        if self._reader is not None:
            return self._reader
        
        try:
            import easyocr
            
            # Get all languages needed
            lang_codes = [self.LANG_MAP.get(language, "en")]
            # Add common fallback languages
            if "ar" not in lang_codes:
                lang_codes.append("ar")
            if "fr" not in lang_codes:
                lang_codes.append("fr")
            
            self._reader = easyocr.Reader(
                lang_codes,
                gpu=self.use_gpu,
                verbose=False
            )
            
            logger.info(f"Initialized EasyOCR reader for languages: {lang_codes}")
            return self._reader
            
        except ImportError:
            logger.error("EasyOCR not installed. Run: pip install easyocr")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize EasyOCR reader: {e}")
            raise
    
    def recognize(self, image, language: str) -> List[Dict]:
        """
        Perform OCR on an image for a specific language.
        
        Args:
            image: numpy array (RGB) or PIL Image
            language: Language code
        
        Returns:
            List of dicts with keys: text, confidence, bbox
        """
        # Convert PIL Image to numpy if needed
        if hasattr(image, 'convert'):
            image = np.array(image)
        
        # EasyOCR expects RGB
        if len(image.shape) == 2:
            image = np.stack([image] * 3, axis=-1)
        
        try:
            reader = self._get_reader(language)
            results = reader.readtext(image)
            
            ocr_results = []
            for bbox, text, confidence in results:
                # Convert bbox format from EasyOCR to our format
                # EasyOCR: [[x1,y1], [x2,y1], [x2,y2], [x1,y2]]
                # Our format: same
                ocr_results.append({
                    "text": text.strip(),
                    "confidence": float(confidence),
                    "bbox": bbox
                })
            
            return ocr_results
            
        except Exception as e:
            logger.error(f"EasyOCR recognition failed: {e}")
            return []
    
    def close(self):
        """Clean up EasyOCR reader."""
        self._reader = None
