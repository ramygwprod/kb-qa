"""G1 · Capture integrity — g1 --staging <f> --capture <f>

A missing capture is a FAIL, never a warning. A check that cannot run has
not passed. (spec §G1, §7)
"""

import argparse
from pathlib import Path
from typing import List, Optional, Tuple

from ..manifest import sha256_file
from ..parsing import parse_capture, parse_staging
from ..verdict import FAIL, PASS, Finding, Verdict, input_ref
from . import EXIT_FAIL, EXIT_PASS

GATE = "g1_capture"


def run(argv: Optional[List[str]] = None) -> Tuple[Verdict, int]:
    ap = argparse.ArgumentParser(prog="kbqa g1")
    ap.add_argument("--staging", required=True)
    ap.add_argument("--capture", required=True)
    args = ap.parse_args(argv)

    staging = Path(args.staging)
    capture = Path(args.capture)
    findings: List[Finding] = []

    inputs = {"staging": input_ref(staging), "capture": input_ref(capture)}

    if not staging.exists():
        findings.append(Finding("staging_missing", f"staging file not found: {staging}"))
        v = Verdict(GATE, FAIL, inputs, {"declared_pages": 0, "checked": 0, "failed": 1}, findings)
        return v, EXIT_FAIL

    # 1 · capture exists and is non-empty
    if not capture.exists():
        findings.append(
            Finding("capture_missing", f"capture file not found: {capture}")
        )
        v = Verdict(GATE, FAIL, inputs, {"declared_pages": 0, "checked": 0, "failed": 1}, findings)
        return v, EXIT_FAIL

    if capture.stat().st_size == 0:
        findings.append(Finding("capture_empty", f"capture file is empty: {capture}"))

    parsed = parse_staging(staging)
    if parsed.frontmatter_error:
        findings.append(Finding("frontmatter_unparseable", parsed.frontmatter_error))

    cap = parse_capture(capture)

    # 2 · markers balanced and paired
    for err in cap.marker_errors:
        findings.append(Finding("marker_unbalanced", err))
    for dup in cap.duplicate_urls:
        findings.append(
            Finding("duplicate_page_block", f"URL appears in more than one block: {dup}", where=dup)
        )

    # 3 · every declared page has a marker pair
    #
    # The declaration lives in the frontmatter `pages:` list in some batches and
    # in a markdown table in others; the parser reports whichever it found and
    # names the source. Reading only the frontmatter reported `no_declared_pages`
    # against batches that declare their pages perfectly well in a table — a
    # finding untrue of them, which would send a maker hunting for a list that
    # was never that batch's convention.
    declared = list(parsed.declared_pages)

    fm_pages = parsed.frontmatter_raw.get("pages")
    if fm_pages is not None and not isinstance(fm_pages, list):
        findings.append(
            Finding("pages_not_a_list", "frontmatter 'pages' is not a list of URLs")
        )

    if not declared:
        findings.append(
            Finding(
                "no_declared_pages",
                "the staging file declares no pages — neither a frontmatter "
                "'pages:' list nor a markdown table of page URLs — so what was "
                "cited cannot be checked against what was fetched; treated as a "
                "defect, not a pass",
            )
        )

    missing = [u for u in declared if u not in cap.blocks]
    for url in missing:
        findings.append(
            Finding("page_not_in_capture", f"declared page has no marker pair: {url}", where=url)
        )

    # 4 · frontmatter hash equals the actual capture hash
    declared_hash = parsed.frontmatter_raw.get("source_capture_sha256")
    actual_hash = sha256_file(capture)
    if not declared_hash:
        findings.append(
            Finding("capture_hash_absent", "frontmatter has no source_capture_sha256")
        )
    elif declared_hash != actual_hash:
        findings.append(
            Finding(
                "capture_hash_mismatch",
                f"frontmatter source_capture_sha256={declared_hash} but capture hashes to {actual_hash}",
            )
        )

    # 5 · capture precedes staging
    cap_mtime = capture.stat().st_mtime
    stg_mtime = staging.stat().st_mtime
    if not cap_mtime < stg_mtime:
        findings.append(
            Finding(
                "capture_not_before_staging",
                f"capture mtime ({cap_mtime}) does not precede staging mtime ({stg_mtime}); "
                "rows cannot have been written from this capture",
            )
        )

    counts = {
        "declared_pages": len(declared),
        "pages_source": parsed.pages_source,
        "capture_blocks": len(cap.blocks),
        "checked": len(declared),
        "failed": len(findings),
    }
    verdict = PASS if not findings else FAIL
    v = Verdict(GATE, verdict, inputs, counts, findings)
    return v, (EXIT_PASS if verdict == PASS else EXIT_FAIL)
