"""kbqa status — the subject ledger: what is left, and what is done.

    python3 -m kbqa status <subject dir> [--pattern "<name>"] [--json]
    python3 -m kbqa status [<subject dir>] --estate <root> [--pattern "<name>"] [--json]

One answer, computed by code from the subject's files, never claimed by an
agent. **It writes nothing**: every number is read from what is on disk, by the
same code that wrote or checks it.

**Per surface** (`product`, `docs`, `help`): its state as `kbqa surfaces` reads
it; the current denominator and its items; the items captured (a page of a
window's record or of a capture file); the items staged (a page of a batch
that has a staging file — the staging file's own `pages:`, else its receipt's);
the rows, as features (anchors: rows without `same_feature_as`) and other
sources; the items a stop line covers or a surface line closes; and the **open
items** — index items with neither a row nor a stop line — counted by `g4`'s own
code over the surface's batches, exactly as `/kbqa-check` runs it. Then its
windows: recorded, cut from the current denominator, `exhausted` or parked
(where the next window resumes), ended in error, `unstaged` (a capture and no
staging file, as `kbqa collect-surface` lists them); and the pages still to
retry and those given up on (`capture`'s own retry state).

**Per batch**: rows; the last check's status and round, from
`_qa/<batch>.report.json` when that report was made on the staging file's
current bytes — `not checked` without one, `stale` when it was made on other
bytes; the autofix records; each mapping pass present — its map file, whether
it was made from the current staging file (the sidecar's sha256; `unknown`
without a sidecar), its draft, rejects rounds and retired folders; merged or
not — read from the tree by id, as `g6` reads it (every row id in
`feature-tree.md`: merged; some: partly merged; none: not merged).

**Open questions**: every `needs-human` line of every map file, grouped by the
`[pattern]` its note opens with (`mapcheck`'s own `note_pattern`,
`group_by_pattern` and `questions`), names joined without case — one question
per pattern for the whole subject, each with its batches, row ids and passes.
With `--estate <root>`, the same across every subject folder under the
estate's `subjects_dir` (`kbqa-estate.json`).

**After a ruling**, `--pattern "<name>"` lists exactly the rows whose
`needs-human` note names that pattern — subject, batch, id, pass — the rows to
re-map, and per batch and pass the `mapstage --reopen "<pattern>"` command that
sends only those rows back to the mapper, then the re-map step — and, when
`--reopen` would refuse that pass (a map file with no sidecar), why.

What the files cannot tell — a subject left by kbqa 6.21: a staging file
written by an agent, no window records, no drafts, no sidecars — is `unknown`,
never 0.

Prints a short markdown summary, or with `--json` the whole structure. Exit 0;
1 only when it refuses: no subject folder, or an estate whose
`kbqa-estate.json` is missing, cannot be read or names no `subjects_dir`.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from . import __version__, capture, collect_surface, features, mapstage, roles, stage
from .gates import g4_completeness, mapcheck
from .gates import surfaces as surfaces_gate
from .parsing import parse_capture, parse_staging
from .profile import conventions

UNKNOWN = "unknown"
NOT_CHECKED = "not checked"
STALE = "stale"
NOT_STAGED = "not staged"
MERGED, PARTLY, NOT_MERGED = "merged", "partly merged", "not merged"
PASSES = mapstage.PASSES
NEEDS_HUMAN = mapstage.NEEDS_HUMAN
READ_ERRORS = (OSError, UnicodeDecodeError, ValueError)
MAP_RE = re.compile(r"^_map-(?P<batch>.+)-(?P<letter>[AB])\.jsonl$")
MAPDRAFT_RE = re.compile(r"^_mapdraft-(?P<batch>.+)-(?P<letter>[AB])(?:\.rejects-\d+)?\.jsonl$")
DRAFT_RE = re.compile(r"^_draft-(?P<batch>.+?)(?:\.rejects-\d+)?\.jsonl$")
CAPTURE_RE = re.compile(r"^_capture-(?P<batch>.+)\.raw\.txt$")
OPEN_LISTED = 10  # open items named per surface in the markdown; the JSON names them all


class Refused(Exception):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> Tuple[Optional[object], Optional[str]]:
    """(the file's JSON, None) or (None, why it cannot be read)."""
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except READ_ERRORS as exc:
        return None, f"{path.name} cannot be read: {exc}"


def _map_lines(path: Path) -> Tuple[List[dict], int]:
    """A map file's lines that are JSON objects, and how many are not —
    counted, never dropped unseen."""
    lines, unreadable = [], 0
    try:
        raw = path.read_text(encoding="utf-8").splitlines()
    except READ_ERRORS:
        return [], -1
    for ln in raw:
        if not ln.strip():
            continue
        try:
            obj = json.loads(ln)
        except ValueError:
            unreadable += 1
            continue
        if isinstance(obj, dict):
            lines.append(obj)
        else:
            unreadable += 1
    return lines, unreadable


def _staging_rows(path: Path) -> Tuple[Optional[List[dict]], int, Tuple[str, ...], Optional[str]]:
    """(rows, unreadable rows, the pages it declares, why it cannot be read)."""
    try:
        parsed = parse_staging(path)
    except READ_ERRORS as exc:
        return None, 0, (), f"{path.name} cannot be read: {exc}"
    rows = [r.obj for r in parsed.rows if r.obj is not None]
    return rows, sum(1 for r in parsed.rows if r.obj is None), parsed.declared_pages, None


def batches_of(subject: Path) -> List[str]:
    """Every batch the subject's files name: staging files, captures, drafts,
    map files and mappers' drafts."""
    conv = conventions()
    names: Set[str] = set()
    for p in subject.iterdir():
        if not p.is_file():
            continue
        n = p.name
        if n.startswith(conv.staging_prefix) and n.endswith(conv.staging_suffix):
            names.add(conv.batch_of(n))
            continue
        for rx in (CAPTURE_RE, DRAFT_RE, MAP_RE, MAPDRAFT_RE):
            m = rx.match(n)
            if m:
                names.add(m.group("batch"))
                break
    return sorted(names)


# --------------------------------------------------------------------------
# One batch
# --------------------------------------------------------------------------

def check_of(qa: Path, batch: str, sha: Optional[str]) -> Dict[str, object]:
    """The last check of the batch: the report's status and round, only when
    it was made on the staging file's current bytes."""
    p = qa / f"{batch}.report.json"
    if not p.is_file():
        return {"status": NOT_CHECKED, "round": None, "report": None}
    rep, err = _json(p)
    if err or not isinstance(rep, dict):
        return {"status": UNKNOWN, "round": UNKNOWN, "report": f"_qa/{p.name}", "why": err or "not a report"}
    if sha is None or rep.get("staging_sha256") != sha:
        return {"status": STALE, "round": None, "report": f"_qa/{p.name}",
                "report_status": rep.get("status"), "report_round": rep.get("round"),
                "why": "the report was made on other staging bytes: the batch is not checked as it is now"}
    rnd = rep.get("round")
    return {"status": rep.get("status") or UNKNOWN, "round": rnd if isinstance(rnd, int) else UNKNOWN,
            "report": f"_qa/{p.name}", "generated": rep.get("generated")}


def autofix_records(qa: Path, batch: str, sha: Optional[str]) -> List[Dict[str, object]]:
    pat = re.compile(re.escape(batch) + r"\.autofix-(\d+)\.json")
    found = sorted((int(m.group(1)), p) for p in (qa.iterdir() if qa.is_dir() else [])
                   for m in [pat.fullmatch(p.name)] if m)
    out = []
    for n, p in found:
        rec, err = _json(p)
        entry: Dict[str, object] = {"record": f"_qa/{p.name}", "run": n}
        if err or not isinstance(rec, dict):
            entry["why"] = err or "not an autofix record"
            entry["changes"] = entry["left_findings"] = entry["on_current_staging"] = UNKNOWN
        else:
            entry["changes"] = len(rec.get("changes") or [])
            entry["left_findings"] = len(rec.get("left_findings") or [])
            entry["on_current_staging"] = rec.get("staging_sha256_after") == sha if sha else UNKNOWN
        out.append(entry)
    return out


def _retired(qa: Path, batch: str, letter: str) -> int:
    pat = mapstage.retired_dir_re(batch, letter)
    return sum(1 for p in (qa.iterdir() if qa.is_dir() else []) if p.is_dir() and pat.fullmatch(p.name))


def map_pass(subject: Path, batch: str, letter: str, sha: Optional[str]) -> Dict[str, object]:
    """One mapping pass of the batch: its files, and whether its map file was
    made from the staging file as it is now (the sidecar's record)."""
    mp, meta = subject / mapstage.map_name(batch, letter), subject / mapstage.meta_name(batch, letter)
    out: Dict[str, object] = {"map": mp.is_file(), "draft": (subject / mapstage.draft_name(batch, letter)).is_file(),
                              "rejects_rounds": len(mapstage._rounds(subject, batch, letter)),
                              "retired": _retired(subject / "_qa", batch, letter)}
    if not mp.is_file():
        out["from_current_staging"] = None
        return out
    if not meta.is_file():
        out["from_current_staging"] = UNKNOWN
        out["why"] = f"no {meta.name}: a map file written before sidecars existed (kbqa 6.22.0)"
    else:
        rec, err = _json(meta)
        recorded = rec.get("staging_sha256") if isinstance(rec, dict) else None
        if not recorded or sha is None:
            out["from_current_staging"] = UNKNOWN
            out["why"] = err or ("no staging file" if sha is None else f"{meta.name} records no staging_sha256")
        else:
            out["from_current_staging"] = recorded == sha
    lines, unreadable = _map_lines(mp)
    out["lines"] = len(lines) if unreadable >= 0 else UNKNOWN
    out["unreadable_lines"] = unreadable if unreadable >= 0 else UNKNOWN
    out["needs_human"] = sum(1 for o in lines if o.get("status") == NEEDS_HUMAN)
    return out


def merged_state(ids: List[str], tree_ids: Optional[Set[str]]) -> Dict[str, object]:
    """Merged is read from the tree itself, by id, as `g6` reads it."""
    if not ids:
        return {"state": UNKNOWN, "why": "no row id of the staging file could be read"}
    if tree_ids is None:
        return {"state": NOT_MERGED, "ids": len(ids), "ids_in_tree": 0, "why": "the subject has no feature-tree.md"}
    present = sum(1 for i in ids if i in tree_ids)
    state = MERGED if present == len(ids) else NOT_MERGED if present == 0 else PARTLY
    return {"state": state, "ids": len(ids), "ids_in_tree": present}


def batch_ledger(subject: Path, batch: str, tree_ids: Optional[Set[str]]) -> Dict[str, object]:
    conv = conventions()
    staging = subject / conv.staging_for(batch)
    qa = subject / "_qa"
    out: Dict[str, object] = {
        "batch": batch, "surface": conv.surface_of(batch),
        "capture": (subject / conv.capture_for(batch)).is_file(),
        "drafts": (subject / stage.draft_name(batch)).is_file(),
        "draft_rejects_rounds": len(stage._rounds(subject, batch)),
        "staged": staging.is_file(),
    }
    sha = _sha(staging) if staging.is_file() else None
    out["staging_sha256"] = sha
    if sha is None:
        out.update(rows=None, features=None, other_sources=None, unreadable_rows=None,
                   check={"status": NOT_STAGED, "round": None, "report": None},
                   merged={"state": NOT_STAGED})
    else:
        rows, unreadable, _, why = _staging_rows(staging)
        if rows is None:
            out.update(rows=UNKNOWN, features=UNKNOWN, other_sources=UNKNOWN, unreadable_rows=UNKNOWN,
                       staging_unreadable=why)
            ids: List[str] = []
        else:
            others = [r for r in rows if r.get("same_feature_as")]
            out.update(rows=len(rows), features=len(rows) - len(others), other_sources=len(others),
                       unreadable_rows=unreadable)
            ids = [str(r["id"]) for r in rows if r.get("id")]
        out["check"] = check_of(qa, batch, sha)
        out["merged"] = merged_state(ids, tree_ids)
    out["autofix"] = autofix_records(qa, batch, sha)
    out["maps"] = {letter: map_pass(subject, batch, letter, sha) for letter in PASSES}
    return out


# --------------------------------------------------------------------------
# One surface
# --------------------------------------------------------------------------

def _receipt_pages(subject: Path, batch: str) -> Optional[List[dict]]:
    rec, err = _json(subject / "_raw" / batch / capture.RECEIPT)
    if err or not isinstance(rec, dict) or not isinstance(rec.get("pages"), list):
        return None
    return [p for p in rec["pages"] if isinstance(p, dict) and p.get("url")]


def surface_ledger(subject: Path, surface: str, batches: List[Dict[str, object]],
                   states: Dict[str, dict]) -> Dict[str, object]:
    conv = conventions()
    st = states.get(surface) or {}
    out: Dict[str, object] = {"surface": surface, "state": st.get("state", UNKNOWN),
                              "surface_stop_lines": len(st.get("stop_lines") or [])}
    den = capture.current_denominator(subject, surface)
    out["denominator"] = den.name if den else None
    mine = [b for b in batches if b["surface"] == surface]
    staged = [b for b in mine if b["staged"]]
    out["batches"] = len(mine)
    out["batches_staged"] = len(staged)

    def total(key: str) -> object:
        vals = [b[key] for b in staged]
        return UNKNOWN if any(not isinstance(v, int) for v in vals) else sum(vals)
    for key in ("rows", "features", "other_sources", "unreadable_rows"):
        out[key] = total(key)

    # The windows, as capture records them; a subject from before window
    # records has none, and then what they would say is unknown, never none.
    try:
        windows: Optional[List[Dict]] = capture._windows(subject, surface)
        windows_why = None
    except READ_ERRORS as exc:
        windows, windows_why = None, f"a window record cannot be read: {exc}"
    captures = sorted(p for p in subject.glob(f"_capture-{surface}-*.raw.txt") if p.is_file())
    legacy_only = not windows and bool(captures or mine)

    # Items: the current denominator's, read by g4's own parser.
    item_urls: Optional[Set[str]] = None
    if den is not None:
        try:
            item_urls = {u for _, u in g4_completeness.disambiguate(g4_completeness.parse_denominator(den)).values()}
        except READ_ERRORS:
            item_urls = None
    out["items"] = len(item_urls) if item_urls is not None else (None if den is None else UNKNOWN)

    captured: Optional[Set[str]] = set()
    for w in windows or []:
        captured |= {str(u) for u in w.get("pages") or []}
    for cap in captures:
        try:
            captured |= set(parse_capture(cap).blocks)
        except READ_ERRORS:
            captured = None
            break
    staged_urls: Optional[Set[str]] = set()
    staged_unknown: List[str] = []
    for b in staged:
        _, _, pages, _ = _staging_rows(subject / conv.staging_for(str(b["batch"])))
        rpages = _receipt_pages(subject, str(b["batch"]))
        listed = set(pages) or ({p["url"] for p in rpages} if rpages else set())
        if not listed:
            staged_unknown.append(str(b["batch"]))
            continue
        staged_urls |= listed
        # a page captured under the URL it was redirected to was asked for by the item's URL
        staged_urls |= {str(p.get("requested")) for p in rpages or [] if p.get("url") in listed and p.get("requested")}

    def of_items(urls: Optional[Set[str]]) -> object:
        if item_urls is None:
            return None if den is None else UNKNOWN
        return UNKNOWN if urls is None else len(item_urls & urls)
    out["items_captured"] = of_items(captured)
    out["items_staged"] = of_items(None if staged_unknown else staged_urls)
    if staged_unknown:
        out["staged_pages_unknown_in"] = staged_unknown

    # Open items: g4's own count, over the batches /kbqa-check gives it.
    stops = subject / conv.stops_name
    if den is None:
        out["open_items"] = None if out["state"] == "stop-condition" else UNKNOWN
        out["open_item_urls"] = []
        out["stop_lines"] = None
        out["open_items_why"] = ("the surface is closed by a stop line: it has no items" if out["state"] == "stop-condition"
                                 else "no denominator: the surface's items are not known")
    else:
        rows_files = [str(subject / conv.staging_for(str(b["batch"]))) for b in staged]
        verdict, _ = g4_completeness.coverage(den, rows_files, stops if stops.is_file() else None)
        c = verdict.counts
        out["open_items"] = c.get("without_row", UNKNOWN)
        out["open_item_urls"] = [f.where for f in verdict.findings if f.code == "index_item_without_row"]
        out["stop_lines"] = {"items_stopped": c.get("existence_stopped"),
                             "items_closed_by_surface_line": c.get("existence_closed_by_surface_line"),
                             "closing_lines": c.get("closing_lines", {})}
        out["covered"] = {"by_url": c.get("evidence_covered_by_url"), "by_name": c.get("evidence_covered_by_name")}
        other = sorted({f.code for f in verdict.findings if f.code != "index_item_without_row"})
        if other:
            out["coverage_findings"] = other

    # Windows: exhausted, or parked with where it resumes.
    w_out: Dict[str, object] = {}
    if windows is None:
        w_out = {"recorded": UNKNOWN, "exhausted": UNKNOWN, "parked": UNKNOWN, "why": windows_why}
    else:
        chain = capture._chain(windows, den.name if den else None)
        w_out["recorded"] = len(windows)
        w_out["from_current_denominator"] = len(chain)
        if chain:
            last = chain[-1]
            w_out["exhausted"] = last.get("window_end") == "exhausted"
            w_out["parked"] = None if w_out["exhausted"] else {
                "resume_from": last.get("next_offset"), "remaining": last.get("remaining"),
                "last_window": last.get("batch"), "last_window_end": last.get("window_end")}
            w_out["ended_in_error"] = [w.get("batch") for w in chain if w.get("window_end") == "error"]
        elif legacy_only:
            w_out.update(exhausted=UNKNOWN, parked=UNKNOWN,
                         why="batches or captures with no window record (written before window records): "
                             "whether the selection was exhausted cannot be told")
        else:
            w_out.update(exhausted=False, parked=None,
                         why="no window cut from the current denominator" if windows else "nothing captured yet")
        no_capture = [w.get("batch") for w in windows
                      if not (subject / conv.capture_for(str(w.get("batch")))).is_file()]
        if no_capture:
            w_out["without_capture"] = no_capture
    try:
        w_out["unstaged"] = [{"batch": u["batch"], "state": u["state"]} for u in collect_surface.unstaged(subject, surface)]
    except READ_ERRORS:
        w_out["unstaged"] = UNKNOWN
    out["windows"] = w_out

    if windows is None or legacy_only:
        out["retryable_pages"] = out["given_up_pages"] = UNKNOWN
    else:
        retryable, given_up = capture._retry_state(subject, windows)
        out["retryable_pages"], out["given_up_pages"] = retryable, given_up
    return out


# --------------------------------------------------------------------------
# Open questions
# --------------------------------------------------------------------------

def _map_batches(subject: Path) -> List[str]:
    return sorted({m.group("batch") for p in subject.iterdir() if p.is_file()
                   for m in [MAP_RE.match(p.name)] if m})


def batch_questions(subject: Path, batch: str) -> List[dict]:
    """The batch's questions, one per pattern, across its passes — as mapcheck
    groups them."""
    by_pass: Dict[str, Dict[str, List[str]]] = {}
    for letter in PASSES:
        mp = subject / mapstage.map_name(batch, letter)
        if mp.is_file():
            by_pass[letter] = mapcheck.group_by_pattern(_map_lines(mp)[0])
    return mapcheck.questions(by_pass)


def open_questions(subjects: List[Tuple[Optional[str], Path]]) -> List[Dict[str, object]]:
    """Every needs-human line of every batch, one question per `[pattern]`,
    names joined without case; the subject named when there are several."""
    joined: Dict[str, Dict[str, object]] = {}
    for name, subject in subjects:
        for batch in _map_batches(subject):
            for q in batch_questions(subject, batch):
                key = str(q["pattern"]).casefold()
                entry = joined.setdefault(key, {"pattern": q["pattern"], "rows": 0, "batches": []})
                b: Dict[str, object] = {"batch": batch, "rows": q["rows"], "per_pass": q["per_pass"]}
                if name is not None:
                    b = {"subject": name, **b}
                entry["batches"].append(b)
                entry["rows"] = int(entry["rows"]) + len(q["rows"])
    out = sorted(joined.values(), key=lambda e: (-int(e["rows"]), str(e["pattern"]).casefold()))
    for e in out:
        if any("subject" in b for b in e["batches"]):
            e["subjects"] = len({b["subject"] for b in e["batches"]})
    return out


def _named(name: str) -> str:
    """The pattern as given, spaces collapsed, without the brackets a note writes it in."""
    n = " ".join(name.split())
    if n.startswith("[") and n.endswith("]"):
        n = " ".join(n[1:-1].split())
    return n


def _wanted(name: str) -> str:
    return mapcheck.pattern_key(name)


def reopen_now(subject: Path, batch: str, letter: str, name: str) -> Optional[str]:
    """None when `mapstage --reopen` would run on this pass now, else why it
    would refuse — by mapstage's own plan; nothing is moved."""
    try:
        mapstage.reopen_plan(subject, batch, letter, name)
    except mapstage.Refused as exc:
        return str(exc)
    return None


def _elements(subject: Path) -> str:
    cfg = roles.estate_config(subject)
    data = _json(cfg)[0] if cfg is not None else None
    value = data.get("apqc_elements") if isinstance(data, dict) else None
    return str(cfg.parent / value) if cfg is not None and isinstance(value, str) and value else "<the element list>"


def pattern_rows(subjects: List[Tuple[Optional[str], Path]], name: str) -> Dict[str, object]:
    """Exactly the rows whose needs-human note names the pattern, and per
    batch and pass the commands that retire and re-map it."""
    want = _wanted(name)
    rows: List[Dict[str, object]] = []
    passes: List[Dict[str, object]] = []
    for sname, subject in subjects:
        for batch in _map_batches(subject):
            for letter in PASSES:
                mp = subject / mapstage.map_name(batch, letter)
                if not mp.is_file():
                    continue
                ids = [str(o.get("id")) for o in _map_lines(mp)[0] if mapcheck.names_pattern(o, want)]
                if not ids:
                    continue
                where = {"subject": sname} if sname is not None else {}
                rows += [{**where, "batch": batch, "id": i, "pass": letter} for i in ids]
                cmd = f'python3 -m kbqa mapstage --subject "{subject}" --batch {batch} --pass {letter}'
                entry = {**where, "batch": batch, "pass": letter, "ids": ids,
                         "reopen": f'{cmd} --reopen "{_named(name)}"',
                         "then": f"the mapper rewrites only the placeholder lines of "
                                 f"{mapstage.draft_name(batch, letter)}, applying the ruling, then "
                                 f'{cmd} --elements "{_elements(subject)}"'}
                why = reopen_now(subject, batch, letter, name)
                if why is not None:
                    entry["reopen_refused"] = why
                passes.append(entry)
    return {"pattern": _named(name), "rows": rows, "passes": passes}


# --------------------------------------------------------------------------
# The subject, the estate
# --------------------------------------------------------------------------

def tree_ids(subject: Path) -> Optional[Set[str]]:
    """Every row id in the subject's `feature-tree.md`; None without one."""
    tree = subject / features.TREE
    if not tree.is_file():
        return None
    rows, _, _, _ = _staging_rows(tree)
    return {str(r["id"]) for r in rows or [] if r.get("id")}


def subject_ledger(subject: Path) -> Dict[str, object]:
    conv = conventions()
    ids = tree_ids(subject)
    batches = [batch_ledger(subject, b, ids) for b in batches_of(subject)]
    verdict, _ = surfaces_gate.run(["--subject", str(subject)])
    states = verdict.counts.get("surfaces") or {}
    return {"subject": str(subject),
            "surfaces": [surface_ledger(subject, s, batches, states) for s in conv.surfaces],
            "batches": batches,
            "legacy_batches": [b["batch"] for b in batches if b["surface"] is None],
            "open_questions": open_questions([(None, subject)])}


def estate_subjects(root: Path) -> Tuple[Path, List[Path]]:
    """The estate's subjects folder and every subject folder in it."""
    cfg = root / roles.CONFIG
    if not cfg.is_file():
        raise Refused(f"no {roles.CONFIG} in {root}: the estate names its subjects folder there (`subjects_dir`)")
    data, err = _json(cfg)
    if err:
        raise Refused(err)
    sd = data.get("subjects_dir") if isinstance(data, dict) else None
    if not isinstance(sd, str) or not sd.strip():
        raise Refused(f"{cfg} names no `subjects_dir`")
    folder = root / sd
    if not folder.is_dir():
        raise Refused(f"the estate's subjects_dir {folder} is not a folder")
    return folder, sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith("."))


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------

def _v(x: object) -> str:
    if x is None:
        return "–"
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, list):
        return str(len(x))
    return str(x)


def _questions_md(qs: List[Dict[str, object]], a) -> None:
    rows = sum(int(q["rows"]) for q in qs)
    a(f"## Open questions — {len(qs)} pattern(s), {rows} row(s)")
    a("")
    if not qs:
        a("No needs-human line in any map file.")
    for q in qs:
        where = "; ".join(
            (f"{b['subject']} / " if "subject" in b else "") + f"{b['batch']} ("
            + ", ".join(f"{p}: {' '.join(ids)}" for p, ids in sorted(b["per_pass"].items())) + ")"
            for b in q["batches"])
        a(f"- `[{q['pattern']}]` — {q['rows']} row(s) in {len(q['batches'])} batch(es): {where}")
    a("")


def markdown(out: Dict[str, object]) -> str:
    lines: List[str] = []
    a = lines.append
    if "pattern" in out:
        a(f"# Rows to re-map — `[{out['pattern']}]`")
        a("")
        a(f"kbqa {out['kbqa']} · read-only: computed from the files, nothing written")
        a("")
        if not out["rows"]:
            a("No needs-human line names this pattern.")
        else:
            a("| subject | batch | pass | id |")
            a("|---|---|---|---|")
            for r in out["rows"]:
                a(f"| {r.get('subject', '–')} | {r['batch']} | {r['pass']} | `{r['id']}` |")
            a("")
            for p in out["passes"]:
                a(f"**{p.get('subject', '') + ' / ' if 'subject' in p else ''}{p['batch']} pass {p['pass']}** "
                  f"({len(p['ids'])} row(s))")
                a(f"- reopen: `{p['reopen']}`" + (f" — refused now: {p['reopen_refused']}"
                                                   if "reopen_refused" in p else ""))
                a(f"- then: {p['then']}")
        a("")
        return "\n".join(lines) + "\n"
    if "surfaces" in out:
        a(f"# Ledger — {Path(str(out['subject'])).name}")
        a("")
        a(f"kbqa {out['kbqa']} · read-only: computed from the files, nothing written · "
          "`unknown` = the files cannot tell")
        a("")
        a("## Surfaces")
        a("")
        a("| surface | state | denominator | items | captured | staged | rows (features / other sources) "
          "| stopped | open items | windows | retryable | given up |")
        a("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for s in out["surfaces"]:
            w = s["windows"]
            win = "none" if w.get("recorded") == 0 and w.get("exhausted") is False else \
                (f"{_v(w.get('recorded'))}, " + ("exhausted" if w.get("exhausted") is True else
                                                   "exhausted: unknown" if w.get("exhausted") == UNKNOWN else
                                                   f"parked at {w['parked'].get('resume_from')}"
                                                   if isinstance(w.get("parked"), dict) else "not exhausted"))
            if isinstance(w.get("unstaged"), list) and w["unstaged"]:
                win += f", {len(w['unstaged'])} unstaged"
            stopped = s.get("stop_lines")
            st = "–" if not isinstance(stopped, dict) else \
                f"{_v(stopped.get('items_stopped'))} + {_v(stopped.get('items_closed_by_surface_line'))} closed"
            a(f"| {s['surface']} | {s['state']} | {s['denominator'] or '–'} | {_v(s['items'])} | "
              f"{_v(s['items_captured'])} | {_v(s['items_staged'])} | {_v(s['rows'])} ({_v(s['features'])} / "
              f"{_v(s['other_sources'])}) | {st} | {_v(s['open_items'])} | {win} | "
              f"{_v(s['retryable_pages'])} | {_v(s['given_up_pages'])} |")
        a("")
        notes = []
        for s in out["surfaces"]:
            urls = s.get("open_item_urls") or []
            if urls:
                more = f" … and {len(urls) - OPEN_LISTED} more (--json)" if len(urls) > OPEN_LISTED else ""
                notes.append(f"- {s['surface']} open items: " + ", ".join(urls[:OPEN_LISTED]) + more)
            uns = s["windows"].get("unstaged")
            if isinstance(uns, list):
                notes += [f"- {s['surface']} unstaged: {u['batch']} — {u['state']}" for u in uns]
        if notes:
            lines.extend(notes + [""])
        a("## Batches")
        a("")
        if not out["batches"]:
            a("No batch.")
        else:
            a("| batch | rows (features / other sources) | check | round | autofix | map A | map B | merged |")
            a("|---|---|---|---|---|---|---|---|")
            for b in out["batches"]:
                maps = []
                for letter in PASSES:
                    m = b["maps"][letter]
                    maps.append("–" if not m["map"] else
                                "current" if m["from_current_staging"] is True else
                                "other bytes" if m["from_current_staging"] is False else "unknown")
                rows = f"{_v(b['rows'])} ({_v(b['features'])} / {_v(b['other_sources'])})" if b["staged"] \
                    else NOT_STAGED
                a(f"| {b['batch']} | {rows} | {b['check']['status']} | {_v(b['check'].get('round'))} | "
                  f"{len(b['autofix'])} | {maps[0]} | {maps[1]} | {b['merged']['state']} |")
        a("")
        _questions_md(out["open_questions"], a)
    if "estate" in out:
        e = out["estate"]
        a(f"# Estate — {e['subjects_dir']} ({len(e['subjects'])} subject(s))")
        a("")
        _questions_md(e["open_questions"], a)
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------

def run(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="kbqa status")
    ap.add_argument("subject", nargs="?", help="the subject folder")
    ap.add_argument("--estate", help="the estate root (its kbqa-estate.json): open questions across every subject")
    ap.add_argument("--pattern", help="the rows whose needs-human note names this pattern: the rows to re-map")
    ap.add_argument("--json", action="store_true", help="the whole structure as JSON, not the markdown summary")
    args = ap.parse_args(argv)
    try:
        if args.subject is None and args.estate is None:
            raise Refused("give a subject folder, or --estate <root>")
        if args.subject is not None and not Path(args.subject).is_dir():
            raise Refused(f"no subject folder {args.subject}")
        if args.pattern is not None and not _wanted(args.pattern):
            raise Refused("--pattern needs a name")
        estate = estate_subjects(Path(args.estate)) if args.estate else None
    except Refused as exc:
        print(json.dumps({"refused": str(exc), "next_step": "operator"}, ensure_ascii=False, indent=2))
        return 1
    out: Dict[str, object] = {"kbqa": __version__, "read_only": True}
    scope: List[Tuple[Optional[str], Path]] = (
        [(p.name, p) for p in estate[1]] if estate is not None else [(None, Path(args.subject))])
    if args.pattern is not None:
        out.update(pattern_rows(scope, args.pattern))
        out["scope"] = "estate" if estate is not None else "subject"
    else:
        if args.subject is not None:
            out.update(subject_ledger(Path(args.subject)))
        if estate is not None:
            out["estate"] = {"root": str(args.estate), "subjects_dir": str(estate[0]),
                             "subjects": [p.name for p in estate[1]], "open_questions": open_questions(scope)}
    print(json.dumps(out, ensure_ascii=False, indent=2) if args.json else markdown(out), end="" if not args.json else "\n")
    return 0


def main() -> None:  # pragma: no cover
    sys.exit(run())
