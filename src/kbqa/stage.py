"""kbqa stage — the staging file written by code, from the row-writer's drafts.

    python3 -m kbqa stage --subject <d> --batch <b> --lists
    python3 -m kbqa stage --subject <d> --batch <b> [--leave-out-rejects]

**The row-writer judges; code copies.** The row-writer reads one part of a page
at a time and writes a draft per row in `_draft-<batch>.jsonl`, one JSON object
per line: the page (its URL as in the receipt), the part (its index in that
page's `parts`, from 0), the quote (the words it chose) and its judgement —
`vendor_term`, `what_it_does`, `evidence_grade`, `confidence`, `mechanism`,
`outcome`, and when they apply `same_feature_as`, `interface_type`,
`operation`, `parameter`, `source_typo`, `mechanism_raw`, `outcome_raw`,
`mechanism_via`. A page it read and found no row on is one line
`{"page": <url>, "no_row": "<what the page is>"}`. A page the receipt marks
`unchanged_since` an earlier capture (collected again, the same text hash) is
not drafted again: one line `{"page": <url>, "unchanged": "<that batch>"}` says
the rows already recorded stand.

`kbqa stage` writes `_collect-<batch>-staging.md` from those drafts and the
batch's receipt, so nothing a code can copy is typed by an agent:

- the frontmatter is the receipt's: batch, capture name and sha256, every page,
  `fetched_by_this_agent: false`, the window fields, the access date;
- each draft's quote is found in its part's **own lines** — whitespace, quotes
  and dashes folded as `parsing.normalise_for_match`, nothing else — and the
  capture's exact text of that span becomes `source_quote`. A quote not found
  there, or found more than once, is rejected and listed with the reason;
  never guessed at;
- `source_url`, `access_date`, `parent_path` (the part's breadcrumb, else
  `unknown`), `depth_level` (the breadcrumb's levels counted, else `unknown`)
  and `canonical: NOVEL` are filled in; the `id` is
  `<subject>.<surface>.<breadcrumb's last item>.<vendor_term>`, each a slug,
  made unique with `-2`, `-3`… against every id the subject already has (the
  feature tree and every staging file) — the same drafts give the same ids;
- a page drafted `no_row` becomes a suggested `no feature: …` stop line; when
  every page is drafted `no_row` (or `unchanged`) there are no rows, no staging
  file, and the next step is `no rows — skip mapping for this batch`;
- a page drafted `unchanged` adds nothing to the staging file: it is listed
  under `unchanged_pages` — the earlier batch, and the batch and row ids where
  its rows are recorded (back along the pages' `unchanged_since` marks), or the
  stop line that names it — and becomes a suggested `no feature: unchanged
  since <batch>` stop line, so the page is accounted for in this window. The
  line is **rejected** unless the page is unchanged by text hash: its
  `text_sha256` equals the one the named batch's receipt records for the URL,
  that batch is the page's latest earlier capture (the receipt's
  `unchanged_since`), and a row or a stop line is recorded there to stand.
  Nothing earlier is edited;
- after the staging file is written, `_raw/<batch>/ROLE-ROWS.md` is written
  again, so the mappers see the batch's own rows (`role_rows_refreshed`).

**It checks what it can before the check.** Rejected in the draft round, as a
quote not found is: a page of the receipt that no draft line names — no row
and no `no_row` line (no row and no reason, listed by its page); a
`same_feature_as` id that is not an anchor of the subject (no row of the
feature tree or of any staging file, or a row that is itself another source);
an enumerated field (`evidence_grade`, `confidence`, `mechanism`, `outcome`,
`interface_type`) whose value is not one of the profile's (`Profile.enumerated`).
A grade written another known way — the respelling `kbqa autofix` would fix —
is not rejected: it is written in the schema's spelling and listed under
`respelt_by_code` (line, field, before, after).

`same_feature_as` names an anchor's id, or another draft of this batch as
`draft:<line>` (1-based line of the draft file), which code resolves to the id
it gives that draft — an anchor, never another source, never rejected.

**Exact repeats are linked by code.** A draft whose `parameter` (when it has
one, else its `vendor_term`) and whose quote — the capture's exact text, folded
by `normalise_for_match` — are identical, on the same host, to those of an
anchor already in the subject, or of an earlier anchor draft of this batch, gets
`same_feature_as` set to that anchor (`draft:<line>` for a draft, resolved as
above). Each is listed under `linked_by_code` with what matched. A draft that
already names that anchor is left as it is; one that names another anchor is
changed in nothing and listed under `link_conflicts`, as is a repeat of several
anchors at once, or of a draft that other drafts name as their anchor (linking
it would leave them pointing at a row that is not an anchor). Code never links
to a row that itself carries `same_feature_as`.

**A rejected draft blocks the staging file.** Each run that rejects a draft
writes only `_draft-<batch>.rejects-<n>.jsonl` (each reject with its draft
line, reason and suggested next step; never overwritten) and exits 1. The
row-writer has one correction round — it rewrites only the rejected lines —
and stage runs again. Drafts still rejected after it are not dropped unseen:
`--leave-out-rejects` writes the staging file without them and prints each
under `needs_operator`; a third run without it is refused. The result says
which round it is. The staging file is never overwritten.

`--lists` writes, before the row-writer runs, the lists it and the mapper read:
`_raw/<batch>/FEATURES.md` (the subject's anchors, `kbqa.features`) and
`_raw/<batch>/ROLE-ROWS.md` (rows that may name a role, `kbqa.roles`, only when
the estate names patterns), and `_raw/<batch>/SAME-FEATURE.md`, the
same-feature shortlist per page of the window (`kbqa.shortlist`; not written,
with the reason under `same_feature_note`, when the window has no capture to
read). Built when they are needed, they hold every row staged so far — the
windows before this one included. When the receipt marks pages
`unchanged_since` an earlier capture, `_raw/<batch>/UNCHANGED.md` lists them for
the row-writer, each with the rows recorded for it (ids) or the stop line that
names it, or `nothing recorded` (then it is drafted like any page); the result
lists them under `unchanged_pages`. They are refused once the batch's staging
file exists: they are what the drafts were written from.

Both print one JSON result. Exit 0 when the files were written, 1 when refused.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from . import features, roles, shortlist, stops
from .parsing import _QUOTE_MAP, normalise_for_match, parse_capture, parse_staging
from .profile import active, conventions

BATCH_RE = re.compile(r"^(product|docs|help)-\d{4}-\d{2}-\d{2}-w\d{2}$")
RECEIPT = "RECEIPT.json"
FEATURES = "FEATURES.md"    # the subject's anchors, for the row-writer's same_feature_as
ROLE_ROWS = "ROLE-ROWS.md"  # rows that may name a role, for the mapper (estate patterns)

# The row-writer's judgement: every draft carries these …
JUDGEMENT = ("vendor_term", "what_it_does", "evidence_grade", "confidence", "mechanism", "outcome")
# … and these when they apply. Copied as written; the gates judge the values.
OPTIONAL = ("same_feature_as", "interface_type", "operation", "parameter", "source_typo",
            "mechanism_raw", "outcome_raw", "mechanism_via")
LOCATION = ("page", "part", "quote")
NO_ROW_KEYS = {"page", "no_row"}
UNCHANGED_KEYS = {"page", "unchanged"}  # a page unchanged since an earlier capture: its rows stand
UNCHANGED = "UNCHANGED.md"              # the window's unchanged pages, for the row-writer
UNCHANGED_REASON = "no feature: unchanged since "
WINDOW_FIELDS = ("window_offset", "window_requested", "window_returned", "window_end")
UNKNOWN = "unknown"
CRUMB_SEP = " > "  # how the capture writes a breadcrumb's items on one line
DRAFT_REF = "draft:"  # same_feature_as naming another draft of this batch by its line
CORRECTION_ROUNDS = 1  # the row-writer corrects rejected drafts once; there is no second round
LEAVE_OUT = "--leave-out-rejects"
OPERATOR_RULES = "the operator rules on the row: corrected in the fix round, or left out"
NO_ROWS_STEP = "no rows — skip mapping for this batch"


def draft_name(batch: str) -> str:
    return f"_draft-{batch}.jsonl"


def rejects_name(batch: str, round_no: int) -> str:
    return f"_draft-{batch}.rejects-{round_no}.jsonl"


def slug(text: object) -> str:
    """Lowercase ASCII letters and digits, other runs as one `-`."""
    s = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def fold(text: str) -> Tuple[str, List[int]]:
    """`normalise_for_match` one character at a time, keeping for every folded
    character the index of the character it came from — so a match in the
    folded text is a span of the original text."""
    out: List[str] = []
    at: List[int] = []
    for i, ch in enumerate(text):
        for c in unicodedata.normalize("NFKC", ch):
            for c2 in _QUOTE_MAP.get(c, c):
                if c2.isspace():
                    if out and out[-1] == " ":
                        continue
                    c2 = " "
                out.append(c2)
                at.append(i)
    return "".join(out), at


def find_quote(text: str, quote: str) -> List[str]:
    """Every span of `text` that folds to the folded `quote`, as the exact text
    of that span — overlapping matches included, so a quote that could be read
    in two places is never taken as one."""
    nq = normalise_for_match(quote)
    if not nq:
        return []
    folded, at = fold(text)
    spans: List[str] = []
    i = folded.find(nq)
    while i >= 0:
        spans.append(text[at[i]:at[i + len(nq) - 1] + 1])
        i = folded.find(nq, i + 1)
    return spans


def repeat_field(row: dict) -> str:
    """The name compared for exact repeats: `parameter` when the row has one,
    else `vendor_term`."""
    param = row.get("parameter")
    return "parameter" if isinstance(param, str) and param.strip() else "vendor_term"


def repeat_key(url: object, row: dict, quote: object) -> Optional[Tuple[str, str, str]]:
    """What makes two rows exact repeats: (host, the name as written, the quote
    folded by `normalise_for_match`). None when one of them is missing."""
    value = row.get(repeat_field(row))
    host = (urlparse(str(url or "")).hostname or "").lower()
    nq = normalise_for_match(quote) if isinstance(quote, str) else ""
    if not host or not nq or not isinstance(value, str) or not value.strip():
        return None
    return host, value, nq


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _write_new(path: Path, data: bytes) -> None:
    """Write a file that must not exist yet: never over one that does."""
    with open(path, "xb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())


def frontmatter(receipt: Dict) -> str:
    """The staging frontmatter, copied from the receipt — nothing typed."""
    b = receipt["batch"]
    out = ["---", f"batch: {b}", f"source_capture: {Path(receipt['capture']).name}",
           f"source_capture_sha256: {receipt['sha256']}", "pages:"]
    out += [f"  - {p['url']}" for p in receipt["pages"]]
    out.append("fetched_by_this_agent: false")
    out += [f"{k}: {receipt[k]}" for k in WINDOW_FIELDS if receipt.get(k) is not None]
    out += [f"access_date: {receipt['access_date']}", "---"]
    return "\n".join(out) + "\n"


def _crumb_levels(crumb: Optional[str]) -> List[str]:
    return [s.strip() for s in (crumb or "").split(CRUMB_SEP) if s.strip()]


def position(crumb: Optional[str]) -> Tuple[str, str]:
    """A row's `parent_path` and `depth_level` from its part's breadcrumb: the
    breadcrumb as the capture wrote it and its levels counted, else `unknown`
    for both. `kbqa autofix` re-derives them with this same function."""
    levels = _crumb_levels(crumb)
    return (str(crumb), str(len(levels))) if levels else (UNKNOWN, UNKNOWN)


class Refused(Exception):
    def __init__(self, message: str, next_step: str = "operator"):
        super().__init__(message)
        self.next_step = next_step


def _receipt(subject: Path, batch: str) -> Dict:
    if not subject.is_dir():
        raise Refused(f"no subject folder {subject}")
    if not BATCH_RE.match(batch):
        raise Refused(f"batch {batch!r} is not <surface>-<YYYY-MM-DD>-wNN")
    path = subject / "_raw" / batch / RECEIPT
    if not path.is_file():
        raise Refused(f"no receipt _raw/{batch}/{RECEIPT}: run kbqa capture first")
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Refused(f"_raw/{batch}/{RECEIPT} cannot be read: {exc}")
    if receipt.get("batch") != batch:
        raise Refused(f"_raw/{batch}/{RECEIPT} is the receipt of {receipt.get('batch')!r}, not {batch!r}")
    return receipt


def _capture_text(subject: Path, receipt: Dict) -> str:
    """The capture the receipt names, checked against the receipt: its sha256,
    and one block per receipt page, in order."""
    if not receipt.get("capture"):
        raise Refused("the receipt names no capture: this window captured no page, so there is nothing to stage")
    cap = subject / Path(receipt["capture"]).name
    if not cap.is_file():
        raise Refused(f"the capture {cap.name} the receipt names is not in the subject folder")
    data = cap.read_bytes()
    if hashlib.sha256(data).hexdigest() != receipt.get("sha256"):
        raise Refused(f"{cap.name} does not hash to the receipt's sha256: the capture changed after it was "
                      "written, so rows staged from it could not be checked")
    blocks = list(parse_capture(cap).blocks)
    pages = [p.get("url") for p in receipt.get("pages", [])]
    if blocks != pages:
        raise Refused(f"{cap.name} holds the pages {blocks}, the receipt lists {pages}")
    if any(not p.get("parts") for p in receipt["pages"]):
        raise Refused("a page of the receipt lists no parts (a capture from before kbqa 6.18.0): "
                      "it cannot be staged by code")
    return data.decode("utf-8")


def _stop_reasons(subject: Path) -> Dict[str, List[str]]:
    """{url: every reason a stop line gives it}, from the subject's stop-conditions."""
    f = subject / stops.STOPS_NAME
    out: Dict[str, List[str]] = {}
    if f.is_file():
        for ln in f.read_text(encoding="utf-8").splitlines():
            m = stops.LINE_RE.match(ln.strip())
            if m:
                out.setdefault(m.group("url"), []).append(m.group("reason"))
    return out


def receipt_page(subject: Path, batch: str, url: str) -> Optional[dict]:
    """The page `url` of another batch's receipt, or None (no receipt, not a page of it)."""
    try:
        rec = json.loads((subject / "_raw" / batch / RECEIPT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    pages = rec.get("pages") if isinstance(rec, dict) else None
    for p in pages if isinstance(pages, list) else []:
        if isinstance(p, dict) and p.get("url") == url:
            return p
    return None


def recorded(subject: Path, url: str, since: str) -> Dict[str, object]:
    """What is already recorded for a page unchanged since the batch `since`:
    from that batch back along the pages' own `unchanged_since` marks, the first
    batch whose staging file has rows citing the page — `rows_in`, the row `ids`
    and their `anchors` (the feature each row is of) — else, where the walk ends,
    the stop line that names the page (`stop_line`; never an `unchanged since`
    line, which would vouch for itself), else nothing: `why`."""
    conv = conventions()
    via: List[str] = []   # batches passed: the page unchanged there too
    seen: List[str] = []  # every batch looked at
    b: Optional[str] = since
    while b and b not in seen and BATCH_RE.match(b):
        seen.append(b)
        staging = subject / conv.staging_for(b)
        if staging.is_file():
            rows = [r.obj for r in parse_staging(staging).rows
                    if r.obj and r.obj.get("source_url") == url and r.obj.get("id")]
            if rows:
                return {"rows_in": b, "ids": [str(r["id"]) for r in rows],
                        "anchors": sorted({str(r.get("same_feature_as") or r["id"]) for r in rows}), "via": via}
        page = receipt_page(subject, b, url)
        nxt = page.get("unchanged_since") if page else None
        if not isinstance(nxt, str) or not nxt:
            break
        via.append(b)
        b = nxt
    reasons = [r for r in _stop_reasons(subject).get(url, []) if not r.startswith(UNCHANGED_REASON)]
    out: Dict[str, object] = {"rows_in": None, "ids": [], "anchors": [], "via": via}
    if reasons:
        out["stop_line"] = reasons[0]
    else:
        out["why"] = (f"nothing is recorded for the page since {since}: no staging file of "
                      f"{', '.join(seen) or since} has a row citing it, and no stop line names it")
    return out


def unchanged_refusal(subject: Path, batch: str, page: dict, since: str) -> Optional[str]:
    """Why an `unchanged` draft line cannot stand for this page, or None. By
    text hash only: the page's text sha256 must equal the one the batch named
    recorded for the same URL, that batch must be the page's latest earlier
    capture (the receipt's `unchanged_since`), and something must be recorded
    there to stand."""
    url = page["url"]
    if not BATCH_RE.match(since) or since == batch:
        return f"unchanged {since!r} names no earlier batch (<surface>-<YYYY-MM-DD>-wNN, not this one)"
    earlier = receipt_page(subject, since, url)
    if earlier is None:
        return f"{since} has no receipt listing {url}: the page is not unchanged since it"
    before, now = earlier.get("text_sha256"), page.get("text_sha256")
    if not before or not now or before != now:
        return (f"the page is not unchanged by text hash: {since} recorded "
                f"{str(before)[:12] if before else 'no text hash'}, this batch "
                f"{str(now)[:12] if now else 'no text hash'} — draft its rows, or its no_row line")
    marked = page.get("unchanged_since")
    if marked != since:
        return (f"the receipt marks the page unchanged since {marked}" if marked else
                "the receipt does not mark the page unchanged") + (
                f", not since {since}: its latest earlier capture is another — draft its rows, or its no_row line")
    rec = recorded(subject, url, since)
    if rec.get("why"):
        return f"{rec['why']} — draft its rows, or its no_row line"
    return None


def unchanged_list(subject: Path, batch: str, pages: List[dict]) -> Tuple[Optional[str], List[dict]]:
    """The receipt's pages marked unchanged, each with what is recorded for it:
    (the markdown list the row-writer reads, or None when there are none; the entries)."""
    entries: List[dict] = []
    for p in pages:
        since = p.get("unchanged_since")
        if not isinstance(since, str) or not since:
            continue
        rec = recorded(subject, p["url"], since)
        entries.append({"page": p["url"], "unchanged_since": since,
                        **{k: rec[k] for k in ("rows_in", "ids", "stop_line", "why") if k in rec}})
    if not entries:
        return None, entries
    out = [f"# Unchanged pages — {batch}", "",
           "Written by `kbqa stage --lists`. Each page below has the same text (its `text_sha256`) as its",
           "latest earlier capture, in the batch named: what is recorded for it there stands. Do not",
           "draft it again; write one line for it:",
           "",
           '`{"page": "<url>", "unchanged": "<the batch named>"}`',
           "",
           "A page marked **nothing recorded** is drafted like any other page.",
           ""]
    for e in entries:
        if e.get("ids"):
            what = f"rows recorded in {e['rows_in']}: {', '.join(e['ids'])}"
        elif e.get("stop_line"):
            what = f"no row; stop line: {e['stop_line']}"
        else:
            what = f"**nothing recorded** ({e['why']})"
        out.append(f"- {e['page']} | unchanged since {e['unchanged_since']} | {what}")
    return "\n".join(out) + "\n", entries


def lists(subject: Path, batch: str) -> Dict[str, object]:
    """Write the subject's features list, role-row list and same-feature
    shortlist beside the receipt."""
    receipt = _receipt(subject, batch)
    staged = subject / conventions().staging_for(batch)
    if staged.exists():
        # The lists are what the row-writer reads before it drafts: once the
        # batch is staged, rebuilding them would describe rows the drafts never saw.
        raise Refused(f"{staged.name} exists: the lists are built before the row-writer drafts this batch, "
                      "never after it is staged",
                      next_step="nothing to rebuild: kbqa stage refreshed ROLE-ROWS.md when it wrote the staging "
                                "file; the batch goes on to mapping")
    raw = subject / "_raw" / batch
    same: Optional[str] = None
    try:
        text = _capture_text(subject, receipt)
        same = shortlist.same_feature_list(batch, receipt["pages"], text.split("\n"),
                                           features.subject_rows(subject))
        same_why = ""
    except Refused as exc:
        same_why = str(exc)
    _write_atomic(raw / FEATURES, features.features_list(subject).encode("utf-8"))
    out: Dict[str, object] = {"batch": batch, "features": f"_raw/{batch}/{FEATURES}"}
    if same is not None:
        _write_atomic(raw / shortlist.NAME, same.encode("utf-8"))
        out["same_feature"] = f"_raw/{batch}/{shortlist.NAME}"
    else:
        out["same_feature"] = None
        out["same_feature_note"] = f"not written: {same_why}"
    listed, why = roles.role_rows_list(subject)
    if listed is not None:
        _write_atomic(raw / ROLE_ROWS, listed.encode("utf-8"))
        out["role_rows"] = f"_raw/{batch}/{ROLE_ROWS}"
    else:
        out["role_rows"] = None
        out["role_rows_note"] = f"not written: {why}"
    # Collected again: the pages the receipt marks unchanged since an earlier
    # capture, each with the rows already recorded for it — not drafted again.
    text_unchanged, entries = unchanged_list(subject, batch, [p for p in receipt.get("pages") or []
                                                             if isinstance(p, dict) and p.get("url")])
    if text_unchanged is not None:
        _write_atomic(raw / UNCHANGED, text_unchanged.encode("utf-8"))
        out["unchanged"] = f"_raw/{batch}/{UNCHANGED}"
    else:
        out["unchanged"] = None
        out["unchanged_note"] = "not written: no page of this window is unchanged since an earlier capture"
    out["unchanged_pages"] = entries
    return out


def _read_drafts(path: Path) -> List[Tuple[int, Optional[dict], str]]:
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            out.append((n, None, f"not JSON: {exc.msg}"))
            continue
        if not isinstance(obj, dict):
            out.append((n, None, "not a JSON object"))
            continue
        out.append((n, obj, ""))
    return out


def _rounds(subject: Path, batch: str) -> List[Path]:
    """The batch's rejects files so far, one per stage run that rejected a draft."""
    found = []
    for p in subject.glob(f"_draft-{batch}.rejects-*.jsonl"):
        m = re.fullmatch(re.escape(f"_draft-{batch}.rejects-") + r"(\d+)\.jsonl", p.name)
        if m:
            found.append((int(m.group(1)), p))
    return [p for _, p in sorted(found)]


def _command(subject: Path, batch: str, *extra: str) -> str:
    return " ".join([f'python3 -m kbqa stage --subject "{subject}" --batch {batch}', *extra])


def stage(subject: Path, batch: str, leave_out: bool = False) -> Tuple[int, Dict[str, object]]:
    receipt = _receipt(subject, batch)
    conv = conventions()
    staging = subject / conv.staging_for(batch)
    if staging.exists():
        raise Refused(f"{staging.name} already exists — a staging file is never overwritten")
    drafts_path = subject / draft_name(batch)
    if not drafts_path.is_file():
        raise Refused(f"no drafts {drafts_path.name}: the row-writer writes them first")
    earlier = _rounds(subject, batch)
    if len(earlier) >= CORRECTION_ROUNDS + 1 and not leave_out:
        raise Refused(
            f"drafts were rejected in {len(earlier)} runs ({', '.join(p.name for p in earlier)}) and the row-writer's "
            "one correction round is used: there is no second",
            next_step=_command(subject, batch, LEAVE_OUT) + " — writes the staging file without the rejected "
                      "drafts and lists each for the operator")
    if leave_out and len(earlier) < CORRECTION_ROUNDS + 1:
        raise Refused(
            f"{LEAVE_OUT} comes only after the row-writer's correction round has left drafts rejected "
            f"({len(earlier)} rejects file(s) so far, {CORRECTION_ROUNDS + 1} needed)",
            next_step=_command(subject, batch) + (" — then, if drafts are rejected, the row-writer's one "
                                                  "correction round" if not earlier else ""))
    round_no = max([int(p.name.rsplit("-", 1)[1].split(".")[0]) for p in earlier] or [0]) + 1
    text = _capture_text(subject, receipt)
    lines = text.split("\n")
    blocks = parse_capture(subject / Path(receipt["capture"]).name).blocks
    pages = {p["url"]: p for p in receipt["pages"]}
    subject_slug = slug(subject.name)
    if not subject_slug:
        raise Refused(f"the subject folder's name {subject.name!r} gives no id prefix")
    surface = receipt.get("surface") or batch.split("-", 1)[0]
    existing = features.subject_rows(subject)
    taken = set(existing)
    id_re = re.compile(conv.id_pattern)
    profile = active()
    respelt: List[dict] = []  # a known respelling, written in the schema's spelling (what autofix would do)

    rejects: Dict[int, dict] = {}
    candidates: Dict[int, dict] = {}  # draft line -> what is needed to make its row
    no_row_at: Dict[int, str] = {}    # draft line -> page, for `no_row` lines
    no_row: Dict[str, str] = {}
    no_row_lines: Dict[str, int] = {}
    unchanged: Dict[str, str] = {}      # page -> the earlier batch its rows stand in
    unchanged_at: Dict[int, str] = {}   # draft line -> page, for `unchanged` lines
    stop_lines: List[str] = []
    stop_lines_refused: List[dict] = []

    def reject(n: int, obj: Optional[dict], reason: str, next_step: str = OPERATOR_RULES, raw: str = "") -> None:
        rejects[n] = {"line": n, "reason": reason, "next_step": next_step,
                      **({"draft": obj} if obj is not None else {"raw": raw})}

    raw_lines = drafts_path.read_text(encoding="utf-8").splitlines()
    for n, obj, err in _read_drafts(drafts_path):
        if obj is None:
            reject(n, None, err, raw=raw_lines[n - 1])
            continue
        url = obj.get("page")
        if url not in pages:
            reject(n, obj, f"page {url!r} is not a page of the receipt (copy its `url` exactly)")
            continue
        if "no_row" in obj:
            words = obj.get("no_row")
            if set(obj) != NO_ROW_KEYS or not isinstance(words, str) or not words.strip():
                reject(n, obj, "a page with no row is exactly {\"page\": <url>, \"no_row\": \"<what the page is>\"}")
                continue
            no_row[url] = words.strip()
            no_row_lines[url] = n
            no_row_at[n] = url
            continue
        if "unchanged" in obj:
            since = obj.get("unchanged")
            if set(obj) != UNCHANGED_KEYS or not isinstance(since, str) or not since.strip():
                reject(n, obj, "an unchanged page is exactly {\"page\": <url>, \"unchanged\": \"<the earlier batch "
                               "the receipt names>\"}")
                continue
            # By text hash only: never taken on the draft's word.
            why = unchanged_refusal(subject, batch, pages[url], since.strip())
            if why is not None:
                reject(n, obj, why, "the row-writer drafts the page's rows, or its no_row line, in its correction round")
                continue
            unchanged[url] = since.strip()
            unchanged_at[n] = url
            continue
        unknown = sorted(set(obj) - set(LOCATION) - set(JUDGEMENT) - set(OPTIONAL))
        if unknown:
            reject(n, obj, f"fields no row carries: {', '.join(unknown)}")
            continue
        missing = [k for k in JUDGEMENT if not isinstance(obj.get(k), str) or not obj[k].strip()]
        if missing:
            reject(n, obj, f"missing or empty: {', '.join(missing)}")
            continue
        sfa = obj.get("same_feature_as")
        if "same_feature_as" in obj and not (isinstance(sfa, str) and sfa.startswith(DRAFT_REF)):
            anchor = existing.get(sfa) if isinstance(sfa, str) else None
            if anchor is None or not features.is_anchor(anchor):
                reject(n, obj, f"same_feature_as {sfa!r} is not an anchor of the subject: "
                               + ("it names no row of the feature tree or of any staging file" if anchor is None
                                  else f"that row is itself another source (of {anchor.get('same_feature_as')!r}); "
                                       "name that anchor instead"))
                continue
        bad_values, fixed_values = [], {}
        for field, allowed in profile.enumerated.items():
            if field not in obj or (field not in JUDGEMENT and obj[field] is None):
                continue
            value = obj[field]
            if value in allowed:
                continue
            respell = profile.respellings.get(field)
            new = respell(value) if respell is not None else None
            if new is not None and new in allowed:
                fixed_values[field] = new
                continue
            bad_values.append(f"{field} {value!r} is not one of {' | '.join(allowed)}")
        if bad_values:
            reject(n, obj, "; ".join(bad_values))
            continue
        respelt.extend({"line": n, "field": f, "before": obj[f], "after": v} for f, v in fixed_values.items())
        page = pages[url]
        part_no = obj.get("part")
        if isinstance(part_no, bool) or not isinstance(part_no, int) or not 0 <= part_no < len(page["parts"]):
            reject(n, obj, f"part {part_no!r} is not a part of {url}: it has parts 0 to {len(page['parts']) - 1}")
            continue
        quote = obj.get("quote")
        if not isinstance(quote, str) or not normalise_for_match(quote):
            reject(n, obj, "no quote")
            continue
        part = page["parts"][part_no]
        a, b = part["lines"]
        words_at = (f"the operator reads capture lines {a}-{b} and rules: the row quoting words those lines print "
                    "once, added in the fix round, or no row")
        own = "\n".join(lines[a - 1:b])
        hits = find_quote(own, quote)
        if not hits:
            elsewhere = ("it is on this page, outside the part's own lines — draft it from the part that holds it"
                         if find_quote(blocks[url], quote) else
                         "it is not on this page" + (" (it is on another page of the capture)"
                                                     if any(find_quote(t, quote) for u, t in blocks.items()
                                                            if u != url) else ""))
            reject(n, obj, f"quote not found in part {part_no}'s own lines (capture lines {a}-{b}); {elsewhere}",
                   words_at)
            continue
        if len(hits) > 1:
            reject(n, obj, f"quote found {len(hits)} times in part {part_no}'s own lines: quote enough words "
                           "to be found once", words_at)
            continue
        exact = hits[0]
        nq = normalise_for_match(quote)
        if normalise_for_match(exact) != nq or nq not in normalise_for_match(blocks[url]):
            reject(n, obj, "the capture's text for this quote does not fold back to it", words_at)
            continue
        candidates[n] = {"obj": {**obj, **fixed_values}, "url": url, "part": part, "exact": exact}

    # A link to another draft of this batch: `draft:<line>`, resolved to the id
    # that draft is given. One step only: the target is an anchor, never itself
    # another source; a target that is rejected takes its source with it.
    def target_of(n: int) -> Optional[int]:
        sfa = candidates[n]["obj"].get("same_feature_as")
        if not isinstance(sfa, str) or not sfa.startswith(DRAFT_REF):
            return None
        ref = sfa[len(DRAFT_REF):]
        return int(ref) if ref.isdigit() else -1

    for n in sorted(candidates):
        t = target_of(n)
        if t is None:
            continue
        obj = candidates[n]["obj"]
        link = "link it to its anchor in the fix round once both rows are staged, or leave it as its own anchor"
        if t < 1:
            reason = f"same_feature_as {obj['same_feature_as']!r} is not `{DRAFT_REF}<line number>`"
        elif t == n:
            reason = f"same_feature_as names this draft's own line ({t})"
        elif t in no_row_at:
            reason = f"same_feature_as names draft line {t}, a page with no row"
        elif t in unchanged_at:
            reason = f"same_feature_as names draft line {t}, a page drafted unchanged (no row in this batch)"
        elif t in rejects:
            reason = f"same_feature_as names draft line {t}, which is rejected: {rejects[t]['reason']}"
        elif t not in candidates:
            reason = f"same_feature_as names draft line {t}, which holds no draft"
        elif "same_feature_as" in candidates[t]["obj"]:
            reason = (f"same_feature_as names draft line {t}, which is itself another source "
                      f"(of {candidates[t]['obj']['same_feature_as']!r}); name that anchor instead")
        else:
            continue
        reject(n, obj, reason, f"the operator rules: {link}")
    for n in list(candidates):
        if n in rejects:
            del candidates[n]

    # Exact repeats: the same name and the same quote on the same host as an
    # anchor — of the subject, or an earlier anchor draft of this batch — are
    # linked by code. Anchors only: a row that carries same_feature_as is never
    # a target. A draft that names another anchor is listed, never changed.
    subject_anchors: Dict[Tuple[str, str, str], List[str]] = {}
    for rid, row in existing.items():
        k = repeat_key(row.get("source_url"), row, row.get("source_quote"))
        if k is not None and features.is_anchor(row):
            subject_anchors.setdefault(k, []).append(rid)
    named_by: Dict[int, List[int]] = {}  # draft line -> the drafts that name it as their anchor
    for n in sorted(candidates):
        t = target_of(n)
        if t is not None:
            named_by.setdefault(t, []).append(n)
    batch_anchors: Dict[Tuple[str, str, str], int] = {}
    linked: List[dict] = []
    conflicts: List[dict] = []
    for n in sorted(candidates):
        c = candidates[n]
        obj = c["obj"]
        k = repeat_key(c["url"], obj, c["exact"])
        has = obj.get("same_feature_as")
        if k is None:
            continue
        field = repeat_field(obj)
        matched = {"host": k[0], field: k[1], "quote": c["exact"]}
        if k in subject_anchors:
            ids_of = subject_anchors[k]
            if len(ids_of) > 1 and has not in ids_of:
                conflicts.append({"line": n, "same_feature_as": has, "anchor": ids_of,
                                  "matched": matched, "reason": f"an exact repeat of {len(ids_of)} anchors of "
                                  "the subject: which one is the feature is not code's to choose"})
                continue
            target, anchor_line = (has if has in ids_of else ids_of[0]), None
        elif k in batch_anchors:
            anchor_line = batch_anchors[k]
            target = f"{DRAFT_REF}{anchor_line}"
        else:
            if not has:
                batch_anchors[k] = n
            continue
        if has == target:
            continue
        entry: Dict[str, object] = {"line": n, "anchor": target if anchor_line is None else None}
        if anchor_line is not None:
            entry["anchor_line"] = anchor_line  # the id it is given is filled in below
        entry["matched"] = matched
        if has:
            conflicts.append({**entry, "same_feature_as": has,
                              "reason": "the draft names another anchor: nothing changed"})
            continue
        if n in named_by:
            conflicts.append({**entry, "same_feature_as": None,
                              "reason": f"draft line(s) {', '.join(map(str, named_by[n]))} name this draft as "
                                        "their anchor: linking it would leave them pointing at a row that is "
                                        "not an anchor, so nothing changed"})
            continue
        c["obj"] = {**obj, "same_feature_as": target}
        linked.append(entry)

    rows: List[dict] = []
    ids: Dict[int, str] = {}
    for n in sorted(candidates):
        c = candidates[n]
        obj, part = c["obj"], c["part"]
        levels = _crumb_levels(part.get("breadcrumb"))
        segs = [subject_slug, surface] + ([slug(levels[-1]) or "unnamed"] if levels else []) \
            + [slug(obj["vendor_term"]) or "unnamed"]
        base = ".".join(segs)
        rid, k = base, 1
        while rid in taken:
            k += 1
            rid = f"{base}-{k}"
        if not id_re.match(rid):
            reject(n, obj, f"the id {rid!r} made from it does not match the id pattern {conv.id_pattern}")
            continue
        taken.add(rid)
        ids[n] = rid
        parent_path, depth_level = position(part.get("breadcrumb"))
        row = {"id": rid, "source_url": c["url"], "source_quote": c["exact"],
               "access_date": receipt["access_date"],
               "vendor_term": obj["vendor_term"], "what_it_does": obj["what_it_does"],
               "parent_path": parent_path,
               "evidence_grade": obj["evidence_grade"], "confidence": obj["confidence"],
               "mechanism": obj["mechanism"], "outcome": obj["outcome"],
               "depth_level": depth_level, "canonical": "NOVEL"}
        row.update({k2: obj[k2] for k2 in OPTIONAL if k2 in obj})
        row["_line"] = n
        rows.append(row)
    for row in rows:
        t = target_of(row["_line"])
        if t is not None and t in ids:
            row["same_feature_as"] = ids[t]
        elif t is not None:
            reject(row["_line"], candidates[row["_line"]]["obj"],
                   f"same_feature_as names draft line {t}, which is rejected: {rejects[t]['reason']}")
    rows = [{k: v for k, v in r.items() if k != "_line"} for r in rows if r["_line"] not in rejects]
    for e in linked + conflicts:
        if "anchor_line" in e:
            e["anchor"] = ids.get(e["anchor_line"])
    linked = [e for e in linked if e["line"] not in rejects]

    with_rows = {r["source_url"] for r in rows}
    # Every page of the receipt has a row or a reason: a page no draft line names
    # at all — no row, no `no_row` — blocks the staging file like any reject.
    drafted_pages = {obj.get("page") for _, obj, _ in _read_drafts(drafts_path) if obj is not None}
    page_rejects = [{"page": u, "reason": f"no row and no reason: no draft line names the page {u}",
                     "next_step": "the row-writer drafts the page's rows, or one no_row line saying what the "
                                  "page is, in its correction round"}
                    for u in pages if u not in drafted_pages]
    for url, words in no_row.items():
        if url in with_rows:
            reject(no_row_lines[url], {"page": url, "no_row": words},
                   "the page is drafted `no_row` but has rows: one or the other")
            continue
        line, why = stops.try_line(url, f"no feature: {words}")
        if line is None:
            stop_lines_refused.append({"page": url, "no_row": words, "reason": why})
        else:
            stop_lines.append(line)
    # An unchanged page adds nothing to the staging file: the rows recorded
    # earlier stand, and its stop line accounts for the page in this window.
    unchanged_pages: List[dict] = []
    for url, since in unchanged.items():
        n = next(k for k, u in unchanged_at.items() if u == url and k not in rejects)
        if url in with_rows or url in no_row:
            reject(n, {"page": url, "unchanged": since},
                   "the page is drafted `unchanged` but also has " + ("rows" if url in with_rows else "a no_row line")
                   + ": one or the other")
            continue
        rec = recorded(subject, url, since)
        unchanged_pages.append({"page": url, "unchanged_since": since,
                                **{k: rec[k] for k in ("rows_in", "ids", "stop_line") if k in rec}})
        line, why = stops.try_line(url, UNCHANGED_REASON + since)
        if line is not None:
            stop_lines.append(line)  # g4 counts the page once the fetcher adds it
        else:
            stop_lines_refused.append({"page": url, "unchanged": since, "reason": why})

    listed = [rejects[n] for n in sorted(rejects)] + page_rejects
    result: Dict[str, object] = {"batch": batch, "round": round_no, "drafts": str(drafts_path),
                                 "rows": len(rows), "rejected": len(listed), "staging": None, "rejects": None}
    if listed:
        rp = subject / rejects_name(batch, round_no)
        _write_new(rp, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in listed).encode("utf-8"))
        result["rejects"] = str(rp)
        result["rejected_lines"] = [{k: r[k] for k in ("line", "page", "reason") if k in r} for r in listed]
    accounted = with_rows | set(no_row) | {e["page"] for e in unchanged_pages}
    result["pages_without_row_or_no_row"] = [u for u in pages if u not in accounted]
    result["stop_lines_to_add"] = stop_lines
    result["unchanged_pages"] = unchanged_pages
    result["linked_by_code"] = linked
    result["respelt_by_code"] = [e for e in respelt if e["line"] in ids and e["line"] not in rejects]
    result["link_conflicts"] = conflicts
    if stop_lines_refused:
        result["stop_lines_refused"] = stop_lines_refused
    if listed and not leave_out:
        # Rejected drafts block the staging file: the row-writer corrects them
        # once, or the operator rules on each — never left out unseen.
        if round_no <= CORRECTION_ROUNDS:
            result["next_step"] = (f"the row-writer's one correction round: it rewrites only the rejected lines "
                                   f"of {drafts_path.name}" + (" and drafts each page listed with no row and no "
                                                               "reason" if page_rejects else "")
                                   + f", then {_command(subject, batch)}")
        else:
            result["next_step"] = (f"{_command(subject, batch, LEAVE_OUT)} — the correction round is used; the "
                                   "staging file is written without these drafts, each listed for the operator")
        result["note"] = "drafts were rejected, so no staging file was written"
        return 1, result
    if listed:
        result["needs_operator"] = [{k: r[k] for k in ("line", "page", "reason", "next_step", "draft", "raw")
                                     if k in r} for r in listed]
    if not rows:
        result["note"] = "no draft became a row, so no staging file was written"
        if not listed:  # every page was drafted no_row
            result["next_step"] = NO_ROWS_STEP
        return (1 if listed else 0), result
    body = frontmatter(receipt) + "\n```json\n" + "".join(
        json.dumps(r, ensure_ascii=False) + "\n" for r in rows) + "```\n"
    _write_new(staging, body.encode("utf-8"))
    result["staging"] = str(staging)
    # The mappers read ROLE-ROWS.md: refreshed now, it holds this batch's own rows.
    listed_roles, why = roles.role_rows_list(subject)
    if listed_roles is not None:
        _write_atomic(subject / "_raw" / batch / ROLE_ROWS, listed_roles.encode("utf-8"))
        result["role_rows_refreshed"] = f"_raw/{batch}/{ROLE_ROWS}"
    else:
        result["role_rows_refreshed"] = None
        result["role_rows_note"] = f"not written: {why}"
    return 0, result


def run(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="kbqa stage")
    ap.add_argument("--subject", required=True, help="the subject folder")
    ap.add_argument("--batch", required=True, help="the batch, as its receipt names it")
    ap.add_argument("--lists", action="store_true",
                    help="write the features and role-row lists beside the receipt (before the row-writer)")
    ap.add_argument(LEAVE_OUT, action="store_true", dest="leave_out",
                    help="after the one correction round: write the staging file without the drafts still "
                         "rejected, each listed under needs_operator")
    args = ap.parse_args(argv)
    subject, batch = Path(args.subject), args.batch
    try:
        if args.lists and args.leave_out:
            raise Refused(f"--lists and {LEAVE_OUT} are separate runs")
        if args.lists:
            code, out = 0, lists(subject, batch)
        else:
            code, out = stage(subject, batch, args.leave_out)
    except Refused as exc:
        print(json.dumps({"batch": batch, "refused": str(exc), "next_step": exc.next_step},
                         ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return code


def main() -> None:  # pragma: no cover
    sys.exit(run())
