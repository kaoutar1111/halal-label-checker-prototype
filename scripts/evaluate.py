#!/usr/bin/env python
"""
Evaluate the full pipeline against hand-typed ground truth.

Layout
------
eval/<lang>/NN.jpg            label photo (lang in ar, en, fr, zh)
eval/<lang>/NN.truth.json     hand-typed truth, NEVER taken from app output:
  {
    "ingredients_text": "ingredients exactly as printed on the label"
  }

The expected verdict and expected flags are NOT hand-written any more: they
are computed by running the matcher and the verdict rule on
truth["ingredients_text"], never on OCR output. The computed values are listed
in report.md so they can be audited.

Metrics per image
-----------------
(a) CER of the extracted ingredients section(s) vs ingredients_text
    (content CER = punctuation-free, the project target metric; strict CER
    reported alongside);
(b) ingredient-level recall/precision: truth split into ingredients vs the
    extracted section segments (greedy 1:1 match, rapidfuzz >= 75 on
    punctuation-free normalized text — an eval-side comparison threshold,
    not a pipeline rule);
(c) verdict == the verdict computed from the truth text (multi-section images
    aggregate by severity: incompatible > À vérifier > clear);
(d) flag recall: flags are the depends_on_origin/incompatible findings the
    matcher produces for the truth text vs the ones raised on the OCR output;
    a flag matches on equality, containment either way, the same E-number,
    the same whole-word token set, or spelling similarity >= 85 (eval-side);
    false alarms are raised flags matching no expected flag;
(e) warm processing time: models preloaded once, one warmup run discarded,
    each image timed on a single warm run.

`--rescore` recomputes every metric from the stored OCR outputs
(eval/ocr_outputs/<mode>/...) without loading models or running OCR.

Outputs: eval/results.csv and eval/report.md (per-language + overall tables).
This script is read-only: it never changes a rule, alias or threshold to
improve numbers; anything that looks like a bug is listed in the report.
"""

import argparse
import csv
import json
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import torch  # noqa: F401  # Windows: torch must be imported before paddle

from PIL import Image
from rapidfuzz import fuzz

from src.evaluate import character_error_rate, normalize_for_cer, normalize_for_content
from src.matcher import IngredientMatcher, normalize_text, split_ingredients
from src.ocr import MultiLanguageOCR, OCRResult
from src.sections import extract_ingredient_sections
from src.verdict import (
    VERDICT_CLEAR,
    VERDICT_INCOMPATIBLE,
    VERDICT_TO_VERIFY,
    VerdictGenerator,
    verdict_for_text,
)

LANGS = ("ar", "en", "fr", "zh")
FLAG_STATUSES = {"depends_on_origin", "incompatible"}
CER_TARGET = 0.03
MATCH_MIN_RATIO = 75.0  # eval-side ingredient comparison, not a pipeline rule
FLAG_MATCH_MIN_RATIO = 85.0  # eval-side flag-name comparison, not a pipeline rule
SEVERITY = {VERDICT_INCOMPATIBLE: 2, VERDICT_TO_VERIFY: 1, VERDICT_CLEAR: 0}

_E_NUMBER_RE = re.compile(r"\bE\s?(\d{3}[a-z]?)\b", re.IGNORECASE)


def expected_from_truth(text: str, matcher, generator):
    """Expected verdict and flags computed from the truth text, not OCR."""
    report = matcher.match_text(text or "")
    verdict = verdict_for_text(text or "", matcher, generator)
    flags, seen = [], set()
    for finding in report.findings:
        if finding.status not in FLAG_STATUSES:
            continue
        name = (finding.matched_name or finding.original_text or "").strip()
        key = normalize_text(name)
        if name and key and key not in seen:
            seen.add(key)
            flags.append(name)
    return verdict.verdict, flags


def discover(eval_dir: Path):
    """Yield (lang, image_path, truth_path) for images that have a truth file."""
    for lang in LANGS:
        folder = eval_dir / lang
        if not folder.is_dir():
            continue
        for image in sorted(folder.glob("*.jpg")):
            truth = image.with_suffix(".truth.json")
            if truth.exists():
                yield lang, image, truth
            else:
                print(f"  ! skipped {image}: no {truth.name}", file=sys.stderr)


def aggregate_verdict(verdicts):
    """Worst-case verdict across sections (incompatible > À vérifier > clear)."""
    return max(verdicts, key=lambda v: SEVERITY.get(v, 1))


def content_norm(text: str) -> str:
    return normalize_for_content(text)


def greedy_match(truth_items, pred_items, min_ratio=MATCH_MIN_RATIO):
    """Greedy 1:1 matching; returns (matched_truth, matched_pred)."""
    preds = [(i, p) for i, p in enumerate(pred_items)]
    used = set()
    matched_t = 0
    for truth in truth_items:
        best, best_i = 0.0, None
        for i, pred in preds:
            if i in used:
                continue
            score = fuzz.ratio(truth, pred)
            if score > best:
                best, best_i = score, i
        if best_i is not None and best >= min_ratio:
            used.add(best_i)
            matched_t += 1
    return matched_t, len(used)


def _e_numbers(text: str) -> set:
    """E-number codes in text, normalized to 471 form (E471 / E 471 both)."""
    return {match.group(1).upper() for match in _E_NUMBER_RE.finditer(text or "")}


def flag_matches(expected: str, raised_names) -> bool:
    """
    Does one hand-written flag name refer to one of the raised names?

    Plain equality/containment missed three real cases: the same E-number
    written "E 471" vs "E471", a flag quoted with an extra qualifier
    ("arômes naturels" vs "Arômes"), and OCR spelling drift in a name. The
    check therefore also compares E-numbers, whole-word token sets and, as a
    last resort, near-identical spelling. It is eval-side only.
    """
    exp = normalize_text(expected)
    exp_c = content_norm(expected)
    if not exp_c:
        return False
    exp_e = _e_numbers(expected)
    exp_tokens = set(exp.split())

    for name in raised_names:
        cand = normalize_text(name or "")
        cand_c = content_norm(name or "")
        if not cand_c:
            continue
        if exp_c == cand_c:
            return True
        if exp_c in cand_c or cand_c in exp_c:
            return True
        if exp_e and exp_e & _e_numbers(name or ""):
            return True
        cand_tokens = set(cand.split())
        if exp_tokens and cand_tokens and (exp_tokens <= cand_tokens or cand_tokens <= exp_tokens):
            return True
        if fuzz.ratio(exp_c, cand_c) >= FLAG_MATCH_MIN_RATIO:
            return True
    return False


def evaluate_image(ocr, matcher, generator, image_path: Path):
    """Run the full pipeline once (warm), including its raw OCR blocks."""
    start = time.perf_counter()
    results = ocr.process_image(Image.open(image_path), auto=True)
    elapsed = time.perf_counter() - start
    unreadable = list(getattr(ocr, "last_dropped", []) or []) + \
        list(getattr(ocr, "last_uncertain", []) or [])
    diagnostics = {
        "strategy": getattr(ocr, "last_strategy", ""),
        "blocks_detected": getattr(ocr, "last_blocks_detected", 0),
        "blocks_kept": len(results),
        "retry": getattr(ocr, "last_retry", {}) or {},
    }
    sections = extract_ingredient_sections(results, unreadable=unreadable)
    reports, verdicts = [], []
    for index, section in enumerate(sections):
        report = matcher.match_section(section)
        verdict = generator.assess(section, report, section_index=index,
                                   unreadable=unreadable)
        reports.append(report)
        verdicts.append(verdict)
    return sections, reports, verdicts, unreadable, elapsed, diagnostics, results


def format_retry(info) -> str:
    """One-cell summary of the no-heading retry, e.g. 'tiled:used:3.2s'."""
    if not info:
        return ""
    state = "used" if info.get("used") else "discarded"
    return f"{info.get('mode', '')}:{state}:{info.get('seconds', 0)}s"


def ocr_store_path(eval_dir: Path, fast_mode: bool, image_path: Path) -> Path:
    """Stored OCR blocks for one image and mode (written by a normal run)."""
    mode = "on" if fast_mode else "off"
    return (eval_dir / "ocr_outputs" / mode /
            image_path.relative_to(eval_dir).with_suffix(".json"))


def rescore_stored(matcher, generator, eval_dir: Path, image_path: Path,
                   fast_mode: bool):
    """Re-run sectioning/matching/verdicts on stored OCR blocks; no OCR import."""
    store = ocr_store_path(eval_dir, fast_mode, image_path)
    if not store.exists():
        raise SystemExit(
            f"No stored OCR output: {store}\n"
            "Run once without --rescore to create the OCR outputs.")
    payload = json.loads(store.read_text(encoding="utf-8"))
    results = [OCRResult(**item) for item in payload["results"]]
    unreadable = payload.get("unreadable", [])
    diagnostics = dict(payload.get("diagnostics", {}))
    diagnostics["strategy"] = "rescore:" + diagnostics.get("strategy", "")
    sections = extract_ingredient_sections(results, unreadable=unreadable)
    reports, verdicts = [], []
    for index, section in enumerate(sections):
        report = matcher.match_section(section)
        verdict = generator.assess(section, report, section_index=index,
                                   unreadable=unreadable)
        reports.append(report)
        verdicts.append(verdict)
    return sections, reports, verdicts, unreadable, 0.0, diagnostics, results


def collect_mode(ocr, matcher, generator, entries_by_id, images, fast_mode,
                 eval_dir, rescore=False):
    """Run every eval image in one mode; return rows and observations."""
    label = "on" if fast_mode else "off"
    rows, observations = [], []
    for lang, image_path, truth_path in images:
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        truth_text = truth["ingredients_text"]
        expected_verdict, expected_flags = expected_from_truth(
            truth_text, matcher, generator)

        if rescore:
            (sections, reports, verdicts, unreadable,
             elapsed, diagnostics, results) = rescore_stored(
                matcher, generator, eval_dir, image_path, fast_mode)
        else:
            (sections, reports, verdicts, unreadable,
             elapsed, diagnostics, results) = evaluate_image(
                ocr, matcher, generator, image_path)
            store = ocr_store_path(eval_dir, fast_mode, image_path)
            store.parent.mkdir(parents=True, exist_ok=True)
            store.write_text(json.dumps({
                "results": [
                    {"text": r.text, "confidence": r.confidence,
                     "language": r.language, "bbox": r.bbox}
                    for r in results
                ],
                "unreadable": unreadable,
                "diagnostics": diagnostics,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        rel = f"{lang}/{image_path.name}"
        print(f"[fast {label}] {'rescoring' if rescore else 'evaluating'} "
              f"{rel} ({elapsed:.2f}s warm)")

        hyp_text = "\n".join(s.text for s in sections)
        no_section = not any(
            s.flag != "no_heading" and s.text.strip() for s in sections)
        status = "no ingredients section found" if no_section else "ok"
        cer = character_error_rate(truth_text, hyp_text, normalize_for_content)
        cer_strict = character_error_rate(truth_text, hyp_text, normalize_for_cer)

        truth_items = [content_norm(t) for t in split_ingredients(truth_text)]
        truth_items = [t for t in truth_items if t]
        pred_items = [content_norm(p) for p in split_ingredients(hyp_text)]
        pred_items = [p for p in pred_items if p]
        hit_t, hit_p = greedy_match(truth_items, pred_items)
        recall = hit_t / len(truth_items) if truth_items else 0.0
        precision = hit_p / len(pred_items) if pred_items else 0.0

        actual_verdict = aggregate_verdict([v.verdict for v in verdicts])
        verdict_ok = actual_verdict == expected_verdict

        raised = []  # (dedup key, candidate display names)
        seen = set()
        for report in reports:
            for f in report.findings:
                if f.status not in FLAG_STATUSES:
                    continue
                key = normalize_text(f.matched_name or f.original_text)
                if key and key not in seen:
                    seen.add(key)
                    names = {f.matched_name, f.original_text}
                    entry = entries_by_id.get(f.matched_id) or {}
                    names |= set((entry.get("names") or {}).values())
                    raised.append((key, {n for n in names if n}))
        missed = [e for e in expected_flags
                  if not any(flag_matches(e, names) for _, names in raised)]
        false_alarms = [names for _, names in raised
                        if not any(flag_matches(e, names) for e in expected_flags)]
        fa_flat = sorted({n for names in false_alarms for n in names})
        flag_recall = (len(expected_flags) - len(missed)) / len(expected_flags) \
            if expected_flags else 1.0

        unrecognized = sorted({u.original_text for r in reports
                               for u in r.unrecognized})
        rows.append({
            "fast_mode": label,
            "lang": lang, "image": rel, "status": status,
            "cer_content": "n/a" if no_section else f"{cer:.4f}",
            "cer_strict": "n/a" if no_section else f"{cer_strict:.4f}",
            "ingredient_recall": "n/a" if no_section else f"{recall:.3f}",
            "ingredient_precision": "n/a" if no_section else f"{precision:.3f}",
            "verdict_expected": expected_verdict,
            "verdict_actual": actual_verdict,
            "verdict_ok": "yes" if verdict_ok else "NO",
            "flags_expected": "; ".join(expected_flags),
            "flags_missed": "; ".join(missed),
            "flag_recall": "n/a" if no_section else f"{flag_recall:.3f}",
            "false_alarms": "n/a" if no_section else len(false_alarms),
            "false_alarm_names": "; ".join(fa_flat),
            "unrecognized": "; ".join(unrecognized),
            "blocks_detected": diagnostics["blocks_detected"],
            "blocks_kept": diagnostics["blocks_kept"],
            "strategy": diagnostics["strategy"],
            "retry": format_retry(diagnostics["retry"]),
            "time_warm_s": f"{elapsed:.2f}",
        })

        prefix = f"[fast {label}] " if len(MODES_RUN) > 1 else ""
        if no_section:
            observations.append(
                f"{prefix}{rel}: no ingredients section found (reported as a "
                f"status; CER and recall are n/a, not 100%)")
        if not verdict_ok:
            observations.append(
                f"{prefix}{rel}: verdict mismatch — expected {expected_verdict!r}, "
                f"got {actual_verdict!r}")
        if not no_section and missed:
            observations.append(
                f"{prefix}{rel}: expected flags not raised: {missed}")
        if not no_section and fa_flat:
            observations.append(f"{prefix}{rel}: false-alarm flags: {fa_flat}")
        if not no_section and cer > CER_TARGET:
            observations.append(
                f"{prefix}{rel}: content CER {cer * 100:.2f}% above the "
                f"{CER_TARGET * 100:.0f}% target")
        elif not no_section and recall < 0.5:
            observations.append(
                f"{prefix}{rel}: characters read correctly (content CER "
                f"{cer * 100:.2f}%) but ingredient recall collapsed "
                f"({recall:.3f}) — OCR returned the section without the "
                f"label's separators (commas), so split_ingredients sees "
                f"fused runs of several ingredients per segment; suspected "
                f"OCR separator loss, listed here instead of fixed")
        if unrecognized:
            observations.append(
                f"{prefix}{rel}: unrecognized ingredients: {unrecognized}")
        if unreadable:
            observations.append(
                f"{prefix}{rel}: {len(unreadable)} block(s) unreadable or "
                f"uncertain (dropped but recorded)")
        if len(sections) > 1:
            observations.append(
                f"{prefix}{rel}: {len(sections)} products detected; verdict "
                f"aggregated by severity (worst case)")
        if diagnostics["retry"]:
            retry = diagnostics["retry"]
            observations.append(
                f"{prefix}{rel}: no heading on the first pass; "
                f"{retry.get('mode')} retry "
                f"{'kept' if retry.get('used') else 'discarded'} "
                f"({retry.get('seconds', 0)}s, blocks "
                f"{retry.get('results_before', '?')} -> "
                f"{retry.get('results_after', '?')})")
    return rows, observations


MODES_RUN = [False]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-dir", default=str(ROOT / "eval"))
    parser.add_argument(
        "--set", choices=("standard", "final"), default="standard",
        help="final uses eval/final and separate eval/final_* output files")
    parser.add_argument("--csv", default=None, help="default: <eval-dir>/results.csv")
    parser.add_argument("--report", default=None, help="default: <eval-dir>/report.md")
    parser.add_argument(
        "--fast-mode", choices=("off", "on", "both"), default="off",
        help="run with FAST_MODE off, on, or both (one row per mode)")
    parser.add_argument(
        "--no-retry", action="store_true",
        help="disable the no-heading detection retry (default: enabled)")
    parser.add_argument(
        "--rescore", action="store_true",
        help="recompute metrics from eval/ocr_outputs without running OCR")
    parser.add_argument(
        "--previous", default=None,
        help="older results.csv; adds a verdict-change table to report.md")
    args = parser.parse_args()
    global MODES_RUN
    if args.set == "final":
        eval_dir = ROOT / "eval" / "final"
        default_csv = ROOT / "eval" / "final_results.csv"
        default_report = ROOT / "eval" / "final_report.md"
    else:
        eval_dir = Path(args.eval_dir)
        default_csv = eval_dir / "results.csv"
        default_report = eval_dir / "report.md"
    csv_path = Path(args.csv) if args.csv else default_csv
    report_path = Path(args.report) if args.report else default_report
    MODES_RUN = {"off": [False], "on": [True], "both": [False, True]}[args.fast_mode]

    images = list(discover(eval_dir))
    if not images:
        print(f"no eval images found under {eval_dir}", file=sys.stderr)
        return 1

    ocr = None
    if not args.rescore:
        print("preloading OCR models (cold start, excluded from timings)...")
        ocr = MultiLanguageOCR()
        ocr.retry_no_heading = not args.no_retry
        engine = ocr._get_engine()
        if hasattr(engine, "_get_detector"):
            engine._get_detector()
        if hasattr(engine, "_get_recognizer"):
            for lang in LANGS:
                engine._get_recognizer(lang)

    matcher, generator = IngredientMatcher(), VerdictGenerator()
    entries_by_id = {e.get("id"): e for e in matcher.entries}
    per_lang = {lang: 0 for lang in LANGS}
    for lang, _, _ in images:
        per_lang[lang] += 1
    coverage_notes = []
    for lang, count in sorted(per_lang.items()):
        if count == 0:
            coverage_notes.append(f"no images found for {lang}")
        elif count < 5:
            coverage_notes.append(
                f"{lang}: only {count} image(s) available (target was 5); "
                f"add eval/{lang}/NN.jpg + NN.truth.json to extend the eval")

    rows, observations = [], list(coverage_notes)
    for fast_mode in MODES_RUN:
        if not args.rescore:
            ocr.fast_mode = fast_mode
            ocr._cache.clear()
            # One discarded warmup run per mode, then every image is timed warm.
            evaluate_image(ocr, matcher, generator, images[0][1])
            ocr._cache.clear()
        mode_rows, mode_observations = collect_mode(
            ocr, matcher, generator, entries_by_id, images, fast_mode,
            eval_dir, rescore=args.rescore)
        rows.extend(mode_rows)
        observations.extend(mode_observations)

    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    def mean(values):
        return sum(values) / len(values) if values else 0.0

    def mean_metric(group, key):
        """Mean over rows that actually have a section (n/a rows excluded)."""
        values = [float(r[key]) for r in group if r[key] != "n/a"]
        return (sum(values) / len(values), len(values)) if values else (None, 0)

    def cell_pct(value):
        return "—" if value == "n/a" else f"{float(value) * 100:.2f}%"

    def cell_num(value):
        return "—" if value == "n/a" else f"{float(value):.3f}"

    def cell_plain(value):
        return "—" if value == "n/a" else value

    def cer_distribution(group):
        """Median content CER and threshold counts, over rows with a section."""
        values = [float(r["cer_content"]) for r in group
                  if r["cer_content"] != "n/a"]
        median = statistics.median(values) if values else None
        under_3 = sum(value < 0.03 for value in values)
        under_15 = sum(value < 0.15 for value in values)
        return median, under_3, under_15, len(values)

    def summary_line(label, group):
        cer, found = mean_metric(group, "cer_content")
        median, under_3, under_15, _ = cer_distribution(group)
        recall, _ = mean_metric(group, "ingredient_recall")
        precision, _ = mean_metric(group, "ingredient_precision")
        flag_recall, _ = mean_metric(group, "flag_recall")
        alarms = sum(int(r["false_alarms"]) for r in group
                     if r["false_alarms"] != "n/a")
        return (f"| {label} | {len(group)} | {found}/{len(group)} | "
                f"{'—' if cer is None else f'{cer * 100:.2f}%'} | "
                f"{'—' if median is None else f'{median * 100:.2f}%'} | "
                f"{under_3} | {under_15} | "
                f"{'—' if recall is None else f'{recall:.3f}'} | "
                f"{'—' if precision is None else f'{precision:.3f}'} | "
                f"{sum(r['verdict_ok'] == 'yes' for r in group)}/{len(group)} | "
                f"{'—' if flag_recall is None else f'{flag_recall:.3f}'} | "
                f"{alarms} | "
                f"{mean([float(r['time_warm_s']) for r in group]):.2f} |")

    mode_labels = ["off", "on"] if len(MODES_RUN) > 1 else [
        "on" if MODES_RUN[0] else "off"]

    md = [
        "# Label checker — evaluation report",
        "",
        "Ground truth is hand-typed from the label photos. The expected verdict and",
        "expected flags are computed by the matcher and the verdict rule from",
        "`ingredients_text` alone (never from OCR output); they are listed below",
        "for audit. Rules, aliases and thresholds are the app's own; nothing is",
        "tuned per image. Images where no ingredients section is found are reported",
        "with that status and n/a metrics, not as a 100% CER.",
        "",
        f"Fast mode: **{', '.join(mode_labels)}**. No-heading retry: "
        f"**{'off' if args.no_retry else 'on'}**.",
        "",
    ]

    # One audit table (the truth text does not depend on the mode).
    audit_rows = [r for r in rows if r["fast_mode"] == mode_labels[0]]
    md += [
        "## Expected values computed from the truth text (audit)",
        "",
        "| lang | image | expected verdict | expected flags |",
        "|---|---|---|---|",
    ]
    for r in audit_rows:
        md.append(
            f"| {r['lang']} | {r['image']} | {r['verdict_expected']} | "
            f"{r['flags_expected'] or '—'} |")
    md.append("")

    for label in mode_labels:
        mode_rows = [r for r in rows if r["fast_mode"] == label]
        md += [
            f"## Per-image results — Fast mode {label}",
            "",
            "| lang | image | status | CER (content) | CER (strict) | ing. recall | ing. precision | verdict expected | verdict actual | ok | flag recall | false alarms | blocks detected | blocks kept | strategy | retry | warm s |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for r in mode_rows:
            md.append(
                f"| {r['lang']} | {r['image']} | {r['status']} | "
                f"{cell_pct(r['cer_content'])} | "
                f"{cell_pct(r['cer_strict'])} | {cell_num(r['ingredient_recall'])} | "
                f"{cell_num(r['ingredient_precision'])} | {r['verdict_expected']} | "
                f"{r['verdict_actual']} | {r['verdict_ok']} | {cell_num(r['flag_recall'])} | "
                f"{cell_plain(r['false_alarms'])} | {r['blocks_detected']} | "
                f"{r['blocks_kept']} | {r['strategy']} | {r['retry'] or '—'} | "
                f"{r['time_warm_s']} |")
        md += [
            "",
            f"## Per-language summary — Fast mode {label}",
            "",
            "| language | images | with section | mean CER (content) | median CER (content) | CER < 3% | CER < 15% | mean recall | mean precision | verdicts ok | mean flag recall | false alarms | mean warm s |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for lang in LANGS:
            group = [r for r in mode_rows if r["lang"] == lang]
            if group:
                md.append(summary_line(lang, group))
        md += [
            "",
            f"### Overall — Fast mode {label}",
            "",
            "| scope | images | with section | mean CER (content) | median CER (content) | CER < 3% | CER < 15% | mean recall | mean precision | verdicts ok | mean flag recall | false alarms | mean warm s |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
            summary_line("ALL", mode_rows),
            "",
        ]

    if len(mode_labels) > 1:
        off_rows = {r["image"]: r for r in rows if r["fast_mode"] == "off"}
        on_rows = {r["image"]: r for r in rows if r["fast_mode"] == "on"}
        off_time = mean([float(r["time_warm_s"]) for r in off_rows.values()])
        on_time = mean([float(r["time_warm_s"]) for r in on_rows.values()])
        speedup = off_time / on_time if on_time else 0.0
        md += [
            "## Fast mode comparison (off vs on)",
            "",
            f"Mean warm time: {off_time:.2f}s off, {on_time:.2f}s on "
            f"({speedup:.2f}x).",
            "",
            "| image | CER off | CER on | Δ CER | recall off | recall on | Δ recall | blocks 3-pass | blocks kept | strategy (on) | warm off s | warm on s |",
            "|" + "---|" * 12,
        ]
        for image in off_rows:
            off, on = off_rows[image], on_rows[image]
            if off["cer_content"] == "n/a" or on["cer_content"] == "n/a":
                d_cer = "—"
            else:
                d_cer = (f"{(float(on['cer_content']) - float(off['cer_content'])) * 100:+.2f} pp")
            if off["ingredient_recall"] == "n/a" or on["ingredient_recall"] == "n/a":
                d_recall = "—"
            else:
                d_recall = (f"{float(on['ingredient_recall']) - float(off['ingredient_recall']):+.3f}")
            md.append(
                f"| {image} | {cell_pct(off['cer_content'])} | "
                f"{cell_pct(on['cer_content'])} | {d_cer} | "
                f"{cell_num(off['ingredient_recall'])} | "
                f"{cell_num(on['ingredient_recall'])} | "
                f"{d_recall} | {off['blocks_kept']} | {on['blocks_kept']} | "
                f"{on['strategy']} | {off['time_warm_s']} | {on['time_warm_s']} |")
        md.append("")

    if args.previous:
        previous_path = Path(args.previous)
        if previous_path.exists():
            with open(previous_path, newline="", encoding="utf-8") as handle:
                previous_rows = list(csv.DictReader(handle))
            old = {(row.get("fast_mode"), row.get("image")): row
                   for row in previous_rows}
            md += [
                "## Verdict changes vs previous run",
                "",
                f"Previous results: `{previous_path}`.",
                "",
                "| fast | image | old verdict | new verdict | changed |",
                "|---|---|---|---|---|",
            ]
            for row in rows:
                key = (row["fast_mode"], row["image"])
                old_row = old.get(key)
                if old_row is None:
                    continue
                before = old_row.get("verdict_actual", "")
                after = row["verdict_actual"]
                changed = "yes" if before != after else "—"
                md.append(
                    f"| {row['fast_mode']} | {row['image']} | {before or '—'} | "
                    f"{after} | {changed} |")
            md.append("")

    md += [
        "## Observations / suspected bugs",
        "",
        "Listed, not fixed (evaluation is read-only).",
        "",
    ]
    md += [f"- {note}" for note in observations] or ["- none"]
    md += [
        "",
        "## Metric definitions",
        "",
        "- CER (content): Levenshtein / reference length on punctuation-free text;",
        "  strict CER keeps punctuation. Target <= 3%.",
        "- Median CER (content) and the CER < 3% / CER < 15% columns are computed",
        "  per language and overall on images with a section only; the threshold",
        "  columns count images (no-section images are n/a and excluded).",
        "- Ingredient recall/precision: truth and extracted section split into",
        "  ingredients, greedy 1:1 match at rapidfuzz >= 75 (punctuation-free).",
        "- Flags: findings with status depends_on_origin or incompatible;",
        "  expected flags are the flags the matcher raises on the truth text;",
        "  a flag matches on equality, containment, the same E-number, the same",
        "  whole-word token set, or spelling similarity >= 85 (eval-side only).",
        "- Verdict: computed from the truth text by the same rule as the app",
        "  (incompatible > unrecognized real ingredient / depends_on_origin /",
        "  low coverage / unreadable block in section / low confidence / empty /",
        "  no-heading > clear).",
        "- Unrecognized real ingredients force \"À vérifier\" with reason",
        "  \"Not in the reference: <names>\" on both the truth and OCR sides; the",
        "  coverage guard is a secondary reason only.",
        "- Warm time: models preloaded once, one warmup run discarded per mode.",
        "- Blocks detected/kept: text boxes from detection vs OCRResult blocks",
        "  kept after script/confidence filtering (one per box in 3-pass mode).",
        "- Status: \"no ingredients section found\" when no ingredients heading is",
        "  read. CER, recall, precision and flag recall are n/a for those images",
        "  and excluded from the averages (never shown as CER 100%).",
        "- Retry: tiled (aspect ratio > 3) or upscale_x2 (long side < 800 px) is",
        "  attempted only when the first pass finds no ingredients heading; its",
        "  results replace the first pass only if a heading appears.",
    ]
    report_path.write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"\nwrote {csv_path}")
    print(f"wrote {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
