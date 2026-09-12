"""G3 · Grounding — g3 --staging <f> --capture <f>

THE correctness gate. Its ground truth is the vendor's own page rather than
our plan, so it is the one gate that can catch a wrong specification.
Everything else tests conformance. (spec §G3)

Two rules, both strict:
  1. source_url appears as a BEGIN marker in the capture.
  2. source_quote is a substring of THAT ROW'S OWN page block — not of the
     whole capture. A quote lifted from a different page is invention with a
     real-looking citation, and whole-capture matching would bless it.

⛔ Normalisation folds quotes, dashes and whitespace. Never spelling.
Vendor typos are evidence; correcting one breaks the match correctly.
"""

import argparse
from pathlib import Path
from typing import List, Optional, Tuple

from ..parsing import normalise_for_match, parse_capture, parse_staging
from ..verdict import FAIL, PASS, Finding, Verdict, input_ref
from . import EXIT_FAIL, EXIT_PASS

GATE = "g3_grounding"


def run(argv: Optional[List[str]] = None) -> Tuple[Verdict, int]:
    ap = argparse.ArgumentParser(prog="kbqa g3")
    ap.add_argument("--staging", required=True)
    ap.add_argument("--capture", required=True)
    args = ap.parse_args(argv)

    staging = Path(args.staging)
    capture = Path(args.capture)
    findings: List[Finding] = []
    inputs = {"staging": input_ref(staging), "capture": input_ref(capture)}

    for label, path in (("staging", staging), ("capture", capture)):
        if not path.exists():
            findings.append(Finding(f"{label}_missing", f"{label} file not found: {path}"))
    if findings:
        return Verdict(GATE, FAIL, inputs, {"rows": 0, "checked": 0, "failed": 1}, findings), EXIT_FAIL

    parsed = parse_staging(staging)
    cap = parse_capture(capture)

    # A capture with no BEGIN/END markers at all cannot be split into pages, so
    # per-page grounding is not merely failing — it is impossible. Falling
    # through would emit one `url_not_in_capture` per row: on a real batch that
    # was 181 findings saying "this quote is not on its page" when the truth was
    # "this file records no pages". Loud, specific, and completely wrong.
    #
    # Reported once, as a structural gap in Bronze. NOT degraded to
    # whole-capture matching: §G3 scopes to the row's own page precisely so a
    # quote lifted from a different page cannot pass, and the
    # bad_quote_from_wrong_page fixture exists to keep that honest.
    rows_present = len([r for r in parsed.rows if r.obj is not None])
    if not cap.blocks and capture.stat().st_size > 0:
        findings.append(
            Finding(
                "capture_has_no_page_blocks",
                f"capture contains no =====BEGIN <url>===== markers, so it cannot "
                f"be split into pages and no row can be grounded to the page it "
                f"cites; {rows_present} row(s) are unassessable, not ungrounded",
                where=str(capture),
            )
        )
        return (
            Verdict(
                GATE,
                FAIL,
                inputs,
                {"rows": rows_present, "checked": 0, "grounded": 0,
                 "unassessable": rows_present, "capture_blocks": 0, "failed": 1},
                findings,
            ),
            EXIT_FAIL,
        )

    # Normalise every block once.
    norm_blocks = {url: normalise_for_match(text) for url, text in cap.blocks.items()}
    whole_capture_norm = normalise_for_match("\n".join(cap.blocks.values()))

    checked = 0
    grounded = 0
    for rp in parsed.rows:
        if rp.obj is None:
            # G2 owns unparseable rows. G3 reports what it could not check
            # rather than silently skipping it.
            findings.append(
                Finding(
                    "row_unparseable_not_checked",
                    "row could not be parsed, so grounding was not verified",
                    f"{staging.name}:{rp.line_no}",
                )
            )
            continue

        where = f"{staging.name}:{rp.line_no}"
        row_id = rp.obj.get("id", "<no id>")
        url = rp.obj.get("source_url")
        quote = rp.obj.get("source_quote")
        checked += 1

        if not url:
            findings.append(Finding("no_source_url", f"row {row_id} has no source_url", where))
            continue
        if not quote:
            findings.append(Finding("no_source_quote", f"row {row_id} has no source_quote", where))
            continue

        # Rule 1 · the cited page must be in the capture.
        if url not in norm_blocks:
            findings.append(
                Finding(
                    "url_not_in_capture",
                    f"row {row_id} cites {url} but the capture has no BEGIN marker for it",
                    where,
                )
            )
            continue

        # Rule 2 · the quote must be in that row's own page block.
        nq = normalise_for_match(quote)
        if nq and nq in norm_blocks[url]:
            grounded += 1
            continue

        if nq and nq in whole_capture_norm:
            findings.append(
                Finding(
                    "quote_from_wrong_page",
                    f"row {row_id}: quote is present in the capture but NOT on the page "
                    f"it cites ({url}); the citation does not support the quote",
                    where,
                )
            )
        else:
            findings.append(
                Finding(
                    "quote_not_in_capture",
                    f"row {row_id}: quote does not appear on {url}; "
                    "a paraphrase presented as a quote is invention",
                    where,
                )
            )

    if checked == 0:
        findings.append(
            Finding(
                "nothing_checked",
                "no rows were checked; an empty check is not a pass",
            )
        )

    counts = {
        "rows": len(parsed.rows),
        "checked": checked,
        "grounded": grounded,
        "failed": len(findings),
    }
    verdict = PASS if not findings else FAIL
    return Verdict(GATE, verdict, inputs, counts, findings), (
        EXIT_PASS if verdict == PASS else EXIT_FAIL
    )
