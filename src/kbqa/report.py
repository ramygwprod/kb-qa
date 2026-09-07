"""Remediation report — the checker's output to the maker.

A verdict says a batch failed. It does not say what to do about it, and the
difference matters: spec §5 routes a failed gate back to the **planner**, never
to the executor, because "try again" is the retry loop and the retry loop is
where gaming begins.

So this report separates findings into two kinds, and the split is the whole
point:

  structural — cannot be fixed by editing rows. A missing capture is not a
               defect in the staging file; it is an absent Bronze artifact.
               Editing rows to make the gate pass would be fabrication.

  fixable    — the rows disagree with the contract or with their own evidence,
               and correcting them is legitimate work.

A maker agent handed only "G3 FAILED, 14 rows" will edit 14 quotes until the
gate goes green. That is the failure this whole package exists to prevent, so
the report never says what failed without saying what may legitimately change.
"""

from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

from . import __version__
from .gates import g1_capture, g2_conformance, g3_grounding, g4_completeness
from .manifest import MANIFEST_SHA256
from .verdict import Verdict, utc_now_iso, write_verdict

STRUCTURAL = "structural"
FIXABLE = "fixable"
PLANNER = "planner"


class Remedy(NamedTuple):
    kind: str
    text: str


REMEDIES: Dict[str, Remedy] = {
    "capture_missing": Remedy(
        STRUCTURAL,
        "No capture exists for this batch. The rows cannot be grounded — not by "
        "this tool and not by a reader. Either re-collect the batch with a "
        "fetcher that writes `_capture-<batch>.raw.txt`, or record the batch as "
        "unverifiable. Do NOT edit rows to make this pass; there is nothing to "
        "check them against.",
    ),
    "capture_empty": Remedy(
        STRUCTURAL,
        "The capture exists but holds no text. Re-fetch and write a new dated "
        "file. Bronze is never edited in place.",
    ),
    "bronze_missing": Remedy(
        STRUCTURAL,
        "A Bronze artifact is absent. Bronze is not reconstructable by editing; "
        "re-fetch and write a new dated file.",
    ),
    "marker_unbalanced": Remedy(
        STRUCTURAL,
        "The capture's BEGIN/END markers are unbalanced, so page blocks cannot "
        "be delimited. The capture is corrupt: re-fetch. Do not hand-repair it.",
    ),
    "duplicate_page_block": Remedy(
        STRUCTURAL,
        "The same URL is captured more than once. Re-fetch the batch cleanly "
        "rather than deleting one block by hand.",
    ),
    "staging_missing": Remedy(
        STRUCTURAL,
        "No staging file exists for this batch. Either the batch name is wrong "
        "or the row-writer never ran. Check the name against the vendor "
        "directory before concluding the rows are missing.",
    ),
    "denominator_missing": Remedy(
        STRUCTURAL,
        "No denominator file, so coverage cannot be measured against anything. "
        "Capture the vendor's own index surface first — a denominator invented "
        "from our expectations measures our plan, not their product.",
    ),
    "rows_file_missing": Remedy(
        STRUCTURAL,
        "A rows file named on the command line does not exist. This is a "
        "run-configuration fault, not a data fault: correct the path and re-run "
        "before reading anything into the result.",
    ),
    "stops_file_missing": Remedy(
        STRUCTURAL,
        "The stop-conditions file named does not exist. Either the path is "
        "wrong or no stop-conditions were recorded for this vendor; the two are "
        "not the same and should not be conflated.",
    ),
    "root_missing": Remedy(
        STRUCTURAL,
        "The project root given does not exist, so nothing was inspected. "
        "Correct the path — an integrity check that examined no files is not a "
        "clean integrity check.",
    ),
    "robots_unreachable": Remedy(
        STRUCTURAL,
        "robots.txt could not be fetched. This is not permission to proceed. "
        "Retry later; if it stays unreachable, treat the vendor as closed.",
    ),
    "verdict_unreadable": Remedy(
        STRUCTURAL,
        "A recorded verdict cannot be parsed, so its claim about the batch is "
        "unavailable. Re-run the gate that produced it rather than assuming the "
        "batch was previously green.",
    ),

    "capture_hash_absent": Remedy(
        FIXABLE,
        "Staging frontmatter has no `source_capture_sha256`. Add it, computed "
        "from the capture this batch was written from.",
    ),
    "frontmatter_unparseable": Remedy(
        FIXABLE,
        "The staging frontmatter cannot be read, so the batch's own claims "
        "about its provenance are unavailable. Correct it to `key: value` lines "
        "with list items as `  - item`.",
    ),
    "pages_not_a_list": Remedy(
        FIXABLE,
        "`pages:` must be a list of the URLs this batch declares, one per line "
        "as `  - <url>`. Without it G1 cannot check that what was cited is what "
        "was fetched.",
    ),
    "row_unparseable": Remedy(
        FIXABLE,
        "The row is not valid JSON, so it was never checked by the other gates. "
        "Correct the serialisation — an unparseable row is not a passing row.",
    ),
    "schema_violation": Remedy(
        FIXABLE,
        "The row disagrees with the contract. Correct the row — or, if the "
        "contract is wrong, change `models.py` deliberately with a version bump "
        "and a note in `_DECISIONS-OPEN.md`. Never mid-run.",
    ),
    "no_source_url": Remedy(
        FIXABLE,
        "Every row cites the page it came from. Add `source_url`, pointing at "
        "the page whose captured text contains the quote — not at a plausible "
        "page that happens to be about the same feature.",
    ),
    "no_source_quote": Remedy(
        FIXABLE,
        "Every row carries a verbatim quote. If the page does not say it, the "
        "row is not supported and should be dropped, not paraphrased.",
    ),
    "proof_unparseable": Remedy(
        FIXABLE,
        "The GOLD file's `proof:` line cannot be read, so its row count cannot "
        "be checked against its content. Restore it to a form that states the "
        "count plainly.",
    ),
    "stop_condition_without_reason": Remedy(
        FIXABLE,
        "Every stop-condition states why. \"We stopped\" is not a reason.",
    ),

    # --- grounding: where gaming is most likely, so the remedies are explicit
    "quote_not_in_capture": Remedy(
        FIXABLE,
        "The quote does not appear in the page it cites. Legitimate fixes: "
        "replace the quote with text the page actually contains, or drop the "
        "row. Illegitimate: editing the quote until it matches something, "
        "anything, elsewhere in the capture. If the page does not support the "
        "claim, the claim is not supported — a paraphrase presented as a quote "
        "is the exact defect this gate exists to catch.",
    ),
    "quote_from_wrong_page": Remedy(
        FIXABLE,
        "The quote exists in the capture but in a different page's block. The "
        "row is misattributed: correct `source_url` to the page the text is "
        "actually on. Do not leave the citation pointing at a page that does "
        "not contain the quote.",
    ),
    "url_not_in_capture": Remedy(
        PLANNER,
        "The row cites a URL with no block in the capture. Either the page was "
        "never fetched — add it to the fetch list and re-run the fetcher — or "
        "the URL is invented.",
    ),

    # --- role separation and provenance: not repairable by editing rows
    "role_collapse": Remedy(
        STRUCTURAL,
        "The staging file attests `fetched_by_this_agent: true` — one agent both "
        "fetched and wrote rows. Attestation is not the problem; the collapse "
        "is. Re-collect with a fetcher and a row-writer that has no `WebFetch`. "
        "Clearing the flag hides the collapse instead of fixing it.",
    ),
    "capture_hash_mismatch": Remedy(
        STRUCTURAL,
        "The staging file's `source_capture_sha256` does not match the capture "
        "on disk. The rows were written from different bytes than the ones "
        "present. Re-run the row-writer against this capture; do not simply "
        "update the hash to match.",
    ),
    "capture_not_before_staging": Remedy(
        STRUCTURAL,
        "The capture is newer than the staging file, so the rows cannot have "
        "been written from it. Re-run the row-writer against the current "
        "capture. Touching timestamps changes the evidence, not the fact.",
    ),
    "bronze_modified": Remedy(
        STRUCTURAL,
        "A Bronze artifact changed after it was written. Bronze is never edited "
        "— not for a typo, not for whitespace. Re-fetch into a new dated file "
        "and leave the original alone.",
    ),
    "bronze_touched_after_verdict": Remedy(
        STRUCTURAL,
        "A Bronze file was modified after a verdict was recorded against it. "
        "Every verdict citing it is now void. Re-fetch, then re-run the gates.",
    ),
    "manifest_mismatch": Remedy(
        STRUCTURAL,
        "The recorded verdicts were produced by different gate code than is now "
        "installed. This is the tamper-evidence signal firing. Establish which "
        "version is approved, then re-run the gates from it. Do not reconcile "
        "by editing the recorded manifest.",
    ),
    "site_wide_disallow": Remedy(
        STRUCTURAL,
        "robots.txt disallows our agent site-wide. This is terminal for the "
        "vendor: no retry, no alternate fetcher, no different user-agent. "
        "Record the stop reason and close the vendor.",
    ),

    # --- the checks that report on the checking itself
    "zero_rows": Remedy(
        STRUCTURAL,
        "No rows were parsed. A parser that sees nothing and a file that holds "
        "nothing look identical, so this is treated as a defect rather than an "
        "empty pass. Confirm the file has rows and that `parsing.py` reads this "
        "serialisation before concluding anything about the data.",
    ),
    "parser_disagrees_with_naive_count": Remedy(
        STRUCTURAL,
        "The structured parse and the naive count disagree, so one of them is "
        "wrong and the gate cannot say which. This is a tooling fault, not a "
        "data fault — do not edit rows to reconcile it. Fix `parsing.py`.",
    ),
    "row_unparseable_not_checked": Remedy(
        STRUCTURAL,
        "Rows failed to parse and were therefore never checked. Their absence "
        "from the findings is not evidence they are sound.",
    ),
    "nothing_checked": Remedy(
        STRUCTURAL,
        "The gate ran but examined nothing. An empty check is not a pass — "
        "treat this as a failure of the run, not a clean result.",
    ),

    # --- contract and completeness
    "duplicate_id": Remedy(
        FIXABLE,
        "Two rows share an `id`. An id identifies one node in the tree, so a "
        "duplicate means either two nodes were given the same name or one node "
        "was recorded twice. Establish which before renaming: silently "
        "suffixing the second one preserves a duplicate rather than resolving it.",
    ),
    "no_declared_pages": Remedy(
        FIXABLE,
        "The staging frontmatter declares no pages, so G1 cannot check that "
        "what was cited was what was fetched. Add the `pages:` list.",
    ),
    "empty_denominator": Remedy(
        STRUCTURAL,
        "The denominator holds no index items, so coverage is unmeasurable. "
        "Re-capture the index surface.",
    ),
    "proof_count_mismatch": Remedy(
        FIXABLE,
        "The GOLD file's `proof:` count disagrees with its own content. Correct "
        "the count to match the rows actually present.",
    ),
    "term_at_multiple_urls": Remedy(
        PLANNER,
        "Advisory only. The same term appears at several URLs, which is an R2 "
        "question about naming, not a defect. Do not resolve it by guessing a "
        "relationship — a `usecase_of` inferred from string similarity is "
        "indistinguishable later from a sourced one.",
    ),

    "page_not_in_capture": Remedy(
        PLANNER,
        "The row cites a page that is not in the capture. Either the page was "
        "never fetched — add it to the fetch list and re-run the fetcher — or "
        "the citation does not correspond to anything fetched, in which case "
        "the row is unsupported. Changing the quote to match a different page "
        "is not a fix.",
    ),
    "index_item_without_row": Remedy(
        PLANNER,
        "An index item has no row citing it. Plan a batch covering it, or "
        "record a stop-condition with a stated reason. Do not lower the "
        "denominator to close the gap.",
    ),
}

DEFAULT_REMEDY = Remedy(FIXABLE, "See the finding message.")

KIND_HEADING = {
    STRUCTURAL: "Structural — must NOT be fixed by editing rows",
    PLANNER: "For the planner — scope or fetch-list changes",
    FIXABLE: "Fixable — correct and re-run",
}

KIND_ORDER = (STRUCTURAL, PLANNER, FIXABLE)


def _run(mod, argv: List[str]) -> Tuple[Verdict, int]:
    result = mod.run(argv)
    return result[0], result[1]


def build(
    vendor_dir: Path,
    batch: str,
    vendor: Optional[str] = None,
    denominator: Optional[Path] = None,
    stops: Optional[Path] = None,
) -> Tuple[str, List[Tuple[Verdict, int]], int]:
    """Run the batch gates and render a report. Returns (markdown, results, code)."""
    staging = vendor_dir / f"_collect-{batch}-staging.md"
    capture = vendor_dir / f"_capture-{batch}.raw.txt"

    results: List[Tuple[Verdict, int]] = [
        _run(g1_capture, ["--staging", str(staging), "--capture", str(capture)]),
        _run(g2_conformance, ["--staging", str(staging)]),
        _run(g3_grounding, ["--staging", str(staging), "--capture", str(capture)]),
    ]
    if denominator is not None:
        argv = ["--denominator", str(denominator), "--rows", str(staging)]
        if stops is not None:
            argv += ["--stops", str(stops)]
        results.append(_run(g4_completeness, argv))

    worst = max(code for _, code in results)

    grouped: Dict[str, List[Tuple[str, object]]] = {k: [] for k in KIND_ORDER}
    for verdict, _ in results:
        for f in verdict.findings:
            remedy = REMEDIES.get(f.code, DEFAULT_REMEDY)
            grouped[remedy.kind].append((verdict.gate, f))

    blocked = any(v.verdict == "FAIL" for v, _ in results)
    lines: List[str] = []
    a = lines.append

    a(f"# QA report — {vendor or vendor_dir.name} / {batch}")
    a("")
    a(f"**{'BLOCKED' if blocked else 'CLEAR'}**")
    a("")
    a(f"- generated: `{utc_now_iso()}`")
    a(f"- kbqa: `{__version__}`  ·  manifest: `{MANIFEST_SHA256[:16]}…`")
    a("")
    a("Route to the **planner**. A failed gate never returns to the executor as "
      "\"try again\" — that is the retry loop, and it is where gaming begins. (§5)")
    a("")

    a("## Gates")
    a("")
    a("| gate | verdict | rows | failed |")
    a("|---|---|---|---|")
    for verdict, _ in results:
        c = verdict.counts
        a(
            f"| `{verdict.gate}` | **{verdict.verdict}** | "
            f"{c.get('rows', '–')} | {c.get('failed', '–')} |"
        )
    a("")

    total = sum(len(v) for v in grouped.values())
    if total == 0:
        a("No findings. Every gate that ran is green.")
        a("")
        if blocked:
            a("⚠ A gate reported FAIL with no findings — that is a bug in the gate, "
              "not a clean batch. Do not treat this as a pass.")
            a("")
    else:
        a(f"## What to do — {total} finding(s)")
        a("")
        for kind in KIND_ORDER:
            items = grouped[kind]
            if not items:
                continue
            a(f"### {KIND_HEADING[kind]}")
            a("")
            by_code: Dict[str, List[Tuple[str, object]]] = {}
            for gate, f in items:
                by_code.setdefault(f.code, []).append((gate, f))
            for code, entries in sorted(by_code.items()):
                remedy = REMEDIES.get(code, DEFAULT_REMEDY)
                a(f"**`{code}`** — {len(entries)} occurrence(s)")
                a("")
                a(f"> {remedy.text}")
                a("")
                for gate, f in entries[:25]:
                    where = f" — `{f.where}`" if f.where else ""
                    a(f"- [{gate}]{where} {f.message}")
                if len(entries) > 25:
                    a(f"- … and {len(entries) - 25} more (see the verdict JSON)")
                a("")

    a("## Provenance")
    a("")
    a("Each gate's full verdict is in `_qa/` and carries the `manifest_sha256` of "
      "the code that produced it. A verdict from edited gates is distinguishable "
      "from a verdict from approved gates; that is what makes this report "
      "tamper-evident rather than merely tidy.")
    a("")

    return "\n".join(lines) + "\n", results, worst


def run(argv: List[str]) -> int:
    vendor_dir = batch = vendor = out = None
    denominator = stops = None
    log = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        nxt = argv[i + 1] if i + 1 < len(argv) else None
        if arg == "--vendor-dir" and nxt:
            vendor_dir = Path(nxt); i += 2; continue
        if arg == "--batch" and nxt:
            batch = nxt; i += 2; continue
        if arg == "--vendor" and nxt:
            vendor = nxt; i += 2; continue
        if arg == "--denominator" and nxt:
            denominator = Path(nxt); i += 2; continue
        if arg == "--stops" and nxt:
            stops = Path(nxt); i += 2; continue
        if arg == "--log" and nxt:
            log = Path(nxt); i += 2; continue
        if arg == "--out" and nxt:
            out = Path(nxt); i += 2; continue
        print(f"report: unexpected argument {arg!r}")
        return 1

    if not vendor_dir or not batch:
        print("report: need --vendor-dir <dir> --batch <name>")
        return 1
    if not vendor_dir.is_dir():
        print(f"report: not a directory: {vendor_dir}")
        return 1

    markdown, results, code = build(vendor_dir, batch, vendor, denominator, stops)

    for verdict, _ in results:
        write_verdict(verdict, vendor_dir, batch, log, vendor)

    target = out or (vendor_dir / "_qa" / f"{batch}.report.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown, encoding="utf-8")
    print(f"report written: {target}")
    for verdict, _ in results:
        print(f"  {verdict.gate:<16} {verdict.verdict}")
    return code
