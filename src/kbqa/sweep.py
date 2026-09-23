"""Estate audit — sort what already exists by whether it can be checked at all.

Most of the estate was collected before captures were kept. Those rows cannot
be grounded: not by this tool, not by a reader, not ever, because the page text
they quote was never stored. Re-fetching does not help — it returns today's
page, not the page the claim came from.

That is not a defect to be fixed. It is a property of the data, and the useful
response is to record it rather than keep rediscovering it. A tree whose quotes
can be verified and a tree whose quotes cannot are different kinds of evidence,
and today nothing in the estate says which is which.

So this sweep answers one question per batch:

    can a reader check this against the vendor's own words?

and reports the estate split by the answer. Conformance (G2) runs everywhere,
since it needs no capture. Grounding (G3) runs only where it can mean something.

⛔ This makes no claim that verifiable rows are correct — only that they are
checkable. Checking them is G3's job, and it is reported separately.
"""

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import __version__
from .gates import g2_conformance, g3_grounding
from .manifest import MANIFEST_SHA256
from .profile import row_model
from .parsing import parse_staging
from .verdict import PASS, utc_now_iso

STAGING_GLOB = "**/_collect-*-staging.md"

VERIFIABLE = "verifiable"
UNASSESSABLE = "unassessable-no-page-markers"
UNVERIFIABLE = "unverifiable-no-capture"
NOT_A_BATCH = "not-a-batch"

# The frontmatter keys that make a file a collection batch. Names are a
# convention; provenance is evidence.
BATCH_FM_KEYS = frozenset(
    {"batch", "source_capture", "source_capture_sha256", "pages", "fetched_by_this_agent"}
)

TIER_MEANING = {
    VERIFIABLE: "capture exists and splits into pages — every quote can be checked",
    UNASSESSABLE: "capture exists but records no page boundaries — grounding is "
                  "impossible, though nothing is shown wrong",
    UNVERIFIABLE: "no capture — the page text was never stored",
}


def batch_name(staging: Path) -> str:
    return staging.name[len("_collect-"):-len("-staging.md")]


def vendor_of(staging: Path, root: Optional[Path], depth: int = 2) -> str:
    """Name the vendor from position under the estate root, not the parent dir.

    Estates nest: `<root>/<container>/<Vendor>/` and sometimes
    `<root>/<container>/<Vendor>/<subfolder>/`. Using the immediate parent
    labelled a folder called `_to_delete` as a vendor and counted it in the
    totals as live data.

    `depth` is which component under root names the vendor (1-based), so the
    default of 2 reads `<container>/<Vendor>`. Falls back to the parent
    directory when the path is shallower than that.
    """
    if root is not None:
        try:
            parts = staging.relative_to(root).parts[:-1]  # drop the filename
        except ValueError:
            parts = ()
        if len(parts) >= depth:
            return parts[depth - 1]
        if parts:
            return parts[-1]
    return staging.parent.name


def audit_batch(staging: Path, root: Optional[Path] = None, depth: int = 2) -> dict:
    """Classify one batch. Never raises: a batch that cannot be read is a result."""
    batch = batch_name(staging)
    capture = staging.parent / f"_capture-{batch}.raw.txt"
    rec = {
        "vendor": vendor_of(staging, root, depth),
        "path": str(staging.relative_to(root)) if root else str(staging),
        "batch": batch,
        "staging": str(staging),
        "capture": str(capture) if capture.exists() else None,
        # Three states, not two. A capture that exists but has no page markers
        # cannot ground anything — but that is not the same as having no capture,
        # and neither is the same as being wrong. Collapsing them would report
        # rows as unverifiable when the text is right there, unsplittable.
        "tier": VERIFIABLE if capture.exists() else UNVERIFIABLE,
        "capture_blocks": None,
        "rows": 0,
        "rows_unparseable": 0,
        "row_format": "unknown",
        "conformant": None,
        "schema_violations": 0,
        "grounded": None,
        "ungrounded_rows": None,
        "unassessable_rows": None,
        "error": None,
    }

    try:
        parsed = parse_staging(staging)
    except Exception as exc:  # noqa: BLE001 — an unreadable batch is a finding
        rec["error"] = f"{type(exc).__name__}: {exc}"
        return rec

    # A document is not a batch merely because its name matched. Provenance or
    # rows make it one; neither makes it a document that happened to be called
    # a staging file. Counting those as batches inflates every estate total and
    # produces gate failures about files nobody ever collected into.
    declares = BATCH_FM_KEYS & set(parsed.frontmatter_raw or {})
    has_rows = bool(parsed.rows) or parsed.naive_count > 0
    if not declares and not has_rows:
        rec["tier"] = NOT_A_BATCH
        rec["row_format"] = parsed.row_format
        return rec

    rec["row_format"] = parsed.row_format
    rec["rows"] = len([r for r in parsed.rows if r.obj is not None])
    rec["rows_unparseable"] = len([r for r in parsed.rows if r.obj is None])

    # Conformance needs no capture, so it runs on every batch in the estate.
    bad = 0
    for r in parsed.rows:
        if r.obj is None:
            continue
        try:
            row_model()(**r.obj)
        except Exception:  # noqa: BLE001 — pydantic raises many shapes
            bad += 1
    rec["schema_violations"] = bad
    rec["conformant"] = bad == 0 and rec["rows"] > 0 and rec["rows_unparseable"] == 0

    # Grounding only where there is something to ground against. Reporting a
    # grounding result for a batch with no capture would be a claim about
    # evidence that does not exist.
    if capture.exists():
        try:
            from .parsing import parse_capture

            blocks = len(parse_capture(capture).blocks)
            rec["capture_blocks"] = blocks
            if blocks == 0:
                rec["tier"] = UNASSESSABLE
                rec["unassessable_rows"] = rec["rows"]
                rec["ungrounded_rows"] = 0
            else:
                v, _ = g3_grounding.run(
                    ["--staging", str(staging), "--capture", str(capture)]
                )
                rec["grounded"] = v.verdict == PASS
                rec["unassessable_rows"] = v.counts.get("unassessable", 0)
                rec["ungrounded_rows"] = v.counts.get("failed")
        except Exception as exc:  # noqa: BLE001
            rec["error"] = f"g3: {type(exc).__name__}: {exc}"

    return rec


def field_distribution(stagings: List[Path], cap: int = 40) -> Dict[str, dict]:
    """Observed value sets per field — evidence for constraining schema v3.

    Records how many DISTINCT values a field takes, and lists them only when
    the set is small enough to be an enumeration rather than free text. A field
    holding one value across the estate is an unexercised default, which is a
    question for the collector rather than a validation failure.
    """
    values: Dict[str, Counter] = defaultdict(Counter)
    seen: Counter = Counter()
    long_valued: Counter = Counter()

    for stg in stagings:
        try:
            parsed = parse_staging(stg)
        except Exception:  # noqa: BLE001
            continue
        for r in parsed.rows:
            if r.obj is None:
                continue
            for k, v in r.obj.items():
                # EVERY field is counted, whatever its values look like.
                #
                # An earlier version only recorded values of 40 characters or
                # fewer — and since a field was only listed if it had recorded
                # values, any field whose values are all long was invisible.
                # The registry built from that output was missing nine fields,
                # which then failed rows the sweep had reported as fine. A
                # diagnostic that omits what it cannot summarise is worse than
                # one that says "present, too long to show".
                seen[k] += 1
                if isinstance(v, (str, int, bool)):
                    s = str(v)
                    if len(s) <= 40:
                        values[k][s] += 1
                    else:
                        long_valued[k] += 1
                else:
                    long_valued[k] += 1

    out: Dict[str, dict] = {}
    for field in sorted(seen):
        counter = values.get(field, Counter())
        entry = {
            "rows": seen[field],
            "distinct": len(counter),
            "in_contract": field in row_model().model_fields,
        }
        if long_valued[field]:
            entry["values_too_long_to_summarise"] = long_valued[field]
        if counter and len(counter) <= cap:
            entry["values"] = dict(counter.most_common())
        out[field] = entry
    return out


def build(
    root: Path,
    with_fields: bool = False,
    exclude: Optional[List[str]] = None,
    depth: int = 2,
) -> Tuple[str, dict]:
    import fnmatch

    exclude = exclude or []
    all_stagings = sorted(root.glob(STAGING_GLOB))

    # Excluded paths are counted and named, never silently dropped. A batch that
    # vanishes from a total without explanation is indistinguishable from one
    # that was never there.
    stagings, excluded = [], []
    for s in all_stagings:
        rel = str(s.relative_to(root))
        if any(fnmatch.fnmatch(rel, pat) for pat in exclude):
            excluded.append(rel)
        else:
            stagings.append(s)

    scanned = [audit_batch(s, root, depth) for s in stagings]

    # Gold with no Silver beneath it.
    #
    # The tiers above describe BATCHES. A subject whose rows live only in a
    # merged tree has no batch, so it appears in no tier — and an audit that
    # reports 15% verifiable while silently omitting the subjects it never
    # looked at is the failure this package exists to name. Counted separately
    # because it is a different question, and reported because the alternative
    # is silence that reads as coverage.
    trees = [
        g for g in sorted(root.glob("**/feature-tree*.md"))
        if not any(fnmatch.fnmatch(str(g.relative_to(root)), pat) for pat in exclude)
    ]
    tree_subjects: Dict[str, int] = {}
    for g in trees:
        subj = vendor_of(g, root, depth)
        rows_in_tree = 0
        try:
            rows_in_tree = len([r for r in parse_staging(g).rows if r.obj is not None])
        except Exception:  # noqa: BLE001 — an unreadable tree is still a tree
            pass
        tree_subjects[subj] = tree_subjects.get(subj, 0) + rows_in_tree

    # Named and counted, never silently dropped — the same rule as --exclude.
    not_batches = [b for b in scanned if b["tier"] == NOT_A_BATCH]
    batches = [b for b in scanned if b["tier"] != NOT_A_BATCH]

    by_vendor: Dict[str, List[dict]] = defaultdict(list)
    for b in batches:
        by_vendor[b["vendor"]].append(b)

    batch_subjects = {b["vendor"] for b in batches}
    ungrounded_subjects = {
        s: n for s, n in sorted(tree_subjects.items()) if s not in batch_subjects
    }

    verifiable = [b for b in batches if b["tier"] == VERIFIABLE]
    unassessable = [b for b in batches if b["tier"] == UNASSESSABLE]
    unverifiable = [b for b in batches if b["tier"] == UNVERIFIABLE]
    # Rows nothing could parse are in no tier and in no total — `rec["rows"]`
    # counts only what came back as an object. Reported in the body but never in
    # the summary, so 962 of them sat inside figures that looked accounted for.
    unreadable = [b for b in batches if b["rows_unparseable"]]
    rows_unreadable = sum(b["rows_unparseable"] for b in unreadable)

    rows_v = sum(b["rows"] for b in verifiable)
    rows_x = sum(b["rows"] for b in unassessable)
    rows_u = sum(b["rows"] for b in unverifiable)
    total_rows = rows_v + rows_x + rows_u

    lines: List[str] = []
    a = lines.append

    a("# Estate audit")
    a("")
    a("| | |")
    a("|---|---|")
    a(f"| generated | `{utc_now_iso()}` |")
    a(f"| kbqa | `{__version__}` |")
    a(f"| manifest | `{MANIFEST_SHA256}` |")
    a(f"| root | `{root}` |")
    a("")

    a("## The split that matters")
    a("")
    a("| tier | batches | rows | what a reader can do |")
    a("|---|---|---|---|")
    a(f"| **{VERIFIABLE}** | {len(verifiable)} | {rows_v} | check every quote against the page it cites |")
    a(f"| **{UNASSESSABLE}** | {len(unassessable)} | {rows_x} | nothing yet — the text is stored but not split into pages |")
    a(f"| **{UNVERIFIABLE}** | {len(unverifiable)} | {rows_u} | nothing — the page text was never kept |")
    a("")
    pct = (rows_v * 100 // total_rows) if total_rows else 0
    a(f"**{pct}% of rows rest on evidence that can be checked.**")
    a("")
    a("None of these tiers says a row is wrong. They say what a reader is able "
      "to do about it, and the three are not the same thing:")
    a("")
    a(f"- **{UNASSESSABLE}** is recoverable. The captured text exists; it simply "
      "records no page boundaries, so a quote cannot be tied to the page it "
      "cites. Re-fetching with a fetcher that writes per-page markers moves "
      "these into the verifiable tier without re-collecting the rows.")
    a(f"- **{UNVERIFIABLE}** is not. The page text was never written, and "
      "re-fetching returns today's page rather than the page the claim came "
      "from. This is a property of how the batch was collected.")
    a("")

    a("## By vendor")
    a("")
    a("| vendor | batches | verifiable | rows | conformant | schema violations |")
    a("|---|---|---|---|---|---|")
    for vendor in sorted(by_vendor):
        bs = by_vendor[vendor]
        v = len([b for b in bs if b["tier"] == VERIFIABLE])
        conf = len([b for b in bs if b["conformant"]])
        viol = sum(b["schema_violations"] for b in bs)
        a(f"| {vendor} | {len(bs)} | {v} | {sum(b['rows'] for b in bs)} | "
          f"{conf}/{len(bs)} | {viol} |")
    a("")

    if ungrounded_subjects:
        a("## Subjects with a tree and no batch behind it")
        a("")
        a(f"{len(ungrounded_subjects)} subject(s) hold "
          f"{sum(ungrounded_subjects.values())} row(s) in a merged tree with **no "
          "staging file anywhere**, so they appear in none of the tiers above.")
        a("")
        a("This is not the same as unverifiable. An unverifiable batch has a "
          "staging file citing pages — a trail something could re-fetch against. "
          "Rows that exist only in a tree never passed through a capture at all, "
          "and the percentages above are computed without them.")
        a("")
        a("| subject | rows in tree |")
        a("|---|---|")
        for s, n in sorted(ungrounded_subjects.items(), key=lambda kv: -kv[1])[:40]:
            a(f"| `{s}` | {n} |")
        if len(ungrounded_subjects) > 40:
            a(f"| … and {len(ungrounded_subjects) - 40} more | |")
        a("")

    if not_batches:
        a("## Matched the name, but are not batches")
        a("")
        a(f"{len(not_batches)} file(s) match the staging filename pattern while "
          "declaring no batch frontmatter and holding no rows. They are **not** in "
          "any figure above.")
        a("")
        a("A filename is a convention; provenance is evidence. Counting these as "
          "batches inflates every total and produces gate failures about files "
          "nobody collected into.")
        a("")
        for b in not_batches[:20]:
            a(f"- `{b['path']}`")
        if len(not_batches) > 20:
            a(f"- … and {len(not_batches) - 20} more")
        a("")

    if excluded:
        a("## Excluded by pattern")
        a("")
        a(f"{len(excluded)} batch(es) matched `--exclude` and are **not** in any "
          "figure above.")
        a("")
        for rel in excluded[:20]:
            a(f"- `{rel}`")
        if len(excluded) > 20:
            a(f"- … and {len(excluded) - 20} more")
        a("")

    checked = [b for b in verifiable if b["grounded"] is not None]
    if checked:
        ok = [b for b in checked if b["grounded"]]
        a("## Grounding — only where a capture exists")
        a("")
        a(f"{len(ok)} of {len(checked)} verifiable batches pass G3.")
        a("")
        bad = [b for b in checked if not b["grounded"]]
        if bad:
            a("| vendor | batch | ungrounded rows |")
            a("|---|---|---|")
            for b in bad[:30]:
                a(f"| {b['vendor']} | {b['batch']} | {b['ungrounded_rows']} |")
            a("")
            a("Run `kbqa report --vendor-dir <dir> --batch <name>` for the "
              "remediation plan on any of these.")
            a("")

    problems = [b for b in batches if b["error"] or b["rows_unparseable"]]
    if problems:
        a("## Batches that could not be read")
        a("")
        a("| vendor | batch | rows unparseable | error |")
        a("|---|---|---|---|")
        for b in problems[:30]:
            a(f"| {b['vendor']} | {b['batch']} | {b['rows_unparseable']} | {b['error'] or '–'} |")
        a("")
        a("An unreadable batch is not a passing batch. Its rows were never "
          "checked by anything.")
        a("")

    fields: Dict[str, dict] = {}
    if with_fields:
        fields = field_distribution(stagings)
        a("## Observed fields — evidence for schema v3")
        a("")
        a("| field | in contract | distinct values |")
        a("|---|---|---|")
        for name, info in fields.items():
            mark = "yes" if info["in_contract"] else "**NO**"
            long = info.get("values_too_long_to_summarise", 0)
            note = f" ({long} value(s) too long to summarise)" if long else ""
            a(f"| `{name}` | {mark} | {info['distinct']}{note} |")
        a("")
        a("A field marked NO is emitted by the collector but absent from the "
          "contract: it fails G2 on every row until it is named in `models.py` "
          "by a deliberate version bump, or removed by the collector. A field "
          "with **one** distinct value across the whole estate is an "
          "unexercised default — a question for the collector, not a "
          "validation failure.")
        a("")

    a("## What this audit does not say")
    a("")
    a("- It does not say verifiable rows are correct — only that they are "
      "checkable. G3 checks them, and its result is reported separately above.")
    a("- It does not say unverifiable rows are wrong. It says no one can tell.")
    a("- Conformance here re-validates rows directly against the contract. It "
      "does not write verdicts; run `kbqa report` for a batch you intend to act on.")
    a("")

    machine = {
        "kbqa_version": __version__,
        "manifest_sha256": MANIFEST_SHA256,
        "generated": utc_now_iso(),
        "root": str(root),
        "totals": {
            "vendors": len(by_vendor),
            "batches": len(batches),
            "rows": total_rows,
            "unreadable_batches": len(unreadable),
            "unreadable_rows": rows_unreadable,
            "verifiable_batches": len(verifiable),
            "unassessable_batches": len(unassessable),
            "unverifiable_batches": len(unverifiable),
            "verifiable_rows": rows_v,
            "unassessable_rows": rows_x,
            "unverifiable_rows": rows_u,
            "verifiable_row_pct": pct,
        },
        "batches": batches,
        "excluded": excluded,
        "trees_without_batches": ungrounded_subjects,
        "tree_subjects": len(tree_subjects),
        "not_batches": [b["path"] for b in not_batches],
        "fields": fields,
    }
    return "\n".join(lines) + "\n", machine


def run(argv: List[str]) -> int:
    root: Optional[Path] = None
    out: Optional[Path] = None
    with_fields = False
    exclude: List[str] = []
    depth = 2
    i = 0
    while i < len(argv):
        arg = argv[i]
        nxt = argv[i + 1] if i + 1 < len(argv) else None
        if arg == "--root" and nxt:
            root = Path(nxt); i += 2; continue
        if arg == "--out" and nxt:
            out = Path(nxt); i += 2; continue
        if arg == "--exclude" and nxt:
            exclude.append(nxt); i += 2; continue
        if arg == "--vendor-depth" and nxt:
            try:
                depth = int(nxt)
            except ValueError:
                print(f"sweep: --vendor-depth must be an integer, got {nxt!r}")
                return 1
            i += 2; continue
        if arg == "--field-values":
            with_fields = True; i += 1; continue
        print(f"sweep: unexpected argument {arg!r}")
        return 1

    if root is None:
        print("sweep: need --root <estate>")
        return 1
    if not root.is_dir():
        print(f"sweep: not a directory: {root}")
        return 1

    markdown, machine = build(root, with_fields, exclude, depth)

    target = out or (root / "_qa-estate-audit.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown, encoding="utf-8")
    sidecar = target.with_suffix(".json")
    sidecar.write_text(json.dumps(machine, indent=2, default=str) + "\n", encoding="utf-8")

    t = machine["totals"]
    print(f"estate audit written: {target}")
    print(f"machine-readable:     {sidecar}")
    print(
        f"  vendors={t['vendors']} batches={t['batches']} rows={t['rows']}\n"
        f"  verifiable   ={t['verifiable_batches']:>4} batches / {t['verifiable_rows']:>6} rows "
        f"({t['verifiable_row_pct']}%)\n"
        f"  unassessable ={t['unassessable_batches']:>4} batches / {t['unassessable_rows']:>6} rows "
        f"(capture has no page markers — recoverable by re-fetch)\n"
        f"  unverifiable ={t['unverifiable_batches']:>4} batches / {t['unverifiable_rows']:>6} rows "
        f"(no capture ever)"
    )
    # Printed, not only written. A file matched by the discovery glob that is
    # not a batch is a discovery defect, and an operator who reads the terminal
    # and not the report would otherwise never learn the totals excluded it.
    if machine["totals"].get("unreadable_rows"):
        tt = machine["totals"]
        print(
            f"  UNREADABLE   ={tt['unreadable_batches']:>4} batches / "
            f"{tt['unreadable_rows']:>6} rows could not be parsed at all — "
            "counted in no tier and in no total above"
        )
    if machine.get("trees_without_batches"):
        tw = machine["trees_without_batches"]
        print(
            f"  NO BATCH     ={len(tw):>4} subject(s) / {sum(tw.values()):>6} rows "
            "hold a tree with no staging file anywhere — not counted in any tier "
            "above, named in the report"
        )
    if machine.get("not_batches"):
        n = len(machine["not_batches"])
        print(
            f"  not batches  ={n:>4} file(s) matched the name, declared no batch "
            "frontmatter, held no rows — excluded from every figure above; "
            "named in the report"
        )
    # Auditing is not gating: an estate that is mostly unverifiable is a fact to
    # record, not a run to fail. Exit non-zero only when nothing could be read.
    return 0 if machine["totals"]["batches"] else 1
