"""
OCR module for Halal Label Checker.
Uses pluggable OCR backends (PaddleOCR default, EasyOCR fallback).
"""

# Paddle/torch DLL conflict on Windows: import torch first
try:
    import torch
except ImportError:
    pass  # torch not installed, continue without it

import hashlib
import os
import time

import numpy as np
from PIL import Image
from typing import List, Dict, Tuple, Optional
import logging
import re

from .base import OCRError

logger = logging.getLogger(__name__)

# A wrong-language pass must never contaminate a box: keep only the read whose
# script matches the model that produced it, and only when it is confident.
MIN_RESULT_CONFIDENCE = 0.6

# Auto mode: the Latin model also covers English, so three recognizers are
# enough to cover ar / en+fr / zh.
AUTO_LANGUAGES = ["ar", "fr", "zh"]

# FAST_MODE (default ON) bundles three speed options, all quality-neutral:
#   1. language-first: probe a few boxes, keep the winning model(s) only;
#   2. batched recognition calls (crops sent to the model in chunks);
#   3. per-image result cache in memory (same photo -> instant result).
# The default can be overridden per OCR instance or by HALAL_FAST_MODE=0.
FAST_MODE = os.environ.get("HALAL_FAST_MODE", "1").strip().lower() not in {
    "0", "false", "no", "off",
}

# Language probe: read at most this many (largest) boxes with every model.
PROBE_BOXES = 6

# Crops per recognition call when batching (0 = one call, the default).
FAST_BATCH_SIZE = 16

# Bounded in-memory cache of OCR results, keyed by an image pixel hash.
IMAGE_CACHE_SIZE = 32

# No-heading retry: when the first pass finds no ingredients heading, retry
# detection once with a setting suited to the photo's shape.
RETRY_ASPECT_RATIO = 3.0     # wider/taller than this -> tiled detection
RETRY_UPSCALE_BELOW = 800    # long side under this -> upscale x2 and retry
RETRY_UPSCALE_FACTOR = 2

# Expected script of each recognition model.
MODEL_SCRIPT = {
    "ar": "arabic",
    "zh": "cjk",
    "fr": "latin",
    "en": "latin",
    "latin": "latin",
}

_ARABIC_CHAR_RE = re.compile(
    r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufeff]"
)
_CJK_CHAR_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_LATIN_CHAR_RE = re.compile(r"[A-Za-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u024f]")
_FRENCH_ACCENT_RE = re.compile(r"[àâäçéèêëîïôöùûüÿœæ]", re.IGNORECASE)
_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)

_SCRIPT_PRIORITY = {"arabic": 3, "cjk": 2, "latin": 1}


def dominant_script(text: str) -> Optional[str]:
    """Dominant script of a text: 'arabic', 'cjk', 'latin' or None."""
    if not text:
        return None
    counts = {
        "arabic": len(_ARABIC_CHAR_RE.findall(text)),
        "cjk": len(_CJK_CHAR_RE.findall(text)),
        "latin": len(_LATIN_CHAR_RE.findall(text)),
    }
    total = sum(counts.values())
    if total == 0:
        return None
    return max(counts, key=lambda name: (counts[name], _SCRIPT_PRIORITY[name]))


def matches_model_script(text: str, language: str) -> bool:
    """
    True when the text script matches the script expected from the model.

    Digits, punctuation and parentheses are script-neutral. A block with three
    or fewer letters ("B1),", "B3),", "(B6),", "E471") therefore belongs to the
    Latin model: it must never be rejected as a script mismatch. Symbol soup
    with no readable word ("*#L", "##L", "11(") is dropped by is_garbage_text,
    not by this script check.
    """
    expected = MODEL_SCRIPT.get(language)
    if expected is None:
        return True
    letters = _LETTER_RE.findall(text or "")
    if expected == "latin" and len(letters) <= 3:
        return True
    script = dominant_script(text)
    if script is None:
        return True  # digits/punctuation only: neutral, no script mismatch
    return script == expected


def is_garbage_text(text: str) -> bool:
    """True for symbol soup with no readable word ("*#L", "##L", "11(")."""
    text = (text or "").strip()
    if not text:
        return True
    if _CJK_CHAR_RE.search(text):
        return False
    runs = re.findall(r"[^\W\d_]+", text, re.UNICODE)
    if not runs:
        return True
    if any(len(run) >= 2 for run in runs):
        return False
    # Single-letter runs survive only as short codes with a digit ("B1", "E471").
    return not any(char.isdigit() for char in text)


def is_substantive(text: str, min_letters: int = 5) -> bool:
    """True when a low-confidence read still looks like real words."""
    return len(_LETTER_RE.findall(text or "")) >= min_letters


def language_for_text(text: str) -> str:
    """Language code inferred from the script of the confident text."""
    script = dominant_script(text)
    if script == "arabic":
        return "ar"
    if script == "cjk":
        return "zh"
    if script == "latin":
        return "fr" if _FRENCH_ACCENT_RE.search(text) else "en"
    return "unknown"


# Image-level French vs English decision (words + accents over the whole text)
_FRENCH_CHARS = set("àâäçéèêëîïôöùûüÿœæ")
_FRENCH_WORDS = {
    "le", "la", "les", "des", "du", "de", "et", "au", "aux", "avec", "sans",
    "pour", "sur", "dans", "ingredients", "ingrédients", "sucre", "lait",
    "huile", "farine", "aromes", "arômes", "eau", "sel", "cacao", "beurre",
    "poudre", "contient", "matiere", "matière", "emulsifiant", "émulsifiant",
}
_ENGLISH_WORDS = {
    "the", "and", "with", "without", "for", "in", "of", "ingredients",
    "sugar", "milk", "oil", "flour", "salt", "water", "cocoa", "butter",
    "powder", "contains", "fat", "syrup", "emulsifier",
}


def detect_image_language(text: str) -> Optional[str]:
    """
    Language of the whole image text (not per block).

    Arabic/CJK are decided by script; Latin by accents and common words
    across the complete text.
    """
    script = dominant_script(text)
    if script == "arabic":
        return "ar"
    if script == "cjk":
        return "zh"
    if script != "latin":
        return None

    lowered = (text or "").lower()
    accents = sum(1 for char in lowered if char in _FRENCH_CHARS)
    words = re.findall(r"[^\W\d_]+", lowered, re.UNICODE)
    french_hits = sum(1 for word in words if word in _FRENCH_WORDS)
    english_hits = sum(1 for word in words if word in _ENGLISH_WORDS)

    french_score = accents * 3 + french_hits
    if french_score > 0 and french_score >= english_hits:
        return "fr"
    return "en" if english_hits else "fr"


def filter_results(
    results: List["OCRResult"],
    min_confidence: float = MIN_RESULT_CONFIDENCE,
) -> List["OCRResult"]:
    """
    Drop results that are empty, low-confidence, or written in a script that
    does not match the model that produced them (wrong-language garbage).
    """
    kept: List["OCRResult"] = []
    for result in results:
        if not (result.text or "").strip():
            continue
        if result.confidence < min_confidence:
            continue
        if is_garbage_text(result.text):
            continue
        if not matches_model_script(result.text, result.language):
            continue
        kept.append(result)
    return kept


class OCRResult:
    """Represents a single OCR detection result."""
    def __init__(self, text: str, confidence: float, language: str, bbox: Optional[List] = None):
        self.text = text
        self.confidence = confidence
        self.language = language
        self.bbox = bbox or []
    
    def __repr__(self):
        return f"OCRResult(text='{self.text}', confidence={self.confidence:.2f}, lang={self.language})"
    
    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "language": self.language,
            "bbox": self.bbox
        }


class MultiLanguageOCR:
    """
    OCR engine supporting Arabic, French/English (Latin), and Chinese.
    Uses pluggable backend (PaddleOCR default, EasyOCR fallback).
    """
    
    SUPPORTED_LANGUAGES = {
        "ar": "arabic",
        "fr": "french", 
        "en": "english",
        "zh": "chinese"
    }
    
    def __init__(self, use_gpu: bool = False, show_log: bool = False,
                 max_image_size: Optional[int] = None,
                 text_det_limit_type: Optional[str] = None,
                 text_det_limit_side_len: Optional[int] = None,
                 cpu_threads: Optional[int] = None,
                 fast_mode: Optional[bool] = None,
                 probe_boxes: int = PROBE_BOXES,
                 batch_size: int = FAST_BATCH_SIZE,
                 cache_size: int = IMAGE_CACHE_SIZE,
                 retry_no_heading: bool = True):
        """
        Initialize the OCR engine.

        Args:
            use_gpu: Whether to use GPU (default: False for CPU)
            show_log: Whether to show OCR logs (PaddleOCR only)
            max_image_size: If set, longest image side is capped to this
                            many px before OCR (PaddleOCR engine only).
            text_det_limit_type: "min" or "max" detection limit mode.
            text_det_limit_side_len: Detection side length limit in px.
            cpu_threads: Number of CPU threads for inference.
            fast_mode: Enable the three speed options (language-first probe,
                       batched recognition, per-image cache). Default follows
                       the FAST_MODE setting (off).
            probe_boxes: How many boxes (largest first) the probe reads.
            batch_size: Crops per recognition call in fast mode.
            cache_size: How many images the in-memory result cache keeps.
            retry_no_heading: When the first pass finds no ingredients
                heading, retry once with tiled detection (wide/tall photos)
                or a x2 upscale (long side under 800 px). Retry results are
                kept only if a heading appears.
        """
        self.use_gpu = use_gpu
        self.show_log = show_log
        self.max_image_size = max_image_size
        self.text_det_limit_type = text_det_limit_type
        self.text_det_limit_side_len = text_det_limit_side_len
        self.cpu_threads = cpu_threads
        self.fast_mode = FAST_MODE if fast_mode is None else bool(fast_mode)
        self.probe_boxes = probe_boxes
        self.batch_size = batch_size
        self.cache_size = cache_size
        self.retry_no_heading = bool(retry_no_heading)
        self._cache: Dict[str, Dict] = {}
        self._engine = None
        self._engine_name = None
        self.last_errors: List[str] = []
        self.last_strategy = ""
        self.last_probe_language = ""
        self.last_probe_scores: Dict[str, float] = {}
        self.last_dropped: List[Dict] = []
        self.last_uncertain: List[Dict] = []
        self.last_retry: Dict = {}
        self.last_blocks_detected = 0
        self._last_run_languages: List[str] = []
    
    def _get_engine(self):
        """Get or create the OCR engine (lazy initialization)."""
        if self._engine is not None:
            return self._engine
        
        # Import here to avoid circular imports
        from .base import get_best_ocr_engine
        
        engine = get_best_ocr_engine()
        
        if engine is None:
            raise RuntimeError(
                "No OCR engine available. Please install either:\n"
                "  - PaddleOCR: pip install paddlepaddle paddleocr\n"
                "  - EasyOCR: pip install easyocr"
            )
        
        # Apply configurable image size cap when the engine supports it
        if self.max_image_size is not None and hasattr(engine, "max_image_size"):
            engine.max_image_size = self.max_image_size

        # Detection-limit / thread options are read when the engine first
        # builds its PaddleOCR instance (lazy), so setting them here is enough.
        for attr in ("text_det_limit_type", "text_det_limit_side_len", "cpu_threads"):
            value = getattr(self, attr, None)
            if value is not None and hasattr(engine, attr):
                setattr(engine, attr, value)

        # Batched recognition only in fast mode; 0 keeps one call per model.
        if hasattr(engine, "recognition_batch_size"):
            engine.recognition_batch_size = self.batch_size if self.fast_mode else 0

        self._engine = engine
        self._engine_name = engine.name
        logger.info(f"Using OCR engine: {engine.name}")

        return engine
    
    @property
    def engine_name(self) -> str:
        """Get the name of the active OCR engine."""
        if self._engine_name is None:
            try:
                self._get_engine()
            except RuntimeError:
                return "None"
        return self._engine_name or "Unknown"
    
    def _detect_language(self, text: str) -> str:
        """Simple heuristic language detection based on character ranges."""
        for char in text:
            code = ord(char)
            # Arabic Unicode range
            if 0x0600 <= code <= 0x06FF or 0x0750 <= code <= 0x077F:
                return "ar"
            # Chinese Unicode range
            if 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF:
                return "zh"
        return "fr/en"  # Default to Latin for French/English
    
    def process_image(self, image: Image.Image, languages: Optional[List[str]] = None,
                      auto: bool = False) -> List[OCRResult]:
        """
        Process an image and extract text using OCR.

        The text detector runs ONCE; every recognition model reuses the same
        boxes. Across models, each box keeps only the read whose script matches
        that model and whose confidence is >= 0.6, so a wrong-language pass can
        never inject garbage into another box.

        Args:
            image: PIL Image object
            languages: Languages to run (default: auto candidates ar/fr/zh)
            auto: Pick detected languages from the script of confident results

        Returns:
            List of OCRResult objects in reading order

        Raises:
            OCRError: If the engine is unavailable or every recognition failed.
                      Errors are NEVER silently converted to empty results.
        """
        if languages is None:
            languages = list(AUTO_LANGUAGES)
            auto = True

        engine = self._get_engine()  # raises RuntimeError/OCRError if unavailable

        # The flag can be toggled between scans; keep the engine in sync.
        if hasattr(engine, "recognition_batch_size"):
            engine.recognition_batch_size = self.batch_size if self.fast_mode else 0

        cache_key = None
        if self.fast_mode and self.cache_size > 0:
            cache_key = self._image_cache_key(image, languages, auto)
            cached = self._cache.get(cache_key)
            if cached is not None:
                self._restore_cached_state(cached)
                return [self._copy_result(r) for r in cached["results"]]

        errors: List[str] = []
        self.last_dropped = []
        self.last_uncertain = []
        self.last_strategy = "three_pass"
        self.last_probe_language = ""
        self.last_probe_scores = {}
        self.last_retry = {}
        self.last_blocks_detected = 0
        self._last_run_languages = list(languages)
        selected = self._run_pass(engine, image, languages, auto, errors)

        # --- no-heading retry (wide/tall -> tiled, small -> upscale) --------
        if (self.retry_no_heading and not errors
                and not self._has_ingredient_heading(selected)):
            blocks_before = self.last_blocks_detected
            retry_results, retry_info = self._retry_no_heading(
                engine, image, auto, errors)
            if retry_info:
                retry_info["results_before"] = len(selected)
                retry_info["results_after"] = len(retry_results or [])
                self.last_retry = retry_info
                if retry_info["used"]:
                    selected = retry_results
                    self.last_strategy = (
                        f"{self.last_strategy}+retry:{retry_info['mode']}")
                else:
                    self.last_blocks_detected = blocks_before

        self.last_errors = errors
        if not selected and errors:
            # Every pass failed -> surface a real error
            raise OCRError("; ".join(errors))

        # Language belongs to the IMAGE, not to individual blocks
        image_language = detect_image_language(" ".join(r.text for r in selected))
        self.last_language = image_language or ""
        if image_language:
            for result in selected:
                result.language = image_language

        from .utils import build_reading_order
        _, ordered = build_reading_order(selected, rtl_languages=["ar"])

        if cache_key is not None:
            self._store_cached_state(cache_key, ordered)
        return ordered

    # -- in-memory per-image cache (fast mode only) --------------------------

    @staticmethod
    def _image_cache_key(image: Image.Image, languages: List[str],
                         auto: bool) -> str:
        """Stable key from the image pixels plus the requested recognition."""
        if image.mode != "RGB":
            image = image.convert("RGB")
        digest = hashlib.sha1(image.tobytes()).hexdigest()
        return f"{digest}:{image.size[0]}x{image.size[1]}:{','.join(languages)}:{auto}"

    @staticmethod
    def _copy_result(result: OCRResult) -> OCRResult:
        """Copy so callers can never mutate the cached objects."""
        return OCRResult(
            text=result.text,
            confidence=result.confidence,
            language=result.language,
            bbox=list(result.bbox or []),
        )

    def _store_cached_state(self, key: str, results: List[OCRResult]) -> None:
        if self.cache_size <= 0:
            return
        if key in self._cache:
            self._cache.pop(key)
        elif len(self._cache) >= self.cache_size:
            self._cache.pop(next(iter(self._cache)))  # oldest first
        self._cache[key] = {
            "results": [self._copy_result(r) for r in results],
            "strategy": self.last_strategy,
            "probe_language": self.last_probe_language,
            "probe_scores": dict(self.last_probe_scores),
            "language": getattr(self, "last_language", ""),
            "errors": list(self.last_errors),
            "dropped": [dict(item) for item in self.last_dropped],
            "uncertain": [dict(item) for item in self.last_uncertain],
            "retry": dict(self.last_retry),
            "blocks_detected": self.last_blocks_detected,
        }

    def _restore_cached_state(self, cached: Dict) -> None:
        self.last_strategy = f"cache:{cached['strategy']}"
        self.last_probe_language = cached["probe_language"]
        self.last_probe_scores = dict(cached["probe_scores"])
        self.last_language = cached["language"]
        self.last_errors = list(cached["errors"])
        self.last_dropped = [dict(item) for item in cached["dropped"]]
        self.last_uncertain = [dict(item) for item in cached["uncertain"]]
        self.last_retry = dict(cached.get("retry") or {})
        self.last_blocks_detected = cached.get("blocks_detected", 0)

    # -- language passes -----------------------------------------------------

    def _run_pass(self, engine, image, languages, auto, errors) -> List[OCRResult]:
        """Run one OCR pass with the strategy that fits the engine."""
        has_polygons = (hasattr(engine, "detect_polygons")
                        and hasattr(engine, "recognize_polygons"))
        self._last_run_languages = list(languages)
        if self.fast_mode and auto and len(languages) > 1 and has_polygons:
            return self._process_fast_mode(engine, image, languages, auto, errors)
        if has_polygons or (hasattr(engine, "detect_boxes")
                            and hasattr(engine, "recognize_boxes")):
            return self._process_shared_detection(engine, image, languages, auto, errors)
        return self._process_per_language(engine, image, languages, auto, errors)

    @staticmethod
    def _has_ingredient_heading(results: List[OCRResult]) -> bool:
        """True when the section extractor finds an ingredients heading."""
        try:
            from .sections import extract_ingredient_sections
        except Exception:  # the check itself must never break OCR
            return True
        return any(section.heading is not None
                   for section in extract_ingredient_sections(results))

    def _retry_no_heading(self, engine, image, auto, errors):
        """
        Retry detection once when no ingredients heading was found.

        Wide/tall photos (aspect ratio > 3) lose small lines when the whole
        page is detected in one pass, so detection is re-run on overlapping
        tiles. Small photos (long side < 800 px) are upscaled x2 first. The
        retry replaces the first pass only when a heading appears.

        Returns:
            (results or None, info dict). Empty info means "no retry".
        """
        width, height = image.size
        long_side = max(width, height)
        short_side = max(1, min(width, height))
        tiled = (long_side / float(short_side)) > RETRY_ASPECT_RATIO
        if tiled and not hasattr(engine, "detect_polygons_tiled"):
            return None, {}
        if not tiled and long_side >= RETRY_UPSCALE_BELOW:
            return None, {}

        run_languages = list(self._last_run_languages or AUTO_LANGUAGES)
        started = time.perf_counter()
        retry_errors: List[str] = []
        if tiled:
            results = self._process_tiled(
                engine, image, run_languages, auto, retry_errors)
            mode = "tiled"
        else:
            retry_image = image.resize(
                (width * RETRY_UPSCALE_FACTOR, height * RETRY_UPSCALE_FACTOR),
                Image.LANCZOS,
            )
            results = self._run_pass(
                engine, retry_image, run_languages, auto, retry_errors)
            mode = f"upscale_x{RETRY_UPSCALE_FACTOR}"
        elapsed = time.perf_counter() - started

        used = bool(results) and self._has_ingredient_heading(results)
        if used and retry_errors:
            errors.extend(retry_errors)
        return results, {
            "mode": mode,
            "used": used,
            "seconds": round(elapsed, 2),
            "languages": run_languages,
            "errors": retry_errors,
        }

    def _process_tiled(self, engine, image, languages, auto, errors) -> List[OCRResult]:
        """Detect on overlapping tiles, then recognize the same lines per model."""
        try:
            polygons = engine.detect_polygons_tiled(image)
            boxes = [list(bbox_to_rect(polygon)) for polygon in polygons]
        except Exception as e:
            msg = f"[tiled detection] {type(e).__name__}: {e}"
            logger.error("OCR tiled detection failed: %s", e)
            errors.append(msg)
            return []
        self.last_blocks_detected = len(polygons)

        per_language: Dict[str, List[Dict]] = {}
        for lang in languages:
            try:
                per_language[lang] = engine.recognize_polygons(image, polygons, lang)
            except Exception as e:
                msg = f"[{lang}] {type(e).__name__}: {e}"
                logger.error("OCR failed for language %s: %s", lang, e)
                errors.append(msg)
        self._last_run_languages = list(languages)
        return self._select_results(boxes, per_language, languages)

    def _process_shared_detection(self, engine, image, languages, auto, errors) -> List[OCRResult]:
        """Detect once (polygons), recognize the same lines with each model."""
        use_polygons = hasattr(engine, "detect_polygons") and hasattr(engine, "recognize_polygons")
        try:
            if use_polygons:
                polygons = engine.detect_polygons(image)
                boxes = [list(bbox_to_rect(polygon)) for polygon in polygons]
            else:
                polygons = None
                boxes = engine.detect_boxes(image)
        except Exception as e:
            msg = f"[detection] {type(e).__name__}: {e}"
            logger.error("OCR detection failed: %s", e)
            errors.append(msg)
            return []
        self.last_blocks_detected = len(boxes)

        per_language: Dict[str, List[Dict]] = {}
        for lang in languages:
            try:
                if use_polygons:
                    per_language[lang] = engine.recognize_polygons(image, polygons, lang)
                else:
                    per_language[lang] = engine.recognize_boxes(image, boxes, lang)
            except Exception as e:
                msg = f"[{lang}] {type(e).__name__}: {e}"
                logger.error("OCR failed for language %s: %s", lang, e)
                errors.append(msg)

        return self._select_results(boxes, per_language, languages)

    def _select_results(self, boxes, per_language: Dict[str, List[Dict]],
                        languages: List[str]) -> List[OCRResult]:
        """Keep, per box, the most confident read whose script matches its model."""
        selected: List[OCRResult] = []
        for index, box in enumerate(boxes):
            candidates = []
            best_lang, best_item = None, None
            for lang in languages:
                items = per_language.get(lang) or []
                if index >= len(items):
                    continue
                item = items[index]
                text = (item.get("text") or "").strip()
                confidence = float(item.get("confidence") or 0.0)
                candidates.append((lang, text, confidence))
                if not text:
                    continue
                if is_garbage_text(text):
                    continue
                if not matches_model_script(text, lang):
                    continue  # wrong-language garbage for this box
                if best_item is None or confidence > float(best_item.get("confidence") or 0.0):
                    best_lang, best_item = lang, item

            if best_item is None:
                self._record_drop(box, candidates)
                continue
            text = best_item["text"].strip()
            confidence = float(best_item.get("confidence") or 0.0)
            if confidence < MIN_RESULT_CONFIDENCE:
                if not is_substantive(text):
                    # Too weak to trust as label text (e.g. "sa aL"): drop it,
                    # but record it so it can never disappear silently.
                    self._record_drop(box, candidates)
                    continue
                # Readable content at low confidence: keep the text and flag it
                # as uncertain instead of deleting a whole label line.
                self.last_uncertain.append({
                    "bbox": list(box), "text": text, "confidence": confidence,
                    "reason": f"low confidence {confidence:.2f} < {MIN_RESULT_CONFIDENCE}",
                })
            selected.append(OCRResult(
                text=text,
                confidence=confidence,
                language=best_lang,
                bbox=list(box),
            ))
        return selected

    # -- language-first recognition (FAST_MODE) ------------------------------

    def _probe_languages(self, engine, image, polygons, boxes,
                         languages: List[str]):
        """
        Pick the recognition model(s) from the mean confidence of a few boxes.

        The largest boxes are read with EVERY candidate model. Every model with
        at least 2 confident, script-consistent probe reads is kept: a
        bilingual label keeps both scripts instead of falling back to all
        three, and a model that only produced a stray read is dropped.

        Probing nearly the whole page costs more than the passes it saves, so
        a small page keeps every language.

        Returns:
            (kept_languages, probe_reads, probe_indices) or None to run all.
        """
        if not boxes:
            return None
        # Few boxes: probing nearly every box with three models costs more than
        # the passes it saves, so keep the plain (batched) all-language run.
        if len(boxes) <= self.probe_boxes + 2:
            return None
        order = sorted(
            range(len(boxes)),
            key=lambda i: -((boxes[i][2] - boxes[i][0]) * (boxes[i][3] - boxes[i][1])),
        )
        indices = order[: max(1, self.probe_boxes)]
        probe = [polygons[i] for i in indices]

        scores: Dict[str, float] = {}
        counts: Dict[str, int] = {}
        probe_reads: Dict[str, List[Dict]] = {}
        for lang in languages:
            try:
                reads = engine.recognize_polygons(image, probe, lang)
            except Exception as e:  # a probe failure must not kill the run
                logger.warning("language probe failed for %s: %s", lang, e)
                continue
            probe_reads[lang] = reads
            confidences = []
            for read in reads:
                text = (read.get("text") or "").strip()
                confidence = float(read.get("confidence") or 0.0)
                if (text and confidence >= MIN_RESULT_CONFIDENCE
                        and not is_garbage_text(text)
                        and matches_model_script(text, lang)):
                    confidences.append(confidence)
            if confidences:
                scores[lang] = sum(confidences) / len(confidences)
                counts[lang] = len(confidences)

        self.last_probe_scores = {lang: round(v, 3) for lang, v in scores.items()}
        if not scores:
            return None

        # Keep every model that read at least two probe boxes convincingly.
        kept = [lang for lang in languages if counts.get(lang, 0) >= 2]
        if not kept:
            return None

        self.last_probe_language = "+".join(kept)
        return kept, probe_reads, indices

    def _process_fast_mode(self, engine, image, languages, auto,
                           errors) -> List[OCRResult]:
        """
        Detect once, probe, then recognize every box with the kept models.

        The boxes read by the probe are not read again: their probe results are
        reused and only the remaining boxes go through the recognizer, so fast
        mode returns exactly what the kept models would have read. Falls back to
        every language on probe failure, so it can only cost time, never
        quality.
        """
        try:
            polygons = engine.detect_polygons(image)
            boxes = [list(bbox_to_rect(polygon)) for polygon in polygons]
        except Exception as e:
            msg = f"[detection] {type(e).__name__}: {e}"
            logger.error("OCR detection failed: %s", e)
            errors.append(msg)
            return []
        self.last_blocks_detected = len(boxes)

        probe = self._probe_languages(engine, image, polygons, boxes, languages)
        if probe is None:
            chosen, probe_reads, probe_indices = list(languages), {}, []
            self.last_strategy = "language_first:all"
        else:
            chosen, probe_reads, probe_indices = probe
            self.last_strategy = f"language_first:{'+'.join(chosen)}"
        self._last_run_languages = list(chosen)

        probe_set = set(probe_indices)
        rest = [index for index in range(len(polygons)) if index not in probe_set]

        per_language: Dict[str, List[Dict]] = {}
        for lang in chosen:
            reads: List[Optional[Dict]] = [None] * len(polygons)
            lang_probe_reads = probe_reads.get(lang) or []
            for position, index in enumerate(probe_indices):
                if position < len(lang_probe_reads):
                    reads[index] = lang_probe_reads[position]
            if rest:
                try:
                    rest_reads = engine.recognize_polygons(
                        image, [polygons[index] for index in rest], lang)
                except Exception as e:
                    msg = f"[{lang}] {type(e).__name__}: {e}"
                    logger.error("OCR failed for language %s: %s", lang, e)
                    errors.append(msg)
                    rest_reads = []
                for position, index in enumerate(rest):
                    if position < len(rest_reads):
                        reads[index] = rest_reads[position]
            per_language[lang] = [read if read is not None else {} for read in reads]

        return self._select_results(boxes, per_language, chosen)


    def _record_drop(self, box, candidates) -> None:
        """Record a box that got no usable reading (never drop it silently)."""
        if not candidates:
            self.last_dropped.append({
                "bbox": list(box), "text": "", "confidence": 0.0,
                "reason": "no recognition output for this box",
            })
            return
        lang, text, confidence = max(candidates, key=lambda item: item[2])
        if not text:
            reason = "empty recognition"
        elif confidence < MIN_RESULT_CONFIDENCE:
            reason = f"low confidence {confidence:.2f} < {MIN_RESULT_CONFIDENCE}"
        elif is_garbage_text(text):
            reason = "no readable word (OCR garbage)"
        elif not matches_model_script(text, lang):
            reason = f"script mismatch for model {lang}"
        else:
            reason = "rejected"
        self.last_dropped.append({
            "bbox": list(box), "text": text, "confidence": confidence,
            "reason": reason,
        })

    def _process_per_language(self, engine, image, languages, auto, errors) -> List[OCRResult]:
        """
        Fallback for engines without a shared detector (e.g. EasyOCR).

        Results from different passes are clustered by bbox overlap and only
        the script-matching, confident read of each box is kept.
        """
        candidates: List[Tuple[str, Dict]] = []
        for lang in languages:
            try:
                for item in engine.recognize(image, lang):
                    candidates.append((lang, item))
            except Exception as e:
                msg = f"[{lang}] {type(e).__name__}: {e}"
                logger.error("OCR failed for language %s: %s", lang, e)
                errors.append(msg)

        groups: List[List[Tuple[str, Dict]]] = []
        for lang, item in candidates:
            bbox = item.get("bbox") or []
            for group in groups:
                if bbox_iou(bbox, group[0][1].get("bbox") or []) >= 0.5:
                    group.append((lang, item))
                    break
            else:
                groups.append([(lang, item)])
        self.last_blocks_detected = len(groups)

        selected: List[OCRResult] = []
        for group in groups:
            best_lang, best_item = None, None
            for lang, item in group:
                text = (item.get("text") or "").strip()
                confidence = float(item.get("confidence") or 0.0)
                if not text:
                    continue
                if is_garbage_text(text):
                    continue
                if not matches_model_script(text, lang):
                    continue
                if best_item is None or confidence > float(best_item.get("confidence") or 0.0):
                    best_lang, best_item = lang, item

            if best_item is None:
                bbox = group[0][1].get("bbox") or []
                lang, text, confidence = max(group, key=lambda entry: float(entry[1].get("confidence") or 0.0))
                self._record_drop(bbox, [(lang, text, float(confidence or 0.0))])
                continue
            text = best_item["text"].strip()
            confidence = float(best_item.get("confidence") or 0.0)
            if confidence < MIN_RESULT_CONFIDENCE:
                if not is_substantive(text):
                    bbox = best_item.get("bbox") or []
                    self._record_drop(bbox, [(best_lang, text, confidence)])
                    continue
                self.last_uncertain.append({
                    "bbox": list(best_item.get("bbox") or []), "text": text,
                    "confidence": confidence,
                    "reason": f"low confidence {confidence:.2f} < {MIN_RESULT_CONFIDENCE}",
                })
            selected.append(OCRResult(
                text=text,
                confidence=confidence,
                language=language_for_text(text) if auto else best_lang,
                bbox=best_item.get("bbox") or [],
            ))
        return selected
    
    def merge_results(self, results: List[OCRResult]) -> Tuple[str, float]:
        """
        Merge multiple OCR results into a single text with average confidence.
        
        Args:
            results: List of OCRResult objects
        
        Returns:
            Tuple of (merged_text, average_confidence)
        """
        if not results:
            return "", 0.0
        
        # Group by language and take unique texts
        seen_texts = set()
        unique_results = []
        
        for result in results:
            # Normalize text for comparison
            normalized = result.text.lower().strip()
            if normalized and normalized not in seen_texts:
                seen_texts.add(normalized)
                unique_results.append(result)
        
        # Combine texts, preserving some order (try Arabic first, then Latin, then Chinese)
        sorted_results = sorted(
            unique_results,
            key=lambda x: {"ar": 0, "fr": 1, "en": 1, "zh": 2}.get(x.language, 3)
        )
        
        merged_text = "\n".join([r.text for r in sorted_results])
        avg_confidence = sum(r.confidence for r in sorted_results) / len(sorted_results)
        
        return merged_text, avg_confidence
    
    def get_results_by_language(self, results: List[OCRResult]) -> Dict[str, List[OCRResult]]:
        """
        Group OCR results by detected language.
        
        Args:
            results: List of OCRResult objects
        
        Returns:
            Dict mapping language codes to lists of results
        """
        grouped = {}
        for result in results:
            if result.language not in grouped:
                grouped[result.language] = []
            grouped[result.language].append(result)
        return grouped
    
    def close(self):
        """Clean up OCR engine resources."""
        if self._engine is not None:
            self._engine.close()
            self._engine = None
            self._engine_name = None


def extract_ingredients_section(text: str) -> Optional[str]:
    """
    Heuristic extraction of ingredients section from full label text.
    Looks for keywords like "ingredients", "composition", etc.
    
    Args:
        text: Full OCR text
        
    Returns:
        Extracted ingredients section or None
    """
    keywords = {
        "en": ["ingredient", "composition"],
        "fr": ["ingredient", "composition"],
        "ar": ["مكونات", "التركيبة"],
        "zh": ["配料", "成分"]
    }
    
    lines = text.split("\n")
    
    for i, line in enumerate(lines):
        line_lower = line.lower()
        for lang, words in keywords.items():
            if any(word in line_lower for word in words):
                # Return this line and following lines as ingredients
                return "\n".join(lines[i:])
    
    # If no keywords found, return the whole text
    return text if text.strip() else None


# Module-level convenience functions
_default_ocr: Optional[MultiLanguageOCR] = None


def get_default_ocr() -> MultiLanguageOCR:
    """Get or create the default OCR instance."""
    global _default_ocr
    if _default_ocr is None:
        _default_ocr = MultiLanguageOCR()
    return _default_ocr


def ocr_image(image: Image.Image, languages: Optional[List[str]] = None) -> Tuple[str, float, List[OCRResult]]:
    """
    Convenience function for OCR processing.
    
    Args:
        image: PIL Image object
        languages: Languages to process
    
    Returns:
        Tuple of (merged_text, average_confidence, all_results)
    """
    ocr = get_default_ocr()
    results = ocr.process_image(image, languages)
    merged_text, avg_confidence = ocr.merge_results(results)
    return merged_text, avg_confidence, results


def get_available_engines() -> List[str]:
    """
    Get list of available OCR engine names.
    
    Returns:
        List of available engine names
    """
    from .base import get_available_ocr_engines
    
    engines = get_available_ocr_engines()
    return [e.name for e in engines]


# ---------------------------------------------------------------------------
# Mixed-script merging (e.g. Arabic + Latin on the same label)
# ---------------------------------------------------------------------------

def detect_script(text: str) -> str:
    """Return "ar" if Arabic letters dominate the text, else "latin"/"other"."""
    arabic = sum(1 for c in text if 0x0600 <= ord(c) <= 0x06FF)
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    if arabic == 0 and latin == 0:
        return "other"
    return "ar" if arabic >= latin else "latin"


def bbox_to_rect(bbox) -> tuple:
    """Normalize a bbox to (x0, y0, x1, y1).

    Handles PaddleOCR `rec_boxes` (flat [x0, y0, x1, y1]) and 4-corner
    polygons [[x0, y0], [x1, y0], [x1, y1], [x0, y1]].
    """
    if bbox is None:
        return (0.0, 0.0, 0.0, 0.0)
    if isinstance(bbox, np.ndarray):
        if bbox.size == 0:
            return (0.0, 0.0, 0.0, 0.0)
        bbox = bbox.tolist()
    if not bbox:
        return (0.0, 0.0, 0.0, 0.0)
    if isinstance(bbox[0], (list, tuple)) or hasattr(bbox[0], "__len__"):
        xs = [float(p[0]) for p in bbox]
        ys = [float(p[1]) for p in bbox]
        return (min(xs), min(ys), max(xs), max(ys))
    x0, y0, x1, y1 = [float(v) for v in bbox[:4]]
    return (x0, y0, x1, y1)


def bbox_iou(a, b) -> float:
    """Intersection-over-union of two bboxes."""
    ax0, ay0, ax1, ay1 = bbox_to_rect(a)
    bx0, by0, bx1, by1 = bbox_to_rect(b)
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _prefer_by_script(a, b):
    """
    Choose one of two overlapping OCRResults, keeping the text whose script
    matches the box's script.

    The box script is inferred from the stronger read (highest confidence):
    if that read is Arabic the box is Arabic, and the Arabic candidate wins.
    """
    sa, sb = detect_script(a.text), detect_script(b.text)
    if sa == sb or sb == "other":
        return a if a.confidence >= b.confidence else b
    if sa == "other":
        return b
    stronger = a if a.confidence >= b.confidence else b
    box_script = detect_script(stronger.text)
    return a if sa == box_script else b


def merge_multiscript_results(
    primary: List[OCRResult],
    secondary: List[OCRResult],
    iou_threshold: float = 0.3,
) -> List[OCRResult]:
    """
    Merge two OCR passes over the same image by bbox overlap.

    Boxes present in both passes are collapsed into one result: the text
    matching the box's script is kept (see `_prefer_by_script`). Non-overlapping
    boxes from either pass are preserved.

    Args:
        primary: Results of the first pass (e.g. "ar").
        secondary: Results of the second pass (e.g. "latin").
        iou_threshold: Minimum IoU for two boxes to be the same box.

    Returns:
        Merged list of OCRResult, sorted by reading order.
    """
    used = set()
    merged: List[OCRResult] = []

    for a in primary:
        best_j, best_iou = None, 0.0
        for j, b in enumerate(secondary):
            if j in used:
                continue
            iou = bbox_iou(a.bbox, b.bbox)
            if iou > best_iou:
                best_j, best_iou = j, iou
        if best_j is not None and best_iou >= iou_threshold:
            used.add(best_j)
            merged.append(_prefer_by_script(a, secondary[best_j]))
        else:
            merged.append(a)

    for j, b in enumerate(secondary):
        if j not in used:
            merged.append(b)

    from .utils import build_reading_order
    _, ordered = build_reading_order(merged, rtl_languages=["ar"])
    return ordered
