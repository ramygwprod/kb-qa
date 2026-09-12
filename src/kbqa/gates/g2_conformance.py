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

from ..profile import row_model
from ..parsing import parse_staging
from ..verdict import FAIL, PASS, Finding, Verdict, input_ref
from . import EXIT_FAIL, EXIT_PASS

GATE = "g2_conformance"


def run(argv: Optional[List[str]] = None) -> Tuple[Verdict, int]:
    ap = argparse.ArgumentParser(prog="kbqa g2")
    ap.add_argument("--staging", required=True)
    args = ap.parse_args(argv)

    staging = Path(args.staging)
    findings: List[Finding] = []
    inputs = {"staging": input_ref(staging)}

    if not staging.exists():
        findings.append(Finding("staging_missing", f"staging file not found: {staging}"))
        return Verdict(GATE, FAIL, inputs, {"rows": 0, "checked": 0, "failed": 1}, findings), EXIT_FAIL

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
                f"parser found {len(parsed.rows)} rows, naive '^{{\"id\"' count found "
                f"{parsed.naive_count}; the parser is wrong until proven otherwise",
            )
        )

    validated = 0
    seen_ids = {}
    for rp in parsed.rows:
        where = f"{staging.name}:{rp.line_no}"
        if rp.obj is None:
            findings.append(Finding("row_unparseable", rp.error or "unparseable row", where))
            continue
        try:
            row = row_model().model_validate(rp.obj)
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(p) for p in err["loc"]) or "<row>"
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

    counts = {
        "rows": len(parsed.rows),
        "naive_rows": parsed.naive_count,
        "checked": len(parsed.rows),
        "validated": validated,
        "failed": len(findings),
    }
    verdict = PASS if not findings else FAIL
    return Verdict(GATE, verdict, inputs, counts, findings), (
        EXIT_PASS if verdict == PASS else EXIT_FAIL
    )
