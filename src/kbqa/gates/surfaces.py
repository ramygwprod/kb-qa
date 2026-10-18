"""K2 · Mandatory surfaces — surfaces --subject <d> [--stops <f>]

Every subject is collected on three surfaces (`Conventions.surfaces`). Each
must have its own denominator, `_denominator-<surface>-<date>.md`, or a line in
the stop-conditions file that says the subject does not publish it and cites
the fetched page that shows so.

A missing surface is a PLANNER finding: no edit to any row can produce a
surface nobody collected. It is a subject-level check, so it does not decide
whether one batch is CLEAR — a docs batch is not blocked by an unstarted help
surface — and it is reported beside the batch reports, never folded into them.

The stop-condition is recognised by the form the collector writes:

    <url> | surface <slug> not published: <what that page shows>

The word `surface` and the slug are what is matched. A line that names the
surface some other way is not recognised, and the surface reports MISSING —
the safe direction: a human reads the line, nothing passes unseen.

A surface that IS published but whose index cannot be read is closed by a
stop line ending `(surface <slug>)` (`js-only: not readable (surface help)` —
the vocabulary in `kbqa.stops`). Beside a denominator such a line is a
contradiction, as it always was: the index WAS read. The one exception is a
line that closes the surface's pages (`refused: robots` or `refused: HTTP
401|403`, the host refusing us as a whole) keyed by an item of the surface's
current denominator: the index was read, its pages could not be, and the line —
approved by the operator — is the surface's end. That is the same line `g4`
accepts, and nothing wider.
"""

import argparse
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..profile import conventions
from ..verdict import FAIL, PASS, Finding, Verdict, input_ref
from . import EXIT_FAIL, EXIT_PASS
from .g4_completeness import read_stop_entries

GATE = "surfaces"


def _page_closing(d: Path, dens: List[str], slug: str,
                  lines: List[Tuple[str, str, int]]) -> List[Tuple[str, str, int]]:
    """The lines that close the surface's pages, as `g4` reads them: a reason
    that closes items, for this surface, keyed by an item of the current
    denominator (the last by date, then correction letter)."""
    from .. import stops as vocabulary
    from ..capture import denominator_items
    current = sorted(dens, key=lambda n: (re.sub(r"[b-z]?\.md$", "", n), n))[-1]
    items = {u for _, u in denominator_items(d / current)}
    out = []
    for k, r, n in lines:
        try:
            entry, surface = vocabulary.classify(r)
        except vocabulary.StopLineError:
            continue
        if entry.closes_items and surface == slug and k in items:
            out.append((k, r, n))
    return out


def run(argv: Optional[List[str]] = None) -> Tuple[Verdict, int]:
    ap = argparse.ArgumentParser(prog="kbqa surfaces")
    # `--subject`, not `--vendor-dir`: the CLI takes `--vendor-dir` as the
    # recording flag (where verdicts are written) before this parser sees it.
    ap.add_argument("--subject", required=True)
    ap.add_argument("--stops", default=None)
    args = ap.parse_args(argv)

    conv = conventions()
    d = Path(args.subject)
    findings: List[Finding] = []
    inputs: Dict[str, object] = {"subject": {"path": str(d)}}

    if not d.is_dir():
        findings.append(Finding("subject_missing", f"not a directory: {d}"))
        return Verdict(GATE, FAIL, inputs, {"scanned": 0, "failed": 1}, findings), EXIT_FAIL

    stops_path = Path(args.stops) if args.stops else d / conv.stops_name
    entries: List[Tuple[str, str, int]] = []
    if stops_path.exists():
        inputs["stops"] = input_ref(stops_path)
        entries, errors, _ = read_stop_entries(stops_path)
        for err in errors:
            findings.append(Finding("stop_condition_without_reason", err))

    den_re = re.compile(conv.surface_denominator_pattern)
    dens: Dict[str, List[str]] = {s: [] for s in conv.surfaces}
    legacy_dens: List[str] = []
    for p in sorted(d.iterdir()):
        if not p.is_file() or not p.name.startswith("_denominator"):
            continue
        m = den_re.match(p.name)
        if m:
            dens[m.group("surface")].append(p.name)
        else:
            legacy_dens.append(p.name)

    batches: Dict[str, List[str]] = {s: [] for s in conv.surfaces}
    for p in sorted(d.glob(f"{conv.staging_prefix}*{conv.staging_suffix}")):
        surface = conv.surface_of(conv.batch_of(p.name))
        if surface:
            batches[surface].append(conv.batch_of(p.name))

    per_surface: Dict[str, dict] = {}
    for slug in conv.surfaces:
        said = re.compile(rf"\bsurface\s+{re.escape(slug)}\b", re.IGNORECASE)
        stop_lines = [(k, r, n) for k, r, n in entries if said.search(r)]
        for k, r, n in stop_lines:
            if not k.startswith(("http://", "https://")):
                findings.append(Finding(
                    "surface_stop_without_page",
                    f"line {n}: the stop-condition for surface {slug!r} is keyed "
                    f"{k!r}, not the URL of a fetched page that shows the absence",
                    where=f"{stops_path.name}:{n}",
                ))
        closing = _page_closing(d, dens[slug], slug, stop_lines) if dens[slug] else []
        other = [x for x in stop_lines if x not in closing]
        if dens[slug] and other:
            state = "contradiction"
            findings.append(Finding(
                "surface_contradiction",
                f"surface {slug!r} has a denominator ({', '.join(dens[slug])}) and "
                f"a stop-condition saying it is not published or cannot be read (line "
                f"{', '.join(str(n) for _, _, n in other)})",
                where=slug,
            ))
        elif dens[slug] and closing:
            state = "denominator, closed by a stop line"
        elif dens[slug]:
            state = "denominator"
            if not batches[slug]:
                findings.append(Finding(
                    "surface_unfinished",
                    f"surface {slug!r} has a denominator but no batch was collected "
                    "against it — unfinished, not done",
                    where=slug,
                ))
        elif stop_lines:
            state = "stop-condition"
        else:
            state = "MISSING"
            hint = (f" (a denominator without a surface in its name exists: "
                    f"{', '.join(legacy_dens)})") if legacy_dens else ""
            findings.append(Finding(
                "surface_missing",
                f"surface {slug!r} has no `_denominator-{slug}-<date>.md` and no "
                f"stop-condition naming it{hint}",
                where=slug,
            ))
        per_surface[slug] = {
            "state": state,
            "denominators": dens[slug],
            "stop_lines": [n for _, _, n in stop_lines],
            "batches": len(batches[slug]),
        }

    counts = {
        "scanned": len(conv.surfaces),
        "surfaces": per_surface,
        "legacy_denominators": legacy_dens,
        "stop_entries": len(entries),
        "failed": len(findings),
    }
    verdict = PASS if not findings else FAIL
    return Verdict(GATE, verdict, inputs, counts, findings), (
        EXIT_PASS if verdict == PASS else EXIT_FAIL
    )
