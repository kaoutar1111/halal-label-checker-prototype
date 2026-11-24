"""
OCR engines package.
Contains backend implementations for different OCR engines.
"""

from ..base import OCREngine, get_available_ocr_engines, get_best_ocr_engine

__all__ = [
    "OCREngine",
    "get_available_ocr_engines",
    "get_best_ocr_engine"
]
