"""G2 · Conformance — g2 --staging <f>

Zero rows parsed is a FAIL. A parser that sees nothing and a file that holds
nothing look identical; treat the ambiguity as a defect. (spec §G2)

The naive cross-check exists because five checkers gave false results in one
session of this project, each caught only by cross-checking against a naive
count. (spec §7)
"""

import argparse
from pathlib import Path
from typing import List, Optional, Tuple

from pydantic import ValidationError

from ..features import TREE, is_anchor, subject_rows
from ..profile import active, conventions, row_model
from ..parsing import parse_staging
from ..verdict import FAIL, PASS, Finding, Verdict, input_ref
from . import EXIT_FAIL, EXIT_PASS

GATE = "g2_conformance"

# A row must carry at least one of these to be a row at all. Used to tell a
# malformed row apart from an object that was never meant to be one.
IDENTIFYING = {"id", "source_url", "source_quote"}


def run(argv: Optional[List[str]] = None) -> Tuple[Verdict, int]:
    ap = argparse.ArgumentParser(prog="kbqa g2")
    ap.add_argument("--staging", required=True)
    args = ap.parse_args(argv)

    staging = Path(args.staging)
    findings: List[Finding] = []
    inputs = {"staging": input_ref(staging)}

    if not staging.exists():
        findings.append(Finding("staging_missing", f"staging file not found: {staging}"))
        return Verdict(GATE, FAIL, inputs, {"rows": 0, "checked": 0, "scanned": 0, "failed": 1}, findings), EXIT_FAIL

    parsed = parse_staging(staging)
    if parsed.frontmatter_error:
        findings.append(Finding("frontmatter_unparseable", parsed.frontmatter_error))

    # Zero rows is a defect, not a pass.
    if len(parsed.rows) == 0:
        findings.append(
            Finding(
                "zero_rows",
                "no rows parsed; a broken parser and an empty file are "
                "indistinguishable, so this is a defect",
            )
        )

    # The parser must agree with a naive count of the same file.
    if len(parsed.rows) != parsed.naive_count:
        findings.append(
            Finding(
                "parser_disagrees_with_naive_count",
                f"parser found {len(parsed.rows)} rows, naive count of '\"id\":' keys "
                f"found {parsed.naive_count}; the parser is wrong until proven otherwise",
            )
        )

    # K1 · rules for batches collected under the current naming convention.
    # A legacy batch is not checked against them — it is re-collected, never
    # edited — and the counts say which happened, so "not applied" is visible.
    batch = conventions().batch_of(staging.name)
    surface = conventions().surface_of(batch)
    strict = active().strict_row_check if surface else None
    strict_checked = 0

    validated = 0
    seen_ids = {}
    for rp in parsed.rows:
        where = f"{staging.name}:{rp.line_no}"
        if rp.obj is None:
            findings.append(Finding("row_unparseable", rp.error or "unparseable row", where))
            continue

        # An object carrying none of the identifying fields is not a broken row
        # — it is a different kind of object, typically batch metadata sitting
        # inside the same fence. Reporting it as six missing core fields says
        # the rows are malformed, which is untrue of them and sends a maker
        # looking for a defect that is not there.
        if not (IDENTIFYING & set(rp.obj)):
            findings.append(
                Finding(
                    "non_row_object",
                    "object has none of "
                    + ", ".join(sorted(IDENTIFYING))
                    + f" — keys are {sorted(rp.obj)}; this looks like batch "
                    "metadata rather than a row",
                    where,
                )
            )
            continue

        if strict is not None:
            strict_checked += 1
            for code, msg in strict(rp.obj):
                findings.append(Finding(code, msg, where))

        try:
            row = row_model().model_validate(rp.obj)
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(p) for p in err["loc"]) or "<row>"
                # An unfetchable citation is a distinct defect with a distinct
                # remedy, not one more shape of "the row is malformed". Buried
                # among schema violations it reads as sloppiness; named, it says
                # exactly what is wrong and what re-sourcing it would take.
                # Measured at 644 rows across 23 subjects in one estate — enough
                # that the difference between one finding and 644 anonymous ones
                # decides whether anybody acts on it.
                if loc == "source_url" and "http" in err["msg"]:
                    findings.append(
                        Finding("unfetchable_source", f"{loc}: {err['msg']}", where)
                    )
                else:
                    findings.append(
                        Finding("schema_violation", f"{loc}: {err['msg']}", where)
                    )
            continue
        validated += 1
        if row.id in seen_ids:
            findings.append(
                Finding(
                    "duplicate_id",
                    f"id {row.id!r} already defined at line {seen_ids[row.id]}",
                    where,
                )
            )
        else:
            seen_ids[row.id] = rp.line_no

    # Another source of a feature names that feature's anchor: a row of this
    # subject — here, in another staging file, or in the tree — that is not
    # itself another source. Checked against the subject folder, because the
    # anchor is often a row of an earlier batch.
    linked = [(f"{staging.name}:{rp.line_no}", rp.obj) for rp in parsed.rows
              if rp.obj is not None and rp.obj.get("same_feature_as") is not None]
    if linked:
        known = subject_rows(staging.parent, skip=staging)
        for rp in parsed.rows:
            if rp.obj is not None and rp.obj.get("id"):
                known[str(rp.obj["id"])] = rp.obj
        for where, row in linked:
            target = row.get("same_feature_as")
            if not isinstance(target, str) or not target.strip() or target == row.get("id"):
                continue  # the row rule `same_feature_as_invalid` reports these
            anchor = known.get(target)
            if anchor is None:
                findings.append(Finding(
                    "same_feature_unknown",
                    f"same_feature_as {target!r} names no row of this subject — not in {TREE}, "
                    "this batch or another staging file", where))
            elif not is_anchor(anchor):
                findings.append(Finding(
                    "same_feature_not_anchor",
                    f"same_feature_as {target!r} names a row that is itself another source (of "
                    f"{anchor.get('same_feature_as')!r}); name that anchor instead", where))

    counts = {
        "rows": len(parsed.rows),
        "naive_rows": parsed.naive_count,
        "scanned": len(parsed.rows),
        "checked": len(parsed.rows),
        "validated": validated,
        "surface": surface or "legacy",
        "strict_rules": "applied" if strict is not None else "not applied (legacy batch name)",
        "strict_checked": strict_checked,
        "same_feature_rows": len(linked),
        "failed": len(findings),
    }
    verdict = PASS if not findings else FAIL
    return Verdict(GATE, verdict, inputs, counts, findings), (
        EXIT_PASS if verdict == PASS else EXIT_FAIL
    )
