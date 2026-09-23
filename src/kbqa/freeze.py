"""Freeze — prove that interpreting the data did not change it.

Mapping a subject's term to a standard category is the one round with no gate
behind it, and it is the round with the most pressure to tidy. Two terms that
nearly match map more cleanly if one of them is edited first. Nothing
downstream can tell that happened: the row still parses, still conforms, and
its quote still matches the capture, because the quote was not what got
adjusted.

So this records a fingerprint of the fields that are the SUBJECT's own words,
before a mapping pass, and compares after. Which fields those are comes from
the active profile (`Profile.verbatim_fields`), not from a constant here — a
domain where nesting is ours rather than the subject's would freeze a different
set.

    kbqa freeze --root <dir> --out _qa/verbatim.freeze.json
    …do the mapping pass…
    kbqa freeze --root <dir> --check _qa/verbatim.freeze.json

THE SNAPSHOT STORES VALUES, NOT ONLY HASHES. A fingerprint answers "did this
change"; it cannot answer "to what". In an estate under version control that is
enough, because the diff is elsewhere. Measured on the estate this was built
for, there is no version control at all — no `.git` anywhere up to the mount
boundary — so a hash-only snapshot would report drift and leave nothing to
restore from, and "revert it" would be advice with no referent.

So the frozen values travel with the fingerprint, and a drift report prints what
the field used to hold. `--fingerprints-only` drops them for an estate that does
have history and would rather keep the file small.

The check is deliberately one-sided about new rows. A row that APPEARED is
reported and does not fail: collection legitimately adds rows, and this command
is also useful mid-collection. A row that CHANGED or DISAPPEARED fails, because
neither is something a mapping pass may do.

Note what this cannot see: it compares a corpus against its own earlier self.
If a term was already wrong when frozen, freezing it certifies nothing except
that nobody touched it since. Grounding is G3's job; this answers a different
question — did we edit the evidence while interpreting it.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import __version__
from .manifest import MANIFEST_SHA256
from .parsing import parse_staging
from .profile import active
from .profile import conventions as _conventions
from .verdict import utc_now_iso

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_USAGE = 1


def _values(obj: dict, fields: Tuple[str, ...]) -> Dict[str, object]:
    return {f: obj.get(f) for f in fields}


def _fingerprint(obj: dict, fields: Tuple[str, ...]) -> str:
    """A stable hash of the verbatim fields only.

    Serialised as an explicit list of pairs rather than a dict dump, so the
    hash cannot shift because a writer reordered keys — a fingerprint that
    changes when nothing did is worse than none, since it teaches the reader to
    ignore the finding.
    """
    payload = [[f, obj.get(f)] for f in fields]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=False, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def _collect(root: Path, keep_values: bool = True) -> Tuple[Dict[str, dict], List[str]]:
    """Every row in the corpus, keyed by id, with where it came from."""
    conv = _conventions()
    fields = active().verbatim_fields
    rows: Dict[str, dict] = {}
    warnings: List[str] = []

    sources = sorted(root.glob(conv.staging_glob)) + sorted(root.glob("**/feature-tree*.md"))
    for path in sources:
        try:
            parsed = parse_staging(path)
        except Exception as exc:  # noqa: BLE001 — an unreadable file is a result
            warnings.append(f"{path}: unreadable ({type(exc).__name__})")
            continue
        for rp in parsed.rows:
            if rp.obj is None:
                continue
            rid = rp.obj.get("id")
            if not rid:
                continue
            fp = _fingerprint(rp.obj, fields)
            if rid in rows and rows[rid]["fingerprint"] != fp:
                # The same id carrying different verbatim content in two files
                # is a real defect, but it is not this command's to rule on —
                # G2 owns duplicate ids. Recorded so a later mismatch is not
                # blamed on a mapping pass that did nothing.
                warnings.append(
                    f"id {rid!r} appears in more than one file with different "
                    "verbatim fields; frozen from the first seen"
                )
                continue
            record = {"fingerprint": fp, "file": str(path)}
            if keep_values:
                record["values"] = _values(rp.obj, fields)
            rows.setdefault(rid, record)
    return rows, warnings


def _record(root: Path, out: Path, keep_values: bool = True) -> int:
    rows, warnings = _collect(root, keep_values)
    if not rows:
        print(f"freeze: no rows found under {root}")
        print("  Freezing nothing would later compare clean against anything,")
        print("  so this is an error rather than an empty snapshot.")
        return EXIT_USAGE

    doc = {
        "kbqa_version": __version__,
        "manifest_sha256": MANIFEST_SHA256,
        "profile": active().name,
        "verbatim_fields": list(active().verbatim_fields),
        "frozen_at": utc_now_iso(),
        "stores_values": keep_values,
        "root": str(root),
        "rows": rows,
        "warnings": warnings,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    size_kb = out.stat().st_size // 1024
    print(f"frozen {len(rows)} row(s) -> {out}  ({size_kb} KB)")
    print(f"  verbatim fields: {', '.join(active().verbatim_fields)}")
    if keep_values:
        print("  values stored — a drift report can show what the field held")
    else:
        print("  fingerprints only — drift will be detectable but not recoverable")
    for w in warnings[:10]:
        print(f"  warning: {w}")
    if len(warnings) > 10:
        print(f"  … and {len(warnings) - 10} more warnings")
    return EXIT_OK


def _check(root: Path, snapshot: Path) -> int:
    if not snapshot.exists():
        print(f"freeze: snapshot not found: {snapshot}")
        return EXIT_USAGE
    doc = json.loads(snapshot.read_text(encoding="utf-8"))

    frozen_fields = tuple(doc.get("verbatim_fields", ()))
    if frozen_fields and frozen_fields != active().verbatim_fields:
        # Comparing against a snapshot taken over a different field set would
        # report drift in every row, which reads as catastrophe and means
        # nothing.
        print("freeze: the snapshot froze a different field set")
        print(f"  snapshot: {', '.join(frozen_fields)}")
        print(f"  now     : {', '.join(active().verbatim_fields)}")
        print("  Re-freeze deliberately; do not compare across contracts.")
        return EXIT_USAGE

    before: Dict[str, dict] = doc.get("rows", {})
    after, warnings = _collect(root)

    changed = sorted(
        rid for rid in before.keys() & after.keys()
        if before[rid]["fingerprint"] != after[rid]["fingerprint"]
    )
    gone = sorted(before.keys() - after.keys())
    new = sorted(after.keys() - before.keys())

    print(f"freeze check against {snapshot}")
    print(f"  frozen {len(before)} -> now {len(after)}")
    print(f"  CHANGED      {len(changed)}  (a verbatim field was edited)")
    print(f"  DISAPPEARED  {len(gone)}")
    print(f"  appeared     {len(new)}  (not a failure — collection adds rows)")

    for rid in changed[:25]:
        print(f"    changed: {rid}  in {after[rid]['file']}")
        was, now = before[rid].get("values"), after[rid].get("values")
        if was and now:
            for f in sorted(was):
                if was[f] != now.get(f):
                    print(f"        {f}:")
                    print(f"          frozen: {was[f]!r}")
                    print(f"          now   : {now.get(f)!r}")
    if len(changed) > 25:
        print(f"    … and {len(changed) - 25} more")
    for rid in gone[:25]:
        print(f"    gone:    {rid}  was in {before[rid]['file']}")
    if len(gone) > 25:
        print(f"    … and {len(gone) - 25} more")
    for w in warnings[:5]:
        print(f"  warning: {w}")

    if changed or gone:
        print()
        print("  A mapping pass may add a mapping. It may not edit the words")
        print("  being mapped.")
        if doc.get("stores_values"):
            print("  Restore each field to its frozen value above.")
        else:
            print("  This snapshot holds fingerprints only, so it cannot say what")
            print("  the field held. Restore from version control if the estate")
            print("  has any; if it does not, the original is gone and the row")
            print("  must be re-collected from its source.")
        print("  Never re-freeze to clear this. Re-freezing records the edit as")
        print("  the new truth, which is the one thing this command exists to")
        print("  prevent — and the request to do it always sounds reasonable.")
        return EXIT_DRIFT
    return EXIT_OK


def run(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="kbqa freeze")
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", default=None, help="record a snapshot here")
    ap.add_argument("--check", default=None, help="compare against this snapshot")
    ap.add_argument(
        "--fingerprints-only", action="store_true",
        help="omit the frozen values. Only for an estate with version control: "
             "without either, a drift report cannot say what was lost",
    )
    args = ap.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        print(f"freeze: not a directory: {root}")
        return EXIT_USAGE
    if bool(args.out) == bool(args.check):
        print("freeze: give exactly one of --out (record) or --check (compare)")
        return EXIT_USAGE

    if args.out:
        return _record(root, Path(args.out), keep_values=not args.fingerprints_only)
    return _check(root, Path(args.check))
