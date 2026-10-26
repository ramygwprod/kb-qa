"""K5 · Mapping files — mapcheck --staging <f> --map <A> [--map <B>]
                                 --codebook <f> --elements <f> [--subject <d>]

A mapping file (`_map-<batch>-<A|B>.jsonl`) is our reading of a batch, kept
outside the rows. This checks that it is WELL-FORMED and that every code it
uses EXISTS — never that a mapping is right. Correctness is a human audit.

Checked, per mapper:
  · one line per staging row: every staging id exactly once, none added —
    except a row with `same_feature_as`: another source of a feature takes
    its anchor's classification and has no line of its own
  · `id` is the first key; exactly the fields of the mapper's §5 format,
    none missing, none extra, none null (empty is `""` or `[]`)
  · `theme` is a codebook code or one of the three non-feature codes;
    every `theme_links` entry is a codebook code
  · every `pcf_ids` entry is `{pcf_id, hierarchy_id, name}` and all three
    equal the element list's values for that id — an id not on the list does
    not exist, and a name that differs was not copied
  · `role_source` is filled (`rbac-row`, `apqc-closest`, or
    `rbac-vendor:<row id>` naming a row of this subject)
  · `actor`, `confidence`, `status` are values of their fixed sets
  · `needs-human` rows are listed and never counted as mapped
  · one APQC element on more than 30 % of the batch's rows, and on at least
    two of them → a finding that a human must read a sample before the batch
    is accepted. An element on one row never dominates: below two rows the
    share measures nothing (one row of three anchors is 33 % by arithmetic)
  · the story's role — the words after "As" (and its "a" / "an", when the
    role is singular), up to "I want" — is the row's `role`, singular or
    plural as printed, compared without case or punctuation (a FAIL: the
    first live run had stories whose "As a …" did not match their `role`).
    When `role_source` is `apqc-closest` the tag "(APQC-closest)" follows the
    role, and only then (the operator's ruling of 2026-10-18)
  · a `needs-human` note opens with the name of the rule or open pattern it
    stops on, in brackets (`[<name>] …`), so the check can group the rows by
    question and the operator answers each question once (a FAIL when absent)
  · advisory, never a FAIL: the story's words that are in neither the row
    (`vendor_term`, `what_it_does`, `source_quote`, `parent_path`), its
    `role`, nor its elements' names, once the story template's own words
    (STORY_TEMPLATE_WORDS) are taken out. The rule is that every word comes
    from the row or the element; which outside words are fair (a plural, a
    joining word) is a human's call, so they are listed, not judged

With two mappers, agreement is reported on ALL staging rows — a needs-human or
missing row is a disagreement, never excluded. Agreement is consistency, not
correctness: two mappers can agree on the same mistake.

Theme codes are read from the codebook's table (`| I01 | …`), and elements
from the element list — derived, never typed here.
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from ..parsing import parse_staging
from ..profile import conventions
from ..verdict import FAIL, PASS, Finding, Verdict, input_ref
from . import EXIT_FAIL, EXIT_PASS

GATE = "mapcheck"

# The mapper's output format (mapper agent §5), in order. Fixed by ruling;
# changing it is a change to the mapper and to this check together.
FIELDS = ("id", "user_story", "role", "role_source", "actor", "theme",
          "theme_links", "pcf_ids", "confidence", "status", "note")
LIST_FIELDS = ("theme_links", "pcf_ids")
NON_FEATURE = ("NONE", "NO-FUNCTION", "NOT-FEATURE")
NO_ROLE = ("NO-FUNCTION", "NOT-FEATURE")  # no story, so no role to source
ACTORS = ("A", "B", "C", "D", "E")
CONFIDENCE = ("low", "medium", "high")
STATUSES = ("mapped", "needs-human")
PCF_KEYS = ("pcf_id", "hierarchy_id", "name")
DOMINANCE = 0.30
# An element on fewer rows than this never dominates: on a batch of three
# anchors one row is 33 % by arithmetic, and that share measures nothing.
DOMINANCE_MIN_ROWS = 2

THEME_ROW_RE = re.compile(r"^\|\s*(?P<code>I\d{2})\s*\|")
# "As a <role>, I want … so that …" — the role is what stands between them.
# The article is optional: a plural role has none ("As admins, I want").
STORY_ROLE_RE = re.compile(r"^\s*As\s+(?:an?\s+)?(?P<role>.+?)\s*,?\s+I\s+want\b", re.IGNORECASE)
# The tag a story carries after its role when the role is the APQC-closest one.
APQC_TAG = "(APQC-closest)"
APQC_TAG_RE = re.compile(r"\s*\(\s*APQC-closest\s*\)\s*$", re.IGNORECASE)
# A needs-human note opens with the name of the rule or open pattern it stops on.
NOTE_PATTERN_RE = re.compile(r"^\s*\[(?P<name>[^\[\]\n]*\S[^\[\]\n]*)\]")
# The template's own words: the only words a story may hold that the row and
# its elements need not. Kept to the template, so nothing else is excused.
STORY_TEMPLATE_WORDS = frozenset({"as", "a", "an", "i", "want", "to", "so", "that", "apqc", "closest"})
WORD_RE = re.compile(r"[a-z0-9]+(?:['’][a-z]+)?")


def words(text: str) -> List[str]:
    return WORD_RE.findall(str(text).casefold())


def story_role(story: str) -> Optional[str]:
    m = STORY_ROLE_RE.match(str(story))
    return m.group("role") if m else None


def note_pattern(note: str) -> Optional[str]:
    """The rule or open pattern a needs-human note names, spaces collapsed."""
    m = NOTE_PATTERN_RE.match(str(note))
    return " ".join(m.group("name").split()) if m else None


def read_codebook(path: Path) -> List[str]:
    return [m.group("code") for line in path.read_text(encoding="utf-8").splitlines()
            for m in [THEME_ROW_RE.match(line)] if m]


def read_elements(path: Path) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            e = json.loads(line)
            out[str(e["pcf_id"])] = e
    return out


def subject_ids(vendor_dir: Path) -> Set[str]:
    conv = conventions()
    ids: Set[str] = set()
    paths = sorted(vendor_dir.glob("feature-tree*.md")) + sorted(
        vendor_dir.glob(f"{conv.staging_prefix}*{conv.staging_suffix}"))
    for p in paths:
        for rp in parse_staging(p).rows:
            if rp.obj and rp.obj.get("id"):
                ids.add(str(rp.obj["id"]))
    return ids


ROW_WORD_FIELDS = ("vendor_term", "what_it_does", "source_quote", "parent_path")


def check_one(letter: str, path: Path, staging_ids: List[str], themes: Set[str],
              elements: Dict[str, dict], known_ids: Optional[Set[str]],
              findings: List[Finding],
              staging_rows: Optional[Dict[str, dict]] = None,
              other_sources: Optional[Set[str]] = None) -> Tuple[Dict[str, dict], dict]:
    by_id: Dict[str, dict] = {}
    outside_words: List[Dict[str, object]] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    scanned = 0
    seen = Counter()

    def f(code: str, msg: str, n: int) -> None:
        findings.append(Finding(code, f"[{letter}] {msg}", f"{path.name}:{n}"))

    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        scanned += 1
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            f("map_line_unparseable", f"invalid JSON: {exc.msg}", n)
            continue
        if not isinstance(obj, dict):
            f("map_line_unparseable", "line is not a JSON object", n)
            continue
        keys = list(obj)
        if not keys or keys[0] != "id":
            f("map_id_not_first", f"first key is {keys[0] if keys else None!r}", n)
        missing = [k for k in FIELDS if k not in obj]
        extra = [k for k in keys if k not in FIELDS]
        if missing or extra:
            f("map_fields_mismatch", f"missing {missing}, extra {extra}", n)
        nulls = [k for k in FIELDS if k in obj and obj[k] is None]
        if nulls:
            f("map_null_value", f"null in {nulls}; empty is \"\" or []", n)
        rid = str(obj.get("id", ""))
        seen[rid] += 1
        if seen[rid] > 1:
            f("map_id_duplicate", f"id {rid!r} appears more than once", n)
            continue
        by_id[rid] = obj

        theme = obj.get("theme")
        if theme not in themes and theme not in NON_FEATURE:
            f("theme_unknown", f"theme {theme!r} is not a codebook code", n)
        links = obj.get("theme_links")
        if not isinstance(links, list):
            f("map_type", "theme_links is not a list", n)
        else:
            for t in links:
                if t not in themes:
                    f("theme_link_unknown", f"theme_links entry {t!r} is not a codebook code", n)
        pcfs = obj.get("pcf_ids")
        if not isinstance(pcfs, list):
            f("map_type", "pcf_ids is not a list", n)
        else:
            for e in pcfs:
                if not isinstance(e, dict) or list(e) != list(PCF_KEYS):
                    f("pcf_entry_shape", f"pcf_ids entry {e!r} is not {{pcf_id, hierarchy_id, name}}", n)
                    continue
                ref = elements.get(str(e["pcf_id"]))
                if ref is None:
                    f("pcf_unknown", f"pcf_id {e['pcf_id']!r} is not in the element list", n)
                    continue
                for k in ("hierarchy_id", "name"):
                    if str(e[k]) != str(ref[k]):
                        f("pcf_not_copied", f"pcf_id {e['pcf_id']} {k} is {e[k]!r}, "
                                            f"the list says {ref[k]!r}", n)
        rs = obj.get("role_source")
        if not rs:
            if theme not in NO_ROLE:
                f("role_source_empty", "role_source is empty", n)
        elif rs in ("rbac-row", "apqc-closest"):
            pass
        elif isinstance(rs, str) and rs.startswith("rbac-vendor:"):
            cited = rs.split(":", 1)[1]
            if known_ids is not None and cited not in known_ids:
                f("role_source_row_unknown", f"{rs!r} cites a row id this subject does not have", n)
        else:
            f("role_source_invalid", f"role_source {rs!r} is not rbac-row | rbac-vendor:<row id> | apqc-closest", n)
        if obj.get("actor") not in ACTORS and not (theme in NO_ROLE and obj.get("actor") == ""):
            f("actor_invalid", f"actor {obj.get('actor')!r} is not one of {'/'.join(ACTORS)}", n)
        if obj.get("confidence") not in CONFIDENCE:
            f("confidence_invalid", f"confidence {obj.get('confidence')!r}", n)
        if obj.get("status") not in STATUSES:
            f("status_invalid", f"status {obj.get('status')!r} is not mapped | needs-human", n)
        if obj.get("status") == "needs-human":
            note = str(obj.get("note", ""))
            if not note.strip():
                f("needs_human_without_reason", "needs-human row has an empty note", n)
            elif note_pattern(note) is None:
                f("needs_human_without_pattern", f"needs-human note {note[:60]!r} does not open with the "
                                                 "rule or open pattern it stops on, in brackets: `[<name>] …`", n)

        story = obj.get("user_story")
        if isinstance(story, str) and story.strip() and theme not in NO_ROLE:
            said = story_role(story)
            role = APQC_TAG_RE.sub("", str(obj.get("role", "")))
            if said is None:
                f("story_role_mismatch", f"user_story {story[:80]!r} does not open \"As <role>, I want\", "
                                         f"so its role cannot be compared with role {obj.get('role')!r}", n)
            else:
                tagged = bool(APQC_TAG_RE.search(said))
                said = APQC_TAG_RE.sub("", said)
                if words(said) != words(role):
                    f("story_role_mismatch", f"user_story says \"As {said}\" but role is {obj.get('role')!r}", n)
                elif rs == "apqc-closest" and not tagged:
                    f("story_role_mismatch", f"role_source is apqc-closest, so the story carries {APQC_TAG} "
                                             f"right after the role: \"As {said} {APQC_TAG}, I want\"", n)
                elif tagged and rs != "apqc-closest":
                    f("story_role_mismatch", f"the story carries {APQC_TAG}, but role_source is {rs!r}: "
                                             "the tag marks an APQC-closest role only", n)
            if staging_rows is not None:
                row = staging_rows.get(rid, {})
                allowed = set(STORY_TEMPLATE_WORDS) | set(words(obj.get("role", "")))
                for k in ROW_WORD_FIELDS:
                    allowed |= set(words(row.get(k, "")))
                for e in (pcfs if isinstance(pcfs, list) else []):
                    if isinstance(e, dict):
                        allowed |= set(words(e.get("name", "")))
                extra = [w for w in dict.fromkeys(words(story)) if w not in allowed]
                if extra:
                    outside_words.append({"id": rid, "words": extra})

    staged = set(staging_ids)
    for rid in staging_ids:
        if rid not in by_id:
            findings.append(Finding("map_id_missing", f"[{letter}] staging id {rid!r} has no line", path.name))
    for rid in by_id:
        if other_sources and rid in other_sources:
            findings.append(Finding("map_line_for_another_source",
                                    f"[{letter}] {rid!r} has `same_feature_as`: it takes its anchor's "
                                    "classification and has no line of its own", path.name))
        elif rid not in staged:
            findings.append(Finding("map_id_not_in_staging", f"[{letter}] {rid!r} is not a row of this batch", path.name))

    rows = [by_id[r] for r in staging_ids if r in by_id]
    needs_human = [r["id"] for r in rows if r.get("status") == "needs-human"]
    by_pattern = group_by_pattern(rows)
    mapped = [r for r in rows if r.get("status") == "mapped"]
    element_rows = Counter()
    for r in rows:
        for e in {str(x.get("pcf_id")) for x in (r.get("pcf_ids") or []) if isinstance(x, dict)}:
            element_rows[e] += 1
    total = len(staging_ids)
    dominant = []
    for e, c in element_rows.most_common():
        # Below two rows the share measures nothing: one element on one row of
        # a three-anchor batch is 33 % by arithmetic alone.
        if total and c >= DOMINANCE_MIN_ROWS and c / total > DOMINANCE:
            dominant.append({"pcf_id": e, "rows": c, "share": round(c / total, 3)})
            findings.append(Finding(
                "element_dominates",
                f"[{letter}] element {e} ({elements.get(e, {}).get('name', '?')}) is on "
                f"{c} of {total} rows (> {int(DOMINANCE * 100)} %) — a human reads a "
                "sample of these rows before the batch is accepted",
                path.name,
            ))
    summary = {
        "scanned": scanned,
        "rows_expected": total,
        "mapped": len(mapped),
        "needs_human": len(needs_human),
        "needs_human_ids": needs_human,
        # one question per rule or open pattern, with the rows it covers
        "needs_human_by_pattern": by_pattern,
        "dominant_elements": dominant,
        # advisory: listed for a human, never a finding
        "story_words_outside_row_and_element": outside_words,
    }
    return by_id, summary


UNNAMED = "(no rule named)"


def group_by_pattern(rows: List[dict]) -> Dict[str, List[str]]:
    """{the named rule or open pattern: the ids stopping on it}, the largest
    group first; names are grouped without case. A note naming none is listed
    under UNNAMED, never dropped."""
    groups: Dict[str, List[str]] = {}
    spelling: Dict[str, str] = {}
    for r in rows:
        if r.get("status") != "needs-human":
            continue
        name = note_pattern(str(r.get("note", ""))) or UNNAMED
        key = name.casefold()
        spelling.setdefault(key, name)
        groups.setdefault(key, []).append(str(r.get("id")))
    ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return {spelling[k]: ids for k, ids in ordered}


def agreement(staging_ids: List[str], a: Dict[str, dict], b: Dict[str, dict]) -> dict:
    """Agreement on ALL staging rows. A row either side lacks, or marks
    needs-human, counts as a disagreement — it is never dropped from the base."""
    def pcfs(r: dict) -> Tuple[str, ...]:
        return tuple(sorted(str(x.get("pcf_id")) for x in (r.get("pcf_ids") or []) if isinstance(x, dict)))

    total = len(staging_ids)
    theme = pcf = both = 0
    for rid in staging_ids:
        ra, rb = a.get(rid), b.get(rid)
        if not ra or not rb or "needs-human" in (ra.get("status"), rb.get("status")):
            continue
        t = ra.get("theme") == rb.get("theme")
        p = pcfs(ra) == pcfs(rb)
        theme += t
        pcf += p
        both += t and p
    rate = (lambda k: round(k / total, 3) if total else None)
    return {"base_rows": total, "theme_agree": theme, "pcf_agree": pcf, "both_agree": both,
            "theme_rate": rate(theme), "pcf_rate": rate(pcf), "both_rate": rate(both),
            "note": "consistency, not correctness"}


def run(argv: Optional[List[str]] = None) -> Tuple[Verdict, int]:
    ap = argparse.ArgumentParser(prog="kbqa mapcheck")
    ap.add_argument("--staging", required=True)
    ap.add_argument("--map", required=True, action="append")
    ap.add_argument("--codebook", required=True)
    ap.add_argument("--elements", required=True)
    ap.add_argument("--subject", default=None)  # not --vendor-dir: that is the CLI's recording flag
    args = ap.parse_args(argv)

    findings: List[Finding] = []
    staging = Path(args.staging)
    maps = [Path(m) for m in args.map]
    inputs: Dict[str, object] = {"staging": input_ref(staging),
                                 "codebook": input_ref(Path(args.codebook)),
                                 "elements": input_ref(Path(args.elements))}
    for i, m in enumerate(maps):
        inputs[f"map[{i}]"] = input_ref(m)
    if len(maps) > 2:
        findings.append(Finding("too_many_maps", "at most two mapping files (A and B)"))
    for p in [staging, Path(args.codebook), Path(args.elements)] + maps:
        if not p.exists():
            findings.append(Finding("input_missing", f"not found: {p}"))
    if findings:
        return Verdict(GATE, FAIL, inputs, {"scanned": 0, "failed": len(findings)}, findings), EXIT_FAIL

    themes = set(read_codebook(Path(args.codebook)))
    elements = read_elements(Path(args.elements))
    if not themes or not elements:
        findings.append(Finding("reference_empty",
                                f"codebook gave {len(themes)} theme codes, element list "
                                f"gave {len(elements)} elements; nothing to check against"))
        return Verdict(GATE, FAIL, inputs, {"scanned": 0, "failed": len(findings)}, findings), EXIT_FAIL

    staged = [r.obj for r in parse_staging(staging).rows if r.obj and r.obj.get("id")]
    # Only anchors are classified; another source of a feature takes its anchor's reading.
    other_sources = {str(o["id"]) for o in staged if o.get("same_feature_as")}
    staging_ids = [str(o["id"]) for o in staged if str(o["id"]) not in other_sources]
    staging_rows = {str(o["id"]): o for o in staged}
    known = subject_ids(Path(args.subject)) if args.subject else None

    per: Dict[str, dict] = {}
    parsed: Dict[str, Dict[str, dict]] = {}
    for m in maps:
        letter = m.stem.rsplit("-", 1)[-1] if "-" in m.stem else m.stem
        by_id, summary = check_one(letter, m, staging_ids, themes, elements, known, findings, staging_rows,
                                   other_sources)
        per[letter] = summary
        parsed[letter] = by_id

    counts: Dict[str, object] = {
        "scanned": sum(s["scanned"] for s in per.values()),
        "staging_rows": len(staged),
        "classified_rows": len(staging_ids),
        "other_sources_not_classified": len(other_sources),
        "theme_codes": len(themes),
        "elements": len(elements),
        "per_mapper": per,
    }
    if len(parsed) == 2:
        (_, a), (_, b) = sorted(parsed.items())
        counts["agreement"] = agreement(staging_ids, a, b)
    # The operator's questions across both passes: one per rule or open pattern.
    questions: Dict[str, Dict[str, List[str]]] = {}
    for letter, s in sorted(per.items()):
        for name, ids in s["needs_human_by_pattern"].items():
            key = next((k for k in questions if k.casefold() == name.casefold()), name)
            questions.setdefault(key, {})[letter] = ids
    counts["questions"] = [{"pattern": k, "rows": sorted({i for ids in v.values() for i in ids}), "per_pass": v}
                           for k, v in sorted(questions.items(),
                                              key=lambda kv: -len({i for ids in kv[1].values() for i in ids}))]
    if not staging_ids:
        findings.append(Finding("nothing_checked", "the staging file has no rows to classify; an empty check "
                                                   "is not a pass"))
    counts["failed"] = len(findings)
    verdict = PASS if not findings else FAIL
    return Verdict(GATE, verdict, inputs, counts, findings), (
        EXIT_PASS if verdict == PASS else EXIT_FAIL
    )
