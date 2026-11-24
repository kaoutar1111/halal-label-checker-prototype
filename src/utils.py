"""
OCR utilities for Halal Label Checker.
Contains helper functions for processing OCRResult objects.

OCR results are `OCRResult` objects with attributes:
    text, confidence, language, bbox
(NOT dicts — do not use .get() or ["key"] on them.)
"""

from typing import List, Dict, Tuple, Optional
import numpy as np


def get_box_center_y(box: List) -> float:
    """Get the y-coordinate of the center of a bounding box."""
    if not box or len(box) == 0:
        return 0.0

    # Box format: [[x1, y1], [x2, y2], [x3, y3], [x4, y4]] (4 corners)
    # or [x0, y0, x1, y1] (PaddleOCR rec_boxes, flat)
    if isinstance(box[0], (list, np.ndarray, tuple)):
        # 4-corner format
        ys = [point[1] for point in box]
        return sum(ys) / len(ys)
    elif len(box) >= 4:
        # flat [x0, y0, x1, y1] -> centre
        return (box[1] + box[3]) / 2.0
    return 0.0


def get_box_center_x(box: List) -> float:
    """Get the x-coordinate of the center of a bounding box."""
    if not box or len(box) == 0:
        return 0.0

    if isinstance(box[0], (list, np.ndarray, tuple)):
        # 4-corner format
        xs = [point[0] for point in box]
        return sum(xs) / len(xs)
    elif len(box) >= 4:
        # flat [x0, y0, x1, y1] -> centre
        return (box[0] + box[2]) / 2.0
    return 0.0


def build_reading_order(
    results: List,
    rtl_languages: Optional[List[str]] = None
) -> Tuple[str, List]:
    """
    Rebuild text in reading order from OCR bounding boxes.

    Groups boxes into lines by y-position, sorts by x-position within lines,
    and reverses each line for RTL languages (Arabic).

    Args:
        results: List of OCRResult objects (attributes: text, confidence,
                 language, bbox)
        rtl_languages: Language codes that are read right-to-left

    Returns:
        Tuple of (text_in_order, reordered_results)
    """
    if not results:
        return "", []

    if rtl_languages is None:
        rtl_languages = ["ar"]

    # Compute positions for each result
    items = []
    for i, result in enumerate(results):
        bbox = getattr(result, "bbox", None)
        if not bbox:
            # No bbox: keep original position as fallback
            items.append({
                "index": i,
                "has_pos": False,
                "x_pos": i * 100.0,
                "result": result,
            })
            continue

        items.append({
            "index": i,
            "has_pos": True,
            "y_pos": get_box_center_y(bbox),
            "x_pos": get_box_center_x(bbox),
            "result": result,
        })

    # If no boxes at all, return original order
    if not any(item["has_pos"] for item in items):
        text = " ".join(r.text for r in results if r.text)
        return text, results

    # Group into lines by y position
    LINE_HEIGHT_THRESHOLD = 20  # pixels

    positioned = [it for it in items if it["has_pos"]]
    positioned.sort(key=lambda x: x["y_pos"])

    lines = []
    current_line: List[dict] = []
    current_line_y: Optional[float] = None

    for item in positioned:
        if current_line_y is None:
            current_line_y = item["y_pos"]
            current_line.append(item)
        elif abs(item["y_pos"] - current_line_y) <= LINE_HEIGHT_THRESHOLD:
            current_line.append(item)
        else:
            lines.append(current_line)
            current_line = [item]
            current_line_y = item["y_pos"]

    if current_line:
        lines.append(current_line)

    # Sort within each line by x position; reverse only RTL lines
    ordered_items: List[dict] = []
    rtl_set = set(rtl_languages or [])
    for line in lines:
        line.sort(key=lambda x: x["x_pos"])
        line_langs = {getattr(it["result"], "language", "") for it in line}
        if rtl_set and line_langs & rtl_set:
            line = list(reversed(line))
        ordered_items.extend(line)

    ordered_results = [item["result"] for item in ordered_items]
    text = " ".join(r.text for r in ordered_results if r.text)

    return text, ordered_results


def merge_ocr_results_by_language(all_results: List, language: str) -> List:
    """Filter OCR results for a specific language."""
    return [r for r in all_results if getattr(r, "language", None) == language]


def calculate_mean_confidence(results: List) -> float:
    """Calculate mean confidence from a list of OCRResult objects."""
    if not results:
        return 0.0

    confidences = [getattr(r, "confidence", 0.0) for r in results]
    return sum(confidences) / len(confidences) if confidences else 0.0


def group_results_by_language(results: List) -> Dict[str, List]:
    """Group OCRResult objects by their .language attribute."""
    grouped: Dict[str, List] = {}
    for result in results:
        lang = getattr(result, "language", None) or "unknown"
        grouped.setdefault(lang, []).append(result)
    return grouped
