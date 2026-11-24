"""
OCR backend base class for Halal Label Checker.
Provides a common interface for different OCR engines.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class OCRError(Exception):
    """Raised when an OCR engine fails to initialize or recognize."""


class OCREngine(ABC):
    """
    Abstract base class for OCR engines.
    All OCR backends must implement this interface.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Return the name of the OCR engine."""
        pass
    
    @property
    @abstractmethod
    def supported_languages(self) -> List[str]:
        """Return list of supported language codes."""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if this OCR engine is available (installed)."""
        pass
    
    @abstractmethod
    def recognize(self, image, language: str) -> List[Dict]:
        """
        Perform OCR on an image for a specific language.
        
        Args:
            image: numpy array (RGB) or PIL Image
            language: Language code (ar, fr, en, zh)
        
        Returns:
            List of dicts with keys: text, confidence, bbox
        """
        pass
    
    def close(self):
        """Clean up resources. Override if needed."""
        pass


def get_available_ocr_engines() -> List[OCREngine]:
    """
    Get list of available OCR engines, ordered by preference.
    
    Returns:
        List of OCREngine instances that are available
    """
    engines = []
    
    # Try PaddleOCR first (preferred)
    try:
        from .engines.paddleocr_engine import PaddleOCREngine
        engine = PaddleOCREngine()
        if engine.is_available():
            engines.append(engine)
            logger.info("PaddleOCR engine available")
    except ImportError as e:
        logger.warning(f"PaddleOCR not available: {e}")
    except Exception as e:
        logger.warning(f"PaddleOCR error: {e}")
    
    # Try EasyOCR as fallback
    try:
        from .engines.easyocr_engine import EasyOCREngine
        engine = EasyOCREngine()
        if engine.is_available():
            engines.append(engine)
            logger.info("EasyOCR engine available")
    except ImportError as e:
        logger.warning(f"EasyOCR not available: {e}")
    except Exception as e:
        logger.warning(f"EasyOCR error: {e}")
    
    return engines


def get_best_ocr_engine() -> Optional[OCREngine]:
    """
    Get the best available OCR engine.
    
    Returns:
        Best available OCREngine or None if no engine is available
    """
    engines = get_available_ocr_engines()
    if engines:
        return engines[0]  # First engine is preferred
    return None
