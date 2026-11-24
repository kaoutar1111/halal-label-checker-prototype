#!/usr/bin/env python
"""
Merge data/reference_validated.json into data/reference.json by alias.

Rules
-----
* Matching is global and longest-alias-first on normalized text
  (src.matcher.normalize_text: lowercase, Latin accents stripped, Arabic
  diacritics/alef variants unified).
* Entries with id >= 100 (the previous unvalidated draft import) are dropped
  first; the validated draft replaces them wholesale.
* STATUS_OVERRIDES applies the user's reviewed resolutions to existing ids
  (the v1 conflicts resolved in favour of the draft status). Wine, beer and
  spirits entries are never touched by overrides.
* After overrides: same-status single-target hits merge (aliases/names union,
  target marked reviewed: true); non-umbrella drafts whose aliases hit
  several entries merge into the entry hit by the most aliases.
* Umbrella drafts in OVERLAP_DRAFT_IDS are still added, but their
  overlapping aliases are left off: the existing entries own those aliases.
  Whole entries are never skipped.
* Entry 30 "emulsifiers" is retired (a function word, fw6); its E-number
  aliases are moved: E471 -> 109, E322 -> 113, E400 stays with 202.
* Bare lecithin terms (lecithin, lécithine, ليسيثين, 卵磷脂, E322) resolve
  to draft 113 (depends_on_origin); id 31 keeps named-origin lecithins
  (soy, sunflower) as compatible.
* Id 2 keeps carmine/E120/胭脂虫红; 胭脂红 belongs to the colours entry 199.
* Draft entries with no alias collision are appended with their own id.
* Existing entry 42 "preservative" is removed: it is a function word
  (data/function_words.json fw5), not an ingredient.

Output: data/reference.json rewritten in place, report printed and saved to
data/merge_report.json.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.matcher import normalize_text  # noqa: E402

REMOVE_IDS = {42: "preservative is a function word (function_words.json fw5)"}

# Entries with id >= this came from the previous unvalidated draft import;
# the validated draft replaces them wholesale.
DROP_FROM_ID = 100

# User-reviewed resolutions of the v1 conflicts, in favour of the draft
# status. Wine, beer and spirits entries are deliberately absent: they stay
# incompatible.
STATUS_OVERRIDES = {
    1: "depends_on_origin",   # gelatin
    2: "depends_on_origin",   # carmine / cochineal
    4: "depends_on_origin",   # alcohol / ethanol
    36: "depends_on_origin",  # alcohol (solvent)
    11: "depends_on_origin",  # shellac
    23: "depends_on_origin",  # vanilla extract
    40: "depends_on_origin",  # collagen
    19: "compatible",         # maltodextrin
    20: "compatible",         # sugar
    21: "compatible",         # (modified) starch
    31: "compatible",         # lecithin
    46: "compatible",         # mixed tocopherols
}
_PROTECTED_NAME_RE = re.compile(r"wine|beer|spirit", re.IGNORECASE)

# Umbrella category drafts whose E-number aliases span several existing
# entries: added with the overlapping aliases left off (the existing
# entries own them), listed in the report with the overlapping alias.
OVERLAP_DRAFT_IDS = {109, 113, 199, 201, 202, 204}

# Entries retired as ingredients (function words, not substances). Their
# E-number aliases are handed over through ALIAS_MOVES below.
RETIRE_IDS = {
    30: "emulsifiers is a function word (function_words.json fw6), "
        "not an ingredient; E471 -> 109, E322 -> 113, E400 -> 202",
}

# Explicit alias moves: (alias, ids it is removed from, draft id it lands on).
# Removal matches on normalized text (so "lécithine" also removes the stored
# "lecithine"). The removals happen before the alias index is built, so the
# target draft keeps the alias naturally; the post-merge pass backstops it.
ALIAS_MOVES = [
    ("E471", (32,), 109),       # fatty-acid emulsifiers umbrella
    ("E322", (31,), 113),       # lecithin, origin not stated
    ("lecithin", (31,), 113),
    ("lécithine", (31,), 113),
    ("ليسيثين", (31,), 113),
    ("卵磷脂", (31,), 113),
]

# Named-origin lecithins stay compatible under id 31.
ADD_ALIASES = {
    31: ["lécithine de soja", "sunflower lecithin",
         "lécithine de tournesol", "向日葵卵磷脂"],
}

# 胭脂红 is the colours entry's alias (199); id 2 keeps 胭脂虫红/carmine/E120.
# Id 31 keeps only named-origin lecithins: its bare names would otherwise
# still resolve "lecithin"/"lécithine"/"ليسيثين"/"卵磷脂" to 31, since the
# matcher indexes names as terms too.
NAME_FIXES = {
    2: {"zh": "胭脂虫红"},
    31: {"en": "soy lecithin", "fr": "lécithine de soja",
         "ar": "ليسيثين الصويا", "zh": "大豆卵磷脂"},
}


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, data) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def build_alias_index(entries):
    """normalized alias/name -> list of existing entries (aliases can repeat)."""
    index = {}
    for entry in entries:
        terms = list(entry.get("aliases") or [])
        terms += [name for name in (entry.get("names") or {}).values() if name]
        for term in terms:
            key = normalize_text(term)
            if not key:
                continue
            bucket = index.setdefault(key, [])
            if entry not in bucket:
                bucket.append(entry)
    return index


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default=str(ROOT / "data" / "reference.json"))
    parser.add_argument("--draft", default=str(ROOT / "data" / "reference_validated.json"))
    parser.add_argument("--report", default=str(ROOT / "data" / "merge_report.json"))
    parser.add_argument("--dry-run", action="store_true", help="report only, do not write")
    args = parser.parse_args()

    reference_path = Path(args.reference)
    data = load_json(reference_path)
    entries = data["ingredients"]
    draft = load_json(Path(args.draft))
    draft_by_id = {e["id"]: e for e in draft}

    report = {"removed": [], "status_overrides": [], "retired": [],
              "name_fixes": [], "alias_moves": [], "resolved": [],
              "merged": [], "added": [], "alias_overlaps": [], "conflicts": []}

    # 1. Remove entries that are function words, not ingredients.
    kept = []
    for entry in entries:
        if entry["id"] in REMOVE_IDS:
            report["removed"].append({
                "id": entry["id"],
                "name": (entry.get("names") or {}).get("en"),
                "why": REMOVE_IDS[entry["id"]],
            })
        else:
            kept.append(entry)
    entries = kept

    # 2. Drop the previous unvalidated draft import (id >= 100); the validated
    #    draft replaces it wholesale.
    dropped = [e for e in entries if e["id"] >= DROP_FROM_ID]
    entries = [e for e in entries if e["id"] < DROP_FROM_ID]
    if dropped:
        report["removed"].append({
            "id": f">={DROP_FROM_ID}",
            "name": f"{len(dropped)} entries from the previous draft import",
            "why": "replaced by the validated draft",
        })

    # 3. Apply the user-reviewed status resolutions. Wine/beer/spirits entries
    #    are never overridden.
    for entry in entries:
        override = STATUS_OVERRIDES.get(entry["id"])
        if override is None or entry.get("status") == override:
            continue
        name = (entry.get("names") or {}).get("en", "")
        if _PROTECTED_NAME_RE.search(name):
            report["conflicts"].append({
                "existing_id": entry["id"], "existing_name": name,
                "action": "override refused: wine/beer/spirits stay incompatible",
            })
            continue
        report["status_overrides"].append({
            "id": entry["id"], "name": name,
            "from": entry.get("status"), "to": override,
        })
        entry["status"] = override
        entry["reviewed"] = True

    # 3b. Retire entries that are function words, not ingredients (id 30).
    by_id = {e["id"]: e for e in entries}
    for retire_id, why in RETIRE_IDS.items():
        entry = by_id.pop(retire_id, None)
        if entry is not None:
            entries.remove(entry)
            report["retired"].append({
                "id": retire_id,
                "name": (entry.get("names") or {}).get("en"),
                "why": why,
            })

    # 3c. Name fixes (胭脂红 belongs to the colours entry, not carmine).
    for fix_id, langs in NAME_FIXES.items():
        entry = by_id.get(fix_id)
        if entry is None:
            continue
        names = entry.setdefault("names", {})
        for lang, new_name in langs.items():
            old = names.get(lang)
            if old != new_name:
                names[lang] = new_name
                report["name_fixes"].append({
                    "id": fix_id, "lang": lang, "from": old, "to": new_name,
                })

    # 3d. Alias moves: strip the alias from its current owners (normalized
    #     match) so the target draft keeps it; the post-merge pass backstops
    #     the target side.
    for alias, from_ids, to_id in ALIAS_MOVES:
        removed_from = []
        wanted = normalize_text(alias)
        for from_id in from_ids:
            entry = by_id.get(from_id)
            if not entry:
                continue
            aliases = entry.get("aliases") or []
            kept = [a for a in aliases if normalize_text(a) != wanted]
            if len(kept) != len(aliases):
                entry["aliases"] = kept
                removed_from.append(from_id)
        report["alias_moves"].append({
            "alias": alias, "removed_from": removed_from, "to": to_id,
        })

    # 3e. Extra aliases on existing entries (named-origin lecithins on id 31).
    for entry_id, aliases in ADD_ALIASES.items():
        entry = by_id.get(entry_id)
        if entry is None:
            continue
        existing = {normalize_text(a) for a in (entry.get("aliases") or [])}
        for alias in aliases:
            if normalize_text(alias) not in existing:
                entry.setdefault("aliases", []).append(alias)
                existing.add(normalize_text(alias))

    # 4. Merge draft entries by alias, longest alias first.
    index = build_alias_index(entries)

    def union_merge(target, draft_entry, matched_alias):
        """Union aliases/names into target; never touches status/reason/source."""
        added_aliases = []
        existing_aliases = {normalize_text(a) for a in (target.get("aliases") or [])}
        existing_aliases |= {normalize_text(n) for n in (target.get("names") or {}).values() if n}
        for alias in draft_entry.get("aliases") or []:
            if normalize_text(alias) and normalize_text(alias) not in existing_aliases:
                target.setdefault("aliases", []).append(alias)
                existing_aliases.add(normalize_text(alias))
                added_aliases.append(alias)
        for lang, name in (draft_entry.get("names") or {}).items():
            names = target.setdefault("names", {})
            if lang not in names and name:
                names[lang] = name
        target["reviewed"] = True
        return added_aliases

    for draft_entry in draft:
        draft_name = (draft_entry.get("names") or {}).get("en") or str(draft_entry["id"])
        draft_terms = sorted(
            {normalize_text(a) for a in (draft_entry.get("aliases") or []) if normalize_text(a)},
            key=len, reverse=True,
        )
        hits = []  # (alias_length, alias, existing entry)
        overlapping = {}  # alias -> [existing ids]
        for key in draft_terms:
            for existing in index.get(key, []):
                hits.append((len(key), key, existing))
                overlapping.setdefault(key, []).append(existing["id"])
        hits.sort(key=lambda h: (-h[0], h[1]))  # longest alias first

        if not hits:
            entries.append(draft_entry)  # brand-new reference entry
            report["added"].append({"id": draft_entry["id"], "name": draft_name,
                                    "status": draft_entry.get("status")})
            continue

        # Umbrella drafts are still added, but their overlapping aliases are
        # left off: the existing entries own those aliases. Whole entries are
        # never skipped.
        if draft_entry["id"] in OVERLAP_DRAFT_IDS:
            owned = set(overlapping)  # normalized aliases owned by existing entries
            kept_aliases = [a for a in (draft_entry.get("aliases") or [])
                            if normalize_text(a) not in owned]
            new_entry = dict(draft_entry)
            new_entry["aliases"] = kept_aliases
            entries.append(new_entry)
            report["alias_overlaps"].append({
                "draft_id": draft_entry["id"],
                "draft_name": draft_name,
                "draft_status": draft_entry.get("status"),
                "overlapping_aliases": [
                    {"alias": alias, "existing_ids": sorted(set(ids))}
                    for alias, ids in sorted(overlapping.items(), key=lambda kv: -len(kv[0]))
                ],
                "action": "added; overlapping aliases left to the existing entries",
            })
            continue

        # Non-umbrella drafts whose aliases hit several existing entries
        # (pork/lard share 'porc', ethyl alcohol/alcohol share 'alcohol')
        # merge into the entry hit by the most aliases; ties break on the
        # longest matching alias, then the lowest id.
        distinct = {}
        for length, key, existing in hits:
            info = distinct.setdefault(existing["id"], {"entry": existing, "hits": 0, "longest": 0})
            info["hits"] += 1
            info["longest"] = max(info["longest"], length)
        if len(distinct) > 1:
            target_id = min(distinct, key=lambda i: (-distinct[i]["hits"], -distinct[i]["longest"], i))
            target = distinct[target_id]["entry"]
        else:
            target = hits[0][2]
        if target.get("status") != draft_entry.get("status"):
            report["conflicts"].append({
                "draft_id": draft_entry["id"],
                "draft_name": draft_name,
                "draft_status": draft_entry.get("status"),
                "matched_alias": hits[0][1],
                "existing_id": target["id"],
                "existing_status": target.get("status"),
                "action": "skipped: status conflict (no override)",
            })
            continue

        added_aliases = union_merge(target, draft_entry, hits[0][1])
        record = {
            "existing_id": target["id"],
            "existing_name": (target.get("names") or {}).get("en"),
            "draft_id": draft_entry["id"],
            "draft_name": draft_name,
            "matched_alias": hits[0][1],
            "aliases_added": added_aliases,
        }
        others = sorted(set(distinct) - {target["id"]})
        if others:
            record["also_overlapped_ids"] = others
        if draft_entry["id"] in draft_by_id and target["id"] in STATUS_OVERRIDES:
            report["resolved"].append(record)  # former conflict, resolved by override
        else:
            report["merged"].append(record)

    # 5. Backstop the alias moves: the target entry must carry the alias.
    final_by_id = {e["id"]: e for e in entries}
    for alias, _from_ids, to_id in ALIAS_MOVES:
        target = final_by_id.get(to_id)
        if target is None:
            report["conflicts"].append({
                "alias": alias, "to": to_id,
                "action": "alias move failed: target entry missing",
            })
            continue
        owned = {normalize_text(a) for a in (target.get("aliases") or [])}
        if normalize_text(alias) not in owned:
            target.setdefault("aliases", []).append(alias)

    entries.sort(key=lambda e: e["id"])

    print(f"removed:          {len(report['removed'])}")
    for item in report["removed"]:
        print(f"  - {item['id']} ({item['name']}): {item['why']}")
    print(f"status overrides: {len(report['status_overrides'])}")
    for item in report["status_overrides"]:
        print(f"  ~ id {item['id']} ({item['name']}): {item['from']} -> {item['to']}")
    print(f"retired: {len(report['retired'])}")
    for item in report["retired"]:
        print(f"  x id {item['id']} ({item['name']}): {item['why']}")
    print(f"name fixes: {len(report['name_fixes'])}")
    for item in report["name_fixes"]:
        print(f"  ~ id {item['id']} names.{item['lang']}: {item['from']} -> {item['to']}")
    print(f"alias moves: {len(report['alias_moves'])}")
    for item in report["alias_moves"]:
        print(f"  > '{item['alias']}' from {item['removed_from']} -> {item['to']}")
    print(f"resolved former conflicts: {len(report['resolved'])}")
    print(f"merged into existing:      {len(report['merged'])}")
    print(f"added as new entries:      {len(report['added'])}")
    print(f"ALIAS OVERLAPS (added, overlapping aliases left off): {len(report['alias_overlaps'])}")
    for c in report["alias_overlaps"]:
        aliases = ", ".join(f"'{a['alias']}' -> {a['existing_ids']}"
                            for a in c["overlapping_aliases"])
        print(f"  ! draft {c['draft_id']} '{c['draft_name']}' ({c['draft_status']}): {aliases}")
    print(f"CONFLICTS: {len(report['conflicts'])}")
    for c in report["conflicts"]:
        print(f"  ! {c}")

    save_json(Path(args.report), report)
    if not args.dry_run:
        data["ingredients"] = entries
        save_json(reference_path, data)
        print(f"\n{reference_path} now holds {len(entries)} entries.")
    print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
