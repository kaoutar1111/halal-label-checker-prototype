"""Function words, allergen annotations and the fuzzy-match safety rule."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.matcher import IngredientMatcher, is_negated_alcohol
from src.verdict import VERDICT_CLEAR, VerdictGenerator

ROOT = Path(__file__).resolve().parent.parent


class FakeSection:
    def __init__(self, text: str):
        self.text = text
        self.flag = None
        self.heading = None
        self.language = "fr"
        self.blocks = []


def verdict_of(text: str):
    matcher = IngredientMatcher()
    section = FakeSection(text)
    report = matcher.match_text(text)
    return report, VerdictGenerator().assess(section, report, ocr_confidence=0.99)


def test_function_word_alone_is_reported_but_does_not_change_the_verdict():
    """'Colorant' alone: no substance to judge; it is informational only."""
    report, verdict = verdict_of("Colorant")

    finding = next(f for f in report.findings if f.original_text == "Colorant")
    assert finding.status == "function_word"
    assert finding.needs_verification
    assert report.unrecognized == []
    assert verdict.verdict == VERDICT_CLEAR
    assert any("Function word without named substance" in r for r in verdict.reasons)


def test_function_word_judges_substances_after_colon():
    """'Humectant : Sorbitol, Glycérol' -> only the substances are judged."""
    report, verdict = verdict_of("Humectant : Sorbitol, Glycérol")

    humectant = next(f for f in report.findings if f.original_text == "Humectant")
    assert humectant.status == "function_word"
    assert not humectant.needs_verification  # substances are named

    names = {f.matched_name for f in report.findings}
    assert any("sorbitol" in (n or "").lower() for n in names)
    assert any("glycérol" in (n or "").lower() or "glycerol" in (n or "").lower() for n in names)
    assert not any("Function word without named substance" in r for r in verdict.reasons)


def test_function_word_prefix_stripped_from_segment():
    """'émulsifiant lécithine de soja': judge the substance, not the word."""
    report, _ = verdict_of("émulsifiant lécithine de soja")

    fw = next(f for f in report.findings if f.status == "function_word")
    assert fw.original_text == "émulsifiant lécithine de soja"
    assert any("lécithine" in (f.matched_name or "").lower() for f in report.findings)


def test_allergen_parentheses_are_not_ingredients():
    """'(Lait)' and '(contient Gluten)' are allergen notes, not ingredients."""
    report, _ = verdict_of("Beurre de cacao - Butteroil (Lait) - Lactose (contient Gluten)")

    notes = [f for f in report.findings if f.status == "allergen_note"]
    assert {f.original_text for f in notes} == {"(Lait)", "(contient Gluten)"}

    ingredient_texts = {f.original_text.lower() for f in report.ingredients}
    assert "lait" not in ingredient_texts
    assert "gluten" not in ingredient_texts
    # Real ingredients around the notes are still judged.
    assert any("lactose" in t for t in ingredient_texts)


def test_parenthesized_sub_ingredients_are_kept():
    """'(棕櫚油)' is a substance list, not an allergen note."""
    matcher = IngredientMatcher()
    report = matcher.match_text("植物油(棕櫚油)")

    assert not [f for f in report.findings if f.status == "allergen_note"]
    assert any("棕櫚油" in f.original_text for f in report.findings)


def test_fuzzy_match_never_incompatible():
    """A fuzzy hit on an incompatible entry must be downgraded."""
    matcher = IngredientMatcher()
    report = matcher.match_text("winee")  # typo one char away from "wine" (id 5)

    fuzzy = [f for f in report.findings if f.method == "fuzzy"]
    assert fuzzy, "expected a fuzzy match"
    assert all(f.status != "incompatible" for f in fuzzy)
    assert fuzzy[0].status == "depends_on_origin"


def test_exact_alias_still_incompatible():
    """Only an exact alias may produce 'incompatible'."""
    matcher = IngredientMatcher()
    report = matcher.match_text("pork gelatin")
    assert any(f.status == "incompatible" and f.method in ("exact", "e-number")
               and f.matched_id == 103
               for f in report.findings)


ALCOHOL_ENTRY_IDS = {4, 36}


@pytest.mark.parametrize(
    "text",
    [
        "sans alcool",
        "Sans alcool",
        "Sans-alcool",
        "alcohol-free",
        "Alcohol-free",
        "alcohol free",
        "bière sans alcool",
    ],
)
def test_sans_alcool_and_alcohol_free_never_trigger_alcohol_entry(text):
    """'sans alcool' / 'alcohol-free' are negation claims, not ingredients."""
    matcher = IngredientMatcher()
    report = matcher.match_text(text)

    assert is_negated_alcohol(text)
    assert not any(f.matched_id in ALCOHOL_ENTRY_IDS for f in report.findings)
    assert not any(f.status == "incompatible" for f in report.findings)


# ---------------------------------------------------------------------------
# Merge script
# ---------------------------------------------------------------------------


def test_merge_applies_overrides_and_keeps_unlisted_conflicts(tmp_path):
    reference = {
        "ingredients": [
            {"id": 4, "names": {"en": "alcohol"}, "aliases": ["alcohol", "éthanol"],
             "status": "incompatible", "reason": "r", "source": "s"},
            {"id": 8, "names": {"en": "lard"}, "aliases": ["lard"],
             "status": "incompatible", "reason": "r", "source": "s"},
            {"id": 30, "names": {"en": "emulsifiers"}, "aliases": ["emulsifier", "E471"],
             "status": "depends_on_origin", "reason": "r", "source": "s"},
            {"id": 32, "names": {"en": "monoglycerides"},
             "aliases": ["monoglycerides", "E471"],
             "status": "depends_on_origin", "reason": "r", "source": "s"},
            {"id": 33, "names": {"en": "diglycerides"}, "aliases": ["diglycerides"],
             "status": "depends_on_origin", "reason": "r", "source": "s"},
            {"id": 42, "names": {"en": "preservative"}, "aliases": ["preservative"],
             "status": "depends_on_origin", "reason": "r", "source": "s",
             "reviewed": False},
        ]
    }
    draft = [
        {"id": 101, "names": {"en": "alcohol"}, "aliases": ["alcohol"],
         "status": "depends_on_origin", "reason": "r", "reviewed": True},
        {"id": 102, "names": {"en": "lard"}, "aliases": ["lard"],
         "status": "compatible", "reason": "r", "reviewed": True},
        {"id": 103, "names": {"en": "new stuff"}, "aliases": ["new stuff"],
         "status": "compatible", "reason": "r", "reviewed": True},
        {"id": 109, "names": {"en": "fatty-acid emulsifiers"},
         "aliases": ["E471", "monoglycerides", "diglycerides", "E472a"],
         "status": "depends_on_origin", "reason": "r", "reviewed": True},
    ]
    ref_path = tmp_path / "reference.json"
    draft_path = tmp_path / "reference_validated.json"
    report_path = tmp_path / "merge_report.json"
    ref_path.write_text(json.dumps(reference, ensure_ascii=False), encoding="utf-8")
    draft_path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "merge_reference.py"),
         "--reference", str(ref_path), "--draft", str(draft_path),
         "--report", str(report_path)],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    assert result.returncode == 0, result.stderr

    merged = {e["id"]: e for e in json.loads(ref_path.read_text(encoding="utf-8"))["ingredients"]}
    report = json.loads(report_path.read_text(encoding="utf-8"))

    # Id 4 is in STATUS_OVERRIDES: the conflict is resolved in favour of the
    # draft status and the merged entry is marked reviewed.
    assert merged[4]["status"] == "depends_on_origin"
    assert merged[4]["reviewed"] is True
    assert any(r["draft_id"] == 101 and r["existing_id"] == 4
               for r in report["resolved"])
    assert any(o["id"] == 4 and o["from"] == "incompatible"
               and o["to"] == "depends_on_origin"
               for o in report["status_overrides"])
    # Id 8 has no override: the conflict is reported and the entry untouched.
    assert merged[8]["status"] == "incompatible"
    assert 102 not in merged
    assert any(c["draft_id"] == 102 for c in report["conflicts"])
    # New entry appended; preservative removed (function word fw5).
    assert 103 in merged
    assert merged[103]["reviewed"] is True
    assert 42 not in merged
    assert any(r["id"] == 42 for r in report["removed"])
    # Id 30 retired (function word fw6); its E471 moved to the umbrella 109.
    assert 30 not in merged
    assert any(r["id"] == 30 for r in report["retired"])
    assert "E471" not in merged[32]["aliases"]
    # Umbrella draft 109 added with only the overlapping aliases left off.
    assert 109 in merged
    assert set(merged[109]["aliases"]) == {"E471", "E472a"}
    overlap = next(o for o in report["alias_overlaps"] if o["draft_id"] == 109)
    owned = {a["alias"]: a["existing_ids"] for a in overlap["overlapping_aliases"]}
    assert owned == {"monoglycerides": [32], "diglycerides": [33]}
