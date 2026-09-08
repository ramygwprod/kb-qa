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
from .models import Row
from .parsing import parse_staging
from .verdict import PASS, utc_now_iso

STAGING_GLOB = "**/_collect-*-staging.md"

VERIFIABLE = "verifiable"
UNVERIFIABLE = "unverifiable-no-capture"


def batch_name(staging: Path) -> str:
    return staging.name[len("_collect-"):-len("-staging.md")]


def audit_batch(staging: Path) -> dict:
    """Classify one batch. Never raises: a batch that cannot be read is a result."""
    batch = batch_name(staging)
    capture = staging.parent / f"_capture-{batch}.raw.txt"
    rec = {
        "vendor": staging.parent.name,
        "batch": batch,
        "staging": str(staging),
        "capture": str(capture) if capture.exists() else None,
        "tier": VERIFIABLE if capture.exists() else UNVERIFIABLE,
        "rows": 0,
        "rows_unparseable": 0,
        "row_format": "unknown",
        "conformant": None,
        "schema_violations": 0,
        "grounded": None,
        "ungrounded_rows": None,
        "error": None,
    }

    try:
        parsed = parse_staging(staging)
    except Exception as exc:  # noqa: BLE001 — an unreadable batch is a finding
        rec["error"] = f"{type(exc).__name__}: {exc}"
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
            Row(**r.obj)
        except Exception:  # noqa: BLE001 — pydantic raises many shapes
            bad += 1
    rec["schema_violations"] = bad
    rec["conformant"] = bad == 0 and rec["rows"] > 0 and rec["rows_unparseable"] == 0

    # Grounding only where there is something to ground against. Reporting a
    # grounding result for a batch with no capture would be a claim about
    # evidence that does not exist.
    if capture.exists():
        try:
            v, _ = g3_grounding.run(
                ["--staging", str(staging), "--capture", str(capture)]
            )
            rec["grounded"] = v.verdict == PASS
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
    for stg in stagings:
        try:
            parsed = parse_staging(stg)
        except Exception:  # noqa: BLE001
            continue
        for r in parsed.rows:
            if r.obj is None:
                continue
            for k, v in r.obj.items():
                if isinstance(v, (str, int, bool)) and len(str(v)) <= 40:
                    values[k][str(v)] += 1

    out: Dict[str, dict] = {}
    for field, counter in sorted(values.items()):
        entry = {"distinct": len(counter), "in_contract": field in Row.model_fields}
        if len(counter) <= cap:
            entry["values"] = dict(counter.most_common())
        out[field] = entry
    return out


def build(root: Path, with_fields: bool = False) -> Tuple[str, dict]:
    stagings = sorted(root.glob(STAGING_GLOB))
    batches = [audit_batch(s) for s in stagings]

    by_vendor: Dict[str, List[dict]] = defaultdict(list)
    for b in batches:
        by_vendor[b["vendor"]].append(b)

    verifiable = [b for b in batches if b["tier"] == VERIFIABLE]
    unverifiable = [b for b in batches if b["tier"] == UNVERIFIABLE]
    rows_v = sum(b["rows"] for b in verifiable)
    rows_u = sum(b["rows"] for b in unverifiable)
    total_rows = rows_v + rows_u

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
    a(f"| **{VERIFIABLE}** | {len(verifiable)} | {rows_v} | check every quote against stored page text |")
    a(f"| **{UNVERIFIABLE}** | {len(unverifiable)} | {rows_u} | nothing — the page text was never kept |")
    a("")
    pct = (rows_v * 100 // total_rows) if total_rows else 0
    a(f"**{pct}% of rows rest on evidence that can be checked.**")
    a("")
    a("Unverifiable rows are not known to be wrong. They are known to be "
      "*uncheckable*: the capture they would be checked against was never "
      "written, and re-fetching returns today's page rather than the page the "
      "claim came from. This is a property of how the batch was collected, not "
      "a defect to be repaired.")
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
            a(f"| `{name}` | {mark} | {info['distinct']} |")
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
            "verifiable_batches": len(verifiable),
            "unverifiable_batches": len(unverifiable),
            "verifiable_rows": rows_v,
            "unverifiable_rows": rows_u,
            "verifiable_row_pct": pct,
        },
        "batches": batches,
        "fields": fields,
    }
    return "\n".join(lines) + "\n", machine


def run(argv: List[str]) -> int:
    root: Optional[Path] = None
    out: Optional[Path] = None
    with_fields = False
    i = 0
    while i < len(argv):
        arg = argv[i]
        nxt = argv[i + 1] if i + 1 < len(argv) else None
        if arg == "--root" and nxt:
            root = Path(nxt); i += 2; continue
        if arg == "--out" and nxt:
            out = Path(nxt); i += 2; continue
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

    markdown, machine = build(root, with_fields)

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
        f"  verifiable={t['verifiable_batches']} batches / {t['verifiable_rows']} rows "
        f"({t['verifiable_row_pct']}%)\n"
        f"  unverifiable={t['unverifiable_batches']} batches / {t['unverifiable_rows']} rows"
    )
    # Auditing is not gating: an estate that is mostly unverifiable is a fact to
    # record, not a run to fail. Exit non-zero only when nothing could be read.
    return 0 if machine["totals"]["batches"] else 1
