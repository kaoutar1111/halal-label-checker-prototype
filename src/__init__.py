"""
__init__.py for src module
"""

from .ocr import MultiLanguageOCR, OCRResult, ocr_image, get_default_ocr, get_available_engines
from .base import OCREngine, OCRError, get_available_ocr_engines, get_best_ocr_engine
from .preprocess import ImagePreprocessor, preprocess_image
from .matcher import IngredientMatcher, MatchResult, match_ingredient, get_default_matcher, parse_ingredient_list
from .verdict import VerdictGenerator, VerdictResult, generate_verdict
from .db import ScanDatabase, get_database
from .utils import build_reading_order, calculate_mean_confidence, group_results_by_language

__all__ = [
    # OCR
    "MultiLanguageOCR",
    "OCRResult", 
    "ocr_image",
    "get_default_ocr",
    "get_available_engines",
    # OCR Engines
    "OCREngine",
    "OCRError",
    "get_available_ocr_engines",
    "get_best_ocr_engine",
    # Preprocessing
    "ImagePreprocessor",
    "preprocess_image",
    # Matching
    "IngredientMatcher",
    "MatchResult",
    "match_ingredient",
    "get_default_matcher",
    "parse_ingredient_list",
    # Verdict
    "VerdictGenerator",
    "VerdictResult",
    "generate_verdict",
    # Database
    "ScanDatabase",
    "get_database",
    # Utils
    "build_reading_order",
    "calculate_mean_confidence",
    "group_results_by_language"
]
