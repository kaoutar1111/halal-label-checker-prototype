"""
Halal Label Checker - Streamlit application.

This module is intentionally UI-only: OCR, sectioning, matching and verdict
logic live in src/. Uploaded and camera images share the same analysis path.
"""

# Paddle/torch DLL conflict on Windows: import torch first
try:
    import torch
except ImportError:
    pass  # torch not installed, continue without it

import hashlib
import html
import io
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st
from PIL import Image

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.base import OCRError  # noqa: F401  # kept for compatibility/import order
from src.matcher import IngredientMatcher
from src.ocr import AUTO_LANGUAGES, MultiLanguageOCR
from src.preprocess import preprocess_image
from src.sections import extract_ingredient_sections
from src.verdict import (
    DISCLAIMER,
    NOT_EVALUATED_LABEL,
    VERDICT_CLEAR,
    VERDICT_INCOMPATIBLE,
    VERDICT_TO_VERIFY,
    VerdictGenerator,
)
from src.db import get_database

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
SUPPORTED_LANGUAGES = ["ar", "fr", "en", "zh"]
LANGUAGE_NAMES = {
    "ar": "Arabic",
    "fr": "French",
    "en": "English",
    "zh": "Chinese",
}
LANGUAGE_HINTS = ["auto", "ar", "fr", "en", "zh"]
LANGUAGE_HINT_LABELS = {
    "auto": "Auto (detect by script)",
    "ar": "Arabic (ar)",
    "fr": "French (fr)",
    "en": "English (en)",
    "zh": "Chinese (zh)",
}

DISCLAIMER_TEXT = "Aid to verification, not a halal certification."
DB_PATH = str(Path(__file__).parent / "halal_checker.db")

STATUS_LABELS = {
    "incompatible": "Incompatible",
    "depends_on_origin": "Depends on origin",
    "compatible": "Compatible",
    "unrecognized": "Not in the reference",
    "negated": "Ignored (negation)",
    "function_word": "Function word",
    "allergen_note": "Allergen note",
}

STATUS_SEVERITY = {
    "incompatible": 0,
    "depends_on_origin": 1,
    "unrecognized": 2,
    "function_word": 3,
    "allergen_note": 3,
    "compatible": 4,
}

STATUS_COLORS = {
    "incompatible": "#f8d7da",
    "depends_on_origin": "#fff3cd",
    "compatible": "#d1e7dd",
    "unrecognized": "#e2e3e5",
}

STATUS_TEXT_COLORS = {
    "incompatible": "#842029",
    "depends_on_origin": "#664d03",
    "compatible": "#0f5132",
    "unrecognized": "#41464b",
}

VERDICT_SEVERITY = {
    VERDICT_INCOMPATIBLE: 2,
    VERDICT_TO_VERIFY: 1,
    VERDICT_CLEAR: 0,
}

# Module-level analysis cache. Key: image SHA1 + normalized settings. This avoids
# rerunning OCR on Streamlit reruns for the same photo/settings. OCR itself also
# keeps an image cache; this second cache is UI-level and cheap.
_PROCESS_CACHE: Dict[Tuple, Dict[str, Any]] = {}


@st.cache_resource
def get_ocr() -> MultiLanguageOCR:
    """
    Shared OCR instance with all models preloaded at startup.

    Model loading is the slow part (one recognizer per language plus the
    shared detector); doing it once here makes the first scan a warm run.
    """
    ocr = MultiLanguageOCR()
    engine = ocr._get_engine()
    engine._get_detector()
    for lang in ["ar", "fr", "en", "zh"]:
        engine._get_recognizer(lang)
    return ocr


def init_session_state() -> None:
    """Initialize Streamlit session state variables."""
    defaults: Dict[str, Any] = {
        "analysis_ready": False,
        "image_name": "",
        "image_sha1": "",
        "source_image": None,
        "processed_image": None,
        "raw_text": "",
        "raw_text_no_preprocess": "",
        "ocr_confidence": 0.0,
        "ocr_confidence_no_preprocess": 0.0,
        "ocr_results": [],
        "per_lang_results": {},
        "per_lang_results_no_preprocess": {},
        "detected_languages": [],
        "ocr_errors": [],
        "ocr_unreadable": [],
        "sections": [],
        "match_reports": [],
        "verdicts": [],
        "scan_saved": False,
        "processing_seconds": 0.0,
        "ocr_strategy": "",
        "ocr_retry": {},
        "blocks_detected": 0,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def render_custom_css() -> None:
    """Small, accessible CSS block for banners, chips, and readability."""
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 1.2rem;
            padding-bottom: 2rem;
        }
        .hlc-disclaimer {
            border: 1px solid #ffe69c;
            background: #fffbe6;
            color: #664d03;
            border-radius: 0.5rem;
            padding: 0.6rem 0.85rem;
            font-weight: 600;
            margin-bottom: 1rem;
        }
        .hlc-banner {
            border-radius: 0.75rem;
            padding: 1rem 1.15rem;
            margin: 0.5rem 0 1rem 0;
            border: 1px solid transparent;
        }
        .hlc-banner h2 {
            margin: 0 0 0.35rem 0;
            font-size: 1.45rem;
        }
        .hlc-banner ul {
            margin: 0.35rem 0 0 1.1rem;
            padding: 0;
        }
        .hlc-incompatible { background: #f8d7da; color: #842029; border-color: #f5c2c7; }
        .hlc-verify { background: #fff3cd; color: #664d03; border-color: #ffe69c; }
        .hlc-clear { background: #d1e7dd; color: #0f5132; border-color: #badbcc; }
        .hlc-empty {
            border: 1px dashed #adb5bd;
            border-radius: 0.75rem;
            padding: 2rem;
            text-align: center;
            color: #495057;
            background: #f8f9fa;
        }
        .hlc-chip {
            display: inline-block;
            border-radius: 999px;
            padding: 0.15rem 0.6rem;
            font-weight: 600;
            font-size: 0.82rem;
            white-space: nowrap;
        }
        .hlc-table th, .hlc-table td {
            vertical-align: top;
            padding: 0.45rem 0.55rem;
        }
        .hlc-legend {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin: 0.25rem 0 0.75rem 0;
        }
        .hlc-legend-item {
            border: 1px solid #ced4da;
            border-radius: 999px;
            padding: 0.2rem 0.65rem;
            font-size: 0.82rem;
            font-weight: 600;
        }
        .hlc-highlight {
            line-height: 1.9;
            font-size: 1rem;
        }
        @media (max-width: 768px) {
            .hlc-banner h2 { font-size: 1.2rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def status_meta(status: str) -> Tuple[str, str]:
    """Return (display label, CSS class) for an ingredient status."""
    label = STATUS_LABELS.get(status, status.replace("_", " ").title())
    if status == "incompatible":
        css = "hlc-incompatible"
    elif status == "depends_on_origin":
        css = "hlc-verify"
    elif status == "compatible":
        css = "hlc-clear"
    else:
        css = "hlc-chip"
    return label, css


def status_chip_html(status: str) -> str:
    """Accessible status chip: color plus a text label, never color alone."""
    label, css = status_meta(status)
    background = STATUS_COLORS.get(status, "#e9ecef")
    text_color = STATUS_TEXT_COLORS.get(status, "#212529")
    return (
        f'<span class="hlc-chip {css}" style="background:{background};'
        f'color:{text_color};">{html.escape(label)}</span>'
    )


def aggregate_verdict(verdicts: List[Any]) -> str:
    """Worst verdict across sections: incompatible > verify > clear."""
    if not verdicts:
        return VERDICT_TO_VERIFY
    return max(verdicts, key=lambda verdict: VERDICT_SEVERITY.get(verdict.verdict, 1)).verdict


def image_sha1(image_bytes: bytes) -> str:
    return hashlib.sha1(image_bytes).hexdigest()


def build_image_payload(
    source: str,
    uploaded_file: Optional[Any] = None,
    camera_file: Optional[Any] = None,
) -> Dict[str, Any]:
    """Normalize either upload or camera input into the same payload shape."""
    if source == "upload":
        if uploaded_file is None:
            return {"ok": False, "message": "Upload a label photo to begin."}
        return {
            "ok": True,
            "bytes": uploaded_file.getvalue(),
            "name": getattr(uploaded_file, "name", "uploaded-image"),
        }
    if source == "camera":
        if camera_file is None:
            return {
                "ok": False,
                "message": (
                    "No photo has been taken yet. If the browser blocked camera "
                    "access, allow permission or use the upload option."
                ),
            }
        return {
            "ok": True,
            "bytes": camera_file.getvalue(),
            "name": getattr(camera_file, "name", "camera-capture.jpg"),
        }
    return {"ok": False, "message": "Choose an input source."}


def load_image(image_bytes: bytes) -> Image.Image:
    """Load an image from bytes; same code for upload and camera."""
    image = Image.open(io.BytesIO(image_bytes))
    if image.mode != "RGB":
        image = image.convert("RGB")
    return image


def analyze_image_payload(payload: Dict[str, Any], settings: Dict[str, Any]) -> Dict[str, Any]:
    """Single entry point used by both upload and camera inputs."""
    return run_label_analysis(payload["bytes"], payload["name"], settings)


def detect_languages_from_results(results: List[Any]) -> List[str]:
    languages = sorted({result.language for result in results if result.language})
    return languages


def _group_results_by_lang(results: List[Any]) -> Dict[str, List[Any]]:
    grouped: Dict[str, List[Any]] = {}
    for result in results:
        grouped.setdefault(result.language or "unknown", []).append(result)
    return grouped


def analyze_sections(results: List[Any], unreadable: Optional[List[Any]] = None):
    """Extract sections, match ingredients, compute verdicts; pure UI helper."""
    matcher = IngredientMatcher()
    generator = VerdictGenerator()
    sections = extract_ingredient_sections(results, unreadable=unreadable) if results else []
    reports = []
    verdicts = []
    for index, section in enumerate(sections):
        report = matcher.match_section(section)
        reports.append(report)
        verdicts.append(
            generator.assess(section, report, section_index=index, unreadable=unreadable)
        )
    return sections, reports, verdicts


def _settings_key(settings: Dict[str, Any]) -> Tuple:
    return (
        bool(settings["preprocessing"]),
        bool(settings["fast_mode"]),
        bool(settings["auto"]),
        tuple(settings["languages"]),
    )


def _run_ocr_once(ocr, image, languages, auto):
    try:
        results = ocr.process_image(image, languages, auto=auto)
        errors = list(getattr(ocr, "last_errors", []) or [])
        unreadable = (
            list(getattr(ocr, "last_dropped", []) or [])
            + list(getattr(ocr, "last_uncertain", []) or [])
        )
        strategy = getattr(ocr, "last_strategy", "") or ""
        retry = dict(getattr(ocr, "last_retry", {}) or {})
        blocks_detected = int(getattr(ocr, "last_blocks_detected", 0) or 0)
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        logger.error("OCR failed: %s", exc, exc_info=True)
        return [], [msg], [], "", {}, 0
    return results, errors, unreadable, strategy, retry, blocks_detected


def run_label_analysis(image_bytes: bytes, image_name: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    """Run OCR + sectioning + matching + verdict once, cached by image SHA1."""
    digest = image_sha1(image_bytes)
    cache_key = (digest,) + _settings_key(settings)
    cached = _PROCESS_CACHE.get(cache_key)
    if cached is not None:
        apply_analysis_bundle(cached)
        return cached

    image = load_image(image_bytes)
    start = time.perf_counter()
    ocr = get_ocr()
    ocr.fast_mode = bool(settings["fast_mode"])

    results_no_prep, errors_no_prep, _, _, _, _ = _run_ocr_once(
        ocr, image, settings["languages"], settings["auto"]
    )
    raw_text_no_prep = "\n".join(r.text for r in results_no_prep)
    confidence_no_prep = (
        sum(r.confidence for r in results_no_prep) / len(results_no_prep)
        if results_no_prep
        else 0.0
    )

    processed_image = preprocess_image(image) if settings["preprocessing"] else image
    results, errors, unreadable, strategy, retry, blocks_detected = _run_ocr_once(
        ocr, processed_image, settings["languages"], settings["auto"]
    )
    all_errors = errors_no_prep + errors

    raw_text = "\n".join(r.text for r in results)
    confidence = (
        sum(r.confidence for r in results) / len(results) if results else 0.0
    )
    sections, reports, verdicts = analyze_sections(results, unreadable)

    bundle = {
        "image_name": image_name,
        "image_sha1": digest,
        "source_image": image,
        "processed_image": processed_image,
        "raw_text": raw_text,
        "raw_text_no_preprocess": raw_text_no_prep,
        "ocr_confidence": confidence,
        "ocr_confidence_no_preprocess": confidence_no_prep,
        "ocr_results": results,
        "per_lang_results": _group_results_by_lang(results),
        "per_lang_results_no_preprocess": _group_results_by_lang(results_no_prep),
        "detected_languages": detect_languages_from_results(results),
        "ocr_errors": all_errors,
        "ocr_unreadable": unreadable,
        "sections": sections,
        "match_reports": reports,
        "verdicts": verdicts,
        "processing_seconds": time.perf_counter() - start,
        "ocr_strategy": strategy,
        "ocr_retry": retry,
        "blocks_detected": blocks_detected,
        "scan_saved": False,
    }
    _PROCESS_CACHE[cache_key] = bundle
    apply_analysis_bundle(bundle)
    return bundle


def apply_analysis_bundle(bundle: Dict[str, Any]) -> None:
    """Copy one analysis bundle into session state for rendering."""
    st.session_state.update(bundle)
    st.session_state["analysis_ready"] = True
    st.session_state["scan_saved"] = False


def clear_analysis() -> None:
    st.session_state["analysis_ready"] = False
    st.session_state["image_name"] = ""
    st.session_state["image_sha1"] = ""
    st.session_state["source_image"] = None
    st.session_state["processed_image"] = None
    st.session_state["raw_text"] = ""
    st.session_state["raw_text_no_preprocess"] = ""
    st.session_state["ocr_confidence"] = 0.0
    st.session_state["ocr_confidence_no_preprocess"] = 0.0
    st.session_state["ocr_results"] = []
    st.session_state["per_lang_results"] = {}
    st.session_state["per_lang_results_no_preprocess"] = {}
    st.session_state["detected_languages"] = []
    st.session_state["ocr_errors"] = []
    st.session_state["ocr_unreadable"] = []
    st.session_state["sections"] = []
    st.session_state["match_reports"] = []
    st.session_state["verdicts"] = []
    st.session_state["scan_saved"] = False
    st.session_state["processing_seconds"] = 0.0
    st.session_state["ocr_strategy"] = ""
    st.session_state["ocr_retry"] = {}
    st.session_state["blocks_detected"] = 0


def format_retry(info: Dict[str, Any]) -> str:
    if not info:
        return "none"
    state = "used" if info.get("used") else "discarded"
    return f"{info.get('mode', '')}:{state}:{info.get('seconds', 0)}s"


def main() -> None:
    init_session_state()
    st.set_page_config(
        page_title="Halal Label Checker",
        page_icon="🔍",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    render_custom_css()

    # APP_TEST_SKIP_OCR is a test-only guard so AppTest can render UI states
    # without loading the heavy OCR models. It does not affect normal runs.
    if os.environ.get("APP_TEST_SKIP_OCR") != "1":
        with st.spinner("Loading OCR models (first launch only)..."):
            get_ocr()

    st.title("🔍 Halal Label Checker")
    st.caption("Multilingual label reader for ingredient verification — upload a photo or take one with your camera.")
    st.markdown(
        f'<div class="hlc-disclaimer">{html.escape(DISCLAIMER_TEXT)}</div>',
        unsafe_allow_html=True,
    )

    preprocessing_enabled, language_hint, fast_mode, page = render_settings()
    if page == "📋 Scan History":
        show_history_page()
        return

    settings = settings_from_hint(preprocessing_enabled, language_hint, fast_mode)
    show_scanner_page(settings)


def settings_from_hint(preprocessing_enabled: bool, language_hint: str, fast_mode: bool) -> Dict[str, Any]:
    if language_hint == "auto":
        return {
            "preprocessing": preprocessing_enabled,
            "fast_mode": fast_mode,
            "auto": True,
            "languages": list(AUTO_LANGUAGES),
            "language_hint": language_hint,
        }
    return {
        "preprocessing": preprocessing_enabled,
        "fast_mode": fast_mode,
        "auto": False,
        "languages": [language_hint],
        "language_hint": language_hint,
    }


def render_settings():
    with st.sidebar:
        st.header("Settings")
        preprocessing_enabled = st.checkbox("Enable preprocessing", value=True)
        language_hint = st.radio(
            "Language hint",
            options=LANGUAGE_HINTS,
            index=0,
            format_func=lambda value: LANGUAGE_HINT_LABELS[value],
            help="Auto detects scripts; a specific language hint narrows recognition.",
        )
        fast_mode = st.checkbox(
            "Fast mode",
            value=True,
            help=(
                "Language-first probe, batched recognition and per-image caching. "
                "Kept on by default."
            ),
        )
        st.divider()
        st.header("Navigation")
        page = st.radio(
            "Go to",
            ["🏠 Scanner", "📋 Scan History"],
            label_visibility="collapsed",
        )
    return preprocessing_enabled, language_hint, fast_mode, page


def show_scanner_page(settings: Dict[str, Any]) -> None:
    """Display the main scanner interface."""
    input_source = st.radio(
        "Image source",
        options=["upload", "camera"],
        index=0,
        format_func=lambda value: "📤 Upload a photo" if value == "upload" else "📷 Take a photo",
        horizontal=True,
        key="input_source",
    )

    uploaded_file = None
    camera_file = None
    if input_source == "upload":
        uploaded_file = st.file_uploader(
            "Choose a food label image",
            type=["jpg", "jpeg", "png", "bmp", "webp"],
            help="Upload a clear photo of the ingredient panel.",
        )
    else:
        st.info(
            "Tip: frame a close-up of the ingredient panel only, flat and straight, "
            "with no glare and good light."
        )
        camera_file = st.camera_input("Take a photo of the label")

    payload = build_image_payload(input_source, uploaded_file, camera_file)

    if payload["ok"]:
        preview_image = load_image(payload["bytes"])
        digest = image_sha1(payload["bytes"])
        if st.session_state.get("image_sha1") != digest:
            clear_analysis()
            st.session_state["image_sha1"] = digest
            st.session_state["image_name"] = payload["name"]
            st.session_state["source_image"] = preview_image
        st.image(preview_image, caption=payload["name"], width="stretch")

    analyze = st.button("🔍 Analyze label", type="primary", width="stretch", disabled=not payload["ok"])
    if analyze and payload["ok"]:
        with st.spinner("Reading the label and checking ingredients..."):
            analyze_image_payload(payload, settings)

    if not payload["ok"] and not st.session_state.get("analysis_ready"):
        render_empty_state(payload["message"], input_source)
        return

    if st.session_state.get("analysis_ready"):
        render_results()
    elif payload["ok"]:
        render_empty_state("Press “Analyze label” to run the checker.", input_source)


def render_empty_state(message: str, input_source: str) -> None:
    action = "Upload a photo" if input_source == "upload" else "Take a photo"
    st.markdown(
        f"""
        <div class="hlc-empty">
          <h3>No label analyzed yet</h3>
          <p>{html.escape(message)}</p>
          <p><strong>{html.escape(action)}</strong>, then choose <strong>Analyze label</strong>.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_results() -> None:
    render_verdict_banner()

    errors = st.session_state.get("ocr_errors") or []
    if errors:
        for error in errors:
            st.error(f"OCR issue: {error}")
        if not st.session_state.get("ocr_results"):
            st.error("No OCR text was produced. Try a clearer photo or the upload option.")

    left, right = st.columns([1, 1])
    with left:
        if st.session_state.get("source_image") is not None:
            st.image(
                st.session_state["source_image"],
                caption=f"Input image: {st.session_state.get('image_name', '')}",
                width="stretch",
            )
    with right:
        st.subheader("Extracted ingredients text")
        raw_text = st.session_state.get("raw_text") or ""
        st.text_area(
            "Extracted ingredients text",
            value=raw_text,
            height=240,
            disabled=True,
            label_visibility="collapsed",
        )
        if raw_text:
            st.download_button(
                "Download extracted text",
                raw_text,
                file_name="extracted_ingredients.txt",
                mime="text/plain",
            )

    render_ingredient_table()
    render_highlighted_text()
    render_technical_details()
    _save_scan_once()


def verdict_banner_meta(verdict: str) -> Tuple[str, str, str]:
    if verdict == VERDICT_INCOMPATIBLE:
        return "⛔", "hlc-incompatible", "Incompatible"
    if verdict == VERDICT_TO_VERIFY:
        return "⚠️", "hlc-verify", "To verify"
    return "✅", "hlc-clear", "Clear"


def render_verdict_banner() -> None:
    verdicts = st.session_state.get("verdicts") or []
    verdict = aggregate_verdict(verdicts)
    icon, css, short_label = verdict_banner_meta(verdict)

    reasons: List[str] = []
    for item in verdicts:
        for reason in item.reasons or []:
            if reason not in reasons:
                reasons.append(str(reason))
    if not reasons:
        reasons = [verdict]

    reason_items = "".join(f"<li>{html.escape(reason)}</li>" for reason in reasons)
    st.markdown(
        f"""
        <div class="hlc-banner {css}">
          <h2>{icon} {html.escape(short_label)} — {html.escape(verdict)}</h2>
          <ul>{reason_items}</ul>
        </div>
        """,
        unsafe_allow_html=True,
    )


def sorted_findings(reports: List[Any]) -> List[Tuple[Any, Any]]:
    rows = []
    for report in reports:
        for finding in report.findings:
            if finding.status == "negated":
                continue
            rows.append((report, finding))
    rows.sort(
        key=lambda item: (
            STATUS_SEVERITY.get(item[1].status, 9),
            html.escape(item[1].original_text or ""),
        )
    )
    return rows


def render_ingredient_table() -> None:
    st.subheader("Ingredient findings")
    reports = st.session_state.get("match_reports") or []
    rows = sorted_findings(reports)
    if not rows:
        st.info("No ingredient findings were generated for this image.")
        return

    table_rows = []
    for _, finding in rows:
        table_rows.append(
            "<tr>"
            f"<td>{html.escape(finding.original_text or '')}</td>"
            f"<td>{html.escape(finding.matched_name or '—')}</td>"
            f"<td>{status_chip_html(finding.status)}</td>"
            f"<td>{html.escape(finding.reason or '')}</td>"
            "</tr>"
        )
    st.markdown(
        """
        <table class="hlc-table" style="width:100%; border-collapse:collapse;">
          <thead>
            <tr>
              <th>Ingredient as read</th>
              <th>Matched reference entry</th>
              <th>Status</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
        """
        + "".join(table_rows)
        + "</tbody></table>",
        unsafe_allow_html=True,
    )


def _highlighted_html(text: str, findings: List[Any]) -> str:
    spans = []
    occupied: List[Tuple[int, int]] = []
    for finding in sorted(findings, key=lambda f: len(f.original_text or ""), reverse=True):
        if finding.status == "negated":
            continue
        needle = finding.original_text or ""
        if not needle:
            continue
        start = 0
        while True:
            index = text.find(needle, start)
            if index == -1:
                break
            end = index + len(needle)
            if not any(index < end_bound and end > start_bound for start_bound, end_bound in occupied):
                occupied.append((index, end))
                spans.append((index, end, finding))
            start = index + 1

    spans.sort(key=lambda item: item[0])
    parts = []
    last = 0
    for index, end, finding in spans:
        parts.append(html.escape(text[last:index]))
        background = STATUS_COLORS.get(finding.status, "#ffffff")
        color = STATUS_TEXT_COLORS.get(finding.status, "#212529")
        tooltip = (
            f"{STATUS_LABELS.get(finding.status, finding.status)}: "
            f"{finding.matched_name or 'not in reference'}"
        )
        parts.append(
            '<span style="background-color:%s; color:%s; padding:1px 2px; border-radius:3px;" '
            'title="%s">%s</span>'
            % (background, color, html.escape(tooltip), html.escape(text[index:end]))
        )
        last = end
    parts.append(html.escape(text[last:]))
    return "".join(parts)


def render_highlighted_text() -> None:
    st.subheader("Highlighted ingredients")
    st.markdown(
        """
        <div class="hlc-legend">
          <span class="hlc-legend-item" style="background:#f8d7da;color:#842029;">Red = incompatible</span>
          <span class="hlc-legend-item" style="background:#fff3cd;color:#664d03;">Amber = depends on origin</span>
          <span class="hlc-legend-item" style="background:#d1e7dd;color:#0f5132;">Green = compatible</span>
          <span class="hlc-legend-item" style="background:#e2e3e5;color:#41464b;">Grey = not in the reference (verdict set to À vérifier)</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    sections = st.session_state.get("sections") or []
    reports = st.session_state.get("match_reports") or []
    if not sections:
        st.info("No ingredients section was extracted from this image.")
        return
    for index, (section, report) in enumerate(zip(sections, reports), start=1):
        heading = section.heading.text if getattr(section, "heading", None) else "(no heading)"
        st.markdown(f"**Section {index}:** `{html.escape(heading)}`")
        st.markdown(
            '<div class="hlc-highlight">%s</div>'
            % _highlighted_html(section.text or "", report.findings),
            unsafe_allow_html=True,
        )


def render_technical_details() -> None:
    with st.expander("Technical details"):
        confidence = float(st.session_state.get("ocr_confidence") or 0.0)
        results = st.session_state.get("ocr_results") or []
        unreadable = st.session_state.get("ocr_unreadable") or []
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("OCR confidence", f"{confidence:.1%}")
        with col2:
            st.metric("Blocks kept", len(results))
        with col3:
            st.metric("Blocks dropped", len(unreadable))
        with col4:
            st.metric(
                "Processing time",
                f"{float(st.session_state.get('processing_seconds') or 0.0):.2f}s",
            )
        st.write(
            f"Strategy: `{st.session_state.get('ocr_strategy') or 'unknown'}` · "
            f"Retry: `{format_retry(st.session_state.get('ocr_retry') or {})}` · "
            f"Detected: {int(st.session_state.get('blocks_detected') or 0)} boxes"
        )
        if unreadable:
            st.dataframe(
                [
                    {
                        "text": entry.get("text") or "—",
                        "confidence": round(float(entry.get("confidence") or 0.0), 2),
                        "reason": entry.get("reason") or "",
                    }
                    for entry in unreadable
                ],
                width="stretch",
                hide_index=True,
            )


def _save_scan_once() -> None:
    """Save one row per section in the SQLite scan history (once per scan)."""
    if st.session_state.get("scan_saved"):
        return
    sections = st.session_state.get("sections") or []
    reports = st.session_state.get("match_reports") or []
    verdicts = st.session_state.get("verdicts") or []
    try:
        database = get_database(DB_PATH)
        for index, (section, report, verdict) in enumerate(
            zip(sections, reports, verdicts), start=1
        ):
            heading = section.heading.text if getattr(section, "heading", None) else ""
            database.save_scan(
                image_path=st.session_state.get("image_name", "uploaded"),
                raw_text=section.text or "",
                ocr_confidence=verdict.overall_confidence,
                verdict=verdict.verdict,
                verdict_details={
                    "section_index": index,
                    "heading": heading,
                    "language": section.language,
                    "flag": section.flag,
                    "reasons": verdict.reasons,
                    "e_numbers": report.e_numbers,
                },
                highlighted_text={
                    "text": section.text or "",
                    "highlights": [f.to_dict() for f in report.findings],
                },
                match_results=[f.to_dict() for f in report.findings],
            )
        st.session_state.scan_saved = True
    except Exception as exc:  # history must never break the scan
        logger.warning("Could not save scan history: %s", exc)


def show_history_page() -> None:
    """Display scan history page."""
    st.subheader("📋 Scan History")
    st.markdown(
        f'<div class="hlc-disclaimer">{html.escape(DISCLAIMER_TEXT)}</div>',
        unsafe_allow_html=True,
    )

    database = get_database(DB_PATH)
    statistics = database.get_statistics()

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total scans", statistics["total_scans"])
    with col2:
        st.metric("Average OCR confidence", f"{statistics['average_confidence']:.1%}")
    with col3:
        incompatible = statistics["verdict_counts"].get(VERDICT_INCOMPATIBLE, 0)
        st.metric("Incompatible scans", incompatible)

    if statistics["verdict_counts"]:
        st.markdown("**Verdict distribution:**")
        st.bar_chart(statistics["verdict_counts"])

    scans = database.get_recent_scans(50)
    if not scans:
        st.info("No scans yet. Run a scan on the Scanner page.")
        return

    if st.button("🗑️ Clear all history", type="secondary"):
        database.clear_all_scans()
        st.rerun()

    st.divider()
    for scan in scans:
        details = scan.get("verdict_details") or {}
        title = f"Scan #{scan['id']} · {scan.get('created_at', '')} · {scan.get('verdict', '')}"
        with st.expander(title):
            st.markdown(f"**Image:** `{scan.get('image_path', '')}`")
            st.markdown(
                f"**Section:** {details.get('section_index', '?')} · "
                f"heading `{details.get('heading', '')}` · "
                f"language `{details.get('language', '')}` · "
                f"flag `{details.get('flag', '')}`"
            )
            st.markdown(f"**Mean OCR confidence:** {scan.get('ocr_confidence', 0.0):.1%}")
            reasons = details.get("reasons") or []
            if reasons:
                st.markdown("**Reasons:**")
                for reason in reasons:
                    st.markdown(f"- {reason}")
            if details.get("e_numbers"):
                st.markdown("**E-numbers:** " + ", ".join(details["e_numbers"]))
            matches = scan.get("match_results") or []
            if matches:
                rows = [
                    {
                        "Ingredient": item.get("ingredient", ""),
                        "Matched entry": item.get("matched_name", "") or "—",
                        "Status": STATUS_LABELS.get(item.get("status", ""), item.get("status", "")),
                        "Reason": item.get("reason", ""),
                    }
                    for item in matches
                ]
                st.dataframe(rows, width="stretch", hide_index=True)
            if st.button(f"Delete scan #{scan['id']}", key=f"delete_scan_{scan['id']}"):
                database.delete_scan(scan["id"])
                st.rerun()


if __name__ == "__main__":
    main()
