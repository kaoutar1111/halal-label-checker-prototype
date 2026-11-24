#!/usr/bin/env python
"""
Compare the current OCR pipeline against a fixture.

Usage:
    python scripts/compare_to_fixture.py <image> <lang>
    python scripts/compare_to_fixture.py <image> <lang> --mode pipeline|shared|both
    python scripts/compare_to_fixture.py samples/label-fr.jpg fr --fixture tests/fixtures/label-fr.json

The comparison normalizes whitespace and reports the character error rate
(CER) plus fixture lines that are missing from the output.
"""

import argparse
import sys
import time
from pathlib import Path

try:
    import torch  # noqa: F401  (Paddle/torch DLL order on Windows)
except ImportError:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.evaluate import (  # noqa: E402
    canonical_error_rate,
    canonical_text,
    format_report,
    load_fixture,
    missing_lines,
)
from src.ocr import MultiLanguageOCR  # noqa: E402


def run_shared(ocr: MultiLanguageOCR, image, lang: str) -> tuple:
    start = time.perf_counter()
    results = ocr.process_image(image, [lang], auto=False)
    elapsed = time.perf_counter() - start
    texts = [r.text for r in results]
    languages = sorted({r.language for r in results})
    dropped = len(getattr(ocr, "last_dropped", []) or [])
    uncertain = len(getattr(ocr, "last_uncertain", []) or [])
    return texts, languages, dropped, uncertain, elapsed


def run_pipeline(ocr: MultiLanguageOCR, image, lang: str) -> tuple:
    """Original per-language PaddleOCR full pipeline (detection + recognition)."""
    engine = ocr._get_engine()
    start = time.perf_counter()
    raw = engine.recognize(image, lang)
    elapsed = time.perf_counter() - start
    return [item["text"] for item in raw], [lang], 0, 0, elapsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", help="label image path")
    parser.add_argument("lang", choices=["en", "fr", "ar", "zh"])
    parser.add_argument("--fixture", default=None,
                        help="fixture JSON (default: tests/fixtures/label-<lang>.json)")
    parser.add_argument("--mode", choices=["shared", "pipeline", "both"], default="shared")
    parser.add_argument("--target", type=float, default=3.0, help="CER target in %%")
    args = parser.parse_args()

    image_path = Path(args.image)
    if not image_path.is_absolute():
        image_path = (Path.cwd() / image_path).resolve()
    fixture_path = Path(args.fixture) if args.fixture else (
        ROOT / "tests" / "fixtures" / f"label-{args.lang}.json"
    )

    from PIL import Image

    image = Image.open(image_path).convert("RGB")
    blocks = load_fixture(fixture_path)
    reference_texts = [str(block.get("text", "")) for block in blocks]

    ocr = MultiLanguageOCR()
    modes = ["shared", "pipeline"] if args.mode == "both" else [args.mode]

    worst_cer = 0.0
    for mode in modes:
        if mode == "shared":
            hypothesis_texts, languages, dropped, uncertain, elapsed = run_shared(
                ocr, image, args.lang)
        else:
            hypothesis_texts, languages, dropped, uncertain, elapsed = run_pipeline(
                ocr, image, args.lang)

        cer = canonical_error_rate(reference_texts, hypothesis_texts)
        strict_cer = canonical_error_rate(reference_texts, hypothesis_texts, strict=True)
        missing = missing_lines(blocks, hypothesis_texts)
        print(f"\n=== mode: {mode} ===")
        print(f"processing time: {elapsed:.2f}s   "
              f"detected languages: {languages}   blocks: {len(hypothesis_texts)}"
              f"   dropped blocks: {dropped}   uncertain blocks: {uncertain}")
        print(format_report(
            str(image_path), args.lang, str(fixture_path), cer,
            canonical_text(reference_texts), canonical_text(hypothesis_texts),
            missing, target=args.target / 100.0, strict_cer=strict_cer,
        ))
        worst_cer = max(worst_cer, cer)

    return 0 if worst_cer <= args.target / 100.0 else 1


if __name__ == "__main__":
    sys.exit(main())
