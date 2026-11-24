# Halal Label Checker

A local Python prototype for verifying food labels for halal compliance. **This is an aid to verification, NOT a halal certification.**

## Requirements

- **Python 3.11** (recommended) or Python 3.10+
- At least one OCR engine (see Installation)

## Overview

This application helps users verify food labels by:
- Extracting ingredient text from food label images using OCR
- Matching ingredients against a multilingual reference database
- Highlighting ingredients by status (incompatible, to verify, compatible)
- Providing a clear verdict with detailed information

## Supported Languages

- Arabic (ar)
- French (fr)
- English (en)
- Chinese (zh)

## Installation

1. **Create a virtual environment (recommended):**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. **Install dependencies:**
```bash
pip install -r requirements.txt
```

3. **Install an OCR engine** (at least one required):

   **Option A: PaddleOCR** (recommended, more accurate)
   ```bash
   pip install paddlepaddle paddleocr
   ```

   **Option B: EasyOCR** (fallback, easier to install)
   ```bash
   pip install easyocr
   ```

   The app will automatically detect and use the best available engine.

## Usage

### CLI Tool (for testing OCR)

Test OCR on a single image without starting Streamlit:
```bash
python scripts/ocr_check.py samples/label.jpg
python scripts/ocr_check.py samples/label.jpg --languages en,ar
python scripts/ocr_check.py samples/label.jpg --compare-preprocessing
```

### Run the Streamlit application:
```bash
streamlit run app.py
```

The app can receive a label image by uploading a photo or by taking one with
`st.camera_input`. Both inputs use the same OCR, sectioning, matching and
verdict code path.

Browsers only allow the camera on `localhost` or HTTPS. On a phone, the app
must therefore be served over HTTPS, not over plain `http://LAN-IP`.

### Run tests:
```bash
pytest tests/ -v
```

## Project Structure

```
halal-label-checker/
├── app.py                 # Streamlit web application
├── src/
│   ├── ocr.py             # OCR orchestration (backend-agnostic, fast mode, retry)
│   ├── base.py            # OCR engine base class
│   ├── engines/           # PaddleOCR (default) + EasyOCR (fallback) backends
│   ├── preprocess.py      # Image preprocessing (OpenCV)
│   ├── sections.py        # Ingredients-heading detection + section extraction
│   ├── utils.py           # Reading-order reconstruction from bounding boxes
│   ├── matcher.py         # Reference matching (exact + fuzzy + CJK substring)
│   ├── verdict.py         # Verdict generation rules
│   ├── evaluate.py        # CER / metric helpers shared by the eval harness
│   └── db.py              # SQLite database for scan history
├── scripts/
│   ├── ocr_check.py       # CLI tool for OCR testing on a single image
│   └── evaluate.py        # End-to-end evaluation harness
├── data/
│   ├── reference.json     # Ingredient reference database
│   └── function_words.json
├── eval/                  # Evaluation images, ground truth, OCR stores, report
├── tests/                 # Pytest test suite
├── samples/               # Sample food label images
└── README.md
```

## Features

- **Multilingual OCR** (Arabic, French, English, Chinese) with a pluggable
  backend — PaddleOCR by default, EasyOCR as an automatic fallback. A *fast
  mode* combines a language-first probe, batched recognition and a per-image
  cache; a no-heading retry (tiled detection for wide/tall photos, 2× upscale
  for small ones) runs automatically when the first pass finds no ingredients
  heading.
- **Ingredients section extraction** that locates the ingredients heading in
  any of the four languages (excluding nutrition-declaration headings), assigns
  only same-column blocks to the section, cuts the list at nutrition / storage /
  allergen / manufacturer stop markers, reconstructs reading order from the
  bounding boxes (right-to-left for Arabic), and strips allergen annotations
  and vitamin annotations before matching.
- **Reference matching** against `data/reference.json` — **133 ingredient
  entries** (84 compatible, 42 `depends_on_origin`, 7 incompatible) with
  aliases in all four languages. Matching uses Unicode normalization (Arabic
  diacritics and alef variants, Latin accents, full-width punctuation), exact
  whole-word aliases, fuzzy matching (rapidfuzz), substring matching for
  Chinese, and separate E-number resolution. Negated alcohol claims
  ("sans alcool", "不含酒精") never match the alcohol entry.
- **Verdict generation** (see below) with a strict rule for unrecognized
  ingredients, a secondary coverage guard, a disclaimer on every result, and
  ingredients absent from the reference listed for review.
- **Streamlit web app** with upload, OCR display, per-ingredient highlighting
  by status, verdict and reasons, plus a SQLite-backed scan history.
- **Evaluation harness** (`scripts/evaluate.py`) measuring character error
  rate, ingredient recall/precision, verdict accuracy and flag recall against
  hand-typed ground truth (see below).

## Verdict Rules

The verdict is an aid to verification, never a halal certification. It follows
the reference with this precedence:

1. **"Incompatible ingredient detected"** — any matched ingredient is
   `incompatible`. This always wins, even when other ingredients are not in
   the reference or coverage is low.
2. **"À vérifier"** — no incompatible ingredient, but ANY of:
   - at least one real ingredient is not in the reference, after function
     words, modifiers, group labels and allergen notes are removed — reported
     as `"Not in the reference: <names>"`,
   - a `depends_on_origin` ingredient,
   - fewer than `MIN_COVERAGE` (50%) of the ingredient segments found in the
     section are recognised by the reference — reported as a secondary reason
     `"Only X of Y ingredients are in the reference"`,
   - a dropped/uncertain OCR block falls inside the ingredients region,
   - mean OCR confidence of the section is below the threshold,
   - the section is empty,
   - the `multiple_products` or `no_heading` flag is set (no heading shows the
     retake message).
3. **"No incompatible ingredient found in the reference"** — only when every
   ingredient is recognised, none is incompatible or `depends_on_origin`, and
   the reading is otherwise certain.

Ingredients not in the reference are still listed under **"Not in the reference
(not evaluated)"** for review; any such real ingredient forces **"À vérifier"**.
The tool never outputs "halal" or "certified" and always shows the disclaimer.

## Evaluation

The harness runs the full pipeline (OCR → section extraction → matching →
verdict) against hand-typed ground truth and is read-only: it never tunes a
rule, alias or threshold to improve the numbers.

Ground truth lives next to each photo:

```
eval/<lang>/NN.jpg          label photo (lang in ar, en, fr, zh)
eval/<lang>/NN.truth.json   { "ingredients_text": "..." }
```

The expected verdict and expected flags are computed by running the matcher and
the verdict rule on `ingredients_text` alone (never on OCR output), so they
stay auditable and change automatically when a rule changes.

Run it:

```bash
# Run OCR for both fast modes (writes eval/results.csv + eval/report.md):
python scripts/evaluate.py --fast-mode both

# Recompute every metric from the stored OCR outputs, without running OCR:
python scripts/evaluate.py --fast-mode both --rescore

# Compare against an older results.csv (adds a verdict-change table):
python scripts/evaluate.py --fast-mode both --previous eval/diagnostics/results_before_policy.csv
```

Metrics per image: content CER (punctuation-free, target ≤ 3%) and strict CER;
ingredient recall/precision (greedy 1:1 match at rapidfuzz ≥ 75); verdict
accuracy (aggregated by severity across sections); flag recall and false alarms;
warm processing time (models preloaded, one warmup run discarded per mode).
Stored OCR blocks live under `eval/ocr_outputs/<on|off>/<lang>/<NN>.json`.

## Limitations

- **Reference scope.** The reference covers commonly encountered ingredients
  and additives. Ingredients not listed are reported as "not in the reference
  (not evaluated)" and force **"À vérifier"**; a clear verdict means only that
  every read ingredient was recognised and no *recognised* incompatible
  ingredient was found, not that the product is halal.
- **OCR quality.** Accuracy drops on curved text, very small or low-contrast
  print, glossy surfaces, skewed or partially obscured labels, and decorative
  fonts. The verdict flags low-confidence or unreadable regions inside the
  ingredients list as "À vérifier", but OCR errors can still cause an
  ingredient to be missed or misread.
- **Not a certification.** This tool is an aid to verification only. Always
  confirm with official halal certification bodies for definitive guidance.

## Disclaimer

⚠️ **This tool is an aid to verification, NOT a halal certification.** Always verify with official halal certification bodies for definitive guidance.

## License

MIT License
