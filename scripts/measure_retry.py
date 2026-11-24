#!/usr/bin/env python
"""
Measure the no-heading retry: CER / recall with the retry off vs on.

Only images that can trigger the retry are measured (aspect ratio > 3 or a
long side < 800 px), and the retry is only run when the first pass finds no
ingredients heading, exactly as in the app. Writes the result to
eval/diagnostics/retry_effect.json and prints a table.

Fast mode stays off so the retry is the only difference between the two runs.
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import torch  # noqa: F401  # Windows: torch must be imported before paddle

from PIL import Image

import evaluate as eval_mod
from src.evaluate import character_error_rate, normalize_for_content
from src.matcher import split_ingredients
from src.ocr import RETRY_ASPECT_RATIO, RETRY_UPSCALE_BELOW, MultiLanguageOCR
from src.sections import extract_ingredient_sections


def _cer_cell(run) -> str:
    """Show 'no section' instead of a fake CER when nothing was extracted."""
    return f"{run['cer'] * 100:.2f}%" if run.get("has_section") else "no section"


def _recall_cell(run) -> str:
    return f"{run['recall']:.3f}" if run.get("has_section") else "n/a"


def run_once(ocr, image_path, truth_text, retry: bool) -> dict:
    """One full pipeline run with the retry flag set, plus the metrics."""
    ocr.retry_no_heading = retry
    start = time.perf_counter()
    results = ocr.process_image(Image.open(image_path), auto=True)
    elapsed = time.perf_counter() - start

    sections = extract_ingredient_sections(results)
    hyp_text = "\n".join(section.text for section in sections)
    has_section = any(s.flag != "no_heading" and s.text.strip()
                      for s in sections)
    cer = character_error_rate(truth_text, hyp_text, normalize_for_content)

    truth_items = [eval_mod.content_norm(t)
                   for t in split_ingredients(truth_text)]
    truth_items = [t for t in truth_items if t]
    pred_items = [eval_mod.content_norm(p) for p in split_ingredients(hyp_text)]
    pred_items = [p for p in pred_items if p]
    hit_truth, _ = eval_mod.greedy_match(truth_items, pred_items)
    recall = hit_truth / len(truth_items) if truth_items else 0.0

    return {
        "cer": cer,
        "recall": recall,
        "has_section": has_section,
        "seconds": elapsed,
        "blocks_detected": ocr.last_blocks_detected,
        "blocks_kept": len(results),
        "has_heading": any(s.heading is not None for s in sections),
        "retry": dict(ocr.last_retry or {}),
    }


def main() -> int:
    eval_dir = ROOT / "eval"
    images = list(eval_mod.discover(eval_dir))

    print("preloading OCR models (cold start, excluded from timings)...")
    ocr = MultiLanguageOCR(fast_mode=False, retry_no_heading=False)
    engine = ocr._get_engine()
    if hasattr(engine, "_get_detector"):
        engine._get_detector()
    if hasattr(engine, "_get_recognizer"):
        for lang in eval_mod.LANGS:
            engine._get_recognizer(lang)
    eval_mod.evaluate_image(ocr, eval_mod.IngredientMatcher(),
                            eval_mod.VerdictGenerator(), images[0][1])

    rows = []
    for lang, image_path, truth_path in images:
        width, height = Image.open(image_path).size
        long_side, short_side = max(width, height), max(1, min(width, height))
        aspect = long_side / short_side
        wide = aspect > RETRY_ASPECT_RATIO
        small = long_side < RETRY_UPSCALE_BELOW
        if not (wide or small):
            continue

        truth_text = json.loads(
            truth_path.read_text(encoding="utf-8"))["ingredients_text"]
        rel = f"{lang}/{image_path.name}"
        first = run_once(ocr, image_path, truth_text, retry=False)
        print(f"{rel}: retry off {first['seconds']:.2f}s, "
              f"blocks {first['blocks_kept']}, heading={first['has_heading']}")

        row = {
            "image": rel,
            "size": f"{width}x{height}",
            "aspect": round(aspect, 2),
            "condition": "tiled" if wide else "upscale_x2",
            "off": first,
        }
        if not first["has_heading"]:
            second = run_once(ocr, image_path, truth_text, retry=True)
            row["on"] = second
            both = first["has_section"] and second["has_section"]
            row["delta_cer_pp"] = round(
                (second["cer"] - first["cer"]) * 100, 2) if both else None
            row["delta_recall"] = round(
                second["recall"] - first["recall"], 3) if both else None
            row["added_seconds"] = second["retry"].get("seconds", 0.0)
            row["retry"] = second["retry"]
            print(f"{rel}: retry on {second['seconds']:.2f}s, "
                  f"{second['retry'].get('mode')} "
                  f"{'kept' if second['retry'].get('used') else 'discarded'}, "
                  f"CER {_cer_cell(first)} -> {_cer_cell(second)}, "
                  f"recall {_recall_cell(first)} -> {_recall_cell(second)}, "
                  f"+{second['retry'].get('seconds', 0):.1f}s")
        else:
            row["on"] = None
            row["delta_cer_pp"] = 0.0
            row["delta_recall"] = 0.0
            row["added_seconds"] = 0.0
            row["retry"] = {}
            print(f"{rel}: heading found on the first pass, retry never runs")
        rows.append(row)

    out = {
        "conditions": {
            "aspect_ratio_above": RETRY_ASPECT_RATIO,
            "long_side_below_px": RETRY_UPSCALE_BELOW,
        },
        "rows": rows,
    }
    target = eval_dir / "diagnostics" / "retry_effect.json"
    target.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    print(f"\nwrote {target}")

    append_report(eval_dir / "report.md", rows)
    return 0


def append_report(report_path: Path, rows: list) -> None:
    """Append (or refresh) the retry section of the evaluation report."""
    md = [
        "## No-heading retry effect",
        "",
        "The retry runs only when the first pass finds no ingredients heading:",
        f"tiled detection when the aspect ratio is above "
        f"{RETRY_ASPECT_RATIO:g}, or a x2 upscale when the long side is under "
        f"{RETRY_UPSCALE_BELOW} px. Its results replace the first pass only if",
        "a heading appears. Fast mode stays off here, so the retry is the only",
        "difference between the two runs.",
        "",
        "| image | size | aspect | condition | blocks off | blocks on | used | CER off | CER on | Δ CER | recall off | recall on | Δ recall | added s |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        if row.get("on") is None:
            continue
        before, after = row["off"], row["on"]
        used = "kept" if row["retry"].get("used") else "discarded"
        delta_cer = ("n/a" if row["delta_cer_pp"] is None
                     else f"{row['delta_cer_pp']:+.2f} pp")
        delta_recall = ("n/a" if row["delta_recall"] is None
                        else f"{row['delta_recall']:+.3f}")
        md.append(
            f"| {row['image']} | {row['size']} | {row['aspect']} | "
            f"{row['condition']} | {before['blocks_kept']} | "
            f"{after['blocks_kept']} | {used} | "
            f"{_cer_cell(before)} | {_cer_cell(after)} | "
            f"{delta_cer} | {_recall_cell(before)} | "
            f"{_recall_cell(after)} | {delta_recall} | "
            f"{row['added_seconds']} |")
    skipped = [row["image"] for row in rows if row.get("on") is None]
    if skipped:
        md += ["", f"No retry needed (heading found on the first pass): "
               f"{', '.join(skipped)}."]
    md.append("")

    section = "\n".join(md)
    if report_path.exists():
        text = report_path.read_text(encoding="utf-8")
        marker = "## No-heading retry effect"
        if marker in text:
            text = text[:text.index(marker)]
        text = text.rstrip("\n") + "\n\n" + section + "\n"
        report_path.write_text(text, encoding="utf-8")
        print(f"updated {report_path}")


if __name__ == "__main__":
    sys.exit(main())
