"""Block-level diagnostic for a single label image.

Usage (fresh OCR, needs model load):
    python scripts/diagnose_blocks.py eval/en/07.jpg --fast-mode on
Usage (from stored OCR, no model load):
    python scripts/diagnose_blocks.py --from-store on en 01

Prints, per block: detection index, reading-order index, line index, bbox,
text, confidence, model (engine:language), kept/dropped + reason, and which
section(s) it belongs to. Then the final section text passed to the matcher,
and a reading-order analysis comparing three within-line orderings:
  A = raw detection order (as returned by the engine)
  B = build_reading_order (x-sorted within line; used by the CLI display and
      the Arabic merge path)
  C = section text order (line-grouped by y-centre, x-sorted within line, RTL
      for mostly-Arabic lines; what the matcher sees)
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LINE_HEIGHT_THRESHOLD = 20


def center(bbox):
    if not bbox:
        return 0.0, 0.0
    if isinstance(bbox[0], (list, tuple)) or hasattr(bbox[0], "__len__"):
        xs = [p[0] for p in bbox]; ys = [p[1] for p in bbox]
        return sum(xs) / len(xs), sum(ys) / len(ys)
    if len(bbox) >= 4:
        return (bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0
    return 0.0, 0.0


def assign_lines(results):
    """Replicate build_reading_order line grouping: return line index per
    result (by id()) and the ordered (line_idx, pos_in_line, result) list."""
    positioned = []
    no_pos = []
    for i, r in enumerate(results):
        cx, cy = center(getattr(r, "bbox", None))
        if getattr(r, "bbox", None):
            positioned.append((i, r, cx, cy))
        else:
            no_pos.append((i, r))
    positioned.sort(key=lambda t: t[3])  # by y
    lines = []
    cur = []
    cur_y = None
    for item in positioned:
        _, _, _, y = item
        if cur_y is None:
            cur_y = y; cur.append(item)
        elif abs(y - cur_y) <= LINE_HEIGHT_THRESHOLD:
            cur.append(item)
        else:
            lines.append(cur); cur = [item]; cur_y = y
    if cur:
        lines.append(cur)
    line_of = {}
    ordered = []
    for li, line in enumerate(lines):
        line_sorted = sorted(line, key=lambda t: t[2])  # by x
        for pi, (i, r, cx, cy) in enumerate(line_sorted):
            line_of[id(r)] = (li, pi)
            ordered.append((li, pi, r))
    for i, r in no_pos:
        line_of[id(r)] = (-1, -1)
        ordered.append((-1, -1, r))
    return line_of, ordered


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image", nargs="?", help="image path, e.g. eval/en/07.jpg")
    ap.add_argument("--fast-mode", choices=("on", "off"), default="on")
    ap.add_argument("--from-store", nargs=3, metavar=("mode", "lang", "num"))
    ap.add_argument("--out", help="write output to this file instead of stdout")
    args = ap.parse_args()

    if args.from_store:
        mode, lang, num = args.from_store
        from src.ocr import OCRResult
        p = ROOT / "eval" / "ocr_outputs" / mode / lang / f"{num}.json"
        payload = json.loads(p.read_text(encoding="utf-8"))
        results = [OCRResult(**r) for r in payload["results"]]
        unreadable = payload.get("unreadable", [])
        diag = dict(payload.get("diagnostics", {}))
        diag["engine"] = diag.get("engine", "stored")
        source = f"store {mode}/{lang}/{num} ({p})"
    elif args.image:
        import torch  # noqa: F401  (Windows: torch before paddle)
        from PIL import Image
        from src.ocr import MultiLanguageOCR
        ocr = MultiLanguageOCR(fast_mode=(args.fast_mode == "on"),
                               retry_no_heading=True)
        engine = ocr._get_engine()
        results = ocr.process_image(Image.open(args.image), auto=True)
        engine_name = getattr(ocr, "_engine_name", None) or type(engine).__name__
        unreadable = list(getattr(ocr, "last_dropped", []) or []) + \
            list(getattr(ocr, "last_uncertain", []) or [])
        diag = {
            "strategy": getattr(ocr, "last_strategy", ""),
            "blocks_detected": getattr(ocr, "last_blocks_detected", len(results)),
            "engine": engine_name,
            "retry": getattr(ocr, "last_retry", {}),
        }
        source = f"fresh {args.image} (fast {args.fast_mode})"
    else:
        ap.error("provide an image path (e.g. eval/en/07.jpg) or --from-store")

    from src.sections import extract_ingredient_sections
    from src.utils import build_reading_order

    sections = extract_ingredient_sections(results, unreadable=unreadable)
    _, ordered = build_reading_order(results, rtl_languages=["ar"])
    reading_idx = {id(r): i for i, r in enumerate(ordered)}
    line_of, line_ordered = assign_lines(results)
    det_idx = {id(r): i for i, r in enumerate(results)}

    # Map each kept block -> section index + position-in-section (y-sorted)
    sec_of = {}
    for si, sec in enumerate(sections):
        for pi, blk in enumerate(sec.blocks):
            sec_of.setdefault(id(blk), []).append((si, pi))
    # section final text
    sec_texts = [s.text for s in sections]

    out = []
    def p(s=""): out.append(s)

    p(f"# Block diagnostic — {source}")
    p(f"strategy={diag.get('strategy')} engine={diag.get('engine')} "
      f"blocks_detected={diag.get('blocks_detected')} kept={len(results)} "
      f"dropped/uncertain={len(unreadable)}")
    p(f"sections={len(sections)}")
    p()
    p("## Kept blocks (reading-order sorted)")
    p("| ro | det | line | pos | bbox | text | conf | lang | model | section |")
    p("|---|---|---|---|---|---|---|---|---|---|")
    for ro_i, r in enumerate(ordered):
        li, pi = line_of.get(id(r), (-1, -1))
        cx, cy = center(getattr(r, "bbox", None))
        di = det_idx.get(id(r), -1)
        secs = ",".join(f"s{si}[{pi}]" for si, pi in sec_of.get(id(r), [])) or "-"
        model = f"{diag.get('engine')}:{r.language}"
        p(f"| {ro_i} | {di} | {li} | {pi} | {r.bbox} | "
          f"{r.text!r} | {r.confidence:.3f} | {r.language} | {model} | {secs} |")
    p()
    p("## Dropped / uncertain blocks")
    p("| # | bbox | text | conf | reason | model |")
    p("|---|---|---|---|---|---|")
    for i, e in enumerate(unreadable):
        if isinstance(e, dict):
            p(f"| {i} | {e.get('bbox')} | {e.get('text')!r} | "
              f"{float(e.get('confidence') or 0):.3f} | {e.get('reason')!r} | "
              f"{diag.get('engine')} |")
        else:
            p(f"| {i} | {getattr(e,'bbox',None)} | {getattr(e,'text',None)!r} | "
              f"{getattr(e,'confidence',0):.3f} | {getattr(e,'reason','')!r} | "
              f"{diag.get('engine')} |")
    p()
    p("## Final section text passed to the matcher")
    for si, t in enumerate(sec_texts):
        p(f"--- section {si} (flag={sections[si].flag}, "
          f"lang={sections[si].language}, blocks={len(sections[si].blocks)}) ---")
        p(t)
    p()

    # Reading-order analysis: within-line reversals
    p("## Reading-order analysis (within-line)")
    p("For each line with >1 block, comparing: detection order (A), "
      "reading/x order (B), and section text order (C).")
    # group line_ordered by line index
    by_line = {}
    for li, pi, r in line_ordered:
        if li < 0:
            continue
        by_line.setdefault(li, []).append((pi, r))
    reversals = []
    for li in sorted(by_line):
        blocks = by_line[li]
        if len(blocks) < 2:
            continue
        # x order = sorted by pi (already)
        x_order = [r for _, r in blocks]
        # detection order among these
        det_order = sorted(x_order, key=lambda r: det_idx.get(id(r), 1e9))
        # section order: sort by min section position; blocks not in any
        # section keep detection order
        def sec_key(r):
            s = sec_of.get(id(r))
            return (s[0][0], s[0][1]) if s else (999, det_idx.get(id(r), 1e9))
        sec_order = sorted(x_order, key=sec_key)
        x_texts = [r.text for r in x_order]
        det_texts = [r.text for r in det_order]
        sec_texts_l = [r.text for r in sec_order]
        if x_texts != det_texts or x_texts != sec_texts_l:
            reversals.append((li, x_texts, det_texts, sec_texts_l))
            p(f"- line {li}:")
            p(f"    B (x/read) : {' | '.join(x_texts)}")
            p(f"    A (detect) : {' | '.join(det_texts)}"
              f"{'   <-- detector order != x order' if x_texts != det_texts else ''}")
            p(f"    C (section): {' | '.join(sec_texts_l)}"
              f"{'   <-- section order != x order -> reaches matcher' if x_texts != sec_texts_l else ''}")
    if not reversals:
        p("- no within-line ordering differences detected across A/B/C.")
    p()
    p("## Stage interpretation")
    p("- A is the order the OCR engine returns boxes (detection order).")
    p("- B is build_reading_order (group by y within 20px, sort by x; reverse "
      "RTL). Used by the CLI display and the Arabic merge in ocr.py.")
    p("- C is the order the matcher actually sees: extract_ingredient_sections "
      "line-groups a section's blocks by y-centre (tolerance 0.5x the section's "
      "median box height), sorts by x within a line, and reverses mostly-Arabic "
      "lines. So a printed line split into multiple boxes with slightly "
      "different top-y comes out in true reading order.")

    text = "\n".join(out) + "\n"
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
