"""kbqa autofix — the mechanical findings, fixed by code before the row-writer's fix round.

    python3 -m kbqa autofix --subject <d> --batch <b>

It reads the batch's check report, `_qa/<batch>.report.json`, and refuses unless
that report was made on the staging file's current bytes (its
`staging_sha256`), and refuses a report of round 2 or later — from the report,
or, when it names no round, from the subject's `_qa-log.jsonl`: autofix is part
of the one fix round, never a second. Of the report's findings it fixes only those with one right
answer that code computes from the evidence, with nothing to judge:

- `evidence_grade_spelling` — a known respelling of one of the schema's grades:
  another case or spaces (`Help`, `[ verify ]`), or the bare `verify` for
  `[verify]`. Any other value is left: which grade was meant is not code's call.
- `parent_path_empty` and `depth_unknown_with_breadcrumb` — re-derived from the
  batch's receipt as `kbqa stage` derives them (`stage.position`): the parts of
  the row's page whose own lines hold the row's quote give the breadcrumb and
  its levels counted. Only when the receipt and its capture agree (sha256 and
  pages, `stage`'s own check), the staging file names that capture's sha256,
  the row's `source_url` is a page of the receipt, its quote is in that page's
  parts and those parts give one answer. A depth is written only when the row's
  `parent_path` is that breadcrumb; an empty `parent_path` filled this way also
  gets the depth when its `depth_level` is `unknown`.
- `id_not_first_key` — `id` moved to the front; no value changes.

Nothing else. Only a row whose line reads exactly as `kbqa stage` writes it
(`json.dumps(row, ensure_ascii=False)`) is rewritten, so nothing but the fixed
fields changes; every other line keeps its bytes and its place, and every
finding's line number stays true. A finding of another code, or one whose fix
the evidence does not give, is left for the row-writer's fix round and listed
with the reason.

When at least one fix applies it writes, in this order and never over a file
that exists: `_qa/<batch>.staging-before-autofix-<n>.md` (the old bytes, so
nothing is lost), `_qa/<batch>.autofix-<n>.json` (every change — finding code,
row id, line, field, before, after — and the staging sha256 before and after),
then the staging file, atomically. `n` is one past every earlier run's. When no
fix applies it writes nothing.

Run again while the staging file is the bytes an earlier run wrote (that run's
`staging_sha256_after`; the report on disk is still the one before it), it is
no dead end: it writes nothing and prints `already applied`, that run's
`left_findings` and the next step — the row-writer's fix round.

It prints one JSON result: what was fixed (per code), what is left for the
row-writer (per code, and each finding word for word), the files written and
the next step. Exit 0 when it ran (or was already applied), 1 when refused.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pydantic import ValidationError

from . import __version__, stage
from .manifest import MANIFEST_SHA256
from .parsing import parse_staging
from .profile import conventions, row_model
from .profiles.vendor_catalogue import DEPTH_UNKNOWN, schema_evidence_grade
from .report import FIXABLE, fix_round

REPORT = "{batch}.report.json"
LOG = "_qa-log.jsonl"  # where /kbqa-check records each run, and so each round
PARKED_STEP = "operator: the one fix round is used; the batch is PARKED for the operator"
RECORD = "{batch}.autofix-{n}.json"
BEFORE = "{batch}.staging-before-autofix-{n}.md"
SPELLING, PARENT, DEPTH, ID_FIRST = ("evidence_grade_spelling", "parent_path_empty",
                                     "depth_unknown_with_breadcrumb", "id_not_first_key")
FIXES = (SPELLING, PARENT, DEPTH, ID_FIRST)
ROW_WRITER_STEP = ("the row-writer's fix round, with left_findings word for word (/kbqa-collect <Subject> fix "
                   "{batch}); then /kbqa-check {subject} again — the batch's next round")
Refused = stage.Refused


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _applied(qa: Path, batch: str, sha: str) -> Optional[Tuple[Path, dict]]:
    """The latest earlier autofix record of this batch whose staging sha256
    after is `sha` — these bytes are that run's own — or None."""
    pat = re.compile(re.escape(batch) + r"\.autofix-(\d+)\.json")
    found = []
    if qa.is_dir():
        for p in qa.iterdir():
            m = pat.fullmatch(p.name)
            if m:
                found.append((int(m.group(1)), p))
    for _, p in sorted(found, reverse=True):
        try:
            record = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(record, dict) and record.get("staging_sha256_after") == sha:
            return p, record
    return None


def _runs(qa: Path, batch: str) -> int:
    """The highest run number any earlier autofix of this batch used."""
    pat = re.compile(re.escape(batch) + r"\.(?:autofix-(\d+)\.json|staging-before-autofix-(\d+)\.md)")
    found = [0]
    if qa.is_dir():
        for p in qa.iterdir():
            m = pat.fullmatch(p.name)
            if m:
                found.append(int(m.group(1) or m.group(2)))
    return max(found)


class Evidence:
    """The batch's receipt and capture, read once and only when a fix needs them."""

    def __init__(self, subject: Path, batch: str, staging_capture_sha: object):
        self.why = ""
        self.pages: Dict[str, dict] = {}
        self.lines: List[str] = []
        try:
            receipt = stage._receipt(subject, batch)
            text = stage._capture_text(subject, receipt)
        except Refused as exc:
            self.why = f"the batch's receipt cannot vouch for it: {exc}"
            return
        if staging_capture_sha != receipt.get("sha256"):
            self.why = (f"the staging file names capture sha256 {staging_capture_sha!r}, the receipt "
                        f"{receipt.get('sha256')!r}: the receipt is not this staging file's evidence")
            return
        self.pages = {p["url"]: p for p in receipt["pages"]}
        self.lines = text.split("\n")

    def position(self, row: dict) -> Tuple[Optional[Tuple[str, str]], str]:
        """(parent_path, depth_level) as `kbqa stage` derives them for this row,
        or None and why the evidence does not give them."""
        if self.why:
            return None, self.why
        page = self.pages.get(row.get("source_url"))
        if page is None:
            return None, f"source_url {row.get('source_url')!r} is not a page of the batch's receipt"
        quote = str(row.get("source_quote") or "")
        found = set()
        for part in page["parts"]:
            if "breadcrumb" not in part:
                return None, "the receipt's parts carry no breadcrumb"
            a, b = part["lines"]
            if stage.find_quote("\n".join(self.lines[a - 1:b]), quote):
                found.add(stage.position(part["breadcrumb"]))
        if len(found) != 1:
            return None, ("the row's source_quote is in no part's own lines of its page" if not found else
                          f"the parts holding the row's quote give {len(found)} different breadcrumbs")
        return found.pop(), ""


def _fix(code: str, row: dict, evidence: Evidence) -> Tuple[List[Tuple[str, object]], str]:
    """The field changes that fix one finding on one row — (field, new value)
    pairs, applied in order — or none and why."""
    if code == SPELLING:
        new = schema_evidence_grade(row.get("evidence_grade"))
        if new is None:
            return [], f"evidence_grade {row.get('evidence_grade')!r} is no known respelling of a schema grade"
        if new == row.get("evidence_grade"):
            return [], "evidence_grade is already the schema's spelling"
        return [("evidence_grade", new)], ""
    if code == ID_FIRST:
        if "id" not in row:
            return [], "the row has no id"
        if next(iter(row)) == "id":
            return [], "id is already the first key"
        return [("<order>", None)], ""
    pp = row.get("parent_path")
    if code == PARENT and isinstance(pp, str) and pp.strip():
        return [], "parent_path is not empty"
    if code == DEPTH and str(row.get("depth_level", "")).strip() != DEPTH_UNKNOWN:
        return [], "depth_level is not unknown"
    pos, why = evidence.position(row)
    if pos is None:
        return [], why
    parent_path, depth_level = pos
    if code == PARENT:
        out: List[Tuple[str, object]] = [("parent_path", parent_path)]
        if str(row.get("depth_level", "")).strip() == DEPTH_UNKNOWN and depth_level != DEPTH_UNKNOWN:
            out.append(("depth_level", depth_level))
        return out, ""
    if pp != parent_path:
        return [], (f"parent_path {pp!r} is not the breadcrumb of its part in the receipt "
                    f"({parent_path!r}): which depth it has is not code's to say")
    return [("depth_level", depth_level)], ""


def _error_fields(row: dict) -> set:
    try:
        row_model().model_validate(row)
    except ValidationError as exc:
        return {".".join(str(p) for p in e["loc"]) or "<row>" for e in exc.errors()}
    return set()


def autofix(subject: Path, batch: str) -> Dict[str, object]:
    if not subject.is_dir():
        raise Refused(f"no subject folder {subject}")
    if not stage.BATCH_RE.match(batch):
        raise Refused(f"batch {batch!r} is not <surface>-<YYYY-MM-DD>-wNN: a legacy batch is never edited, "
                      "it goes on the re-collection list")
    staging = subject / conventions().staging_for(batch)
    if not staging.is_file():
        raise Refused(f"no staging file {staging.name}")
    qa = subject / "_qa"
    report_path = qa / REPORT.format(batch=batch)
    if not report_path.is_file():
        raise Refused(f"no check report _qa/{report_path.name}", next_step=f"/kbqa-check {subject}")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Refused(f"_qa/{report_path.name} cannot be read: {exc}", next_step=f"/kbqa-check {subject}")
    if not isinstance(report, dict) or report.get("batch") != batch or not isinstance(report.get("findings"), list):
        raise Refused(f"_qa/{report_path.name} is not a check report of {batch}", next_step=f"/kbqa-check {subject}")
    data = staging.read_bytes()
    sha_before = _sha(data)
    applied = _applied(qa, batch, sha_before) if report.get("staging_sha256") != sha_before else None
    if applied is not None:
        # Autofix ran already and these are the bytes it wrote: running it again
        # is no dead end — what it left is the row-writer's, word for word.
        path, record = applied
        left = record.get("left_findings") or []
        return {"batch": batch, "already_applied": f"_qa/{path.name}", "staging": str(staging),
                "note": f"already applied: {staging.name} is the bytes _qa/{path.name} wrote; nothing was written",
                "left_findings": left, "files_written": [],
                "next_step": ROW_WRITER_STEP.format(batch=batch, subject=subject) if left else
                             f"/kbqa-check {subject} again — the staging file changed, so the report on disk no "
                             "longer describes it"}
    if report.get("staging_sha256") != sha_before:
        raise Refused(f"the report was made on staging bytes {report.get('staging_sha256')!r}, the file now "
                      f"hashes to {sha_before}: it is not the report of these rows",
                      next_step=f"/kbqa-check {subject} — then autofix on the report of the current bytes")
    # Autofix is part of the one fix round, never a second one: a round-2 report
    # is the operator's. A report made without a log names no round; the
    # subject's log then says which round these bytes are.
    round_no = report.get("round")
    log = subject / LOG
    if round_no is None and log.is_file():
        round_no, _ = fix_round(log, batch, sha_before)
    if isinstance(round_no, int) and round_no >= 2:
        raise Refused(f"the report is the batch's round {round_no}: code fixes only in round 1, as part of "
                      "the one fix round", next_step=PARKED_STEP)

    text = data.decode("utf-8")
    lines = text.splitlines(keepends=True)  # the line numbering `parse_staging` and the gates use
    parsed = parse_staging(staging)
    by_line = {rp.line_no: rp for rp in parsed.rows}
    evidence: Optional[Evidence] = None
    rows: Dict[int, dict] = {}     # line -> the row as fixed so far
    changes: List[dict] = []
    fixed: List[dict] = []
    left: List[dict] = []
    others: List[dict] = []

    for f in report["findings"]:
        if not isinstance(f, dict):
            continue
        code, where = f.get("code"), str(f.get("where") or "")
        if f.get("kind") != FIXABLE:
            others.append(f)
            continue
        if code not in FIXES:
            left.append(f)
            continue
        name, _, num = where.rpartition(":")
        rp = by_line.get(int(num)) if name == staging.name and num.isdigit() else None
        if rp is None or rp.obj is None:
            left.append({**f, "why_not_by_code": f"{where!r} names no row of {staging.name}"})
            continue
        n = rp.line_no
        content = lines[n - 1].splitlines()[0] if lines[n - 1].strip() else ""
        if content != json.dumps(rp.obj, ensure_ascii=False):
            left.append({**f, "why_not_by_code": "the row's line is not as kbqa stage writes it, so code "
                                                 "cannot rewrite it without changing other bytes"})
            continue
        if code in (PARENT, DEPTH) and evidence is None:
            evidence = Evidence(subject, batch, parsed.frontmatter_raw.get("source_capture_sha256"))
        row = rows.get(n, dict(rp.obj))
        edits, why = _fix(code, row, evidence)
        if not edits:
            left.append({**f, "why_not_by_code": why})
            continue
        for field, value in edits:
            if field == "<order>":
                keys = list(row)
                row = {"id": row["id"], **{k: v for k, v in row.items() if k != "id"}}
                changes.append({"code": code, "id": row["id"], "line": n, "field": "key order",
                                "before": keys, "after": list(row)})
                continue
            changes.append({"code": code, "id": row.get("id"), "line": n, "field": field,
                            "before": row.get(field), "after": value})
            row[field] = value
        rows[n] = row
        fixed.append(f)

    # A schema finding on a row a fix changed is resolved when the fixed row no
    # longer fails on that field — checked against the row model, never assumed.
    resolved: List[dict] = []
    still: List[dict] = []
    errors = {n: _error_fields(r) for n, r in rows.items()}
    for f in left:
        name, _, num = str(f.get("where") or "").rpartition(":")
        n = int(num) if name == staging.name and num.isdigit() else None
        field = str(f.get("message") or "").split(":", 1)[0]
        if f.get("code") == "schema_violation" and n in errors and field not in errors[n]:
            resolved.append(f)
        else:
            still.append(f)

    def per_code(items: List[dict]) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for i in items:
            out[str(i.get("code"))] = out.get(str(i.get("code")), 0) + 1
        return dict(sorted(out.items()))

    result: Dict[str, object] = {
        "batch": batch, "report": f"_qa/{report_path.name}", "staging": str(staging),
        "fixed": per_code(fixed), "changes": changes,
        "resolved_by_a_fix": [{k: f.get(k) for k in ("code", "where", "message")} for f in resolved],
        "left_for_row_writer": per_code(still),
        "left_findings": [{k: f[k] for k in ("code", "where", "message", "why_not_by_code") if k in f}
                          for f in still],
        "not_for_row_writer": per_code(others),
        "files_written": [],
    }
    if not changes:
        result["note"] = "no finding of the report has a fix code can compute exactly: nothing was written"
    else:
        new_lines = list(lines)
        for n, row in rows.items():
            ending = lines[n - 1][len(lines[n - 1].splitlines()[0]):]
            new_lines[n - 1] = json.dumps(row, ensure_ascii=False) + ending
        new = "".join(new_lines).encode("utf-8")
        run_no = _runs(qa, batch) + 1
        before_path = qa / BEFORE.format(batch=batch, n=run_no)
        record_path = qa / RECORD.format(batch=batch, n=run_no)
        record = {"batch": batch, "autofix": run_no, "kbqa_version": __version__,
                  "manifest_sha256": MANIFEST_SHA256, "report": result["report"],
                  "report_generated": report.get("generated"), "staging": staging.name,
                  "staging_sha256_before": sha_before, "staging_sha256_after": _sha(new),
                  "before_copy": f"_qa/{before_path.name}", "changes": changes,
                  "resolved_by_a_fix": result["resolved_by_a_fix"],
                  "left_findings": result["left_findings"], "not_for_row_writer": result["not_for_row_writer"]}
        if _sha(staging.read_bytes()) != sha_before:
            raise Refused(f"{staging.name} changed while autofix ran: nothing was written",
                          next_step=f"/kbqa-check {subject}")
        stage._write_new(before_path, data)
        stage._write_new(record_path, (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        stage._write_atomic(staging, new)
        result["files_written"] = [str(before_path), str(record_path), str(staging)]
        result["staging_sha256_before"], result["staging_sha256_after"] = sha_before, _sha(new)
    if still:
        result["next_step"] = (ROW_WRITER_STEP.format(batch=batch, subject=subject)
                               + (". Not /kbqa-check before the fix round: a check of the new bytes is that "
                                  "next round, and leaves the row-writer none" if changes else ""))
    elif changes:
        result["next_step"] = (f"/kbqa-check {subject} again — the staging file changed, so the report on disk "
                               "no longer describes it")
    else:
        result["next_step"] = ("nothing for code or the row-writer to fix" +
                               ("; the structural and planner findings go to planning" if others else ""))
    return result


def run(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="kbqa autofix")
    ap.add_argument("--subject", required=True, help="the subject folder")
    ap.add_argument("--batch", required=True, help="the batch whose report and staging file to read")
    args = ap.parse_args(argv)
    subject, batch = Path(args.subject), args.batch
    try:
        out = autofix(subject, batch)
    except Refused as exc:
        print(json.dumps({"batch": batch, "refused": str(exc), "next_step": exc.next_step},
                         ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def main() -> None:  # pragma: no cover
    sys.exit(run())
