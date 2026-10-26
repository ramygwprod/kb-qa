"""kbqa map — the product map: the vendor's architecture, as the rows show it.

    python3 -m kbqa map <subject dir> [--merged-only] [--json]

A derived, read-only view, computed by code from the subject's feature tree and
every staging file (with `--merged-only`, the tree alone). **It writes
nothing**, is never typed by hand and is never merged into the tree.

- **Modules** are the rows' `parent_path` exactly as printed, split on ` > `:
  the vendor's own words, never renamed, merged or normalised — two modules are
  one only when their names are the same string. They nest as the breadcrumbs
  nest.
- Under each module, its **features**: the anchor rows (no `same_feature_as`)
  whose `parent_path` is that module — id, `vendor_term`, `what_it_does`,
  `mechanism`, `outcome`, `evidence_grade`, `depth_level`, `source_url`.
- Under each feature, its **other sources** (every row whose `same_feature_as`
  names it, each with its own `parent_path`) and its **ways in**: the
  interfaces its rows — the anchor's and its other sources' — document, grouped
  by `interface_type` and `operation`, each with its parameters and the row
  ids that document them.
- **Counts** per module (its own, and with its sub-modules: features, other
  sources, ways in, interface rows) and totals. Every row read is counted once:
  rows = features + other sources + links to no anchor.
- Rows whose `parent_path` is `unknown` (or missing, or empty) are listed under
  one **position unknown** group, never dropped: the features there in full,
  and the other sources there by id beside the feature they are listed under.
  Rows whose `depth_level` is `unknown` beside a breadcrumb are listed too.
- Rows whose `same_feature_as` names an anchor the subject does not have — no
  row with that id, or a row that is itself another source — are listed under
  **links to no anchor**, with the id they name and why.
- A row that cannot be parsed, a row with no id, a file that cannot be read and
  an id read again (other than a merged row still staged: its tree copy is the
  one mapped) are listed by file and line: the map is then marked incomplete, and its
  counts are of the rows that could be read.

The tree is read first, so a row merged and still staged is read as merged
(as `features.subject_rows` reads them).

Prints a markdown nested list, or with `--json` the whole structure. Exit 0;
1 only when it refuses: no subject folder.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import __version__, features
from .parsing import parse_staging
from .profile import conventions

SEP = " > "  # how a breadcrumb's items are written on one line (`stage.CRUMB_SEP`)
UNKNOWN = "unknown"
READ_ERRORS = (OSError, UnicodeDecodeError, ValueError)
FEATURE_FIELDS = ("id", "vendor_term", "what_it_does", "mechanism", "outcome", "evidence_grade",
                  "depth_level", "source_url")
SOURCE_FIELDS = ("id", "vendor_term", "what_it_does", "evidence_grade", "source_url", "parent_path",
                 "interface_type", "operation", "parameter")
INTERFACE_FIELDS = ("interface_type", "operation", "parameter")
COUNT_KEYS = ("features", "other_sources", "interfaces", "interface_rows")


class Refused(Exception):
    pass


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------

def read_rows(subject: Path, merged_only: bool) -> Dict[str, object]:
    """Every row of the tree and (unless merged-only) of every staging file,
    each with the file it was read from; and what could not be read."""
    conv = conventions()
    tree = subject / features.TREE
    paths = [tree]
    if not merged_only:
        paths += sorted(subject.glob(f"{conv.staging_prefix}*{conv.staging_suffix}"))
    rows: Dict[str, dict] = {}
    files: List[Dict[str, object]] = []
    unreadable_files: List[Dict[str, str]] = []
    unreadable_rows: List[Dict[str, object]] = []
    without_id: List[Dict[str, object]] = []
    seen: Dict[str, List[str]] = {}
    for p in paths:
        if not p.is_file():
            continue
        try:
            parsed = parse_staging(p)
        except READ_ERRORS as exc:
            unreadable_files.append({"file": p.name, "why": f"cannot be read: {exc}"})
            continue
        n = 0
        for rp in parsed.rows:
            if not isinstance(rp.obj, dict):
                unreadable_rows.append({"file": p.name, "line": rp.line_no, "error": rp.error})
                continue
            rid = rp.obj.get("id")
            if rid in (None, ""):
                without_id.append({"file": p.name, "line": rp.line_no})
                continue
            n += 1
            seen.setdefault(str(rid), []).append(p.name)
            # the tree first: a row merged and still staged is read as merged
            rows.setdefault(str(rid), {"row": rp.obj, "file": p.name})
        files.append({"file": p.name, "rows": n})
    # A row merged and still staged is read twice by design (the tree's copy is
    # mapped); any other id read again is listed, the copies not mapped named.
    again = []
    for rid, names in seen.items():
        rest = names[1:]
        if names[0] == features.TREE and rest and rest[0] != features.TREE:
            rest = rest[1:]
        if rest:
            again.append({"id": rid, "mapped_from": names[0], "not_mapped_from": rest})
    return {"rows": rows, "files": files, "tree": tree.is_file(), "unreadable_files": unreadable_files,
            "unreadable_rows": unreadable_rows, "rows_without_id": without_id, "ids_read_again": again}


def position(parent_path: object) -> Optional[List[str]]:
    """The module path of a row — its `parent_path` split on ` > `, each item
    exactly as printed — or None when the position is unknown."""
    if not isinstance(parent_path, str) or not parent_path.strip() or parent_path.strip() == UNKNOWN:
        return None
    return parent_path.split(SEP)


def _key(v: object) -> Optional[str]:
    return None if v is None else v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def is_interface_row(row: dict) -> bool:
    return any(row.get(k) not in (None, "") for k in INTERFACE_FIELDS)


def ways_in(rows: List[Tuple[str, dict]]) -> List[Dict[str, object]]:
    """The interfaces these rows document, grouped by `interface_type` and
    `operation`, each with its parameters and the rows that document them."""
    groups: Dict[Tuple[Optional[str], Optional[str]], Dict[str, object]] = {}
    for rid, row in rows:
        if not is_interface_row(row):
            continue
        k = (_key(row.get("interface_type")), _key(row.get("operation")))
        g = groups.setdefault(k, {"interface_type": k[0], "operation": k[1], "ids": [], "parameters": {}})
        g["ids"].append(rid)
        param = _key(row.get("parameter"))
        if param not in (None, ""):
            g["parameters"].setdefault(param, []).append(rid)
    out = []
    for k in sorted(groups, key=lambda t: (t[0] or "", t[1] or "")):
        g = groups[k]
        out.append({"interface_type": g["interface_type"], "operation": g["operation"], "ids": sorted(g["ids"]),
                    "parameters": [{"parameter": p, "ids": sorted(ids)} for p, ids in sorted(g["parameters"].items())]})
    return out


# --------------------------------------------------------------------------
# The map
# --------------------------------------------------------------------------

def _zero() -> Dict[str, int]:
    return {k: 0 for k in COUNT_KEYS}


def _feature(rid: str, entry: dict, others: List[Tuple[str, dict]]) -> Dict[str, object]:
    row = entry["row"]
    out: Dict[str, object] = {k: row.get(k) for k in FEATURE_FIELDS}
    out["id"] = rid
    out["file"] = entry["file"]
    out["other_sources"] = [{**{k: o["row"].get(k) for k in SOURCE_FIELDS}, "id": oid, "file": o["file"]}
                            for oid, o in others]
    out["ways_in"] = ways_in([(rid, row)] + [(oid, o["row"]) for oid, o in others])
    out["counts"] = {"features": 1, "other_sources": len(others), "interfaces": len(out["ways_in"]),
                     "interface_rows": sum(1 for _, r in [(rid, row)] + [(oid, o["row"]) for oid, o in others]
                                           if is_interface_row(r))}
    return out


def build(subject: Path, merged_only: bool = False) -> Dict[str, object]:
    read = read_rows(subject, merged_only)
    rows: Dict[str, dict] = read["rows"]
    anchors = {rid for rid, e in rows.items() if features.is_anchor(e["row"])}
    linked: Dict[str, List[Tuple[str, dict]]] = {}
    broken: List[Dict[str, object]] = []
    for rid in sorted(rows):
        e = rows[rid]
        sfa = e["row"].get("same_feature_as")
        if rid in anchors:
            continue
        if isinstance(sfa, str) and sfa in anchors:
            linked.setdefault(sfa, []).append((rid, e))
            continue
        if not isinstance(sfa, str):
            why = "same_feature_as is not a row id"
        elif sfa not in rows:
            why = "no row of the subject has that id"
        else:
            why = f"that row is itself another source (of {_key(rows[sfa]['row'].get('same_feature_as'))!r})"
        broken.append({**{k: e["row"].get(k) for k in SOURCE_FIELDS}, "id": rid,
                       "same_feature_as": sfa, "why": why, "file": e["file"]})

    # the module tree, keyed by the path's items exactly as printed
    nodes: Dict[Tuple[str, ...], Dict[str, object]] = {}

    def node(path: Tuple[str, ...]) -> Dict[str, object]:
        if path not in nodes:
            nodes[path] = {"module": path[-1], "path": SEP.join(path), "features": [], "modules": []}
            if len(path) > 1:
                node(path[:-1])
        return nodes[path]

    unknown_features: List[Dict[str, object]] = []
    depth_unknown: List[str] = []
    for rid in sorted(anchors):
        e = rows[rid]
        f = _feature(rid, e, linked.get(rid, []))
        path = position(e["row"].get("parent_path"))
        if path is None:
            f["parent_path"] = e["row"].get("parent_path")
            unknown_features.append(f)
        else:
            node(tuple(path))["features"].append(f)
    for rid, e in sorted(rows.items()):
        if position(e["row"].get("parent_path")) is not None and str(e["row"].get("depth_level")).strip() == UNKNOWN:
            depth_unknown.append(rid)

    for path in sorted(nodes, key=len, reverse=True):
        n = nodes[path]
        own = _zero()
        for f in n["features"]:
            for k in COUNT_KEYS:
                own[k] += f["counts"][k]
        sub = dict(own)
        for child in n["modules"]:
            for k in COUNT_KEYS:
                sub[k] += child["with_sub_modules"][k]
        n["counts"], n["with_sub_modules"] = own, sub
        n["modules"].sort(key=lambda c: c["module"])
        if len(path) > 1:
            nodes[path[:-1]]["modules"].append(n)
    top = sorted((nodes[p] for p in nodes if len(p) == 1), key=lambda c: c["module"])

    unknown_counts = _zero()
    for f in unknown_features:
        for k in COUNT_KEYS:
            unknown_counts[k] += f["counts"][k]
    elsewhere = [{"id": oid, "listed_under": anchor}
                 for anchor, others in sorted(linked.items()) for oid, o in others
                 if position(o["row"].get("parent_path")) is None]
    totals = _zero()
    for n in top:
        for k in COUNT_KEYS:
            totals[k] += n["with_sub_modules"][k]
    for k in COUNT_KEYS:
        totals[k] += unknown_counts[k]
    totals.update(rows=len(rows), modules=len(nodes),
                  position_unknown=sum(1 for e in rows.values() if position(e["row"].get("parent_path")) is None),
                  depth_unknown=len(depth_unknown), links_to_no_anchor=len(broken),
                  unreadable_rows=len(read["unreadable_rows"]), rows_without_id=len(read["rows_without_id"]), ids_read_again=len(read["ids_read_again"]))
    complete = not (read["unreadable_files"] or read["unreadable_rows"] or read["rows_without_id"]
                    or read["ids_read_again"])
    return {"subject": str(subject),
            "read_from": "the feature tree" if merged_only else "the feature tree and every staging file",
            "merged_only": merged_only, "tree": read["tree"], "files": read["files"],
            "complete": complete, "totals": totals, "modules": top,
            "position_unknown": {"features": unknown_features, "counts": unknown_counts,
                                 "other_sources_listed_under_their_feature": elsewhere},
            "depth_unknown": depth_unknown, "links_to_no_anchor": broken,
            "unreadable_files": read["unreadable_files"], "unreadable_rows": read["unreadable_rows"],
            "rows_without_id": read["rows_without_id"], "ids_read_again": read["ids_read_again"]}


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------

def _t(v: object) -> str:
    return "–" if v is None else str(v).replace("\n", " ")


def _n(k: int, one: str, many: str) -> str:
    return f"{k} {one if k == 1 else many}"


def _counts(c: Dict[str, int]) -> str:
    return (f"{_n(c['features'], 'feature', 'features')}, {_n(c['other_sources'], 'other source', 'other sources')}, "
            f"{_n(c['interfaces'], 'way in', 'ways in')}")


def _ids(ids: List[str]) -> str:
    return ", ".join(f"`{i}`" for i in ids)


def _feature_md(f: Dict[str, object], pad: str, a) -> None:
    a(f"{pad}- feature `{f['id']}` **{_t(f['vendor_term'])}** — {_t(f['what_it_does'])} · "
      f"{_t(f['mechanism'])} / {_t(f['outcome'])} · {_t(f['evidence_grade'])} · depth {_t(f['depth_level'])} · "
      f"{_t(f['source_url'])}")
    for o in f["other_sources"]:
        a(f"{pad}  - other source `{o['id']}` **{_t(o['vendor_term'])}** — {_t(o['what_it_does'])} · "
          f"{_t(o['evidence_grade'])} · {_t(o['source_url'])} · at `{_t(o['parent_path'])}`")
    for w in f["ways_in"]:
        typ = _t(w["interface_type"]) if w["interface_type"] is not None else "(no interface type)"
        op = f"`{_t(w['operation'])}`" if w["operation"] is not None else "(no operation named)"
        params = "; parameters: " + ", ".join(f"`{_t(p['parameter'])}` ({_ids(p['ids'])})" for p in w["parameters"]) \
            if w["parameters"] else ""
        a(f"{pad}  - way in: {typ} · {op} — rows {_ids(w['ids'])}{params}")


def _module_md(n: Dict[str, object], depth: int, a) -> None:
    pad = "  " * depth
    line = f"{pad}- **{_t(n['module'])}** — {_counts(n['counts'])}"
    if n["modules"]:
        line += f"; with sub-modules: {_counts(n['with_sub_modules'])}"
    a(line)
    for f in n["features"]:
        _feature_md(f, pad + "  ", a)
    for child in n["modules"]:
        _module_md(child, depth + 1, a)


def markdown(out: Dict[str, object]) -> str:
    lines: List[str] = []
    a = lines.append
    t = out["totals"]
    a(f"# Product map — {Path(str(out['subject'])).name}")
    a("")
    a(f"kbqa {out['kbqa']} · read-only: computed from {out['read_from']}, nothing written · "
      "modules are the vendor's breadcrumbs, as printed")
    a("")
    if not out["complete"]:
        a("**Incomplete:** some rows or files cannot be read (listed at the end); the counts are of the rows "
          "that could be read.")
        a("")
    if out["merged_only"] and not out["tree"]:
        a("The subject has no feature-tree.md: nothing is merged.")
        a("")
    a(f"Totals: {_n(t['rows'], 'row', 'rows')} · {_n(t['modules'], 'module', 'modules')} · {_counts(t)} "
      f"({_n(t['interface_rows'], 'interface row', 'interface rows')}) · "
      f"{t['position_unknown']} at an unknown position · {t['links_to_no_anchor']} linking to no anchor")
    a("")
    a("## Modules")
    a("")
    if not out["modules"]:
        a("No module.")
    for n in out["modules"]:
        _module_md(n, 0, a)
    a("")
    pu = out["position_unknown"]
    a(f"## Position unknown — {_counts(pu['counts'])}")
    a("")
    if not pu["features"] and not pu["other_sources_listed_under_their_feature"]:
        a("No row at an unknown position.")
    for f in pu["features"]:
        _feature_md(f, "", a)
    for o in pu["other_sources_listed_under_their_feature"]:
        a(f"- other source `{o['id']}`, listed under the feature `{o['listed_under']}`")
    a("")
    if out["depth_unknown"]:
        a(f"Depth unknown beside a breadcrumb: {_ids(out['depth_unknown'])}")
        a("")
    a(f"## Links to no anchor — {len(out['links_to_no_anchor'])}")
    a("")
    if not out["links_to_no_anchor"]:
        a("Every other source names an anchor of the subject.")
    for b in out["links_to_no_anchor"]:
        a(f"- `{b['id']}` names `{_t(b['same_feature_as'])}`: {b['why']} ({b['file']})")
    a("")
    if not out["complete"]:
        a("## Not read")
        a("")
        lines.extend(f"- {u['file']}: {u['why']}" for u in out["unreadable_files"])
        lines.extend(f"- {u['file']} line {u['line']}: {_t(u['error'])}" for u in out["unreadable_rows"])
        lines.extend(f"- {u['file']} line {u['line']}: a row with no id" for u in out["rows_without_id"])
        lines.extend(f"- `{u['id']}` read again in {', '.join(u['not_mapped_from'])}: mapped from {u['mapped_from']} only"
                     for u in out["ids_read_again"])
        a("")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------

def run(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="kbqa map")
    ap.add_argument("subject", nargs="?", help="the subject folder")
    ap.add_argument("--merged-only", action="store_true", help="the feature tree alone, not the staging files")
    ap.add_argument("--json", action="store_true", help="the whole structure as JSON, not the markdown list")
    args = ap.parse_args(argv)
    try:
        if args.subject is None:
            raise Refused("give a subject folder")
        if not Path(args.subject).is_dir():
            raise Refused(f"no subject folder {args.subject}")
    except Refused as exc:
        print(json.dumps({"refused": str(exc), "next_step": "operator"}, ensure_ascii=False, indent=2))
        return 1
    out: Dict[str, object] = {"kbqa": __version__, "read_only": True}
    out.update(build(Path(args.subject), args.merged_only))
    print(json.dumps(out, ensure_ascii=False, indent=2) if args.json else markdown(out), end="" if not args.json else "\n")
    return 0


def main() -> None:  # pragma: no cover
    sys.exit(run())
