#!/usr/bin/env python3
"""
OCR Check CLI - Test OCR on food label images without Streamlit.

Usage:
    python scripts/ocr_check.py <image_path> [--languages en,fr,ar,zh]
    python scripts/ocr_check.py <image_path> --compare-preprocessing
    python scripts/ocr_check.py --from-json tests/fixtures/label-fr.json

Example:
    python scripts/ocr_check.py samples/label.jpg
    python scripts/ocr_check.py samples/label.jpg --languages en,ar
    python scripts/ocr_check.py samples/label.jpg --compare-preprocessing
    python scripts/ocr_check.py --from-json tests/fixtures/label-fr.json
"""

# Paddle/torch DLL conflict on Windows: import torch first
try:
    import torch
except ImportError:
    pass  # torch not installed, continue without it

import sys
import argparse
import json
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PIL import Image
import numpy as np
from src.ocr import (
    OCRResult,
    MultiLanguageOCR,
    get_available_engines,
    merge_multiscript_results,
)
from src.base import OCRError
from src.preprocess import preprocess_image
from src.utils import build_reading_order, calculate_mean_confidence, group_results_by_language
from src.sections import extract_ingredient_sections
from src.engines.paddleocr_engine import RECOGNITION_MODELS, DETECTION_MODEL, DEFAULT_MAX_IMAGE_SIZE


LANGUAGE_NAMES = {
    "ar": "Arabic",
    "fr": "French",
    "en": "English",
    "zh": "Chinese",
    "latin": "Latin"
}


def run_ocr(ocr: MultiLanguageOCR, image, languages: list) -> list:
    """
    Run OCR and exit with a clear ERROR (non-zero exit code) if it fails.
    Never turns an exception into an empty 'No text detected' result.
    """
    try:
        return ocr.process_image(image, languages)
    except OCRError as e:
        print()
        print_separator("!")
        print(" ERROR: OCR FAILED")
        print_separator("!")
        print(f"\n  {e}\n")
        sys.exit(2)
    except Exception as e:
        print()
        print_separator("!")
        print(" ERROR: UNEXPECTED OCR FAILURE")
        print_separator("!")
        print(f"\n  {type(e).__name__}: {e}\n")
        sys.exit(2)


def print_partial_errors(ocr: MultiLanguageOCR):
    """Print per-language errors that occurred while other languages succeeded."""
    errors = getattr(ocr, "last_errors", None)
    if errors:
        print()
        print_separator("!")
        print(" ERROR: SOME LANGUAGE PASSES FAILED")
        print_separator("!")
        for err in errors:
            print(f"  - {err}")
        print()


def print_separator(char="=", length=60):
    """Print a separator line."""
    print(char * length)


def print_metrics(
    engine_name: str,
    image_size: tuple,
    load_times: dict,
    ocr_time: float,
    results: list,
    model_names: dict = None,
    max_image_size: int = None
):
    """Print OCR metrics."""
    print_separator()
    print(" OCR Metrics")
    print_separator()

    print(f"\n  Engine: {engine_name}")

    if model_names:
        print(f"  Detection model: {DETECTION_MODEL}")
        print(f"  Recognition models:")
        for lang, model in model_names.items():
            print(f"    {lang}: {model}")

    print(f"\n  Image size: {image_size[0]}x{image_size[1]}")
    print(f"  Max image size for OCR (longest side): {max_image_size or DEFAULT_MAX_IMAGE_SIZE}px")
    
    print(f"\n  Load times:")
    for lang, load_time in load_times.items():
        print(f"    {lang}: {load_time:.2f}s")
    
    print(f"\n  OCR time: {ocr_time:.2f}s")
    
    if results:
        mean_conf = calculate_mean_confidence(results)
        print(f"  Total text blocks: {len(results)}")
        print(f"  Mean confidence: {mean_conf:.1%}")
    else:
        print("  No text detected")


def print_results_by_language(results: dict, title: str = "OCR Results"):
    """Print OCR results grouped by language."""
    print_separator()
    print(f" {title}")
    print_separator()
    
    if not results:
        print("\n  No text detected.")
        return
    
    for lang, lang_results in results.items():
        if not lang_results:
            continue
        
        lang_name = LANGUAGE_NAMES.get(lang, lang.upper())
        mean_conf = calculate_mean_confidence(lang_results)
        
        print(f"\n  [{lang.upper()}] {lang_name} — {len(lang_results)} blocks, mean conf: {mean_conf:.1%}")
        print("  " + "-" * 40)
        
        for i, result in enumerate(lang_results):
            conf_emoji = "🟢" if result.confidence >= 0.85 else "🟡" if result.confidence >= 0.6 else "🔴"
            print(f"    {conf_emoji} {result.text}")
            print(f"        (conf: {result.confidence:.0%})")
    
    print()


def print_reading_order(results: list, rtl_languages: list = None):
    """Print text in reading order."""
    print_separator()
    print(" Text in Reading Order")
    print_separator()
    
    if not results:
        print("\n  (No text detected)")
        return
    
    # Build reading order
    text, ordered_results = build_reading_order(results, rtl_languages)
    
    print(f"\n  Merged text:")
    print("  " + "-" * 40)
    
    if text:
        # Print with indentation, wrapping at 50 chars
        lines = text.split('\n')
        for line in lines:
            if len(line) > 50:
                # Wrap long lines
                for i in range(0, len(line), 50):
                    print(f"  {line[i:i+50]}")
            else:
                print(f"  {line}")
    else:
        print("  (No text)")
    
    print()


def print_ingredient_sections(results: list):
    """Print the extracted ingredients section(s): heading, flags, text, E-numbers."""
    print_separator()
    print(" Ingredients Sections")
    print_separator()

    sections = extract_ingredient_sections(results)

    if not sections:
        print("\n  No sections extracted.")
        return

    flags = {s.flag for s in sections if s.flag}
    print(f"\n  Sections found: {len(sections)}")
    if flags:
        print(f"  Flags: {', '.join(sorted(flags))}")
    else:
        print("  Flags: none")

    for i, section in enumerate(sections, 1):
        heading = section.heading.text if section.heading else "(no heading)"
        flag = section.flag or "none"
        e_numbers = section.e_numbers

        print(f"\n  [Section {i}]")
        print(f"    Heading: {heading}")
        print(f"    Heading language: {section.language or 'unknown'}")
        print(f"    Flag: {flag}")
        print(f"    Blocks: {len(section.blocks)}")
        print(f"    Text:")
        text = section.text or "(empty)"
        for line in text.split("\n"):
            print(f"      {line}")
        print(f"    E-numbers: {', '.join(e_numbers) if e_numbers else '(none)'}")

    print()


def _jsonable_bbox(bbox):
    """Convert a bbox (numpy floats / nested lists) to plain JSON numbers."""
    if not bbox:
        return []
    if isinstance(bbox[0], (list, tuple)) or hasattr(bbox[0], "__len__"):
        return [[float(v) for v in point] for point in bbox]
    return [float(v) for v in bbox]


def load_results_from_json(path) -> list:
    """Load a saved OCR fixture (text, confidence, language, bbox) as OCRResults."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        OCRResult(
            text=item["text"],
            confidence=float(item["confidence"]),
            language=item["language"],
            bbox=item["bbox"],
        )
        for item in data
    ]


def dump_results_json(path, results: list):
    """Write every OCRResult (text, confidence, language, bbox) to a JSON file."""
    out_path = Path(path)
    if out_path.parent and not out_path.parent.exists():
        out_path.parent.mkdir(parents=True, exist_ok=True)

    data = [
        {
            "text": r.text,
            "confidence": float(r.confidence),
            "language": r.language,
            "bbox": _jsonable_bbox(r.bbox),
        }
        for r in results
    ]
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  JSON dump written: {out_path} ({len(data)} results)")


def main():
    parser = argparse.ArgumentParser(
        description="OCR Check - Test OCR on food label images",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/ocr_check.py samples/label.jpg
  python scripts/ocr_check.py samples/label.jpg --languages en ar
  python scripts/ocr_check.py samples/label.jpg --compare-preprocessing
        """
    )
    
    parser.add_argument(
        "image",
        type=Path,
        nargs="?",
        help="Path to the image file to process"
    )

    parser.add_argument(
        "--from-json",
        dest="from_json",
        default=None,
        help="Extract sections from a saved OCR fixture (JSON) without running OCR"
    )
    
    parser.add_argument(
        "--languages", "-l",
        default="en,fr,ar,zh",
        help="Comma-separated list of languages to try (default: en,fr,ar,zh)"
    )
    
    parser.add_argument(
        "--compare-preprocessing", "-c",
        action="store_true",
        help="Compare results with and without preprocessing"
    )
    
    parser.add_argument(
        "--no-preprocess",
        action="store_true",
        help="Skip image preprocessing"
    )
    
    parser.add_argument(
        "--engine",
        choices=["paddleocr", "easyocr", "auto"],
        default="auto",
        help="Force specific OCR engine (default: auto-detect)"
    )

    parser.add_argument(
        "--max-image-size",
        type=int,
        default=None,
        help=f"Cap longest image side to this many px before OCR (default: {DEFAULT_MAX_IMAGE_SIZE})"
    )

    parser.add_argument(
        "--det-limit-type",
        choices=["min", "max"],
        default=None,
        help="PaddleOCR text_det_limit_type (default: engine default)"
    )

    parser.add_argument(
        "--det-limit-side-len",
        type=int,
        default=None,
        help="PaddleOCR text_det_limit_side_len (px)"
    )

    parser.add_argument(
        "--cpu-threads",
        type=int,
        default=None,
        help="Number of CPU threads for inference"
    )

    parser.add_argument(
        "--merge-scripts",
        action="store_true",
        help="Run Arabic + Latin passes on the same image and merge by bbox overlap"
    )

    parser.add_argument(
        "--json",
        dest="json_path",
        default=None,
        help="Dump all OCRResult objects (text, confidence, language, bbox) to this JSON file"
    )

    args = parser.parse_args()

    # Section-only mode: no OCR engine needed, just a saved fixture.
    if args.from_json:
        fixture = Path(args.from_json)
        if not fixture.exists():
            print(f"Error: Fixture not found: {fixture}")
            sys.exit(1)

        print_separator()
        print(" Halal Label Checker - Section Check (from JSON)")
        print_separator()

        results = load_results_from_json(fixture)
        print(f"\n  Fixture: {fixture}")
        print(f"  OCR blocks loaded: {len(results)}")
        print_ingredient_sections(results)
        print_separator()
        print()
        return

    # Check image exists
    if args.image is None:
        print("Error: No image given (use <image_path> or --from-json <fixture>)")
        sys.exit(1)
    if not args.image.exists():
        print(f"Error: Image not found: {args.image}")
        sys.exit(1)
    
    # Parse languages
    languages = [l.strip() for l in args.languages.split(",")]
    if args.merge_scripts:
        languages = ["ar", "latin"]
    
    # Print header
    print_separator()
    print(" Halal Label Checker - OCR Test Tool")
    print_separator()
    
    print(f"\n  Image: {args.image}")
    print(f"  Languages: {', '.join(languages)}")
    
    # Check available engines
    available = get_available_engines()
    print(f"  Available OCR engines: {', '.join(available) if available else 'None'}")
    
    if not available:
        print("\n  ERROR: No OCR engine available.")
        print("  Please install one of:")
        print("    - PaddleOCR: pip install paddlepaddle==3.3.1 paddleocr==3.7.0")
        print("    - EasyOCR: pip install easyocr")
        sys.exit(1)
    
    # Load image
    print("\n  Loading image...")
    try:
        image = Image.open(args.image)
        image = image.convert("RGB")  # Ensure RGB format
        image_size = (image.width, image.height)
        print(f"  Image size: {image_size[0]}x{image_size[1]}")
    except Exception as e:
        print(f"  Error loading image: {e}")
        sys.exit(1)
    
    print_separator()
    
    # Initialize OCR
    ocr = MultiLanguageOCR(
        max_image_size=args.max_image_size,
        text_det_limit_type=args.det_limit_type,
        text_det_limit_side_len=args.det_limit_side_len,
        cpu_threads=args.cpu_threads,
    )
    print(f"\n  Using OCR engine: {ocr.engine_name}")
    print(f"  Max image size (longest side): {args.max_image_size or DEFAULT_MAX_IMAGE_SIZE}px")
    if args.det_limit_type or args.det_limit_side_len:
        print(f"  Detection limit: type={args.det_limit_type or 'default'}, "
              f"side_len={args.det_limit_side_len or 'default'}")
    if args.cpu_threads:
        print(f"  CPU threads: {args.cpu_threads}")
    
    # Get model names for PaddleOCR
    model_names = None
    if ocr.engine_name == "PaddleOCR":
        model_names = {lang: RECOGNITION_MODELS.get(lang, "unknown") for lang in languages}
    
    # Process without preprocessing first
    if args.compare_preprocessing:
        # WITHOUT preprocessing
        print("\n  Processing WITHOUT preprocessing...")
        start_time = time.time()
        results_no_prep = run_ocr(ocr, image, languages)
        ocr_time_no_prep = time.time() - start_time
        print_partial_errors(ocr)

        by_lang_no_prep = group_results_by_language(results_no_prep)
        
        print_metrics(
            engine_name=ocr.engine_name,
            image_size=image_size,
            load_times=getattr(ocr._engine, '_load_times', {}) if ocr._engine else {},
            ocr_time=ocr_time_no_prep,
            results=results_no_prep,
            model_names=model_names,
            max_image_size=args.max_image_size
        )
        
        print_results_by_language(by_lang_no_prep, "WITHOUT Preprocessing")
        print_reading_order(results_no_prep, rtl_languages=["ar"])
        
        # WITH preprocessing
        print("\n" + "=" * 60)
        print(" Processing WITH preprocessing...")
        print("=" * 60)
        
        image_prep = preprocess_image(image)
        start_time = time.time()
        results_prep = run_ocr(ocr, image_prep, languages)
        ocr_time_prep = time.time() - start_time
        print_partial_errors(ocr)

        by_lang_prep = group_results_by_language(results_prep)
        
        print_metrics(
            engine_name=ocr.engine_name,
            image_size=(image_prep.width, image_prep.height),
            load_times=getattr(ocr._engine, '_load_times', {}) if ocr._engine else {},
            ocr_time=ocr_time_prep,
            results=results_prep,
            model_names=model_names,
            max_image_size=args.max_image_size
        )
        
        print_results_by_language(by_lang_prep, "WITH Preprocessing")
        print_reading_order(results_prep, rtl_languages=["ar"])
        
        # Comparison summary
        print_separator()
        print(" Comparison Summary")
        print_separator()
        
        conf_no_prep = calculate_mean_confidence(results_no_prep)
        conf_prep = calculate_mean_confidence(results_prep)
        
        print(f"\n  Without preprocessing: {len(results_no_prep)} blocks, {conf_no_prep:.1%} confidence, {ocr_time_no_prep:.2f}s")
        print(f"  With preprocessing:    {len(results_prep)} blocks, {conf_prep:.1%} confidence, {ocr_time_prep:.2f}s")
        
        if conf_prep > conf_no_prep:
            print(f"\n  ✓ Preprocessing improved results by {(conf_prep - conf_no_prep)*100:.1f}%")
        elif conf_prep < conf_no_prep:
            print(f"\n  ✗ Preprocessing decreased results by {(conf_no_prep - conf_prep)*100:.1f}%")
        else:
            print("\n  = Preprocessing had no effect")
    
    else:
        # Normal processing
        if args.no_preprocess:
            print("\n  Skipping preprocessing (--no-preprocess flag)")
            processed_image = image
        else:
            print("\n  Applying preprocessing...")
            processed_image = preprocess_image(image)
        
        # Track load times before OCR
        load_times = getattr(ocr._engine, '_load_times', {}) if ocr._engine else {}

        if args.merge_scripts:
            # Mixed script: separate Arabic and Latin passes, merged by bbox
            print("\n  Mixed-script mode: Arabic pass + Latin pass, merged by bbox overlap")
            start_time = time.time()
            ar_results = run_ocr(ocr, processed_image, ["ar"])
            latin_results = run_ocr(ocr, processed_image, ["latin"])
            ocr_time = time.time() - start_time
            print_partial_errors(ocr)

            results = merge_multiscript_results(ar_results, latin_results)
            print(f"\n  Arabic pass: {len(ar_results)} boxes | "
                  f"Latin pass: {len(latin_results)} boxes | "
                  f"Merged: {len(results)} boxes")
        else:
            start_time = time.time()
            results = run_ocr(ocr, processed_image, languages)
            ocr_time = time.time() - start_time
            print_partial_errors(ocr)

        by_lang = group_results_by_language(results)
        
        print_metrics(
            engine_name=ocr.engine_name,
            image_size=(processed_image.width, processed_image.height),
            load_times=load_times,
            ocr_time=ocr_time,
            results=results,
            model_names=model_names,
            max_image_size=args.max_image_size
        )
        
        print_results_by_language(by_lang, "OCR Results")
        print_reading_order(results, rtl_languages=["ar"])
        print_ingredient_sections(results)

        if args.json_path:
            dump_results_json(args.json_path, results)
        
        # Show processed image info
        if not args.no_preprocess:
            print_separator()
            print(" Preprocessed Image")
            print_separator()
            print(f"  Size: {processed_image.width}x{processed_image.height}")
    
    print_separator()
    print()
    
    # Clean up
    ocr.close()


if __name__ == "__main__":
    main()
