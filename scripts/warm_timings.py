#!/usr/bin/env python
"""
Warm-run OCR timings for the sample labels.

Loads every OCR model once (cold load, reported), then processes each sample
image twice; the second run is the warm run reported. Usage:

    python scripts/warm_timings.py
"""

import sys
import time
from pathlib import Path

try:
    import torch  # noqa: F401  (Windows: torch must be imported before paddle)
except ImportError:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from src.ocr import MultiLanguageOCR  # noqa: E402

SAMPLES = [
    ("samples/label-en.jpg", "en"),
    ("samples/label_fr.jpg", "fr"),
    ("samples/label_ar.jpg", "ar"),
    ("samples/label_zh.jpg", "zh"),
]


def main() -> int:
    ocr = MultiLanguageOCR()
    engine = ocr._get_engine()

    start = time.perf_counter()
    engine._get_detector()
    for lang in ["ar", "fr", "en", "zh"]:
        engine._get_recognizer(lang)
    cold_load = time.perf_counter() - start
    print(f"model preload (cold, once): {cold_load:.2f}s\n")

    print(f"{'image':<22}{'lang':<6}{'1st run':>10}{'warm run':>10}{'blocks':>8}")
    for image_name, lang in SAMPLES:
        image_path = ROOT / image_name
        image = Image.open(image_path).convert("RGB")

        start = time.perf_counter()
        ocr.process_image(image, [lang], auto=False)
        first = time.perf_counter() - start

        start = time.perf_counter()
        results = ocr.process_image(image, [lang], auto=False)
        warm = time.perf_counter() - start

        print(f"{image_name:<22}{lang:<6}{first:>9.2f}s{warm:>9.2f}s{len(results):>8}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
