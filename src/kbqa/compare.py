"""kbqa compare — two collections of a subject, side by side; writes nothing.

    python3 -m kbqa compare <subject dir> --from <denominator or date> --to <denominator or date> [--json]

A collection is a surface's denominator and the windows cut from it (with the
retry runs that followed them): its index, its captures and its staged rows.
`--from` and `--to` each name a denominator (`_denominator-<surface>-<date>.md`)
or a date (every surface's denominator of that date — the last correction
letter). Two dates compare every surface that has a denominator on both; one
name compares that surface. **It writes nothing.**

**Per page** (every item of either index), one of:

- `unchanged` / `changed` — in both indexes, captured on both sides, by text
  hash (`text_sha256` of each side's latest capture of the URL);
- `added` — in the later index only; `removed` — in the earlier index only;
- `unknown`, with why — anything the files cannot settle.

**Three states, never two.** `added` is said only when the earlier collection's
coverage is complete, and `removed` only when the later one's is: its
denominator fully accounted for, as `g4` counts it (every item cited by a row of
that collection or covered by a stop line — `g4_completeness.coverage`, the
code `kbqa status` runs). Otherwise the page is `unknown`, with the open items
counted. Two denominators read from different indexes (another rung, source
URL or path prefix in their first lines) cannot say what was added or removed:
`unknown`. A page in both indexes but not captured on a side is `unknown`.

**Per feature** — anchor ids, by the URLs their rows cite (a row's feature is
its `same_feature_as`, else its own id). A page's features on a side are known
when the page was captured there and its rows are staged, or a stop line names
it, or it is unchanged since an earlier capture whose rows stand (`kbqa stage`'s
own `recorded`). A feature on both sides is `unchanged` when every page that
cites it is unchanged by text hash, else `changed`. A feature on the earlier
side only is `removed` only when the later collection's coverage is complete
and every page that cited it was captured and accounted for in the later one
(or left its index): **a feature is never inferred removed from a page that was
not captured.** `added` is the same rule the other way round. Otherwise
`unknown`, with why.

Prints a short markdown summary, or with `--json` the whole structure. Exit 0;
1 only when it refuses: no subject folder, a value that is neither a date nor a
denominator of the subject, two denominators of different surfaces, the same
denominator on both sides, or no surface to compare.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from . import __version__, capture, stage
from .gates import g4_completeness
from .parsing import parse_staging
from .profile import conventions

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HEADER_RE = re.compile(r"^Index: (?P<surface>\w+), rung (?P<rung>\d+) — (?P<source>\S+)(?P<note>.*)$")
PREFIX_RE = re.compile(r"items whose path starts with (?P<prefix>\S+) \(")
WINDOW_NO_RE = re.compile(r"-w(\d+)$")
STATES = ("added", "removed", "changed", "unchanged", "unknown")
SIDES = ("from", "to")
NAMES = {"from": "earlier", "to": "later"}
LISTED = 20  # pages and features named per state in the markdown; the JSON names them all
READ_ERRORS = (OSError, UnicodeDecodeError, ValueError)


class Refused(Exception):
    pass


# --------------------------------------------------------------------------
# Which denominators
# --------------------------------------------------------------------------

def resolve(subject: Path, value: str) -> Dict[str, Path]:
    """{surface: denominator} for a date (every surface's last denominator of
    that date) or a denominator's name."""
    if DATE_RE.match(value):
        out: Dict[str, Path] = {}
        for s in conventions().surfaces:
            dens = [p for p in capture.denominators(subject, s)
                    if capture.DENOMINATOR_RE.match(p.name).group("date") == value]
            if dens:
                out[s] = dens[-1]
        if not out:
            raise Refused(f"no denominator of {subject.name} is dated {value}")
        return out
    name = Path(value).name
    m = capture.DENOMINATOR_RE.match(name)
    if not m:
        raise Refused(f"{value!r} is neither a date (YYYY-MM-DD) nor a denominator "
                      "(_denominator-<surface>-<YYYY-MM-DD>.md)")
    if not (subject / name).is_file():
        raise Refused(f"no denominator {name} in {subject}")
    return {m.group("surface"): subject / name}


def pairs(subject: Path, frm: str, to: str) -> Tuple[Dict[str, Tuple[Path, Path]], List[dict]]:
    """The surfaces compared, each with its two denominators, and those not
    compared with why."""
    a, b = resolve(subject, frm), resolve(subject, to)
    named_a, named_b = not DATE_RE.match(frm), not DATE_RE.match(to)
    if named_a and named_b and set(a) != set(b):
        raise Refused(f"{next(iter(a.values())).name} and {next(iter(b.values())).name} are denominators of "
                      "different surfaces")
    if named_a:
        b = {s: p for s, p in b.items() if s in a}
    if named_b:
        a = {s: p for s, p in a.items() if s in b}
    both = {s: (a[s], b[s]) for s in conventions().surfaces if s in a and s in b}
    skipped = [{"surface": s, "why": f"no denominator of {s} on the {NAMES['to' if s in a else 'from']} side "
                                    f"({to if s in a else frm})"}
               for s in conventions().surfaces if (s in a) != (s in b)]
    for s, (x, y) in both.items():
        if x.name == y.name:
            raise Refused(f"{x.name} is on both sides: nothing to compare")
    if not both:
        raise Refused("no surface has a denominator on both sides: "
                      + "; ".join(e["why"] for e in skipped) if skipped else "no surface to compare")
    return both, skipped


def index_source(den: Path) -> Optional[Tuple[str, str, Optional[str]]]:
    """(rung, source URL, path prefix) from a denominator's first line, or None."""
    try:
        first = den.read_text(encoding="utf-8").split("\n", 1)[0]
    except READ_ERRORS:
        return None
    m = HEADER_RE.match(first)
    if not m:
        return None
    p = PREFIX_RE.search(m.group("note"))
    return m.group("rung"), m.group("source"), p.group("prefix") if p else None


# --------------------------------------------------------------------------
# One collection
# --------------------------------------------------------------------------

def _order(w: dict) -> Tuple[str, int, str]:
    b = str(w.get("batch"))
    m = WINDOW_NO_RE.search(b)
    return str(w.get("access_date") or ""), int(m.group(1)) if m else 0, b


def batches_of(subject: Path, surface: str, den: Path) -> List[str]:
    """The windows cut from this denominator, and the retry runs that followed
    them before the next denominator's windows, in order."""
    out, current = [], None
    for w in sorted(capture._windows(subject, surface), key=_order):
        if w.get("kind") == "window" and w.get("denominator"):
            current = w["denominator"]
            if current == den.name:
                out.append(str(w["batch"]))
        elif w.get("kind") == "retry" and current == den.name:
            out.append(str(w["batch"]))
    return out


def _receipt(subject: Path, batch: str) -> Optional[dict]:
    try:
        rec = json.loads((subject / "_raw" / batch / capture.RECEIPT).read_text(encoding="utf-8"))
    except READ_ERRORS:
        return None
    return rec if isinstance(rec, dict) else None


def collection(subject: Path, surface: str, den: Path, stop_reasons: Dict[str, List[str]]) -> Dict[str, object]:
    """One side: its index items, each URL's latest capture, the rows its
    batches staged, and its coverage as g4 counts it."""
    conv = conventions()
    batches = batches_of(subject, surface, den)
    items = [u for _, u in g4_completeness.disambiguate(g4_completeness.parse_denominator(den)).values()]
    caps: Dict[str, dict] = {}
    for b in batches:
        rec = _receipt(subject, b)
        if rec is None:
            continue
        for p in rec.get("pages") or []:
            if isinstance(p, dict) and p.get("url"):
                c = {"batch": b, "url": p["url"], "text_sha256": p.get("text_sha256"),
                     "unchanged_since": p.get("unchanged_since")}
                for key in {p["url"], p.get("requested") or p["url"]}:
                    caps[key] = c
        for d in rec.get("duplicates") or []:
            if isinstance(d, dict) and d.get("url"):  # a copy: its text hash, never its own rows
                caps[d["url"]] = {"batch": b, "url": d["url"], "text_sha256": d.get("text_sha256"),
                                  "same_text_as": d.get("same_text_as")}
    rows: Dict[str, List[dict]] = {}
    files = []
    for b in batches:
        st = subject / conv.staging_for(b)
        if st.is_file():
            files.append(str(st))
            for r in parse_staging(st).rows:
                if r.obj and r.obj.get("source_url") and r.obj.get("id"):
                    rows.setdefault(str(r.obj["source_url"]), []).append(r.obj)
    stops_file = subject / conv.stops_name
    verdict, _ = g4_completeness.coverage(den, files, stops_file if stops_file.is_file() else None)
    c = verdict.counts
    open_urls = [f.where for f in verdict.findings if f.code == "index_item_without_row"]
    other = sorted({f.code for f in verdict.findings if f.code != "index_item_without_row"})
    complete = verdict.verdict == g4_completeness.PASS
    cov: Dict[str, object] = {"complete": complete, "open_items": c.get("without_row"), "open_item_urls": open_urls}
    if other:
        cov["findings"] = other
    if not complete:
        cov["why"] = (f"{c.get('without_row')} index item(s) of {den.name} have neither a row of this collection "
                      "nor a stop line" + (f" ({', '.join(other)})" if other else ""))
    return {"denominator": den.name, "index_source": index_source(den), "items": items, "batches": batches,
            "staging_files": [Path(f).name for f in files], "captures": caps, "rows": rows,
            "coverage": cov, "_stops": stop_reasons}


def _stopped(side: dict, *urls: str) -> Optional[str]:
    for u in urls:
        for r in side["_stops"].get(u, []):
            return r
    return None


def text_of(side: dict, url: str) -> Tuple[Optional[str], Optional[dict], str]:
    """(the text hash of the URL's latest capture on this side, the capture,
    why there is none)."""
    cap = side["captures"].get(url)
    if cap is None:
        stop = _stopped(side, url)
        return None, None, "not captured" + (f" (stop line: {stop})" if stop else "")
    if not cap.get("text_sha256"):
        return None, cap, f"captured in {cap['batch']} with no text hash (a receipt from before kbqa 6.21.0)"
    return str(cap["text_sha256"]), cap, ""


def _anchor(row: dict) -> str:
    return str(row.get("same_feature_as") or row["id"])


def features_of(subject: Path, side: dict, url: str) -> Tuple[bool, Set[str], str]:
    """(whether this side's features of the page are known, the anchor ids, why not)."""
    cap = side["captures"].get(url)
    if cap is None:
        stop = _stopped(side, url)
        return False, set(), "not captured" + (f" (stop line: {stop})" if stop else "")
    served = str(cap["url"])
    rows = side["rows"].get(served, []) + (side["rows"].get(url, []) if url != served else [])
    if rows:
        return True, {_anchor(r) for r in rows}, ""
    if cap.get("unchanged_since"):
        rec = stage.recorded(subject, served, str(cap["unchanged_since"]))
        if rec.get("anchors"):
            return True, set(rec["anchors"]), ""
        if rec.get("stop_line"):
            return True, set(), ""
        return False, set(), str(rec.get("why"))
    if _stopped(side, served, url):
        return True, set(), ""
    return False, set(), (f"captured in {cap['batch']}, but no staged row of this collection cites it and no stop "
                          "line names it")


# --------------------------------------------------------------------------
# The comparison
# --------------------------------------------------------------------------

def compare_surface(subject: Path, surface: str, dens: Tuple[Path, Path],
                    stop_reasons: Dict[str, List[str]]) -> Dict[str, object]:
    sides = {k: collection(subject, surface, d, stop_reasons) for k, d in zip(SIDES, dens)}
    f, t = sides["from"], sides["to"]
    comparable = f["index_source"] is not None and f["index_source"] == t["index_source"]
    index_why = "" if comparable else (
        "a denominator's first line does not name its index (one not written by kbqa index)"
        if f["index_source"] is None or t["index_source"] is None else
        f"the two denominators were read from different indexes (rung, source or path prefix: "
        f"{list(f['index_source'])} and {list(t['index_source'])}): what one lists and the other does not "
        "says nothing of the subject")
    in_f, in_t = set(f["items"]), set(t["items"])
    order = list(dict.fromkeys(f["items"] + t["items"]))

    def one_sided(other: str) -> Tuple[bool, str]:
        """Whether a page or feature on one side only may be called added/removed:
        the other side's coverage complete, and the indexes comparable."""
        if not comparable:
            return False, index_why
        cov = sides[other]["coverage"]
        if not cov["complete"]:
            return False, f"the {NAMES[other]} collection's coverage is not complete: {cov['why']}"
        return True, ""

    pages: List[dict] = []
    state_of: Dict[str, str] = {}
    for u in order:
        e: Dict[str, object] = {"url": u, "in_from_index": u in in_f, "in_to_index": u in in_t}
        hashes = {}
        for k in SIDES:
            h, cap, why = text_of(sides[k], u)
            hashes[k] = h
            e[k] = ({"batch": cap["batch"], "text_sha256": cap.get("text_sha256")} if cap else None)
            if cap and cap.get("unchanged_since"):
                e[k]["unchanged_since"] = cap["unchanged_since"]
            if not h and u in (in_f if k == "from" else in_t):
                e[f"{k}_why"] = why
        if u in in_f and u in in_t:
            if hashes["from"] and hashes["to"]:
                state = "unchanged" if hashes["from"] == hashes["to"] else "changed"
            else:
                state = "unknown"
                e["why"] = "; ".join(f"{NAMES[k]}: {e[k + '_why']}" for k in SIDES if f"{k}_why" in e)
        else:
            other = "from" if u in in_t else "to"
            ok, why = one_sided(other)
            state = ("added" if u in in_t else "removed") if ok else "unknown"
            if not ok:
                e["why"] = why
        for k in SIDES:
            e.pop(f"{k}_why", None)
        e["state"] = state
        state_of[u] = state
        pages.append(e)

    # Features: the anchor ids each side's rows give each page of its index.
    known: Dict[str, Dict[str, Tuple[bool, str]]] = {k: {} for k in SIDES}
    feats: Dict[str, Dict[str, Set[str]]] = {k: {} for k in SIDES}  # side -> anchor -> its pages
    for k in SIDES:
        for u in sides[k]["items"]:
            ok, ids, why = features_of(subject, sides[k], u)
            known[k][u] = (ok, why)
            for a in ids:
                feats[k].setdefault(a, set()).add(u)
    features: List[dict] = []
    for a in sorted(set(feats["from"]) | set(feats["to"])):
        fu, tu = sorted(feats["from"].get(a, ())), sorted(feats["to"].get(a, ()))
        e = {"id": a, "from_pages": fu, "to_pages": tu}
        if fu and tu:
            e["state"] = "unchanged" if all(state_of.get(u) == "unchanged" for u in set(fu) | set(tu)) else "changed"
        else:
            here, other = ("from", "to") if fu else ("to", "from")
            ok, why = one_sided(other)
            if ok:
                # Never from a page that was not captured: every page that gave the
                # feature is either out of the other index or accounted for there.
                blind = [(u, known[other][u][1]) for u in (fu or tu)
                         if u in sides[other]["items"] and not known[other][u][0]]
                if blind:
                    ok = False
                    why = "; ".join(f"its page {u} is not accounted for in the {NAMES[other]} collection: {w}"
                                    for u, w in blind)
            e["state"] = ("removed" if here == "from" else "added") if ok else "unknown"
            if not ok:
                e["why"] = why
        features.append(e)

    def counts(entries: List[dict]) -> Dict[str, int]:
        return {s: sum(1 for x in entries if x["state"] == s) for s in STATES}
    out_sides = {}
    for k in SIDES:
        s = sides[k]
        out_sides[k] = {"denominator": s["denominator"], "items": len(s["items"]), "batches": s["batches"],
                        "staging_files": s["staging_files"], "coverage": s["coverage"],
                        "pages_features_unknown": sorted(u for u, (ok, _) in known[k].items() if not ok)}
    return {"surface": surface, "from": out_sides["from"], "to": out_sides["to"],
            "index_comparable": comparable, **({"index_why": index_why} if not comparable else {}),
            "page_counts": counts(pages), "feature_counts": counts(features),
            "pages": pages, "features": features}


def compare(subject: Path, frm: str, to: str) -> Dict[str, object]:
    both, skipped = pairs(subject, frm, to)
    reasons = stage._stop_reasons(subject)
    return {"kbqa": __version__, "read_only": True, "subject": str(subject), "from": frm, "to": to,
            "surfaces": [compare_surface(subject, s, d, reasons) for s, d in both.items()],
            "surfaces_not_compared": skipped}


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------

def markdown(out: Dict[str, object]) -> str:
    lines: List[str] = []
    a = lines.append
    a(f"# Compare — {Path(str(out['subject'])).name}: {out['from']} → {out['to']}")
    a("")
    a(f"kbqa {out['kbqa']} · read-only: computed from the files, nothing written · `unknown` = the files "
      "cannot tell")
    a("")
    for e in out["surfaces_not_compared"]:
        a(f"- {e['surface']}: not compared — {e['why']}")
    for s in out["surfaces"]:
        a(f"## {s['surface']}: {s['from']['denominator']} → {s['to']['denominator']}")
        a("")
        for k in SIDES:
            side = s[k]
            cov = side["coverage"]
            a(f"- {NAMES[k]}: {side['items']} items, {len(side['batches'])} window(s), coverage "
              + ("complete" if cov["complete"] else f"not complete — {cov['why']}"))
        if not s["index_comparable"]:
            a(f"- indexes not comparable: {s['index_why']}")
        a("")
        a("| state | pages | features |")
        a("|---|---|---|")
        for st in STATES:
            a(f"| {st} | {s['page_counts'][st]} | {s['feature_counts'][st]} |")
        a("")
        for label, entries, key in (("Pages", s["pages"], "url"), ("Features", s["features"], "id")):
            for st in ("added", "removed", "changed", "unknown"):
                these = [x for x in entries if x["state"] == st]
                if not these:
                    continue
                a(f"**{label} {st}** ({len(these)})")
                for x in these[:LISTED]:
                    a(f"- {x[key]}" + (f" — {x['why']}" if x.get("why") else ""))
                if len(these) > LISTED:
                    a(f"- … and {len(these) - LISTED} more (--json)")
                a("")
    return "\n".join(lines) + "\n"


def run(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="kbqa compare")
    ap.add_argument("subject", help="the subject folder")
    ap.add_argument("--from", dest="frm", required=True, help="the earlier collection: a denominator or a date")
    ap.add_argument("--to", required=True, help="the later collection: a denominator or a date")
    ap.add_argument("--json", action="store_true", help="the whole structure as JSON, not the markdown summary")
    args = ap.parse_args(argv)
    subject = Path(args.subject)
    try:
        if not subject.is_dir():
            raise Refused(f"no subject folder {subject}")
        out = compare(subject, args.frm, args.to)
    except Refused as exc:
        print(json.dumps({"refused": str(exc), "next_step": "operator"}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=2) if args.json else markdown(out), end="\n" if args.json else "")
    return 0


def main() -> None:  # pragma: no cover
    sys.exit(run())
